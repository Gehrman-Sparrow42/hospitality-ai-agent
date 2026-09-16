import time
import re
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
import logging

logger = logging.getLogger("camp-bot-security")

# Rate Limiter State (Phone -> List of Unix timestamps)
_request_timestamps: Dict[str, List[float]] = defaultdict(list)
_blocked_phones: Dict[str, float] = {}  # Phone -> Unblock timestamp

REFUSAL_OFFTOPIC = (
    "Ben yalnızca Masal Kamp ile ilgili konularda (giriş/çıkış saatleri, "
    "kamp alanları, konaklama ve tesis imkanları) bilgi vermek "
    "üzere görevlendirilmiş bir asistanım. Kamp dışı genel konularda destek verememekteyim."
)

REFUSAL_JAILBREAK = (
    "Üzgünüm, sistem güvenlik kuralları gereği bu tür komutları işleyemiyorum. "
    "Yalnızca Masal Kamp organizasyonu ve konaklama ile ilgili sorularınıza yanıt verebilirim."
)

FALLBACK_COORDINATOR = (
    "Bu konuyu kamp koordinatörümüze iletiyorum, en kısa sürede bilgi verilecektir."
)


class SecurityGuard:
    def __init__(
        self,
        rate_limit_per_minute: int = 5,
        rate_limit_daily: int = 30,
        enable_jailbreak_filter: bool = True,
        enable_offtopic_filter: bool = True,
    ):
        self.rate_limit_per_minute = rate_limit_per_minute
        self.rate_limit_daily = rate_limit_daily
        self.enable_jailbreak_filter = enable_jailbreak_filter
        self.enable_offtopic_filter = enable_offtopic_filter

        # Comprehensive prompt injection & jailbreak patterns
        self.jailbreak_patterns = [
            r"(?i)\b(ignore|bypass|override|forget)\b.*\b(instructions?|prompt|rules?|system|guidelines?)\b",
            r"(?i)\b(system\s+prompt|dan\s+mode|jailbreak|unrestricted|developer\s+mode)\b",
            r"(?i)\b(bütün|tüm|önceki)\s+(talimatları|kuralları|komutları|yönergeleri)\s+(unut|yok\s+say|sil|boşver)\b",
            r"(?i)\b(sen\s+artık|bundan\s+sonra|kendini)\b.*\b(olarak\s+davran|gibi\s+davran|rolü\s+oyna|farz\s+et)\b",
            r"(?i)\b(sistem\s+kurallarını|gizli\s+talimatları|promptunu|promptunu)\s+(yaz|göster|listele|söyle|ver)\b",
            r"(?i)\b(pretend|act\s+as\s+a?|roleplay|simulate)\b",
            r"(?i)\b(gizli\s+talimat|gizli\s+kural|sistem\s+yönergesi)\b",
        ]

        # Comprehensive off-topic & chatbot misuse patterns (creative writing, coding, math, general AI exploitation)
        self.offtopic_patterns = [
            # 1. Creative / Poetry / Stories / Entertainment
            r"(?i)\b(şiir|siir|şiiri|siiri|şiirler|siirler|şarkı\s+sözü|sarki\s+sozu|beste|mani|fıkra\s+anlat|fikra\s+anlat|masal\s+anlat|roman\s+yaz)\b",
            r"(?i)\b(poem|poetry|tell\s+a\s+joke|write\s+a\s+story|write\s+a\s+song)\b",
            
            # 2. Programming / Coding / Tech
            r"(?i)\b(python|javascript|typescript|html|css|golang|rust|php|csharp)\b",
            r"(?i)\b(kod\s+yaz|script\s+yaz|program\s+yaz|kodla|web\s+scraper|fonksiyon\s+yaz)\b",
            r"(?i)\b(write\s+code|write\s+a\s+script|coding)\b",
            
            # 3. Homework / Academic Equations
            r"(?i)\b(matematik\s+ödevi|türevi|integrali|denklemi\s+çöz)\b",
            
            # 4. Inappropriate / Romantic Misuse
            r"(?i)\b(sevgilim\s+ol|flört\s+et|bana\s+aşık\s+ol)\b",
            r"(?i)\b(falıma\s+bak|burcum|astroloji|rüya\s+tabiri)\b",
        ]

        # Explicit camp intent phrases that should NEVER be false-positive rejected
        self.camp_explicit_whitelist = [
            "giriş saat", "çıkış saat", "kampa giriş", "kamp çıkış",
            "çadır", "uyku tulum", "mat", "kafa feneri", "el feneri",
            "sabah kahvaltı", "akşam yemek", "öğle yemek", "yiyecek", "içecek",
            "wifi", "wi-fi", "internet", "şebeke", "kafeterya",
            "rezervasyon", "fiyat", "ücret", "kapora", "konaklama",
            "evcil hayvan", "köpek", "kedi", "çocuk", "etkinlik",
            "ulaşım", "nerede", "adres", "otopark", "konum",
            "koordinatör", "kamp alanı", "/reset", "merhaba", "selam", "nasılsın"
        ]

    def check_rate_limit(self, phone: str) -> Tuple[bool, Optional[str]]:
        """
        Sliding-window rate limiter per phone number.
        Returns: (is_allowed: bool, reason_message: Optional[str])
        """
        phone = phone.strip()
        now = time.time()

        # Check temporary block
        if phone in _blocked_phones:
            unblock_time = _blocked_phones[phone]
            if now < unblock_time:
                remaining_sec = int(unblock_time - now)
                return False, f"Çok fazla istek gönderdiniz. Güvenlik nedeniyle {remaining_sec} saniye sonra tekrar deneyebilirsiniz."
            else:
                del _blocked_phones[phone]

        # Clean timestamps older than 24 hours (86400 seconds)
        timestamps = [t for t in _request_timestamps[phone] if now - t < 86400]

        # 1. Check daily limit
        if len(timestamps) >= self.rate_limit_daily:
            _blocked_phones[phone] = now + 3600  # 1 hour cooldown
            logger.warning("Daily rate limit exceeded for %s (%d requests).", phone, len(timestamps))
            return False, "Günlük mesaj limitine ulaştınız. Kamp asistanı yoğunluğu önlemek için yarın tekrar hizmetinizde olacaktır."

        # 2. Check per-minute limit (last 60 seconds)
        recent_timestamps = [t for t in timestamps if now - t < 60]
        if len(recent_timestamps) >= self.rate_limit_per_minute:
            _blocked_phones[phone] = now + 60  # 1 minute temporary cooldown
            logger.warning("Per-minute rate limit exceeded for %s (%d reqs/min). Cooldown applied.", phone, len(recent_timestamps))
            return False, "Çok hızlı mesaj gönderiyorsunuz. Lütfen 1 dakika bekleyip tekrar yazınız."

        # Record this request
        timestamps.append(now)
        _request_timestamps[phone] = timestamps
        return True, None

    def check_input_safety(self, message: str) -> Tuple[bool, Optional[str]]:
        """
        Validates user input against prompt injection, jailbreaks, and off-topic chatbot abuse.
        """
        if not message or not message.strip():
            return False, "Boş mesaj gönderilemez."

        msg_clean = message.strip()

        # Whitelist /reset command
        if msg_clean.lower() == "/reset":
            return True, None

        # 1. Jailbreak & Prompt Injection Check
        if self.enable_jailbreak_filter:
            for pattern in self.jailbreak_patterns:
                if re.search(pattern, msg_clean):
                    logger.warning("Jailbreak / Prompt Injection pattern detected: '%s' in '%s'", pattern, msg_clean)
                    return False, REFUSAL_JAILBREAK

        # 2. Off-Topic & AI Chatbot Abuse Check
        if self.enable_offtopic_filter:
            for pattern in self.offtopic_patterns:
                if re.search(pattern, msg_clean):
                    # Check if it has explicit camp keywords (to prevent rare false positives)
                    is_genuine_camp_query = any(cw in msg_clean.lower() for cw in self.camp_explicit_whitelist)
                    if not is_genuine_camp_query:
                        logger.warning("Off-topic / Chatbot abuse detected by pattern '%s': '%s'", pattern, msg_clean)
                        return False, REFUSAL_OFFTOPIC

        return True, None

    def sanitize_output(self, assistant_reply: str) -> str:
        """
        Sanitizes model output to eliminate foreign tokens and blatant code/poetry leak.
        """
        if not assistant_reply or not assistant_reply.strip():
            return "Nasıl yardımcı olabilirim? Kampımızla ilgili merak ettiğiniz bir konu varsa sorabilirsiniz."

        reply = assistant_reply.strip()

        # 1. Detect CJK/Chinese or foreign characters leaking from base model
        if re.search(r"[\u4e00-\u9fff]", reply):
            logger.warning("Sanitizer caught foreign characters in reply. Replaced with clean fallback.")
            return "Nasıl yardımcı olabilirim? Kamp alanı, konaklama veya fiyatlarla ilgili bilgi alabilirsiniz."

        # 2. Intercept code leak (raw markdown codeblocks for programming)
        if re.search(r"```(python|javascript|html|css|json|sql|bash|sh)", reply):
            logger.warning("Sanitizer caught code block in output. Overriding with scope refusal.")
            return REFUSAL_OFFTOPIC

        # 3. Intercept IBAN leak or unsolicited bank/payment sharing
        # Matches TR IBAN (TR + 24 digits with optional spaces) or general IBAN format
        iban_pattern = r"(?i)\b(?:TR\s*(?:\d\s*){24}|[A-Z]{2}\s*(?:\d\s*){2}(?:[A-Z0-9]\s*){12,30})\b"
        if re.search(iban_pattern, reply):
            logger.warning("Sanitizer caught IBAN in output! Redacting and enforcing human handover.")
            return (
                "Ödeme, kapora ve hesap işlemlerimiz doğrudan işletme yetkilimiz tarafından güvenli şekilde "
                "yürütülmektedir. Yetkilimize bilgi verdim, en kısa sürede sizinle buradan iletişime geçecektir. "
                "[YETKILI_DEVRET: Müşteri ödeme/kapora/IBAN talebi]"
            )

        return reply

    def get_security_metrics(self) -> Dict:
        """Returns active rate limiter and security metrics."""
        now = time.time()
        active_users = len(_request_timestamps)
        currently_blocked = [
            {"phone": p, "remaining_seconds": max(0, int(t - now))}
            for p, t in _blocked_phones.items()
            if t > now
        ]
        return {
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "rate_limit_daily": self.rate_limit_daily,
            "enable_jailbreak_filter": self.enable_jailbreak_filter,
            "enable_offtopic_filter": self.enable_offtopic_filter,
            "active_tracked_phones": active_users,
            "blocked_phones_count": len(currently_blocked),
            "blocked_phones": currently_blocked,
        }

    def detect_intervention_intent(self, message: str) -> bool:
        """Detects severe complaints or emergency legal/scam accusations requiring immediate handoff."""
        msg = message.lower().strip()
        patterns = [
            r"(?i)\b(şikayetim\s+var|dolandırıcı|dava\s+aç|savcılığa|tüketici\s+hakem|avukatıma)\b",
            r"(?i)\b(acil\s+yetkili\s+bağla|derhal\s+yetkiliye)\b",
        ]
        return any(bool(re.search(p, msg)) for p in patterns)

    def detect_reservation_intent(self, message: str) -> bool:
        """Reservation qualification is now handled interactively by LLM to gather details first."""
        return False

    def unblock_phone(self, phone: str) -> bool:
        """Clears blocks and rate limit history for a phone number."""
        phone = phone.strip()
        if phone in _blocked_phones:
            del _blocked_phones[phone]
        if phone in _request_timestamps:
            del _request_timestamps[phone]
        return True


