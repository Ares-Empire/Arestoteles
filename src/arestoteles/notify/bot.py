"""Long-running Telegram bot: kill switch + status (docs/03 §6, docs/05 HITL).

v1 commands: /status, /halt, /resume, /limits. The halt flag lives in app_state;
every run checks it first, so /halt stops trading even while the bot restarts.
Only the configured TELEGRAM_CHAT_ID may issue commands.

Run: python -m arestoteles.notify.bot  (the `bot` service in docker compose)
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from arestoteles.config import load_settings
from arestoteles.db import state
from arestoteles.db.engine import get_engine
from arestoteles.log import get_logger, setup_logging
from arestoteles.notify.telegram import escape

log = get_logger(__name__)


def status_text(
    last_run: dict[str, Any] | None, halted: bool, paused: set[str], events_24h: int
) -> str:
    lines = ["<b>Arestoteles status</b>"]
    lines.append(f"halted: {'⛔ YES' if halted else '✅ no'}")
    if paused:
        lines.append(f"paused tickers: {escape(', '.join(sorted(paused)))}")
    if last_run:
        when = last_run["started_at"]
        lines.append(
            f"last run: {escape(str(last_run['run_type']))} @ {when:%Y-%m-%d %H:%M} UTC "
            f"→ {escape(str(last_run['status']))}"
        )
        if last_run.get("error"):
            lines.append(f"error: <code>{escape(str(last_run['error'])[:300])}</code>")
    else:
        lines.append("last run: none yet")
    lines.append(f"events last 24h: {events_24h}")
    return "\n".join(lines)


def _events_24h(conn) -> int:
    row = conn.execute(
        text("SELECT count(*) FROM events WHERE first_seen_at >= :since"),
        {"since": datetime.now(UTC) - timedelta(hours=24)},
    ).fetchone()
    return int(row[0]) if row else 0


async def cmd_status(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        msg = status_text(
            last_run=state.last_run(conn),
            halted=state.is_halted(conn),
            paused=state.paused_tickers(conn),
            events_24h=_events_24h(conn),
        )
    assert update.message is not None
    await update.message.reply_html(msg)


async def cmd_halt(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    with get_engine().begin() as conn:
        state.set_halted(conn, True)
    log.warning("halt set via telegram")
    assert update.message is not None
    await update.message.reply_html("⛔ <b>HALTED.</b> No run will trade until /resume.")


async def cmd_resume(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    with get_engine().begin() as conn:
        state.set_halted(conn, False)
    log.warning("halt cleared via telegram")
    assert update.message is not None
    await update.message.reply_html("✅ Resumed. Runs may trade again (within limits).")


async def cmd_limits(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_html(
        "Limit headroom view arrives with the execution module (Phase 3). "
        "Risk limits themselves are active in config + risk engine."
    )


def build_application(token: str, chat_id: str) -> Application:
    app = Application.builder().token(token).build()
    allowed = filters.Chat(chat_id=int(chat_id))
    app.add_handler(CommandHandler("status", cmd_status, filters=allowed))
    app.add_handler(CommandHandler("halt", cmd_halt, filters=allowed))
    app.add_handler(CommandHandler("resume", cmd_resume, filters=allowed))
    app.add_handler(CommandHandler("limits", cmd_limits, filters=allowed))
    return app


def main() -> None:
    setup_logging()
    settings = load_settings()
    settings.require("telegram_bot_token", "telegram_chat_id")
    app = build_application(settings.telegram_bot_token, settings.telegram_chat_id)
    log.info("telegram bot starting (long polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
