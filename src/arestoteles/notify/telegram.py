"""Outbound Telegram messages for oneshot runs (alerts, digests).

Send failures never crash a run — notification is best-effort, but every failure
is logged loudly. The long-running bot (commands, approvals) lives in bot.py.
"""

import html

import httpx

from arestoteles.config import load_settings
from arestoteles.log import get_logger

log = get_logger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def escape(text: str) -> str:
    return html.escape(text, quote=False)


def send_message(text: str, *, disable_preview: bool = True) -> bool:
    """Send an HTML-formatted message to the configured chat. Returns success."""
    settings = load_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.warning("telegram not configured — message dropped", preview=text[:120])
        return False
    try:
        resp = httpx.post(
            API_URL.format(token=settings.telegram_bot_token),
            json={
                "chat_id": settings.telegram_chat_id,
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.error("telegram send failed", error=str(exc), preview=text[:120])
        return False


def send_alert(title: str, body: str) -> bool:
    return send_message(f"🚨 <b>{escape(title)}</b>\n{escape(body)}")
