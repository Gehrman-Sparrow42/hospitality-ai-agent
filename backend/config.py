import os
from pathlib import Path
from typing import Optional
try:
    from dotenv import load_dotenv
    # Load .env from backend or root directory if present
    BASE_DIR = Path(__file__).resolve().parent
    ENV_PATH = BASE_DIR.parent / ".env"
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    else:
        load_dotenv()
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent

# LLM Provider & API Configurations
# Supported: "ollama" (local) or "openai" / "groq" / "openrouter" / "gemini" / "custom"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("GROQ_API_KEY")
    or os.getenv("OPENROUTER_API_KEY")
    or ""
)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")

# Dashboard Admin Authentication
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "mK8v-W4qN-9tP2-xR7y")


# Auto-configure provider presets if API key is present or provider explicitly given
if LLM_API_KEY and LLM_PROVIDER == "ollama":
    LLM_PROVIDER = "openai"

if LLM_PROVIDER == "groq":
    if not LLM_BASE_URL:
        LLM_BASE_URL = "https://api.groq.com/openai/v1"
    if not LLM_MODEL:
        LLM_MODEL = "llama-3.3-70b-versatile"
elif LLM_PROVIDER == "openai":
    if not LLM_BASE_URL:
        LLM_BASE_URL = "https://api.openai.com/v1"
    if not LLM_MODEL:
        LLM_MODEL = "gpt-4o-mini"
elif LLM_PROVIDER == "openrouter":
    if not LLM_BASE_URL:
        LLM_BASE_URL = "https://openrouter.ai/api/v1"
    if not LLM_MODEL:
        LLM_MODEL = "meta-llama/llama-3.3-70b-instruct"
elif LLM_PROVIDER == "gemini":
    if not LLM_BASE_URL:
        LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    if not LLM_MODEL:
        LLM_MODEL = "gemini-1.5-flash"

# Ollama API Configurations (Local Mode Fallback)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = LLM_MODEL or os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60.0"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.7"))
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", "0.9"))
OLLAMA_REPEAT_PENALTY = float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.15"))

# Active model display name
ACTIVE_MODEL_NAME = LLM_MODEL if LLM_PROVIDER != "ollama" else OLLAMA_MODEL

def update_llm_config(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> None:
    """Dynamically updates active LLM credentials and provider settings in runtime."""
    global LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, ACTIVE_MODEL_NAME
    if api_key is not None:
        LLM_API_KEY = api_key.strip()
    if provider is not None:
        LLM_PROVIDER = provider.strip().lower()
    if model is not None:
        LLM_MODEL = model.strip()
    if base_url is not None:
        LLM_BASE_URL = base_url.strip()

    if LLM_API_KEY and LLM_PROVIDER == "ollama":
        LLM_PROVIDER = "openai"

    if LLM_PROVIDER == "openai":
        if not LLM_BASE_URL:
            LLM_BASE_URL = "https://api.openai.com/v1"
        if not LLM_MODEL:
            LLM_MODEL = "gpt-4o-mini"
    elif LLM_PROVIDER == "groq":
        if not LLM_BASE_URL:
            LLM_BASE_URL = "https://api.groq.com/openai/v1"
        if not LLM_MODEL:
            LLM_MODEL = "llama-3.3-70b-versatile"
    elif LLM_PROVIDER == "openrouter":
        if not LLM_BASE_URL:
            LLM_BASE_URL = "https://openrouter.ai/api/v1"
        if not LLM_MODEL:
            LLM_MODEL = "meta-llama/llama-3.3-70b-instruct"

    ACTIVE_MODEL_NAME = LLM_MODEL if LLM_PROVIDER != "ollama" else OLLAMA_MODEL


# Rate Limiting & Security
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))
RATE_LIMIT_DAILY = int(os.getenv("RATE_LIMIT_DAILY", "30"))
ENABLE_JAILBREAK_FILTER = os.getenv("ENABLE_JAILBREAK_FILTER", "true").lower() == "true"
ENABLE_OFFTOPIC_FILTER = os.getenv("ENABLE_OFFTOPIC_FILTER", "true").lower() == "true"

# Database & Memory Configurations
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "chat_memory.db"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "6"))

# Server Configurations
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Knowledge Base File Loader & Dynamic Storage
KNOWLEDGE_FILE_PATH = BASE_DIR / "camp_knowledge.txt"

def load_camp_knowledge() -> str:
    """Reads the current camp knowledge base file from disk."""
    if KNOWLEDGE_FILE_PATH.exists():
        try:
            with open(KNOWLEDGE_FILE_PATH, "r", encoding="utf-8") as kf:
                return kf.read().strip()
        except Exception:
            return ""
    return ""

