"""Live Alpaca paper round trip (docs/08 §1 'Integration' row): run after the user
adds ALPACA_PAPER_KEY/SECRET to .env:  uv run pytest -m live tests/test_alpaca_live.py"""

from datetime import UTC, date, datetime, timedelta

import pytest

from arestoteles.config import load_settings
from arestoteles.ingest.alpaca import AlpacaData, adv20_usd

pytestmark = pytest.mark.live

settings = load_settings()
needs_keys = pytest.mark.skipif(
    not (settings.alpaca_paper_key and settings.alpaca_paper_secret),
    reason="ALPACA_PAPER_KEY/SECRET not in .env yet",
)


@needs_keys
def test_clock_calendar_bars_snapshots_roundtrip():
    alpaca = AlpacaData(settings.alpaca_paper_key, settings.alpaca_paper_secret)

    clock = alpaca.clock()
    assert clock.next_open.tzinfo is not None

    days = alpaca.calendar(date.today() - timedelta(days=10), date.today() + timedelta(days=10))
    assert 5 <= len(days) <= 16  # trading days in a ~3-week window

    bars = alpaca.daily_bars(["NVDA", "SOXX", "QQQ"], days=40)
    assert len(bars["NVDA"]) >= 15
    adv = adv20_usd(bars["NVDA"])
    assert adv is not None and adv > 1e9  # NVDA trades billions of dollars a day

    snaps = alpaca.snapshots(["NVDA", "VRT"])
    assert "NVDA" in snaps
    assert snaps["NVDA"].latest_at < datetime.now(UTC) + timedelta(minutes=5)
