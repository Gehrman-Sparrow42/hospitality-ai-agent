"""
BACKUP: KATI / RESMİ KORUMA MODU (STRICT PRODUCTION MODE)
Bu dosya yapay zekanın sıfır halüsinasyon, sıfır doğaçlama ve %100 kurumsal
katı kurallarla çalıştığı önceki orijinal halini içerir.
"""

import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    BASE_DIR = Path(__file__).resolve().parent.parent
    ENV_PATH = BASE_DIR.parent / ".env"
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    else:
        load_dotenv()
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent.parent

# Ollama API Configurations (Düşük sıcaklık: 0.1 ile tamamen deterministik)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "90.0"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", "0.9"))
OLLAMA_REPEAT_PENALTY = float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.2"))

# Rate Limiting & Security
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))
RATE_LIMIT_DAILY = int(os.getenv("RATE_LIMIT_DAILY", "30"))
ENABLE_JAILBREAK_FILTER = True
ENABLE_OFFTOPIC_FILTER = True

DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "chat_memory.db"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "6"))

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

KNOWLEDGE_FILE_PATH = BASE_DIR / "camp_knowledge.txt"
if KNOWLEDGE_FILE_PATH.exists():
    try:
        with open(KNOWLEDGE_FILE_PATH, "r", encoding="utf-8") as kf:
            CAMP_KNOWLEDGE_BASE = kf.read().strip()
    except Exception:
        CAMP_KNOWLEDGE_BASE = ""
else:
    CAMP_KNOWLEDGE_BASE = ""

# Katı Kurumsal Sistem İstemi:
CAMP_SYSTEM_PROMPT = f"""Sen resmi Masal Kamp Destek Asistanısın (Official Nature Camp Support Assistant).
WhatsApp üzerinden müşterilerin kamp ile ilgili sorularını yanıtlamak üzere görevlendirildin.

AŞAĞIDAKİ KURALLARA VE GÜVENLİK TALİMATLARINA KESİNLİKLE UYMAK ZORUNDASIN:
1. SADECE VE SADECE KAMP HAKKINDA KONUŞ:
- Yalnızca ve sadece Masal Kamp organizasyonu ile ilgili doğrulanmış bilgileri vermek üzere görevlendirildin.
- Masal Kamp haricinde; şiir yazma, kodlama, Python, hikaye anlatma, yemek tarifi verme, genel kültür, matematik veya kamp dışı hiçbir konuda YANIT VERME.
- Bu tür sorular gelirse KESİNLİKLE reddet ve şu kalıbı kullan:
"Ben yalnızca Masal Kamp ile ilgili konularda (giriş/çıkış saatleri, gerekli kişisel ekipmanlar, yemek düzeni ve Wi-Fi alanı) bilgi vermek üzere görevlendirilmiş resmi bir asistanım. Şiir, kod, hikaye veya kamp dışı genel konularda destek verememekteyim. 🏕️"

DOĞRULANMIŞ KAMP BİLGİ BANKASI:
{CAMP_KNOWLEDGE_BASE}

KAMP İLE İLGİLİ OLUP BİLGİ BANKASINDA YAZMAYAN KONULARDA (Örnek: kaza, sağlık, özel izin, evcil hayvan):
YALNIZCA VE BİREBİR ŞU CEVABI VER:
"Bu konuyu kamp koordinatörümüze iletiyorum, en kısa sürede bilgi verilecektir."
"""