# Global security instance
security_guard = SecurityGuard()


class LoginRateLimiter:
    """
    Brute-force protection for admin panel login attempts (/api/auth/login).
    - Tracks failed attempts per IP address using a sliding window.
    - Max 5 failed attempts allowed within 10 minutes.
    - On 5th failure: Locks out the IP for 15 minutes (900 seconds).
    - Checks remaining lockout seconds and returns structured time.
    - An artificial 1-second delay is added on failed attempts to throttle fast automated tools.
    - A successful login resets the failure counter for that IP.
    """
    def __init__(self, max_attempts: int = 5, window_seconds: int = 600, lockout_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._failed_attempts: Dict[str, List[float]] = defaultdict(list)
        self._lockouts: Dict[str, float] = {}

    def is_locked_out(self, ip: str) -> Tuple[bool, int]:
        """Checks if an IP is currently locked out. Returns (is_locked, remaining_seconds)."""
        now = time.time()
        ip = (ip or "127.0.0.1").strip()
        if ip in self._lockouts:
            unlock_time = self._lockouts[ip]
            if now < unlock_time:
                return True, max(1, int(unlock_time - now))
            else:
                del self._lockouts[ip]
                self._failed_attempts[ip] = []
        return False, 0

    def record_failure(self, ip: str) -> Tuple[bool, int]:
        """
        Records a failed attempt for an IP.
        Returns: (is_now_locked: bool, remaining_attempts_or_lockout_seconds: int)
        """
        now = time.time()
        ip = (ip or "127.0.0.1").strip()
        timestamps = [t for t in self._failed_attempts[ip] if now - t < self.window_seconds]
        timestamps.append(now)
        self._failed_attempts[ip] = timestamps

        if len(timestamps) >= self.max_attempts:
            unlock_time = now + self.lockout_seconds
            self._lockouts[ip] = unlock_time
            logger.warning(
                "Admin panel brute-force lockout triggered for IP %s (%d failed attempts). Locked for %ds.",
                ip, len(timestamps), self.lockout_seconds
            )
            return True, self.lockout_seconds

        remaining_attempts = max(0, self.max_attempts - len(timestamps))
        return False, remaining_attempts

    def record_success(self, ip: str) -> None:
        """Clears failure history upon successful authentication."""
        ip = (ip or "127.0.0.1").strip()
        self._failed_attempts.pop(ip, None)
        self._lockouts.pop(ip, None)

    def unblock_ip(self, ip: str) -> None:
        """Manually unblocks an IP (useful for admin / testing)."""
        ip = (ip or "127.0.0.1").strip()
        self._failed_attempts.pop(ip, None)
        self._lockouts.pop(ip, None)


login_rate_limiter = LoginRateLimiter()


import json
import hashlib
import subprocess
from datetime import datetime, timezone
import os
from pathlib import Path

GENESIS_HASH = "0" * 64


def compute_entry_hash(
    prev_hash: str,
    timestamp: str,
    recipient_jid: str,
    message_preview: str,
    status: str,
) -> str:
    """Computes canonical SHA-256 hash for an audit log entry."""
    payload = f"{prev_hash}:{timestamp}:{recipient_jid}:{message_preview}:{status}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_last_audit_entry_hash(target_path: Path) -> str:
    """
    Reads the last non-empty line of the audit log file to extract its entry_hash.
    Returns GENESIS_HASH if the file does not exist, is empty, or has no valid prior hash.
    """
    if not target_path.exists() or target_path.stat().st_size == 0:
        return GENESIS_HASH

    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if line.strip()]
        if not lines:
            return GENESIS_HASH

        last_line = lines[-1]
        try:
            data = json.loads(last_line)
            if "entry_hash" in data and data["entry_hash"]:
                return str(data["entry_hash"]).strip()
            if "hash" in data and data["hash"]:
                return str(data["hash"]).strip()
        except Exception:
            pass

        # Fallback for legacy plain lines: sha-256 of the raw string
        return hashlib.sha256(last_line.encode("utf-8")).hexdigest()
    except Exception as exc:
        logger.warning("Could not read last audit entry hash from %s: %s", target_path, exc)
        return GENESIS_HASH


