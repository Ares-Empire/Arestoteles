"""Refresh the public web watchlist feed (web/live.json) from Alpaca.

Read-only market data only (snapshots + daily bars on the free IEX feed) — this
never touches orders or account state, so it is safe to run outside the trading
pipeline and is consistent with the CLAUDE.md guardrails (the AI/web layer holds
no broker write access).

The frontend (web/app/live.js) reads the JSON this writes. It is a *watchlist* of
real company performance, explicitly NOT the paper book's holdings — the portfolio
stays at its honest Phase-1 state (zero positions) until the brain trades.

Fail closed: on any Alpaca error, or if too few tickers resolve, the existing
live.json is left untouched (a stale-but-valid file beats a broken one) and the
process exits non-zero so a timer/cron surfaces the failure.

Run:  python -m scripts.refresh_quotes        (from repo root, env from .env)
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from arestoteles.config import REPO_ROOT, load_settings
from arestoteles.ingest.alpaca import AlpacaData
from arestoteles.log import get_logger

log = get_logger(__name__)

OUT = REPO_ROOT / "web" / "live.json"

# Curated watchlist: the semiconductor / AI-infrastructure theme this project tracks,
# plus a few of the most-recognisable large caps so there is always something to see.
# (ticker, display name). SpaceX and other private names are intentionally absent —
# they are not publicly tradable.
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


def build_payload() -> dict:
    settings = load_settings()
    settings.require("alpaca_paper_key", "alpaca_paper_secret")
    client = AlpacaData(settings.alpaca_paper_key, settings.alpaca_paper_secret)

    tickers = [t for t, _ in WATCH]
    snaps = client.snapshots(tickers)
    bars = client.daily_bars(tickers, days=SPARK_POINTS + 20)

    try:
        market_open = client.clock().is_open
    except Exception:  # clock is non-essential to the feed
        market_open = False

    quotes: list[dict] = []
    for ticker, name in WATCH:
        snap = snaps.get(ticker)
        if snap is None:
            log.warning("no snapshot for %s — skipping", ticker)
            continue
        series = sorted(bars.get(ticker, []), key=lambda b: b.day)
        spark = [round(b.close, 2) for b in series][-SPARK_POINTS:]
        quotes.append(
            {
                "ticker": ticker,
                "name": name,
                "price": round(snap.latest_price, 2),
                "day": round(snap.pct_move_from_prev_close or 0.0, 2),
                "spark": spark,
            }
        )

    if len(quotes) < 3:
        raise RuntimeError(f"only {len(quotes)} tickers resolved — refusing to write a thin feed")

    now = datetime.now(UTC)
    return {
        "asOf": now.isoformat(timespec="seconds"),
        "asOfLabel": now.strftime("%b %-d, %Y · %H:%M UTC"),
        "marketOpen": market_open,
        "source": "Alpaca · IEX (free feed)",
        "note": "Live watchlist — real quotes, not the paper book's holdings.",
        "quotes": quotes,
    }


def main() -> int:
    try:
        payload = build_payload()
    except Exception as exc:  # fail closed — keep the last good file
        log.error("quote refresh failed, leaving %s untouched: %s", OUT, exc)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(OUT)  # atomic swap so a reader never sees a half-written file
    log.info(
        "wrote %s (%d quotes, market_open=%s)",
        OUT,
        len(payload["quotes"]),
        payload["marketOpen"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
