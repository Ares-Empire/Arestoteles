"""Pure-conversion and math tests for the Alpaca wrapper (SDK objects stubbed).
The live round trip lives in test_alpaca_live.py (pytest -m live, needs keys)."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx

from arestoteles.ingest.alpaca import (
    DailyBar,
    adv20_usd,
    bar_from,
    big_move_events,
    clock_from,
    snapshot_from,
)
from arestoteles.ingest.earnings import CALENDAR_URL, fetch_earnings_dates, trading_days_until

NOW = datetime(2026, 6, 15, 14, 30, tzinfo=UTC)


def bar(day_offset: int, close=100.0, volume=1_000_000.0) -> DailyBar:
    return DailyBar(
        ticker="NVDA",
        day=date(2026, 6, 1) + timedelta(days=day_offset),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
    )


def test_clock_and_bar_conversion_from_sdk_shapes():
    clock = clock_from(
        SimpleNamespace(
            timestamp=NOW, is_open=True, next_open=NOW + timedelta(hours=18), next_close=NOW
        )
    )
    assert clock.is_open and clock.timestamp == NOW
    b = bar_from(
        "NVDA",
        SimpleNamespace(timestamp=NOW, open=1, high=2, low=0.5, close=1.5, volume=10),
    )
    assert b.day == NOW.date() and b.close == 1.5


def test_snapshot_conversion_handles_missing_pieces():
    snap = snapshot_from(
        "NVDA",
        SimpleNamespace(
            latest_trade=SimpleNamespace(price=123.4, timestamp=NOW),
            previous_daily_bar=SimpleNamespace(close=120.0),
        ),
    )
    assert snap is not None
    assert snap.pct_move_from_prev_close == pytest.approx(2.8333, rel=1e-3)
    assert snapshot_from("NVDA", SimpleNamespace(latest_trade=None)) is None
    no_prev = snapshot_from(
        "NVDA",
        SimpleNamespace(
            latest_trade=SimpleNamespace(price=1.0, timestamp=NOW), previous_daily_bar=None
        ),
    )
    assert no_prev is not None and no_prev.pct_move_from_prev_close is None


def test_adv20_math_and_minimum_history():
    bars = [bar(i, close=100.0, volume=1_000_000.0) for i in range(25)]
    assert adv20_usd(bars) == pytest.approx(100_000_000.0)
    assert adv20_usd(bars[:3]) is None  # too little history = no liquidity claim


def test_adv20_uses_only_last_20_days():
    old = [bar(i, close=1.0, volume=1.0) for i in range(10)]
    recent = [bar(10 + i, close=100.0, volume=1_000_000.0) for i in range(20)]
    assert adv20_usd(old + recent) == pytest.approx(100_000_000.0)


def test_big_move_detection_threshold_and_dedup():
    from arestoteles.ingest.alpaca import Snapshot

    snaps = {
        "NVDA": Snapshot(ticker="NVDA", latest_price=106.5, latest_at=NOW, prev_close=100.0),
        "MU": Snapshot(ticker="MU", latest_price=95.0, latest_at=NOW, prev_close=100.0),
        "VRT": Snapshot(ticker="VRT", latest_price=93.9, latest_at=NOW, prev_close=100.0),
    }
    events = big_move_events(snaps, threshold_pct=6.0, now=NOW)
    assert [e.tickers[0] for e in events] == ["NVDA", "VRT"]  # MU at -5% stays quiet
    again = big_move_events(snaps, threshold_pct=6.0, now=NOW + timedelta(hours=1))
    assert {e.dedup_hash for e in events} == {e.dedup_hash for e in again}  # same day+direction


def test_trading_days_until():
    days = [date(2026, 6, 15) + timedelta(days=i) for i in (1, 2, 3, 6, 7)]  # Tue-Thu, Mon-Tue
    today = date(2026, 6, 15)
    assert trading_days_until(date(2026, 6, 16), today, days) == 1
    assert trading_days_until(date(2026, 6, 18), today, days) == 3
    assert trading_days_until(date(2026, 6, 22), today, days) == 5
    assert trading_days_until(today, today, days) == 0
    assert trading_days_until(date(2026, 7, 30), today, days) is None  # beyond window
    assert trading_days_until(date(2026, 6, 20), today, []) is None


@respx.mock
async def test_fetch_earnings_dates_picks_earliest_per_ticker():
    payload = {
        "earningsCalendar": [
            {"symbol": "NVDA", "date": "2026-08-26"},
            {"symbol": "NVDA", "date": "2026-06-20"},
            {"symbol": "OTHER", "date": "2026-06-17"},
            {"symbol": "MU", "date": "2026-06-25"},
        ]
    }
    respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as client:
        out = await fetch_earnings_dates(client, "key", ["NVDA", "MU", "VRT"])
    assert out == {"NVDA": date(2026, 6, 20), "MU": date(2026, 6, 25)}


async def test_fetch_earnings_requires_key():
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
            await fetch_earnings_dates(client, "", ["NVDA"])


def test_alpaca_client_requires_keys():
    from arestoteles.ingest.alpaca import AlpacaData

    with pytest.raises(RuntimeError, match="ALPACA_PAPER_KEY"):
        AlpacaData("", "")
