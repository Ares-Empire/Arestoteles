"""Telegram send helper + status formatting (no token needed)."""

from datetime import UTC, datetime

import httpx
import respx

import arestoteles.notify.telegram as tg
from arestoteles.config import Settings
from arestoteles.notify.bot import status_text
from arestoteles.notify.telegram import API_URL, escape, send_message


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_send_without_config_is_dropped_not_crashed(monkeypatch):
    monkeypatch.setattr(tg, "load_settings", lambda: _settings())
    assert send_message("hello") is False


@respx.mock
def test_send_posts_html_to_bot_api(monkeypatch):
    monkeypatch.setattr(
        tg, "load_settings", lambda: _settings(telegram_bot_token="tok123", telegram_chat_id="42")
    )
    route = respx.post(API_URL.format(token="tok123")).mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert send_message("<b>hi</b>") is True
    import json

    sent = json.loads(route.calls[0].request.content)
    assert sent["chat_id"] == "42" and sent["parse_mode"] == "HTML"


@respx.mock
def test_send_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        tg, "load_settings", lambda: _settings(telegram_bot_token="tok123", telegram_chat_id="42")
    )
    respx.post(API_URL.format(token="tok123")).mock(return_value=httpx.Response(502))
    assert send_message("hi") is False


def test_status_text_formats_all_states():
    run = {
        "run_type": "main_run",
        "started_at": datetime(2026, 6, 15, 13, 30, tzinfo=UTC),
        "status": "failed",
        "error": "boom <tag>",
    }
    txt = status_text(run, halted=True, paused={"NVDA"}, events_24h=17)
    assert "⛔ YES" in txt
    assert "main_run" in txt and "failed" in txt
    assert "&lt;tag&gt;" in txt  # html escaped
    assert "NVDA" in txt and "17" in txt
    empty = status_text(None, halted=False, paused=set(), events_24h=0)
    assert "none yet" in empty


def test_escape():
    assert escape("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
