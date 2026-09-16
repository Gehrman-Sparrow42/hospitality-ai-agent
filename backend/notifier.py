"""
Push notification client using ntfy.sh.
Dispatches high-priority mobile alarms and interactive call/chat action buttons
to the business owner or camp manager without requiring extra SIM cards or SMS costs.
"""

import logging
import re
import httpx
from typing import Optional, List, Dict, Any

import database

logger = logging.getLogger("Notifier")

NTFY_DEFAULT_URL = "https://ntfy.sh"
DEFAULT_TOPIC = "masal-kamp-admin"


def get_active_topic(custom_topic: Optional[str] = None) -> str:
    """Returns the configured ntfy topic or falls back to the default topic."""
    if custom_topic and custom_topic.strip():
        return custom_topic.strip().lower()
    try:
        settings = database.get_system_settings()
        stored = settings.get("ntfy_topic", "").strip()
        if stored:
            return stored.lower()
    except Exception as e:
        logger.warning("Could not read ntfy_topic from settings: %s", e)
    return DEFAULT_TOPIC


def sanitize_phone_for_actions(phone: str) -> tuple[str, str]:
    """
    Cleans raw WhatsApp ID / phone number (e.g. '905522384030@c.us' or '+90 552 238 4030').
    Returns (tel_uri, wa_uri):
      tel_uri: '+905522384030'
      wa_uri:  '905522384030'
    """
    digits = re.sub(r"[^\d]", "", phone)
    if digits.startswith("0") and len(digits) == 11:
        digits = "9" + digits  # Turkish standard: 0552... -> 90552...
    tel_number = f"+{digits}" if not digits.startswith("+") else digits
    wa_number = digits.lstrip("+")
    return tel_number, wa_number


async def send_ntfy_push(
    topic: str,
    title: str,
    message: str,
    priority: int = 4,
    tags: Optional[List[str]] = None,
    actions: Optional[List[Dict[str, Any]]] = None,
    server_url: str = NTFY_DEFAULT_URL,
) -> bool:
    """
    Sends an async push notification to ntfy.sh with JSON payload.
    Priority guide:
      5 = urgent / max (Continuous ringing alarm, bypasses silent/DND on Android)
      4 = high (Loud alert sound, vibration)
      3 = default
    """
    topic_clean = topic.strip().lower()
    if not topic_clean:
        logger.warning("ntfy push aborted: empty topic.")
        return False

    payload = {
        "topic": topic_clean,
        "title": title,
        "message": message,
        "priority": priority,
        "tags": tags or [],
    }
    if actions:
        payload["actions"] = actions

    target_url = server_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.post(
                target_url,
                json=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            if response.status_code == 200:
                logger.info("ntfy push sent successfully to topic '%s': %s", topic_clean, title)
                return True
            else:
                logger.warning(
                    "ntfy push returned HTTP %d for topic '%s': %s",
                    response.status_code,
                    topic_clean,
                    response.text,
                )
                return False
    except Exception as e:
        logger.warning("Failed to dispatch ntfy push to topic '%s': %s", topic_clean, e)
        return False


async def send_intervention_alert(
    phone: str,
    user_message: str,
    topic: Optional[str] = None,
) -> bool:
    """
    Dispatches an urgent alert when a customer requests a human coordinator or complains.
    Bot is silenced for 2 hours, so manager must take over.
    """
    target_topic = get_active_topic(topic)
    tel_num, wa_num = sanitize_phone_for_actions(phone)

    title = "🔔 Yetkili Müdahalesi Gerekli"
    body = (
        f"Müşteri: {tel_num}\n"
        f"Talep: {user_message.strip()}\n\n"
        f"Bot 2 saat durduruldu. Sohbeti devralabilirsiniz."
    )

    actions = [
        {
            "action": "view",
            "label": "Müşteriyi Ara",
            "url": f"tel:{tel_num}",
        },
        {
            "action": "view",
            "label": "WhatsApp'ta Aç",
            "url": f"https://wa.me/{wa_num}",
        },
    ]

    return await send_ntfy_push(
        topic=target_topic,
        title=title,
        message=body,
        priority=5,  # Urgent alarm
        tags=["bell"],
        actions=actions,
    )


async def send_reservation_alert(
    phone: str,
    user_message: str,
    topic: Optional[str] = None,
) -> bool:
    """
    Dispatches a high-priority alarm when a customer wants to book a tent/room or confirm dates.
    """
    target_topic = get_active_topic(topic)
    tel_num, wa_num = sanitize_phone_for_actions(phone)

    title = "📋 Yeni Rezervasyon Talebi"
    body = (
        f"Müşteri: {tel_num}\n"
        f"Detay: {user_message.strip()}\n\n"
        f"Müşteri teyit bekliyor. Bot 2 saat durduruldu."
    )

    actions = [
        {
            "action": "view",
            "label": "Müşteriyi Ara",
            "url": f"tel:{tel_num}",
        },
        {
            "action": "view",
            "label": "WhatsApp'ta Aç",
            "url": f"https://wa.me/{wa_num}",
        },
    ]

    return await send_ntfy_push(
        topic=target_topic,
        title=title,
        message=body,
        priority=5,  # Urgent alarm
        tags=["memo"],
        actions=actions,
    )


async def send_test_alert(topic: Optional[str] = None) -> bool:
    """
    Sends a test alert to verify the phone receives notifications and sound alarms properly.
    """
    target_topic = get_active_topic(topic)
    title = "🔔 Bildirim Testi"
    body = (
        "Bildirim sistemi aktif ve çalışıyor.\n"
        "Müşteri acil yetkili talep ettiğinde veya rezervasyon istediğinde telefonunuz sesli çalacaktır."
    )

    return await send_ntfy_push(
        topic=target_topic,
        title=title,
        message=body,
        priority=4,  # High priority
        tags=["white_check_mark"],
        actions=None,
    )
