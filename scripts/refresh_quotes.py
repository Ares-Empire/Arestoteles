"""Refresh the public web watchlist feed (web/live.json) from Alpaca.

Read-only market data only (snapshots + daily bars on the free IEX feed): this never touches orders or account
state. The frontend (web/app/live.js) reads the JSON this writes. It is a *watchlist* of real company performance,
not holdings.

Fail closed: on any Alpaca error, or if too few tickers resolve, the existing live.json is left untouched (a
stale-but-valid file beats a broken one) and the process exits non-zero so the timer surfaces the failure.

Standalone on purpose (2026-10-24: the trading code it used to import is gone): it needs only `alpaca-py` and the
two paper keys from the environment (ALPACA_PAPER_KEY, ALPACA_PAPER_SECRET). The quotes timer runs it in the
`arestoteles-app` image (deploy/quotes.Dockerfile) with `/app/web` mounted.

Run:  python scripts/refresh_quotes.py        (keys in the environment)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("refresh_quotes")


def _default_out() -> Path:
    here = Path(__file__).resolve().parent
    # In the container the script sits at /app/refresh_quotes.py next to the mounted /app/web;
    # in the repo it sits in scripts/, one level below web/.
    root = here if (here / "web").is_dir() else here.parent
    return root / "web" / "live.json"


OUT = Path(os.environ["LIVE_JSON"]) if os.environ.get("LIVE_JSON") else _default_out()

# Curated watchlist: the semiconductor / AI-infrastructure theme, plus a few of the most-recognisable large caps so
# there is always something to see. (ticker, display name). Private names are absent: not publicly tradable.
WATCH: list[tuple[str, str]] = [
    ("NVDA", "NVIDIA Corp."),
    ("TSM", "Taiwan Semiconductor"),
    ("AVGO", "Broadcom Inc."),
    ("ASML", "ASML Holding"),
    ("AMD", "Advanced Micro Devices"),
    ("MU", "Micron Technology"),
    ("ARM", "Arm Holdings"),
    ("MRVL", "Marvell Technology"),
    ("VRT", "Vertiv Holdings"),
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft Corp."),
    ("GOOGL", "Alphabet Inc."),
    ("TSLA", "Tesla Inc."),
    ("AMZN", "Amazon.com Inc."),
]

SPARK_POINTS = 30  # trailing daily closes drawn in the row sparkline


@dataclass(frozen=True)
class DailyBar:
    day: date
    close: float


@dataclass(frozen=True)
class Snapshot:
    latest_price: float
    prev_close: float | None

    @property
    def pct_move_from_prev_close(self) -> float | None:
        if not self.prev_close:
            return None
        return (self.latest_price - self.prev_close) / self.prev_close * 100.0


def bar_from(raw: Any) -> DailyBar:
    ts = raw.timestamp
    return DailyBar(day=ts.date() if isinstance(ts, datetime) else ts, close=float(raw.close))


def snapshot_from(raw: Any) -> Snapshot | None:
    trade = getattr(raw, "latest_trade", None)
    prev = getattr(raw, "previous_daily_bar", None)
    if trade is None or trade.price is None:
        return None
    return Snapshot(latest_price=float(trade.price),
                    prev_close=float(prev.close) if prev is not None and prev.close else None)


class AlpacaData:
    """Thin read-only wrapper around alpaca-py (paper endpoint, market data only)."""

    def __init__(self, key: str, secret: str) -> None:
        if not key or not secret:
            raise RuntimeError("ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET missing: add the paper keys to .env")
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        self._trading = TradingClient(key, secret, paper=True)
        self._data = StockHistoricalDataClient(key, secret)

    def market_open(self) -> bool:
        return bool(self._trading.get_clock().is_open)

    def daily_bars(self, tickers: list[str], days: int) -> dict[str, list[DailyBar]]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        req = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame.Day,
            start=datetime.now(UTC) - timedelta(days=days * 2),  # weekends/holidays margin
            feed="iex",  # free tier
        )
        raw = self._data.get_stock_bars(req)
        return {t: [bar_from(b) for b in raw.data.get(t, [])] for t in tickers}

    def snapshots(self, tickers: list[str]) -> dict[str, Snapshot]:
        from alpaca.data.requests import StockSnapshotRequest

        raw = self._data.get_stock_snapshot(StockSnapshotRequest(symbol_or_symbols=tickers, feed="iex"))
        out: dict[str, Snapshot] = {}
        for t in tickers:
            snap = snapshot_from(raw[t]) if t in raw else None
            if snap is not None:
                out[t] = snap
        return out


def build_payload(client: Any, now: datetime | None = None) -> dict:
    tickers = [t for t, _ in WATCH]
    snaps = client.snapshots(tickers)
    bars = client.daily_bars(tickers, days=SPARK_POINTS + 20)

    try:
        market_open = client.market_open()
    except Exception:  # the clock is non-essential to the feed
        market_open = False

    quotes: list[dict] = []
    for ticker, name in WATCH:
        snap = snaps.get(ticker)
        if snap is None:
            log.warning("no snapshot for %s, skipping", ticker)
            continue
        series = sorted(bars.get(ticker, []), key=lambda b: b.day)
        spark = [round(b.close, 2) for b in series][-SPARK_POINTS:]
        quotes.append({
            "ticker": ticker,
            "name": name,
            "price": round(snap.latest_price, 2),
            "day": round(snap.pct_move_from_prev_close or 0.0, 2),
            "spark": spark,
        })

    if len(quotes) < 3:
        raise RuntimeError(f"only {len(quotes)} tickers resolved, refusing to write a thin feed")

    now = now or datetime.now(UTC)
    return {
        "asOf": now.isoformat(timespec="seconds"),
        "asOfLabel": now.strftime("%b %-d, %Y · %H:%M UTC"),
        "marketOpen": market_open,
        "source": "Alpaca · IEX (free feed)",
        "note": "Live watchlist — real quotes, not the paper book's holdings.",
        "quotes": quotes,
    }


def write_feed(payload: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(out)  # atomic swap so a reader never sees a half-written file


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        client = AlpacaData(os.environ.get("ALPACA_PAPER_KEY", ""), os.environ.get("ALPACA_PAPER_SECRET", ""))
        payload = build_payload(client)
    except Exception as exc:  # fail closed: keep the last good file
        log.error("quote refresh failed, leaving %s untouched: %s", OUT, exc)
        return 1
    write_feed(payload, OUT)
    log.info("wrote %s (%d quotes, market_open=%s)", OUT, len(payload["quotes"]), payload["marketOpen"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
