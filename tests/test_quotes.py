"""The website's quote refresher (scripts/refresh_quotes.py) with a stub market-data client: no network."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from conftest import ROOT

spec = importlib.util.spec_from_file_location("refresh_quotes", ROOT / "scripts" / "refresh_quotes.py")
quotes = importlib.util.module_from_spec(spec)
sys.modules["refresh_quotes"] = quotes   # dataclasses look their module up while the class is made
spec.loader.exec_module(quotes)


class StubClient:
    def __init__(self, tickers: list[str]):
        self.tickers = tickers

    def snapshots(self, tickers):
        return {t: quotes.Snapshot(latest_price=110.123, prev_close=100.0) for t in tickers if t in self.tickers}

    def daily_bars(self, tickers, days):
        return {t: [quotes.DailyBar(date(2026, 10, d), 100.0 + d) for d in (3, 1, 2)] for t in tickers}

    def market_open(self):
        raise RuntimeError("clock down")


def test_payload():
    payload = quotes.build_payload(StubClient(["NVDA", "AMD", "MU"]), now=datetime(2026, 10, 24, 14, 2, tzinfo=UTC))
    assert payload["asOf"] == "2026-10-24T14:02:00+00:00"
    assert payload["asOfLabel"] == "Oct 24, 2026 · 14:02 UTC"
    assert payload["marketOpen"] is False
    assert [q["ticker"] for q in payload["quotes"]] == ["NVDA", "AMD", "MU"]
    assert payload["quotes"][0] == {"ticker": "NVDA", "name": "NVIDIA Corp.", "price": 110.12, "day": 10.12,
                                    "spark": [101.0, 102.0, 103.0]}


def test_thin_feed_is_refused():
    with pytest.raises(RuntimeError):
        quotes.build_payload(StubClient(["NVDA"]))


def test_conversions_and_write(tmp_path):
    trade = SimpleNamespace(price=12.5)
    assert quotes.snapshot_from(SimpleNamespace(latest_trade=trade, previous_daily_bar=SimpleNamespace(close=10)))\
        .pct_move_from_prev_close == 25.0
    assert quotes.snapshot_from(SimpleNamespace(latest_trade=None, previous_daily_bar=None)) is None
    bar = quotes.bar_from(SimpleNamespace(timestamp=datetime(2026, 10, 1, 4, tzinfo=UTC), close="7.5"))
    assert bar == quotes.DailyBar(date(2026, 10, 1), 7.5)
    out = tmp_path / "web" / "live.json"
    quotes.write_feed({"quotes": []}, out)
    assert json.loads(out.read_text()) == {"quotes": []}
    assert not out.with_suffix(".json.tmp").exists()


def test_missing_keys_fail_closed(tmp_path, monkeypatch):
    out = tmp_path / "live.json"
    out.write_text("old")
    monkeypatch.setattr(quotes, "OUT", out)
    monkeypatch.delenv("ALPACA_PAPER_KEY", raising=False)
    assert quotes.main() == 1
    assert out.read_text() == "old"