def resolve_audit_log_path(log_file_path: Optional[str] = None) -> Path:
    """Resolves standard audit log path respecting environment variables and deployment structure."""
    if log_file_path:
        return Path(log_file_path)
    env_path = os.getenv("AUDIT_LOG_PATH")
    if env_path:
        return Path(env_path)
    
    # Priority paths: project root / app root
    docker_path = Path("/app/bot_audit.log")
    if docker_path.parent.exists() and os.getenv("RUNNING_IN_DOCKER"):
        return docker_path

    repo_root = Path(__file__).resolve().parent.parent / "bot_audit.log"
    if repo_root.parent.exists():
        return repo_root

    return Path("bot_audit.log")


def append_audit_log_file(
    recipient_jid: str,
    message_preview: str,
    status: str = "SENT",
    log_file_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Appends an outgoing bot message record to bot_audit.log in JSON Lines (jsonl) format
    using a cryptographic SHA-256 hash chain (blockchain-like Merkle continuity).
    
    Every entry contains:
      - timestamp: ISO-8601 UTC string
      - recipient_jid: phone/JID
      - message_preview: exact outgoing message body
      - status: SENT or FAILED
      - prev_hash: SHA-256 hash of previous entry (or 64 zeros for genesis)
      - entry_hash: SHA-256(prev_hash:timestamp:recipient_jid:message_preview:status)
      
    Strict append-only compliance: opens with mode "a" so it runs cleanly under Linux chattr +a.
    Non-blocking / failsafe: never raises errors or halts bot operation.
    """
    try:
        target_path = resolve_audit_log_path(log_file_path)
        prev_hash = get_last_audit_entry_hash(target_path)
        now_iso = datetime.now(timezone.utc).isoformat()
        rec_clean = str(recipient_jid or "").strip()
        msg_clean = str(message_preview or "").strip()
        st_clean = str(status or "SENT").strip().upper()

        entry_hash = compute_entry_hash(prev_hash, now_iso, rec_clean, msg_clean, st_clean)

        entry = {
            "timestamp": now_iso,
            "recipient_jid": rec_clean,
            "message_preview": msg_clean,
            "status": st_clean,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(line)
        return entry
    except Exception as exc:
        logger.warning("Failed to write to bot_audit.log: %s", exc)
        return None


def verify_audit_log_chain(log_file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Cryptographically verifies the SHA-256 hash chain in bot_audit.log.
    Verifies that:
      1. Line 1 prev_hash == GENESIS_HASH
      2. For all line i > 1, line[i].prev_hash == line[i-1].entry_hash
      3. For every line, entry_hash == compute_entry_hash(...)
      
    Returns:
      {
        "is_valid": bool,
        "total_records": int,
        "latest_hash": str,
        "genesis_hash": str,
        "failed_at_line": Optional[int],
        "error": Optional[str]
      }
    """
    target_path = resolve_audit_log_path(log_file_path)
    if not target_path.exists() or target_path.stat().st_size == 0:
        return {
            "is_valid": True,
            "total_records": 0,
            "latest_hash": GENESIS_HASH,
            "genesis_hash": GENESIS_HASH,
            "failed_at_line": None,
            "error": None,
            "file_path": str(target_path),
        }

    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if line.strip()]

        expected_prev_hash = GENESIS_HASH
        for idx, raw_line in enumerate(lines, start=1):
            try:
                item = json.loads(raw_line)
            except Exception as e:
                return {
                    "is_valid": False,
                    "total_records": len(lines),
                    "latest_hash": None,
                    "genesis_hash": GENESIS_HASH,
                    "failed_at_line": idx,
                    "error": f"Malformed JSON on line {idx}: {e}",
                    "file_path": str(target_path),
                }

            prev_h = item.get("prev_hash")
            entry_h = item.get("entry_hash")

            if prev_h != expected_prev_hash:
                return {
                    "is_valid": False,
                    "total_records": len(lines),
                    "latest_hash": None,
                    "genesis_hash": GENESIS_HASH,
                    "failed_at_line": idx,
                    "error": f"Chain broken at line {idx}: expected prev_hash '{expected_prev_hash}', found '{prev_h}'",
                    "file_path": str(target_path),
                }

            recalculated_hash = compute_entry_hash(
                prev_h,
                item.get("timestamp", ""),
                item.get("recipient_jid", ""),
                item.get("message_preview", ""),
                item.get("status", ""),
            )

            if entry_h != recalculated_hash:
                return {
                    "is_valid": False,
                    "total_records": len(lines),
                    "latest_hash": None,
                    "genesis_hash": GENESIS_HASH,
                    "failed_at_line": idx,
                    "error": f"Tampering detected at line {idx}: signature mismatch. Expected '{recalculated_hash}', found '{entry_h}'",
                    "file_path": str(target_path),
                }

            expected_prev_hash = entry_h

        return {
            "is_valid": True,
            "total_records": len(lines),
            "latest_hash": expected_prev_hash,
            "genesis_hash": GENESIS_HASH,
            "failed_at_line": None,
            "error": None,
            "file_path": str(target_path),
        }
    except Exception as exc:
        return {
            "is_valid": False,
            "total_records": 0,
            "latest_hash": None,
            "genesis_hash": GENESIS_HASH,
            "failed_at_line": None,
            "error": f"Verification exception: {exc}",
            "file_path": str(target_path),
        }


