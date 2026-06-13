"""Shared free-layer ingestion steps (docs/04 Layer 1) used by the run entrypoints."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from arestoteles.db import events as db_events
from arestoteles.db import state
from arestoteles.ingest import edgar, rss
from arestoteles.log import get_logger
from arestoteles.runs.runner import RunContext

log = get_logger(__name__)

CIK_CACHE_KEY = "edgar_cik_map"
CIK_CACHE_DAYS = 7


def _cached_universe_ciks(ctx: RunContext) -> dict[str, int]:
    with ctx.engine.begin() as conn:
        cached = state.get_state(conn, CIK_CACHE_KEY)
    wanted = ctx.universe.traded_tickers | ctx.universe.monitored_tickers
    if cached:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        fresh = datetime.now(UTC) - fetched_at < timedelta(days=CIK_CACHE_DAYS)
        if fresh and wanted <= set(cached["ciks"]):
            return {t: int(c) for t, c in cached["ciks"].items() if t in wanted}

    async def fetch() -> dict[str, int]:
        async with edgar.make_client(ctx.settings.edgar_user_agent) as client:
            cik_map = await edgar.fetch_cik_map(client)
        return edgar.universe_ciks(cik_map, ctx.universe)

    ciks = asyncio.run(fetch())
    with ctx.engine.begin() as conn:
        state.set_state(
            conn,
            CIK_CACHE_KEY,
            {"fetched_at": datetime.now(UTC).isoformat(), "ciks": ciks},
        )
    return ciks


def ingest_free_layer(ctx: RunContext, since_days: int = 3) -> dict[str, Any]:
    """Poll RSS + EDGAR, store deduped events. Optional big-move detection when
    Alpaca keys exist (sweeps stay useful before the paper account does)."""
    meta: dict[str, Any] = {}

    rss_result = asyncio.run(rss.poll_feeds(ctx.universe))
    with ctx.engine.begin() as conn:
        meta["rss_new"] = db_events.insert_events(conn, rss_result.events, run_id=ctx.run_id)
    meta["rss_feeds_ok"] = len(rss_result.feeds_ok)
    meta["rss_feeds_failed"] = len(rss_result.feeds_failed)

    ciks = _cached_universe_ciks(ctx)

    async def poll_edgar():
        async with edgar.make_client(ctx.settings.edgar_user_agent) as client:
            return await edgar.poll_filings(
                client, ciks, since=(ctx.now - timedelta(days=since_days)).date()
            )

    filings = asyncio.run(poll_edgar())
    with ctx.engine.begin() as conn:
        meta["edgar_new"] = db_events.insert_events(conn, filings, run_id=ctx.run_id)

    if ctx.settings.alpaca_paper_key and ctx.settings.alpaca_paper_secret:
        from arestoteles.ingest.alpaca import AlpacaData, big_move_events

        alpaca = AlpacaData(ctx.settings.alpaca_paper_key, ctx.settings.alpaca_paper_secret)
        snaps = alpaca.snapshots(sorted(ctx.universe.traded_tickers))
        moves = big_move_events(snaps, threshold_pct=6.0, now=ctx.now)
        with ctx.engine.begin() as conn:
            meta["move_events_new"] = db_events.insert_events(conn, moves, run_id=ctx.run_id)
    else:
        log.info("alpaca keys absent — price-move detection skipped")
        meta["move_events_new"] = None

    return meta