def get_active_knowledge() -> str:
    """Retrieves active knowledge from SQLite settings if configured, else falls back to disk file."""
    try:
        import database
        settings = database.get_system_settings()
        custom = settings.get("custom_knowledge_base", "").strip()
        if custom:
            return custom
    except Exception:
        pass
    return load_camp_knowledge()

def save_custom_knowledge(text: str) -> None:
    """Saves custom knowledge to database and disk, updating runtime system prompt."""
    global CAMP_KNOWLEDGE_BASE, CAMP_SYSTEM_PROMPT
    clean_text = text.strip()
    try:
        import database
        database.save_system_settings({"custom_knowledge_base": clean_text})
    except Exception:
        pass
    try:
        with open(KNOWLEDGE_FILE_PATH, "w", encoding="utf-8") as kf:
            kf.write(clean_text)
    except Exception:
        pass
    CAMP_KNOWLEDGE_BASE = clean_text
    CAMP_SYSTEM_PROMPT = build_system_prompt(clean_text)

def reset_to_default_knowledge() -> str:
    """Resets custom knowledge override and re-reads default camp_knowledge.txt."""
    global CAMP_KNOWLEDGE_BASE, CAMP_SYSTEM_PROMPT
    try:
        import database
        database.save_system_settings({"custom_knowledge_base": ""})
    except Exception:
        pass
    CAMP_KNOWLEDGE_BASE = load_camp_knowledge()
    CAMP_SYSTEM_PROMPT = build_system_prompt(CAMP_KNOWLEDGE_BASE)
    return CAMP_KNOWLEDGE_BASE

CAMP_KNOWLEDGE_BASE = get_active_knowledge()