def check_append_only_attribute(log_file_path: Optional[str] = None) -> bool:
    """
    Checks whether the file has the Linux ext2/ext3/ext4 append-only (+a) attribute set.
    Uses 'lsattr' utility on Linux. Returns False on Windows or if unset.
    """
    if os.name == "nt":
        return False

    target_path = resolve_audit_log_path(log_file_path)
    if not target_path.exists():
        return False

    try:
        proc = subprocess.run(
            ["lsattr", str(target_path)],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0:
            # Format: '-----a-------e-- /path/to/file'
            attrs_part = proc.stdout.split()[0] if proc.stdout.split() else ""
            return "a" in attrs_part
    except Exception as exc:
        logger.debug("lsattr check failed: %s", exc)
    return False


def enable_append_only_attribute(log_file_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Applies the Linux append-only (+a) file attribute using chattr.
    Ensures root or sudo cannot overwrite or truncate the audit log.
    """
    if os.name == "nt":
        return False, "Not supported on Windows OS (requires POSIX ext2/ext3/ext4)"

    target_path = resolve_audit_log_path(log_file_path)
    try:
        if not target_path.exists():
            target_path.touch(mode=0o600, exist_ok=True)

        proc = subprocess.run(
            ["chattr", "+a", str(target_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return True, f"Append-only attribute (+a) successfully applied to {target_path}"

        # Try sudo if non-root
        sudo_proc = subprocess.run(
            ["sudo", "chattr", "+a", str(target_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if sudo_proc.returncode == 0:
            return True, f"Append-only attribute (+a) successfully applied with sudo to {target_path}"

        err_msg = sudo_proc.stderr or proc.stderr or "Permission denied"
        return False, f"Could not apply chattr +a: {err_msg.strip()}"
    except Exception as exc:
        return False, f"chattr execution error: {exc}"


def secure_session_directories(paths: Optional[List[str]] = None) -> None:
    """
    Ensures directory permissions on session and auth folders (.wwebjs_auth, auth_info, session)
    are strictly restricted to 0700 (owner-only access) on POSIX/Linux platforms.
    """
    if os.name == "nt":
        return

    default_paths = [
        Path(__file__).resolve().parent.parent / "bridge" / ".wwebjs_auth",
        Path(__file__).resolve().parent.parent / ".wwebjs_auth",
        Path(__file__).resolve().parent.parent / "auth_info",
        Path(__file__).resolve().parent.parent / "session",
        Path(".wwebjs_auth"),
        Path("auth_info"),
        Path("session"),
    ]
    target_dirs = [Path(p) for p in paths] if paths else default_paths

    for p in target_dirs:
        try:
            if p.exists() and p.is_dir():
                os.chmod(p, 0o700)
                for root, dirs, files in os.walk(p):
                    for d_name in dirs:
                        os.chmod(os.path.join(root, d_name), 0o700)
                    for f_name in files:
                        os.chmod(os.path.join(root, f_name), 0o600)
        except Exception as exc:
            logger.warning("Could not set 0700 permissions on session dir %s: %s", p, exc)


def ensure_gitignore_entries(repo_root: Optional[str] = None) -> None:
    """
    Verifies and automatically adds session folders, bot_audit.log, and .env files
    to .gitignore to prevent accidental git commits.
    """
    try:
        candidate_paths = [
            Path(repo_root) / ".gitignore" if repo_root else None,
            Path(__file__).resolve().parent.parent / ".gitignore",
            Path(".gitignore"),
        ]
        required_patterns = [
            ".env",
            "*.env",
            "bot_audit.log",
            "*/bot_audit.log",
            ".wwebjs_auth/",
            "auth_info/",
            "session/",
            "*/.wwebjs_auth/",
            "*/auth_info/",
            "*/session/",
        ]
        for cp in candidate_paths:
            if cp and cp.exists():
                content = cp.read_text(encoding="utf-8")
                missing = [p for p in required_patterns if p not in content]
                if missing:
                    addition = "\n" + "\n".join(missing) + "\n"
                    with open(cp, "a", encoding="utf-8") as f:
                        f.write(addition)
                    logger.info("Automatically updated %s with security exclusions.", cp)
    except Exception as exc:
        logger.warning("Could not auto-update .gitignore: %s", exc)

