import os
import re
import time
import socket
import asyncio
import logging
import subprocess
import atexit
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from pathlib import Path

import uvicorn
import httpx
import base64
import hashlib
import secrets
from fastapi import FastAPI, HTTPException, status, Body, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field


import system_monitor

import config
from config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    CAMP_SYSTEM_PROMPT,
    HOST,
    PORT,
)
import database
import notifier
from security import (
    security_guard,
    login_rate_limiter,
    append_audit_log_file,
    verify_audit_log_chain,
    check_append_only_attribute,
    enable_append_only_attribute,
    secure_session_directories,
    ensure_gitignore_entries,
)

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("camp-bot-backend")

import time
import socket
import subprocess
import atexit

BRIDGE_API_URL = os.getenv("BRIDGE_API_URL", "http://127.0.0.1:3001")
BRIDGE_DIR = Path(__file__).resolve().parent.parent / "bridge"

# Resolve frontend directory with Docker container fallback
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(Path(__file__).resolve().parent.parent / "frontend")))
if not FRONTEND_DIR.exists():
    alt_frontend = Path(__file__).resolve().parent / "frontend"
    if alt_frontend.exists():
        FRONTEND_DIR = alt_frontend

bridge_process: Optional[subprocess.Popen] = None


def is_bridge_port_open(port: int = 3001) -> bool:
    """Checks if the bridge management port 3001 is listening."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def ensure_bridge_service_running():
    """Automatically launches the Node.js WhatsApp Bridge if not already running (local mode)."""
    global bridge_process
    if os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true":
        logger.info("Running in Docker container. WhatsApp Bridge is orchestrated separately.")
        return True

    if is_bridge_port_open(3001):
        return True

    if not BRIDGE_DIR.exists():
        return False

    logger.info("WhatsApp Bridge (port 3001) is offline. Auto-launching Node.js bridge...")
    try:
        bridge_process = subprocess.Popen(
            ["node", "index.js"],
            cwd=str(BRIDGE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        # Wait up to 4 seconds for port 3001 to bind
        for _ in range(16):
            time.sleep(0.25)
            if is_bridge_port_open(3001):
                logger.info("WhatsApp Bridge process successfully started and bound to port 3001.")
                return True
    except Exception as exc:
        logger.error("Failed to auto-spawn Node.js bridge: %s", exc)

    return is_bridge_port_open(3001)


def cleanup_bridge_service():
    """Cleanly terminates child bridge process on backend shutdown."""
    global bridge_process
    if bridge_process and bridge_process.poll() is None:
        logger.info("Stopping child WhatsApp bridge process...")
        bridge_process.terminate()
        try:
            bridge_process.wait(timeout=2.0)
        except Exception:
            bridge_process.kill()


atexit.register(cleanup_bridge_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to handle startup and shutdown events."""
    logger.info("Initializing database...")
    database.init_db()
    logger.info("Database initialized successfully.")
    
    # Forensic & Isolation Sweeps
    ensure_gitignore_entries()
    secure_session_directories()
    
    logger.info("Target Ollama Model: %s at %s", config.OLLAMA_MODEL, config.OLLAMA_BASE_URL)
    
    # Configure security guard from environment
    security_guard.rate_limit_per_minute = config.RATE_LIMIT_PER_MINUTE
    security_guard.rate_limit_daily = config.RATE_LIMIT_DAILY
    security_guard.enable_jailbreak_filter = config.ENABLE_JAILBREAK_FILTER
    security_guard.enable_offtopic_filter = config.ENABLE_OFFTOPIC_FILTER
    logger.info(
        "Security Guard Active: Rate limit (%d/min, %d/day) | Jailbreak Filter (%s) | Offtopic Filter (%s)",
        security_guard.rate_limit_per_minute,
        security_guard.rate_limit_daily,
        security_guard.enable_jailbreak_filter,
        security_guard.enable_offtopic_filter,
    )
    
    # Auto-start Node.js bridge
    ensure_bridge_service_running()

    # Load any saved LLM credentials from database
    try:
        saved_settings = database.get_system_settings()
        if "llm_api_key" in saved_settings and saved_settings["llm_api_key"]:
            config.update_llm_config(
                api_key=saved_settings.get("llm_api_key"),
                provider=saved_settings.get("llm_provider"),
                model=saved_settings.get("llm_model"),
            )
            logger.info("Loaded saved LLM credentials from DB: provider=%s, model=%s", config.LLM_PROVIDER, config.LLM_MODEL)
    except Exception as e:
        logger.warning("Could not load LLM settings from DB: %s", e)

    # KVKK Data minimization: automatically prune raw conversation logs older than 10 days
    try:
        deleted = database.cleanup_old_messages(days=10)
        if deleted > 0:
            logger.info("Startup KVKK cleanup: pruned %d messages older than 10 days.", deleted)
    except Exception as e:
        logger.warning("Failed to run message retention cleanup: %s", e)
    
    yield
    logger.info("Shutting down backend service.")
    cleanup_bridge_service()


