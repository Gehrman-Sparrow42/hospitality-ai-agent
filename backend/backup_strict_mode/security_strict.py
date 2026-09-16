"""
BACKUP: KATI GÜVENLİK VE FİLTRE MOTORU (STRICT SECURITY FILTER)
Bu dosya en ufak kamp dışı genel sohbette, şiirde veya metinde yazmayan bir imkanda
hemen Fallback veya Red yanıtı veren katı güvenlik kurallarını içerir.
"""

import re
import time
import logging
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger("camp-bot-security-strict")

_request_timestamps: Dict[str, List[float]] = defaultdict(list)
_blocked_phones: Dict[str, float] = {}

REFUSAL_JAILBREAK = (
    "Güvenlik politikaları gereği sistem yönergeleri veya yetki dışı talimatlar paylaşılamaz. "
    "Yalnızca Masal Kamp organizasyonu hakkında bilgi alabilirsiniz. 🏕️"
)

REFUSAL_OFFTOPIC = (
    "Ben yalnızca Masal Kamp ile ilgili konularda (giriş/çıkış saatleri, gerekli kişisel ekipmanlar, "
    "yemek düzeni ve Wi-Fi alanı) bilgi vermek üzere görevlendirilmiş resmi bir asistanım. "
    "Şiir, kod, hikaye veya kamp dışı genel konularda destek verememekteyim. 🏕️"
)

FALLBACK_COORDINATOR = "Bu konuyu kamp koordinatörümüze iletiyorum, en kısa sürede bilgi verilecektir."


class SecurityGuardStrict:
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

        self.jailbreak_patterns = [
            r"(?i)\b(ignore|bypass|override|forget)\b.*\b(instructions?|prompt|rules?|system|guidelines?)\b",
            r"(?i)\b(system\s+prompt|initial\s+prompt|hidden\s+rules?|developer\s+mode|dan\s+mode)\b",
            r"(?i)\b(önceki\s+tüm\s+talimatları\s+unut|kuralları\s+yoksay|sistem\s+mesajını\s+yaz)\b",
            r"(?i)\b(pretend|act\s+as\s+a?|roleplay|simulate)\b",
            r"(?i)\b(gizli\s+talimat|gizli\s+kural|sistem\s+yönergesi)\b",
        ]

        self.offtopic_patterns = [
            r"(?i)\b(şiir|şiiri|şiirler|şarkı\s+sözü|beste|mani|fıkra\s+anlat|masal\s+anlat|roman\s+yaz)\b",
            r"(?i)\b(poem|poetry|tell\s+a\s+joke|write\s+a\s+story|write\s+a\s+song)\b",
            r"(?i)\b(python|javascript|typescript|html|css|golang|rust|php|csharp)\b",
            r"(?i)\b(kod\s+yaz|script\s+yaz|program\s+yaz|kodla|web\s+scraper|fonksiyon\s+yaz)\b",
            r"(?i)\b(write\s+code|write\s+a\s+script|coding)\b",
            r"(?i)\b(matematik\s+ödevi|türevi|integrali|denklemi\s+çöz)\b",
            r"(?i)(\d+\s*[\+\-\*\/]\s*\d+\s*=\s*\?|\b\d+x\s*[\+\-])",
            r"(?i)\b(canım\s+sıkıldı|sohbet\s+edelim|muhabbet\s+edelim|dertleşelim|sevgilim\s+ol|flört)\b",
            r"(?i)\b(falıma\s+bak|burcum|astroloji|rüya\s+tabiri)\b",
        ]

        self.camp_explicit_whitelist = [
            "giriş saat", "çıkış saat", "kampa giriş", "kamp çıkış",
            "çadır", "uyku tulum", "mat", "kafa feneri", "el feneri",
            "sabah kahvaltı", "akşam yemek", "öğle yemek", "yiyecek", "içecek",
            "wifi", "wi-fi", "internet", "şebeke", "kafeterya",
            "koordinatör", "kamp alanı", "/reset"
        ]

    def sanitize_output(self, assistant_reply: str) -> str:
        if not assistant_reply or not assistant_reply.strip():
            return FALLBACK_COORDINATOR

        reply = assistant_reply.strip()

        if re.search(r"[\u4e00-\u9fff]", reply):
            return FALLBACK_COORDINATOR

        if "kamp koordinatör" in reply.lower() and len(reply) > 110:
            return FALLBACK_COORDINATOR

        hallucinated_red_flags = [
            r"(?i)\b(otel\s+odası|yüzme\s+havuzu|sauna|masaj|pet\s+hotel|evcil\s+hayvan\s+pansiyonu)\b",
            r"(?i)\b(kampımızda\s+çadır\s+kiralayabilirsiniz|çadırları\s+biz\s+temin\s+ediyoruz)\b",
        ]
        for flag in hallucinated_red_flags:
            if re.search(flag, reply):
                return FALLBACK_COORDINATOR

        return reply