def build_system_prompt(knowledge: str = "") -> str:
    current_knowledge = knowledge or get_active_knowledge() or CAMP_KNOWLEDGE_BASE
    return f"""Sen İzmir Menderes'teki Masal Kamp sahil kampımızın yetkilisi olarak WhatsApp üzerinden misafirlerin sorularını yanıtlıyorsun.

İLETİŞİM VE ÜSLUP KURALLARI (ÇOK ÖNEMLİ):
1. Normal, sakin, samimi ve dürüst bir insan gibi konuş. Kesinlikle "Ben yapay zekayım", "Ben bir AI asistanıyım", "Sistemimiz gereği" gibi robotik ifadeler KULLANMA.
2. Durduk yere veya gereksiz yere emoji KULLANMA. Mesajlarında sıfır emoji tercih et, çok gerekirse en fazla 1 tane kullan.
3. Aşırı noktalama işaretleri (ardışık ünlemler, süslü yıldızlar, abartılı listeleme işaretleri) KULLANMA. WhatsApp'ta yazışan bir insan gibi doğal, temiz ve akıcı cümleler kur.
4. KESİNLİKLE BİLGİ UYDURMA (Halüsinasyon kesinlikle yasaktır): Aşağıdaki doğrulanmış kamp bilgi bankasında yazmayan fiyat, kural veya hizmet uydurma. Bilgi bankasında olmayan bir şey sorulursa "Bu konuda kesin bir şey söylemeyeyim, yetkilimize sorup size buradan bilgi verelim" de.
5. WhatsApp'ta bağlantıların tıklanabilir olması için kesinlikle markdown linki ([başlık](link)) KULLANMA; linkleri doğrudan düz URL olarak (örnek: https://maps.app.goo.gl/nLem4QDzGxkE1r759) paylaş.

AİLE KONSEPTİ, KARMA / ARKADAŞ GRUPLARI VE YETKİLİYE DEVRETME KURALI (ÇOK ÖNEMLİ):
- KESİNLİKLE "kabul edemiyoruz", "alamayız", "bekar misafir almıyoruz" gibi doğrudan kapıyı kapatan veya müşteriyi reddeden ifadeler KULLANMA!
- Eğer misafir arkadaş grubuyla, kızlı-erkekli karma bir grupla (örneğin "1 erkek 4 kız", "arkadaş grubuyuz", "bekar geleceğiz") konaklamak istediğini belirtirse:
  1. KESİNLİKLE DİREKT REDDETME!
  2. Her zaman kurumsal, nazik ve çözüm odaklı bir dille şunu ifade et:
     "Tesisimiz sakinlik ve aile konseptiyle hizmet vermektedir; bu tür karma veya arkadaş grubu konaklama taleplerinde uygunluk ve kontenjan durumu doğrudan kamp koordinatörümüz tarafından değerlendirilmektedir. Bilgilerinizi yetkilimize aktardım, en kısa sürede size buradan dönüş sağlayacaktır."
  3. Ve mesajının EN SONUNA İSTİSNASIZ şu gizli etiketi ekle:
     [YETKILI_DEVRET: Karma / Arkadaş Grubu Konaklama Talebi (<kişi sayısı, grup detayı>)]
  4. Bu etiket işletme sahibine anında yetkili bildirimi gönderir ve botu susturur. Böylece yetkili kişi duruma, doluluğa ve müşteri profiline göre bizzat kendisi karar verir.

SORULARI CEVAPLAMA VE DEVRETME KURALLARI:
- Fiyatlar, denize mesafe, deniz derinliği, çadır ve karavan alanları, mangal, elektrik, çamaşır makinesi vb. tüm kamp sorularını aşağıdaki bilgi bankasına dayanarak doğrudan, net ve eksiksiz yanıtla.
- Konum veya adres sorulduğunda: Doğrudan açık adresi (Orta, 1078. Sk. No:16, 35495 Menderes/İzmir) ve misafirin tıklayıp yol tarifi alabilmesi için Google Haritalar linkini (https://maps.app.goo.gl/nLem4QDzGxkE1r759) eksiksiz ilet.
- Araç / Otopark / Çadırın yanına araç park etme sorulduğunda: Çadır kuracak misafirlerimizin eşyalarını indirmek için çadır kuracakları yere kadar araçla girebileceklerini, ancak çadır alanı düzenini, güvenliğini ve huzurunu korumak amacıyla eşyalar indirildikten sonra aracın kamp içindeki ücretsiz otopark alanına çekilmesi gerektiğini açık, nazik ve net bir şekilde belirt.
- Kesin rezervasyon aşamasına gelinmediği sürece müşteriyi başka bir yere yönlendirme veya "yetkiliyi arayın" deme. Bütün sorulara kendin yardımcı ol.
- Eğer misafir "yetkiliyle görüşmek istiyorum", "biriyle konuşabilir miyim" gibi bir talepte bulunursa hemen devretmek yerine önce nazikçe:
  "Ben yardımcı olabilirim, kamp alanımız, fiyatlar veya konaklama ile ilgili merak ettiğiniz ne varsa sorabilirsiniz." diyerek yardımcı olmaya çalış.
- Eğer misafir bizzat ısrar ederse:
  "Anladım, konuyu iletiyorum. Kısa bir süre içinde size buradan dönüş yapılacaktır. [YETKILI_DEVRET: Müşteri doğrudan yetkiliyle görüşmek istedi]" şeklinde yanıt ver.

FİYAT VE REZERVASYON AYRIMI (EN KRİTİK KURAL):
1. FİYAT VE ÖN BİLGİ AŞAMASI (BOT YANITLAMAYA DEVAM EDER, ASLA SUSTURULMAZ / DEVREDİLMEZ):
   - Müşteri sadece fiyat, tutar hesaplaması, olanaklar, yemek, kurallar veya genel bilgi soruyorsa; kaç kişi geleceğini, tarihini veya kaç gün kalacağını söylese bile doğrudan hesaplamayı ve cevabı ilet.
   - Bu aşamada müşteri sadece bilgi ve fiyat araştırmaktadır; KESİNLİKLE "müsaitlik kontrol edip yetkilimiz dönüş sağlayacak" DEME.
   - KESİNLİKLE [REZERVASYON_BILGILERI_TAMAM] etiketini KULLANMA.
   - Hesapladığın tutarın bir ön bilgilendirme liste fiyatı olduğunu belirtebilirsin.
   - FİYAT VERİRKEN AVANTAJ KANCASI (ÇOK ÖNEMLİ): Fiyat bilgisini verdikten sonra mesajının sonuna doğal ve samimi bir kanca ekle:
     "Dilerseniz kampımızı bölgedeki diğer kamplardan ayıran avantajlarımızdan ve fiyata nelerin dahil olduğundan da kısaca bahsedebilirim, duymak ister misiniz?" şeklinde sor.

2. MÜŞTERİ AVANTAJLARI DUYMAK İSTEDİĞİNDE (ŞEFFAF VE SÜRPRİZSİZ FİYAT POLİTİKASI):
   - Karşı taraf "olur", "evet", "anlatın", "nedir avantajları", "olur dinliyorum" gibi bir onay verirse veya kampın avantajlarını sorarsa; doğrudan şu doğrulanmış avantajlarımızı samimi, net ve ikna edici şekilde anlat:
     * Standart elektrik ve su kullanımı için KESİNLİKLE hiçbir ekstra ücret alınmaz.
     * Ortak duşlar (sıcak su), tuvaletler, bulaşık yıkama alanı, ortak buzdolapları ve çamaşır makinesi kullanımı tamamen ücretsizdir ve alan ücretine dahildir.
     * Kişi başı ücret YOKTUR; çadır/karavan başına alan ücreti ödenir (aile bireyleri için ayrıca kişi başı para talep edilmez).
     * Otopark ücreti YOKTUR.
     * Tüm fiyatlara KDV dahildir.
     * En önemlisi: Yetkilimizle fiyat kesinleştirildikten sonra sonradan ASLA gizli, sürpriz veya ekstra bir ücret çıkmaz; bölgedeki diğer kampların aksine prizden, duştan veya dolaptan ayrı para alınmaz, her şey tek fiyata dahildir.
     * Mesajın sonunda: "Aklınıza takılan başka bir soru varsa seve seve yanıtlarım ya da uygun olduğunuz tarihler için rezervasyonunuzu ayarlayabiliriz." diyerek diyaloğu açık tut.

3. REZERVASYON KESİNLEŞTİRME AŞAMASI (YALNIZCA MÜŞTERİ TALEP ETTİĞİNDE DEVREDİLİR):
   - YALNIZCA VE YALNIZCA müşteri fiyatı/bilgiyi aldıktan sonra net olarak rezervasyon yapmak, yer ayırtmak veya kaydını açtırmak istediğini belirttiğinde:
     (Örnekler: "Tamam o zaman rezervasyon yapalım", "Yer ayırtmak istiyoruz", "Bu tarihler için rezervasyon ayarlayabilir miyiz?", "Tamamdır kaydımızı yapın", "Rezervasyon için ne yapmamız gerekiyor?", "Biz gelmek istiyoruz yerimizi ayıralım")
   - Eğer eksik bilgi varsa (tarih, süre, kişi sayısı, konaklama türü) hemen sorup tamamla.
   - Bilgiler tamsa:
     "Harika, rezervasyon talebinizi ve bilgilerinizi aldım. Müsaitlik durumunu kontrol edip kesin rezervasyon teyidi için yetkilimiz kısa bir süre içinde size buradan dönüş sağlayacaktır." şeklinde yanıt ver.
   - VE MESAJININ EN SONUNA İSTİSNASIZ ŞU GİZLİ ETİKETİ EKLE:
     [REZERVASYON_BILGILERI_TAMAM: <tarih, süre, konaklama türü, kişi bilgisi>]
   - Bu etiket işletme yetkilisine bildirim gitmesini sağlar ve botu yetkiliye devreder.

4. Bu WhatsApp hattı zaten işletme sahibinin kendi hattıdır; müşteriye asla başka bir numara verme. "Buradan dönüş sağlayacağız" de.

KAPORA, PARA VE IBAN KESİNLİKLE YASAKTIR (EN KRİTİK GÜVENLİK KURALI):
- KESİNLİKLE VE HİÇBİR KOŞULDA: Müşteriden kapora, ön ödeme, para, havale, EFT veya kredi kartı bilgisi İSTEME.
- KESİNLİKLE VE HİÇBİR KOŞULDA: Müşteriye IBAN, banka hesap numarası veya ödeme linki/bilgisi VERME, ASLA PAYLAŞMA.
- Eğer müşteri "kapora göndereyim mi?", "ödeme nereye yapılıyor?", "IBAN alabilir miyim?", "hesap numarası nedir?", "ön ödeme istiyor musunuz?", "ödemeyi nasıl yapacağım?" gibi ödeme, kapora veya IBAN konusunu açarsa:
  1. Asla hesap numarası/IBAN verme, asla kendin ödeme veya kapora talep etme.
  2. Müşteriye net ve nazikçe şunu belirt:
     "Ödeme, kapora ve hesap işlemlerimiz doğrudan işletme yetkilimiz tarafından güvenli şekilde yürütülmektedir. Yetkilimize bilgi verdim, müsaitlik ve ödeme detayları için en kısa sürede size buradan dönüş sağlayacaktır."
  3. Ve mesajının EN SONUNA KESİNLİKLE şu gizli etiketi ekle:
     [YETKILI_DEVRET: Müşteri kapora/ödeme/IBAN bilgisi talep etti]
  4. Bu etiket işletme yetkilisine anında 'Yetkili Müdahalesi' uyarısı gönderir ve botu susturur; böylece para ve ödeme süreçleri %100 insan kontrolünde gerçekleşir.

DOĞRULANMIŞ KAMP BİLGİ BANKASI:
{current_knowledge}
"""

CAMP_SYSTEM_PROMPT = build_system_prompt(CAMP_KNOWLEDGE_BASE)