app = FastAPI(
    title="Local WhatsApp AI Camp Assistant Backend & Control Center",
    description="FastAPI service mediating WhatsApp Bridge, SQLite Chat Memory, and Local Ollama with Security Suite",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================================
# Dashboard Authentication System (Password: 15935728)
# =========================================================================
active_tokens = set()

def get_current_panel_password() -> str:
    saved = database.get_system_settings()
    return saved.get("panel_password", config.PANEL_PASSWORD)

def compute_token_for_password(pwd: str) -> str:
    return hashlib.sha256(f"{pwd}_camp_admin_salt_2026".encode()).hexdigest()

def verify_panel_auth(
    authorization: Optional[str] = Header(default=None),
    x_panel_token: Optional[str] = Header(default=None),
) -> bool:
    """Verifies that request comes from an authenticated dashboard session."""
    if os.getenv("TESTING", "false").lower() == "true":
        return True

    current_pass = get_current_panel_password()
    expected_token = compute_token_for_password(current_pass)

    # 1. Custom token header
    if x_panel_token and (x_panel_token == expected_token or x_panel_token in active_tokens):
        return True

    # 2. Authorization header (Bearer or Basic)
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
            if token == expected_token or token in active_tokens:
                return True
        elif authorization.startswith("Basic "):
            try:
                decoded = base64.b64decode(authorization[6:]).decode("utf-8")
                if ":" in decoded:
                    _, pwd = decoded.split(":", 1)
                    if pwd == current_pass:
                        return True
            except Exception:
                pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Yetkisiz erişim. Lütfen panel şifresini girin.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_client_ip(request: Request) -> str:
    """Extracts client IP address respecting reverse proxies and headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


class LoginRequest(BaseModel):
    password: str


@app.post("/api/auth/login", tags=["Auth"])
async def auth_login(payload: LoginRequest, request: Request):
    """Verifies panel password with anti-brute-force rate limiting, delay, and lockout."""
    client_ip = get_client_ip(request)

    # 1. Check if IP is currently locked out
    is_locked, remaining_sec = login_rate_limiter.is_locked_out(client_ip)
    if is_locked:
        logger.warning("Blocked login attempt from locked IP %s (%d sec left)", client_ip, remaining_sec)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Çok fazla hatalı şifre denemesi yapıldı. Güvenliğiniz için erişiminiz {remaining_sec} saniye engellenmiştir."
        )

    current_pass = get_current_panel_password()
    if payload.password.strip() == current_pass:
        login_rate_limiter.record_success(client_ip)
        token = compute_token_for_password(current_pass)
        active_tokens.add(token)
        return {
            "success": True,
            "token": token,
            "message": "Giriş başarılı!"
        }

    # 2. Failed attempt: add artificial 1-second delay to cripple automated brute-force tools
    await asyncio.sleep(1.0)
    is_now_locked, remaining = login_rate_limiter.record_failure(client_ip)

    if is_now_locked:
        # Send security push notification via ntfy
        topic = notifier.get_active_topic()
        asyncio.create_task(
            notifier.send_ntfy_push(
                topic=topic,
                title="🚨 Panel Güvenlik Alarmı",
                message=f"Panel girişine brute-force saldırısı tespit edildi! IP ({client_ip}) 15 dakika boyunca engellendi.",
                priority=5,
                tags=["rotating_light", "warning"],
            )
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Çok fazla hatalı deneme yapıldı! Güvenlik nedeniyle IP adresiniz 15 dakika boyunca engellendi."
        )

    raise HTTPException(
        status_code=401,
        detail=f"Hatalı panel şifresi! Kalan deneme hakkınız: {remaining}"
    )


@app.get("/api/auth/verify", tags=["Auth"])
async def auth_verify(authed: bool = Depends(verify_panel_auth)):
    """Validates whether current session is authenticated."""
    return {"authenticated": True}


@app.post("/api/auth/logout", tags=["Auth"])
async def auth_logout():
    """Logs out and clears session token."""
    return {"success": True, "message": "Oturum kapatıldı."}


@app.post("/api/auth/change-password", tags=["Auth"])
async def change_panel_password(
    current_password: str = Body(..., embed=True),
    new_password: str = Body(..., embed=True),
    authed: bool = Depends(verify_panel_auth),
):
    """Changes the panel password on the fly."""
    current_pass = get_current_panel_password()
    if current_password.strip() != current_pass:
        raise HTTPException(status_code=400, detail="Mevcut şifre hatalı.")
    if len(new_password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 4 karakter olmalıdır.")
    new_pass = new_password.strip()
    database.save_system_settings({"panel_password": new_pass})
    config.PANEL_PASSWORD = new_pass
    new_token = compute_token_for_password(new_pass)
    active_tokens.clear()
    active_tokens.add(new_token)
    return {"success": True, "token": new_token, "message": "Panel şifresi başarıyla güncellendi!"}


@app.middleware("http")
async def dashboard_auth_middleware(request, call_next):
    """Enforces authentication across all /api/* routes except login, webhook, and health."""
    path = request.url.path
    # Public routes:
    if (
        path in ["/", "/health", "/webhook", "/api/auth/login"]
        or path.startswith("/static")
        or path.startswith("/docs")
        or path.startswith("/openapi.json")
        or os.getenv("TESTING", "false").lower() == "true"
    ):
        return await call_next(request)

    # All /api/* routes require authentication
    if path.startswith("/api/"):
        auth_header = request.headers.get("Authorization")
        panel_token = request.headers.get("X-Panel-Token")
        
        current_pass = get_current_panel_password()
        expected_token = compute_token_for_password(current_pass)

        is_authed = False
        if panel_token and (panel_token == expected_token or panel_token in active_tokens):
            is_authed = True
        elif auth_header:
            if auth_header.startswith("Bearer "):
                tok = auth_header[7:].strip()
                if tok == expected_token or tok in active_tokens:
                    is_authed = True
            elif auth_header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    if ":" in decoded:
                        _, pwd = decoded.split(":", 1)
                        if pwd == current_pass:
                            is_authed = True
                except Exception:
                    pass

        if not is_authed:
            return JSONResponse(
                status_code=401,
                content={"detail": "Yetkisiz erişim. Lütfen panel şifresini girin."},
                headers={"WWW-Authenticate": "Bearer"},
            )

    return await call_next(request)


def strip_all_internal_tags(text: str) -> str:
    """
    Robustly strips any internal system, routing, thinking, or bracket tags from user-facing replies.
    Safe against:
      - Variable spacing / line breaks inside brackets (e.g. '[ YETKILI_DEVRET: ... ]')
      - Markdown bold / italic wrappers around tags (e.g. '**[YETKILI_DEVRET: ...]**')
      - Missing colons or missing parameters (e.g. '[REZERVASYON]', '[YETKILI]')
      - Thought / reasoning tags (e.g. '<think>...</think>')
      - Catch-all for any bracket tags containing internal keywords: YETKILI, REZERVASYON, INSAN, LEAD, DEVRET
    """
    if not text:
        return ""

    # 1. Strip reasoning / thinking tags (<think>...</think>, <reasoning>...</reasoning>)
    cleaned = re.sub(r"<(?:think|reasoning|thought)[\s\S]*?</(?:think|reasoning|thought)>", "", text, flags=re.IGNORECASE)

    # 2. Strip bracket tags with optional markdown bold/italic wrapper
    bracket_tag_pattern = (
        r"(?:\*{1,2}|_{1,2})?\[\s*"
        r"(?:YETKILI(?:_DEVRET|_TALEBI)?|INSAN(?:_DEVRAL)?|REZERVASYON(?:_BILGILERI_TAMAM|_TAMAM|_BILGISI)?|LEAD(?:_TAMAM)?)"
        r"(?::\s*[\s\S]*?)?\s*\](?:\*{1,2}|_{1,2})?"
    )
    cleaned = re.sub(bracket_tag_pattern, "", cleaned, flags=re.IGNORECASE)

    # 3. Catch-all for any remaining bracket tags containing internal workflow tokens
    cleaned = re.sub(r"\[\s*(?:YETKILI|REZERVASYON|INSAN|LEAD|DEVRET)[\s\S]*?\]", "", cleaned, flags=re.IGNORECASE)

    # 4. Clean excessive spacing and blank lines
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()


class WebhookRequest(BaseModel):
    phone: str = Field(..., description="Sender's phone number or WhatsApp ID", min_length=3)
    message: str = Field(..., description="Incoming message text", min_length=1)


class WebhookResponse(BaseModel):
    reply: Optional[str] = Field(None, description="AI or system reply message")
    is_muted: bool = Field(False, description="True if chat is currently muted for human intervention")
    action: Optional[str] = Field(None, description="Special event action: intervention_alert | reservation_alert | None")
    alert_details: Optional[str] = Field(None, description="Details for admin notification")


class HealthResponse(BaseModel):
    status: str
    model: str
    provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    llm_base_url: Optional[str] = None


@app.get("/health", response_model=HealthResponse, tags=["Monitoring"])
async def health_check():
    """Health check endpoint to verify backend status and configuration."""
    return HealthResponse(
        status="ok",
        model=config.ACTIVE_MODEL_NAME,
        provider=config.LLM_PROVIDER,
        ollama_base_url=config.OLLAMA_BASE_URL,
        llm_base_url=config.LLM_BASE_URL or None,
    )


@app.post("/webhook", response_model=WebhookResponse, tags=["Messaging"])
async def handle_webhook(payload: WebhookRequest):
    """
    Main webhook endpoint for receiving WhatsApp messages.
    - Checks if chat is muted for human intervention (logs without replying)
    - Validates message content
    - Enforces sliding-window rate limit
    - Runs anti-jailbreak and off-topic domain guard
    - Handles /reset session purge
    - Detects human intervention & reservation booking requests
    - Queries local Ollama model with deterministic sampling
    - Sanitizes output and persists message turns
    """
    phone = payload.phone.strip()
    user_message = payload.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content cannot be empty.",
        )

    # 1. Check if Chat is Muted (Human Intervention Active)
    chat_status = database.get_chat_status(phone)
    if chat_status.get("is_muted"):
        # Chat is muted -> Save user message to database for admin to view, but do NOT auto-reply
        database.save_message(phone, role="user", content=user_message)
        logger.info("Chat %s is muted (until %s). Message logged without AI auto-reply.", phone, chat_status.get("muted_until"))
        return WebhookResponse(reply=None, is_muted=True, action=None)

    # 2. Session Reset Hook
    if user_message.lower() == "/reset":
        deleted_count = database.clear_history(phone)
        security_guard.unblock_phone(phone)
        logger.info("Session reset requested for %s. Cleared %d messages.", phone, deleted_count)
        reset_reply = "Sohbet geçmişiniz sıfırlandı. Yeni bir konuşma başlatabilirsiniz. Size nasıl yardımcı olabilirim?"
        database.log_bot_audit(phone, reset_reply, "SENT")
        append_audit_log_file(phone, reset_reply, "SENT")
        return WebhookResponse(
            reply=reset_reply,
            is_muted=False
        )

    # 3. Per-Phone Rate Limiter Check
    is_allowed, rate_limit_reason = security_guard.check_rate_limit(phone)
    if not is_allowed:
        logger.warning("Rate limit hit for %s: %s", phone, rate_limit_reason)
        database.log_bot_audit(phone, rate_limit_reason, "SENT")
        append_audit_log_file(phone, rate_limit_reason, "SENT")
        return WebhookResponse(reply=rate_limit_reason, is_muted=False)

    # 4. Input Jailbreak & Off-Topic Guard
    is_safe, safety_reply = security_guard.check_input_safety(user_message)
    if not is_safe:
        logger.warning("Input blocked by security filter for %s: '%s'", phone, user_message)
        database.save_message(phone, role="user", content=user_message)
        database.save_message(phone, role="assistant", content=safety_reply)
        database.log_bot_audit(phone, safety_reply, "SENT")
        append_audit_log_file(phone, safety_reply, "SENT")
        return WebhookResponse(reply=safety_reply, is_muted=False)

    # 5. Check Severe Complaint / Legal Emergency Intent
    if security_guard.detect_intervention_intent(user_message):
        logger.info("Severe complaint or emergency detected for %s. Muting chat for 2 hours.", phone)
        database.mute_chat(phone, duration_minutes=120, reason="user_complaint_emergency")
        intervention_reply = "Mesajınızı doğrudan işletme yetkilimize iletiyorum. En kısa sürede bu sohbet üzerinden sizinle iletişime geçilecektir."
        database.save_message(phone, role="user", content=user_message)
        database.save_message(phone, role="assistant", content=intervention_reply)
        database.log_bot_audit(phone, intervention_reply, "SENT")
        append_audit_log_file(phone, intervention_reply, "SENT")
        asyncio.create_task(notifier.send_intervention_alert(phone, user_message))
        return WebhookResponse(
            reply=intervention_reply,
            is_muted=True,
            action="intervention_alert",
            alert_details=f"Acil / Şikayet Talebi: \"{user_message}\""
        )

    # Note: Reservation booking is handled interactively via LLM prompt to gather details first.

    # 6. Fetch past conversation history window
    past_history = database.get_history(phone)
    is_first_interaction = len(past_history) == 0

    # 7. Persist incoming user message to SQLite
    database.save_message(phone, role="user", content=user_message)

    # 8. Construct messages payload
    messages_payload = [{"role": "system", "content": config.build_system_prompt()}]
    messages_payload.extend(past_history)
    messages_payload.append({"role": "user", "content": user_message})

    logger.info(
        "Processing message from %s (provider=%s, model=%s, history=%d turns)...",
        phone,
        config.LLM_PROVIDER,
        config.ACTIVE_MODEL_NAME,
        len(past_history),
    )

    # 9. Query LLM (Cloud API or Local Ollama)
    raw_reply = ""
    try:
        raw_reply = await query_llm(messages_payload)
        assistant_reply = security_guard.sanitize_output(raw_reply)
    except httpx.ConnectError as err:
        logger.error("Could not connect to LLM endpoint: %s", err)
        assistant_reply = (
            "Şu anda mesajınızı işlerken geçici bir aksaklık oluştu. "
            "Yetkilimiz en kısa sürede sizinle bu sohbet üzerinden iletişime geçecektir."
        )
    except httpx.TimeoutException:
        logger.error("LLM request timed out after %s seconds.", config.OLLAMA_TIMEOUT)
        assistant_reply = (
            "Yoğunluk nedeniyle yanıt oluşturulurken gecikme yaşandı. "
            "Lütfen sorunuzu kısaca tekrar iletiniz veya yetkilimizin dönüşünü bekleyiniz."
        )
    except httpx.HTTPStatusError as exc:
        logger.error("LLM returned HTTP error status %s: %s", exc.response.status_code, exc.response.text)
        assistant_reply = (
            "Talebinizi aldım, yetkilimiz en kısa sürede bu sohbet üzerinden size bilgi verecektir."
        )
    except Exception as exc:
        logger.exception("Unexpected error while querying LLM: %s", exc)
        assistant_reply = "Bu konuyu yetkilimize iletiyorum, en kısa sürede bilgi verilecektir."

    # 10. Check for interactive action tags & reservation lead completion
    is_muted = False
    action = None
    alert_details = None

    # 10a. Primary tag detection (search both raw_reply and sanitized assistant_reply)
    all_reply_text = f"{raw_reply} {assistant_reply}"
    intervention_match = re.search(
        r"\[\s*(?:YETKILI_DEVRET|YETKILI_TALEBI|INSAN_DEVRAL)(?::\s*([\s\S]*?))?\s*\]",
        all_reply_text,
        re.IGNORECASE,
    )
    lead_match = re.search(
        r"\[\s*(?:REZERVASYON_BILGILERI_TAMAM|REZERVASYON_TAMAM|REZERVASYON_BILGISI|REZERVASYON|LEAD_TAMAM|LEAD)(?::\s*([\s\S]*?))?\s*\]",
        all_reply_text,
        re.IGNORECASE,
    )

    # 10b. Semantic safety net & price inquiry discriminator
    reservation_intent_patterns = [
        r"(?i)\b(rezervasyon|rezerve)\b",
        r"(?i)\b(yer\s+(?:ayırt|ayır|aç|tut|ayarla))\b",
        r"(?i)\b(?:ayırtmak|ayıralım|ayırtalım)\b",
        r"(?i)\b(?:kesin\s+kayıt|kayıt\s+yap|kaydımızı\s+yap|kayıt\s+aç|kaydımızı\s+al)\b",
        r"(?i)\b(?:haber\s+bekliyorum|ne\s+yapmamız\s+gerekiyor|nasıl\s+kesinleştirebiliriz)\b",
        r"(?i)\b(?:gelmek\s+istiyoruz|geleceğiz)\b.*(?:\byer\s+var\s+mı\b|\bmüsait\s+mi\b|\bkesinleştirelim\b|\bayarlayalım\b)",
    ]
    user_has_reservation_intent = any(re.search(p, user_message) for p in reservation_intent_patterns)

    # General price inquiry or information request patterns
    price_info_patterns = [
        r"(?i)\b(fiyat|fiyatlar|ücret|ne\s+kadar|kaça|kaç\s+para|kaç\s+tl|hesapla|hesaplayalım|öğrenmek\s+istiyorum|bilgi\s+al|bilgi\s+ver)\b"
    ]
    is_price_or_info_inquiry = any(re.search(p, user_message) for p in price_info_patterns)

    # If customer is purely asking price/info without reservation intent, do NOT trigger lead
    if is_price_or_info_inquiry and not user_has_reservation_intent:
        lead_match = None

    is_semantic_reservation_lead = False
    is_semantic_payment_intervention = False

    payment_patterns = [
        r"(?i)\b(kapora|iban|hesap\s+no|hesap\s+numara|para\s+gönder|havale|eft|kredi\s+kart|ödemeyi\s+nereye|nereye\s+öde|hesap\s+bilgi|ödemeyi\s+nasıl\s+yap|ödeme\s+yapmak\s+istiyorum)\b"
    ]
    if any(re.search(p, user_message) for p in payment_patterns):
        is_semantic_payment_intervention = True

    if not lead_match and not intervention_match and not is_semantic_payment_intervention:
        reply_lower = assistant_reply.lower()
        semantic_patterns = [
            r"müsaitlik.*kontrol\s+edip.*(dönüş|haber|iletiş|bilgi)",
            r"kesin\s+kayıt.*(dönüş|iletiş|bilgi)",
            r"bilgilerinizi\s+aldım.*(dönüş|kontrol|kayıt)",
            r"(kısa\s+bir\s+süre\s+içinde|birazdan).*buradan\s+dönüş",
            r"eğer\s+yerimiz\s+varsa.*(rezervasyon|bilgi)",
            r"kontrol\s+edip.*(size\s+buradan|size\s+kısa\s+bir\s+süre).*dönüş",
            r"rezervasyon\s+işlemleri\s+için\s+gerekli\s+bilgileri\s+size\s+ilete",
        ]
        user_lower = user_message.lower()
        user_intent_patterns = [
            r"haber\s+bekliyorum.*(rezervasyon|müsaitlik)",
            r"rezervasyon\s+için\s+ne\s+yapmamız\s+gerekiyor",
            r"(kesin\s+kayıt|yer\s+ayırtmak).*için\s+ne\s+yap",
        ]
        # Only evaluate semantic fallback if not a pure price/info inquiry
        if not (is_price_or_info_inquiry and not user_has_reservation_intent):
            if any(re.search(p, reply_lower) for p in semantic_patterns):
                is_semantic_reservation_lead = True
            elif any(re.search(p, user_lower) for p in user_intent_patterns):
                is_semantic_reservation_lead = True

    # Priority 1: Human intervention (emergency, payment/IBAN security, explicit handoff)
    if intervention_match or is_semantic_payment_intervention:
        if intervention_match:
            reason = (intervention_match.group(1) or "").strip() or "Yetkili devri talep edildi"
        else:
            reason = f"Müşteri ödeme/kapora/IBAN talebinde bulundu: \"{user_message.strip()}\""
            if not any(w in assistant_reply.lower() for w in ["yetkili", "iletişime", "dönüş"]):
                assistant_reply += "\n\nÖdeme, kapora ve hesap işlemlerimiz doğrudan işletme yetkilimiz tarafından güvenli şekilde yürütülmektedir. Yetkilimize bilgi verdim, en kısa sürede size buradan dönüş sağlayacaktır."

        assistant_reply = strip_all_internal_tags(assistant_reply)

        logger.info("Human intervention triggered for %s: %s", phone, reason)
        database.mute_chat(phone, duration_minutes=120, reason="human_requested")
        asyncio.create_task(notifier.send_intervention_alert(phone, reason))
        is_muted = True
        action = "intervention_alert"
        alert_details = reason

    # Priority 2: Reservation lead completion
    elif lead_match or is_semantic_reservation_lead:
        if lead_match:
            lead_summary = (lead_match.group(1) or "").strip() or "Rezervasyon bilgileri tamamlandı"
        else:
            # Fallback: extract last user requests from history + current message
            recent_user_texts = [
                m["content"].strip()
                for m in past_history
                if m.get("role") == "user" and m.get("content")
            ][-2:] + [user_message.strip()]
            lead_summary = " | ".join(recent_user_texts)

        # Clean all hidden tags from customer-facing reply
        assistant_reply = strip_all_internal_tags(assistant_reply)

        logger.info("Reservation lead completed for %s: %s (via_tag=%s)", phone, lead_summary, bool(lead_match))
        database.mark_reservation_lead(phone, lead_details=lead_summary)
        database.mute_chat(phone, duration_minutes=120, reason="reservation_ready")
        asyncio.create_task(notifier.send_reservation_alert(phone, lead_summary))
        is_muted = True
        action = "reservation_alert"
        alert_details = lead_summary

    # Defense-in-depth: Unconditionally strip any bracket tags before sending to user
    assistant_reply = strip_all_internal_tags(assistant_reply)

    # 11. KVKK first-interaction disclosure
    if is_first_interaction and assistant_reply:
        kvkk_notice = (
            "\n\n---\n"
            "ℹ️ *Bilgilendirme:* Hizmet kalitemiz ve rezervasyon süreçleri kapsamında mesajlaşma verileriniz "
            "KVKK'ya uygun olarak işlenmektedir. Sohbeti sürdürerek bunu kabul etmiş sayılırsınız."
        )
        assistant_reply += kvkk_notice

    # 12. Persist assistant reply to SQLite and Outgoing Audit Log
    database.save_message(phone, role="assistant", content=assistant_reply)
    if assistant_reply:
        database.log_bot_audit(phone, assistant_reply, "SENT")
        append_audit_log_file(phone, assistant_reply, "SENT")

    return WebhookResponse(
        reply=assistant_reply,
        is_muted=is_muted,
        action=action,
        alert_details=alert_details,
    )


async def query_llm(messages: List[Dict[str, str]]) -> str:
    """
    Unified LLM query dispatcher.
    Supports:
    - Cloud API (OpenAI, Groq, OpenRouter, Gemini via OpenAI-compatible endpoints)
    - Local Ollama (/api/chat)
    """
    is_cloud_api = (
        config.LLM_PROVIDER in ["openai", "groq", "openrouter", "gemini", "api", "custom"]
        or bool(config.LLM_API_KEY)
    )

    if is_cloud_api:
        base_url = (config.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        model_name = config.LLM_MODEL or "gpt-4o-mini"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}",
        }
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": config.OLLAMA_TEMPERATURE,
            "top_p": config.OLLAMA_TOP_P,
        }
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            elif "message" in data:
                return data["message"].get("content", "")
            return data.get("reply", "")
    else:
        endpoint = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": config.OLLAMA_TEMPERATURE,
                "top_p": config.OLLAMA_TOP_P,
                "repeat_penalty": config.OLLAMA_REPEAT_PENALTY,
            },
        }
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")


# =========================================================================
# Dashboard & Control Center API
# =========================================================================

@app.get("/api/dashboard/status", tags=["Dashboard"])
async def get_dashboard_status(authed: bool = Depends(verify_panel_auth)):
    """Aggregates health, Ollama status & installed models, security, resources, and WhatsApp Bridge state."""
    # 1. LLM Provider status & model list
    is_cloud_api = (
        config.LLM_PROVIDER in ["openai", "groq", "openrouter", "gemini", "api", "custom"]
        or bool(config.LLM_API_KEY)
    )
    if is_cloud_api:
        active_name = f"{config.LLM_PROVIDER.upper()}: {config.LLM_MODEL or 'gpt-4o-mini'}"
        ollama_info = {
            "connected": True,
            "models": [active_name],
            "active_model": active_name,
            "provider": config.LLM_PROVIDER,
            "is_cloud_api": True,
        }
    else:
        ollama_info = {"connected": False, "models": [], "error": None, "provider": "ollama", "is_cloud_api": False}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    ollama_info = {
                        "connected": True,
                        "models": models,
                        "active_model": config.OLLAMA_MODEL,
                        "provider": "ollama",
                        "is_cloud_api": False,
                    }
        except Exception as e:
            ollama_info["error"] = str(e)

    # 2. Bridge status & QR
    bridge_info = {
        "connected": False,
        "status": "OFFLINE",
        "qr": None,
        "connectedUser": None,
        "triggerPrefix": "-test",
        "logs": [],
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{BRIDGE_API_URL}/api/status")
            if res.status_code == 200:
                b_data = res.json()
                bridge_info = {
                    "connected": True,
                    "status": b_data.get("status", "DISCONNECTED"),
                    "qr": b_data.get("qr"),
                    "pairingCode": b_data.get("pairingCode"),
                    "pairingPhone": b_data.get("pairingPhone"),
                    "connectedUser": b_data.get("connectedUser"),
                    "triggerPrefix": b_data.get("triggerPrefix", "-test"),
                    "logs": b_data.get("logs", []),
                }
    except Exception:
        bridge_info["status"] = "OFFLINE"

    # 3. Database metrics & Security metrics & Server Resources
    db_stats = database.get_all_stats()
    security_stats = security_guard.get_security_metrics()
    resources = system_monitor.get_system_metrics()

    return {
        "backend": {
            "status": "online",
            "activeModel": config.OLLAMA_MODEL,
            "ollamaBaseUrl": config.OLLAMA_BASE_URL,
        },
        "ollama": ollama_info,
        "bridge": bridge_info,
        "database": db_stats,
        "security": security_stats,
        "resources": resources,
    }


@app.get("/api/dashboard/messages", tags=["Dashboard"])
async def get_dashboard_messages(limit: int = 50):
    """Returns recent conversation messages for UI inspection."""
    messages = database.get_all_messages(limit=limit)
    return {"messages": messages}


@app.get("/api/dashboard/conversations", tags=["Dashboard"])
async def get_dashboard_conversations():
    """Returns list of distinct active conversations grouped by phone with mute and lead statuses."""
    conversations = database.get_conversations_list()
    statuses = database.get_all_chat_statuses()
    for conv in conversations:
        phone = conv["phone"]
        st = statuses.get(phone, {})
        conv["is_muted"] = st.get("is_muted", False)
        conv["muted_until"] = st.get("muted_until")
        conv["mute_reason"] = st.get("mute_reason")
        conv["is_reservation_lead"] = st.get("is_reservation_lead", False)
        conv["lead_details"] = st.get("lead_details")
    return {"conversations": conversations}


@app.get("/api/dashboard/conversation/{phone}", tags=["Dashboard"])
async def get_dashboard_conversation_history(phone: str):
    """Returns full message history and status for a specific phone conversation."""
    history = database.get_full_conversation(phone=phone)
    st = database.get_chat_status(phone)
    return {"phone": phone, "messages": history, "status": st}


@app.post("/api/chat/mute", tags=["Chat Control"])
async def mute_chat_endpoint(
    phone: str = Body(..., embed=True),
    duration_minutes: int = Body(default=120, embed=True),
    reason: str = Body(default="admin_manual_mute", embed=True),
):
    """Manually silences the AI bot for a specific phone number for duration_minutes (default 2h)."""
    result = database.mute_chat(phone=phone, duration_minutes=duration_minutes, reason=reason)
    logger.info("Chat %s manually muted for %d minutes. Reason: %s", phone, duration_minutes, reason)
    return {"success": True, "data": result}


@app.post("/api/chat/unmute", tags=["Chat Control"])
async def unmute_chat_endpoint(phone: str = Body(..., embed=True)):
    """Unmutes a chat so the AI resumes answering."""
    result = database.unmute_chat(phone=phone)
    logger.info("Chat %s unmuted. AI auto-replies resumed.", phone)
    return {"success": True, "data": result}


@app.get("/api/chat/status/{phone}", tags=["Chat Control"])
async def get_chat_status_endpoint(phone: str):
    """Returns mute and lead status for a specific phone number."""
    status_info = database.get_chat_status(phone)
    return {"success": True, "status": status_info}


@app.get("/api/dashboard/audit-logs", tags=["Audit"])
async def get_audit_logs_endpoint(limit: int = 50, offset: int = 0):
    """Returns outgoing bot message audit logs from the SQLite ledger."""
    logs = database.get_bot_audit_logs(limit=limit, offset=offset)
    return {"success": True, "count": len(logs), "logs": logs}


@app.get("/api/dashboard/audit-logs/verify", tags=["Audit"])
async def verify_audit_logs_endpoint():
    """
    Cryptographically verifies both the JSONL file hash chain and the SQLite ledger hash chain.
    Also checks Linux kernel append-only (chattr +a) status.
    """
    from datetime import datetime, timezone
    file_verify = verify_audit_log_chain()
    db_verify = database.verify_db_audit_chain()
    append_only_status = check_append_only_attribute()

    is_healthy = file_verify["is_valid"] and db_verify["is_valid"]
    return {
        "success": True,
        "overall_status": "SECURE" if is_healthy else "TAMPER_DETECTED",
        "file_chain": {
            **file_verify,
            "append_only_active": append_only_status,
        },
        "db_chain": db_verify,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/settings/filters", tags=["Settings"])
async def get_filter_settings():
    """Retrieves current contact filter, blacklist, debounce duration, admin phone, and LLM configuration."""
    settings = database.get_system_settings()
    masked_key = ""
    if config.LLM_API_KEY:
        if len(config.LLM_API_KEY) > 10:
            masked_key = f"{config.LLM_API_KEY[:6]}...{config.LLM_API_KEY[-4:]}"
        else:
            masked_key = "***"

    return {
        "only_unknown_contacts": settings.get("only_unknown_contacts", "false").lower() == "true",
        "blacklist": [x.strip() for x in settings.get("blacklist", "").split(",") if x.strip()],
        "debounce_seconds": int(settings.get("debounce_seconds", "30")),
        "admin_notify_phone": settings.get("admin_notify_phone", ""),
        "trigger_prefix": settings.get("trigger_prefix", "-test"),
        "ntfy_topic": settings.get("ntfy_topic", "masal-kamp-admin"),
        "ntfy_enabled": settings.get("ntfy_enabled", "true").lower() == "true",
        "auto_mute_on_reservation": settings.get("auto_mute_on_reservation", "true").lower() == "true",
        "mute_duration_minutes": int(settings.get("mute_duration_minutes", "120")),
        "llm_provider": settings.get("llm_provider", config.LLM_PROVIDER),
        "llm_model": settings.get("llm_model", config.LLM_MODEL or "gpt-4o-mini"),
        "has_llm_api_key": bool(config.LLM_API_KEY),
        "masked_api_key": masked_key,
    }


@app.post("/api/settings/filters", tags=["Settings"])
async def update_filter_settings(
    only_unknown_contacts: Optional[bool] = Body(default=None),
    blacklist: Optional[List[str]] = Body(default=None),
    debounce_seconds: Optional[int] = Body(default=None),
    admin_notify_phone: Optional[str] = Body(default=None),
    trigger_prefix: Optional[str] = Body(default=None),
    ntfy_topic: Optional[str] = Body(default=None),
    ntfy_enabled: Optional[bool] = Body(default=None),
    auto_mute_on_reservation: Optional[bool] = Body(default=None),
    mute_duration_minutes: Optional[int] = Body(default=None),
    llm_api_key: Optional[str] = Body(default=None),
    llm_provider: Optional[str] = Body(default=None),
    llm_model: Optional[str] = Body(default=None),
):
    """Updates contact filter, blacklist, debounce, admin phone, ntfy push, and LLM configuration."""
    current = database.get_system_settings()
    updates = {}
    if only_unknown_contacts is not None:
        updates["only_unknown_contacts"] = "true" if only_unknown_contacts else "false"
    if blacklist is not None:
        updates["blacklist"] = ",".join([b.strip() for b in blacklist if b.strip()])
    if debounce_seconds is not None:
        updates["debounce_seconds"] = str(max(1, min(120, debounce_seconds)))
    if admin_notify_phone is not None:
        updates["admin_notify_phone"] = admin_notify_phone.strip()
    if trigger_prefix is not None:
        updates["trigger_prefix"] = trigger_prefix.strip()
    if ntfy_topic is not None:
        updates["ntfy_topic"] = ntfy_topic.strip().lower()
    if ntfy_enabled is not None:
        updates["ntfy_enabled"] = "true" if ntfy_enabled else "false"
    if auto_mute_on_reservation is not None:
        updates["auto_mute_on_reservation"] = "true" if auto_mute_on_reservation else "false"
    if mute_duration_minutes is not None:
        updates["mute_duration_minutes"] = str(max(1, min(1440, mute_duration_minutes)))

    if llm_api_key is not None and llm_api_key.strip():
        clean_key = llm_api_key.strip()
        updates["llm_api_key"] = clean_key
    if llm_provider is not None:
        updates["llm_provider"] = llm_provider.strip().lower()
    if llm_model is not None:
        updates["llm_model"] = llm_model.strip()

    if any(k in updates for k in ["llm_api_key", "llm_provider", "llm_model"]):
        config.update_llm_config(
            provider=updates.get("llm_provider", current.get("llm_provider")),
            api_key=updates.get("llm_api_key", current.get("llm_api_key")),
            model=updates.get("llm_model", current.get("llm_model")),
        )

    database.save_system_settings(updates)
    
    # Also forward updated settings to the WhatsApp bridge
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.post(f"{BRIDGE_API_URL}/api/config", json={
                "only_unknown_contacts": updates.get("only_unknown_contacts", current.get("only_unknown_contacts", "false")) == "true",
                "blacklist": updates.get("blacklist", current.get("blacklist", "")).split(","),
                "debounce_seconds": int(updates.get("debounce_seconds", current.get("debounce_seconds", "30"))),
                "admin_notify_phone": updates.get("admin_notify_phone", current.get("admin_notify_phone", "")),
                "trigger_prefix": updates.get("trigger_prefix", current.get("trigger_prefix", "-test")),
            })
    except Exception as e:
        logger.warning("Could not sync filter settings to bridge: %s", e)

    return {"success": True, "settings": updates}


class KnowledgeUpdateRequest(BaseModel):
    knowledge: str


@app.get("/api/settings/knowledge", tags=["Settings"])
async def get_knowledge_settings():
    """Retrieves active knowledge base, line/char counts, and whether custom override is active."""
    active_text = config.get_active_knowledge()
    default_text = config.load_camp_knowledge()
    custom_in_db = database.get_system_settings().get("custom_knowledge_base", "")
    is_custom = bool(custom_in_db and custom_in_db.strip())

    return {
        "success": True,
        "knowledge": active_text,
        "default_knowledge": default_text,
        "is_custom": is_custom,
        "character_count": len(active_text),
        "word_count": len(active_text.split()),
        "line_count": len(active_text.splitlines()),
    }


@app.post("/api/settings/knowledge", tags=["Settings"])
async def update_knowledge_settings(payload: KnowledgeUpdateRequest):
    """Saves updated knowledge base text to database and updates AI assistant prompt dynamically."""
    clean_text = payload.knowledge.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Bilgi bankası metni boş olamaz.")

    config.save_custom_knowledge(clean_text)
    logger.info("Knowledge base updated via dashboard (%d chars, %d lines).", len(clean_text), len(clean_text.splitlines()))
    return {
        "success": True,
        "message": "Bilgi bankası başarıyla kaydedildi! Asistan yeni bilgilerle yanıt vermeye başladı. 🏕️",
        "character_count": len(clean_text),
        "word_count": len(clean_text.split()),
        "line_count": len(clean_text.splitlines()),
    }


@app.post("/api/settings/knowledge/reset", tags=["Settings"])
async def reset_knowledge_settings():
    """Resets knowledge base back to original camp default."""
    restored = config.reset_to_default_knowledge()
    logger.info("Knowledge base reset to default file (%d chars).", len(restored))
    return {
        "success": True,
        "message": "Bilgi bankası varsayılan orijinal metne sıfırlandı.",
        "knowledge": restored,
        "character_count": len(restored),
        "word_count": len(restored.split()),
        "line_count": len(restored.splitlines()),
    }


@app.post("/api/settings/llm/verify", tags=["Settings"])
async def verify_llm_endpoint(
    api_key: Optional[str] = Body(default=None),
    provider: Optional[str] = Body(default=None),
    model: Optional[str] = Body(default=None),
):
    """Pings the target LLM API with the provided key to verify credentials and save them if valid."""
    target_key = api_key.strip() if api_key else config.LLM_API_KEY
    if not target_key:
        return {"success": False, "connected": False, "message": "API anahtarı boş olamaz."}

    target_provider = (provider or config.LLM_PROVIDER or "openai").lower()
    target_model = model or config.LLM_MODEL or "gpt-4o-mini"

    # Auto-align provider and model if mismatched (e.g. Ollama model selected with OpenAI key)
    if target_key.startswith("gsk_"):
        target_provider = "groq"
        if "llama" not in target_model.lower():
            target_model = "llama-3.3-70b-versatile"
    elif target_key.startswith("sk-or-"):
        target_provider = "openrouter"
        target_model = "meta-llama/llama-3.3-70b-instruct"
    elif target_key.startswith("sk-"):
        target_provider = "openai"
        if not target_model.startswith("gpt"):
            target_model = "gpt-4o-mini"
    
    base_url = (config.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    if target_provider == "groq":
        base_url = "https://api.groq.com/openai/v1"
        if not model:
            target_model = "llama-3.3-70b-versatile"
    elif target_provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        if not model:
            target_model = "meta-llama/llama-3.3-70b-instruct"
    elif target_provider == "openai":
        base_url = "https://api.openai.com/v1"
        if not model:
            target_model = "gpt-4o-mini"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {target_key}",
    }
    payload = {
        "model": target_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 2,
    }

    try:
        async with httpx.AsyncClient(timeout=9.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            if resp.status_code == 200:
                # Save verified key and provider
                updates = {
                    "llm_api_key": target_key,
                    "llm_provider": target_provider,
                    "llm_model": target_model,
                }
                database.save_system_settings(updates)
                config.update_llm_config(
                    provider=target_provider,
                    api_key=target_key,
                    model=target_model,
                    base_url=base_url,
                )
                masked_key = f"{target_key[:6]}...{target_key[-4:]}" if len(target_key) > 10 else "***"
                return {
                    "success": True,
                    "connected": True,
                    "provider": target_provider,
                    "model": target_model,
                    "masked_key": masked_key,
                    "message": f"{target_provider.upper()} API anahtarı başarıyla doğrulandı ve bağlandı! ({target_model})",
                }
            else:
                err_detail = resp.text[:180]
                return {
                    "success": False,
                    "connected": False,
                    "status_code": resp.status_code,
                    "message": f"Doğrulama başarısız (HTTP {resp.status_code}): {err_detail}",
                }
    except Exception as e:
        return {
            "success": False,
            "connected": False,
            "message": f"Bağlantı hatası: {str(e)}",
        }


@app.post("/api/settings/ntfy/test", tags=["Settings"])
async def test_ntfy_endpoint(topic: Optional[str] = Body(default=None, embed=True)):
    """Sends an immediate test push notification via ntfy.sh."""
    target_topic = topic or database.get_system_settings().get("ntfy_topic", "masal-kamp-admin")
    success = await notifier.send_test_alert(topic=target_topic)
    if not success:
        raise HTTPException(
            status_code=502,
            detail="ntfy bildirim gönderimi başarısız oldu. İnternet bağlantınızı kontrol edin."
        )
    return {
        "success": True,
        "message": f"Test bildirimi '{target_topic}' ntfy kanalına başarıyla gönderildi!",
        "topic": target_topic,
    }



@app.post("/api/dashboard/clear-memory", tags=["Dashboard"])
async def clear_database_memory(phone: Optional[str] = Body(default=None, embed=True)):
    """Clears memory for a specific phone or all records."""
    if phone:
        count = database.clear_history(phone)
        security_guard.unblock_phone(phone)
    else:
        count = database.clear_all_history()
    return {"success": True, "cleared_count": count}


@app.post("/api/dashboard/set-model", tags=["Dashboard"])
async def set_active_model(model: str = Body(..., embed=True)):
    """Dynamically updates active Ollama model in memory."""
    config.OLLAMA_MODEL = model.strip()
    logger.info("Active Ollama Model dynamically switched to: %s", config.OLLAMA_MODEL)
    return {"success": True, "active_model": config.OLLAMA_MODEL}


@app.get("/api/dashboard/security", tags=["Security"])
async def get_security_settings():
    """Returns current security and rate limiting settings."""
    return security_guard.get_security_metrics()


@app.post("/api/dashboard/security", tags=["Security"])
async def update_security_settings(
    rate_limit_per_minute: Optional[int] = Body(default=None),
    rate_limit_daily: Optional[int] = Body(default=None),
    enable_jailbreak_filter: Optional[bool] = Body(default=None),
    enable_offtopic_filter: Optional[bool] = Body(default=None),
):
    """Updates security guard settings on the fly."""
    if rate_limit_per_minute is not None:
        security_guard.rate_limit_per_minute = max(1, rate_limit_per_minute)
    if rate_limit_daily is not None:
        security_guard.rate_limit_daily = max(1, rate_limit_daily)
    if enable_jailbreak_filter is not None:
        security_guard.enable_jailbreak_filter = enable_jailbreak_filter
    if enable_offtopic_filter is not None:
        security_guard.enable_offtopic_filter = enable_offtopic_filter

    logger.info("Security settings updated: %s", security_guard.get_security_metrics())
    return {"success": True, "metrics": security_guard.get_security_metrics()}


@app.post("/api/dashboard/security/unblock", tags=["Security"])
async def unblock_phone_number(phone: str = Body(..., embed=True)):
    """Unblocks a specific phone number from rate limiting."""
    security_guard.unblock_phone(phone)
    return {"success": True, "phone": phone}


# Proxy endpoints for WhatsApp Bridge
@app.post("/api/bridge/connect", tags=["Bridge Control"])
async def bridge_connect(authed: bool = Depends(verify_panel_auth)):
    ensure_bridge_service_running()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{BRIDGE_API_URL}/api/connect")
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Bridge unreachable: {str(e)}")


@app.post("/api/bridge/switch-mode", tags=["Bridge Control"])
async def bridge_switch_mode(
    mode: str = Body(..., embed=True),
    authed: bool = Depends(verify_panel_auth),
):
    """Switches WhatsApp Web view seamlessly between QR code mode and 8-digit Pairing Code mode."""
    ensure_bridge_service_running()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{BRIDGE_API_URL}/api/switch-mode", json={"mode": mode})
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Bridge unreachable: {str(e)}")


@app.post("/api/bridge/pair", tags=["Bridge Control"])
async def bridge_pair(
    phone_number: str = Body(..., embed=True),
    authed: bool = Depends(verify_panel_auth),
):
    """Requests an 8-character pairing code for remote client WhatsApp pairing."""
    ensure_bridge_service_running()
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.post(f"{BRIDGE_API_URL}/api/pair", json={"phoneNumber": phone_number})
            data = res.json()
            if not res.is_success or not data.get("success", False):
                err_msg = data.get("error") or "Eşleştirme kodu oluşturulamadı"
                raise HTTPException(status_code=res.status_code if res.status_code != 200 else 400, detail=err_msg)
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Bridge hatası: {str(e)}")



@app.get("/api/bridge/screenshot", tags=["Bridge Control"])
async def bridge_screenshot(authed: bool = Depends(verify_panel_auth)):
    """Captures and returns the live Chromium WhatsApp Web screen for debugging."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{BRIDGE_API_URL}/api/debug/screenshot")
            return Response(content=res.content, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Screenshot error: {str(e)}")




@app.post("/api/bridge/disconnect", tags=["Bridge Control"])
async def bridge_disconnect(
    body: Optional[Dict[str, Any]] = Body(default=None),
    authed: bool = Depends(verify_panel_auth),
):
    clear_session = False
    if body and isinstance(body, dict):
        clear_session = bool(body.get("clearSession", False))
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{BRIDGE_API_URL}/api/disconnect", json={"clearSession": clear_session})
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Bridge unreachable: {str(e)}")


@app.post("/api/bridge/prefix", tags=["Bridge Control"])
async def bridge_set_prefix(
    prefix: str = Body(..., embed=True),
    authed: bool = Depends(verify_panel_auth),
):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(f"{BRIDGE_API_URL}/api/prefix", json={"prefix": prefix})
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Bridge unreachable: {str(e)}")


@app.post("/api/system/start-services", tags=["System Management"])
async def start_services_endpoint():
    """
    Master starter for system services (replaces legacy local start_all.bat).
    Ensures bridge process / container is awake and triggers WhatsApp Web puppeteer connection.
    """
    ensure_bridge_service_running()
    bridge_result = {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{BRIDGE_API_URL}/api/connect")
            if res.status_code == 200:
                bridge_result = res.json()
            else:
                bridge_result = {"status_code": res.status_code, "detail": res.text[:120]}
    except Exception as exc:
        logger.warning("Could not ping bridge /api/connect: %s", exc)
        bridge_result = {"error": str(exc)}

    return {
        "success": True,
        "message": "Servisler başarıyla başlatıldı! WhatsApp köprü bağlantısı tetiklendi.",
        "bridge": bridge_result,
        "backend": "online",
        "timestamp": time.time(),
    }


@app.post("/api/system/stop-bridge", tags=["System Management"])
async def stop_bridge_endpoint():
    """Stops the WhatsApp Bridge and kills background node processes."""
    try:
        cleanup_bridge_service()
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/F", "/IM", "node.exe"], capture_output=True)
            except Exception:
                pass
        return {"success": True, "message": "WhatsApp Köprüsü (Node.js/Puppeteer) başarıyla durduruldu."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Köprü durdurulamadı: {str(e)}")


@app.post("/api/system/shutdown", tags=["System Management"])
async def shutdown_system():
    """Kills background Node/Chromium processes and cleanly shuts down FastAPI."""
    try:
        cleanup_bridge_service()
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/F", "/IM", "node.exe"], capture_output=True)
            except Exception:
                pass
    except Exception as e:
        logger.warning("Error during process cleanup: %s", e)

    async def _delayed_exit():
        await asyncio.sleep(0.5)
        logger.info("Exiting application process...")
        os._exit(0)

    asyncio.create_task(_delayed_exit())
    return {"success": True, "message": "Tüm servisler ve arka plan süreçleri kapatılıyor..."}


# Serve Frontend Web App
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        response = FileResponse(FRONTEND_DIR / "index.html")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


if __name__ == "__main__":
    logger.info("Starting FastAPI server on %s:%d", HOST, PORT)
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
