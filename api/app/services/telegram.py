"""
Telegram notification service.
"""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


async def send_message(text: str, chat_id: Optional[str] = None) -> bool:
    """Send a Telegram message. Returns True on success."""
    token = settings.TELEGRAM_BOT_TOKEN
    cid = chat_id or settings.TELEGRAM_CHAT_ID
    if not token or not cid:
        logger.warning("Telegram not configured – skipping notification")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False
