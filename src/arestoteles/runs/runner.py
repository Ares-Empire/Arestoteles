"""Fail-closed run wrapper (docs/03 §2/§6): every scheduled job goes through here.

Guarantees:
- the /halt kill switch is checked before anything else (skipped_halted run row);
- market-day gating via the Alpaca clock where required (skipped_market_closed);
- one `runs` row per invocation with status/error/cost aggregates;
- ANY exception ⇒ runs.status=failed + Telegram alert + exit code 1 — the run
  produces no decisions and no orders (fail closed, default action is HOLD).
"""

import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine

from arestoteles.config import (
    AppConfig,
    Settings,
    Universe,
    load_config,
    load_settings,
    load_universe,
)
from arestoteles.db import state
from arestoteles.db.engine import get_engine
from arestoteles.log import get_logger, setup_logging
from arestoteles.notify.telegram import send_alert

log = get_logger(__name__)


@dataclass
class RunContext:
    run_id: int
    run_type: str
    now: datetime
    engine: Engine
    settings: Settings
    config: AppConfig
    universe: Universe


RunFn = Callable[[RunContext], dict[str, Any]]


def _market_open_today(settings: Settings) -> bool:
    """True if today is a US trading day per the Alpaca calendar. No keys or API
    failure raises — gated runs must not silently guess (fail closed)."""
    from datetime import timedelta

    from arestoteles.ingest.alpaca import AlpacaData

    alpaca = AlpacaData(settings.alpaca_paper_key, settings.alpaca_paper_secret)
    clock = alpaca.clock()
    today_ny = clock.timestamp.date()
    days = alpaca.calendar(today_ny - timedelta(days=1), today_ny + timedelta(days=1))
    return any(d.day == today_ny for d in days)


def execute_run(run_type: str, fn: RunFn, *, require_market_day: bool, force: bool = False) -> int:
    setup_logging()
    log.info("run starting", run_type=run_type)
    try:
        settings = load_settings()
        config = load_config()
        universe = load_universe()
        engine = get_engine()
    except Exception as exc:
        log.error("run could not even initialize", run_type=run_type, error=str(exc))
        send_alert(f"{run_type} failed to initialize", str(exc)[:800])
        return 1

    try:
        with engine.begin() as conn:
            if state.is_halted(conn) or config.mode.halted:
                run_id = state.start_run(conn, run_type)
                state.finish_run(conn, run_id, "skipped_halted")
                log.warning("halted — run skipped", run_type=run_type)
                return 0
    except Exception as exc:
        log.error("db unreachable", error=str(exc))
        send_alert(f"{run_type}: database unreachable", str(exc)[:800])
        return 1

    if require_market_day and not force:
        try:
            if not _market_open_today(settings):
                with engine.begin() as conn:
                    run_id = state.start_run(conn, run_type)
                    state.finish_run(conn, run_id, "skipped_market_closed")
                log.info("market closed today — run skipped", run_type=run_type)
                return 0
        except Exception as exc:
            with engine.begin() as conn:
                run_id = state.start_run(conn, run_type)
                state.finish_run(conn, run_id, "failed", error=f"market gate: {exc}")
            send_alert(f"{run_type}: market-day gate failed", str(exc)[:800])
            return 1

    with engine.begin() as conn:
        run_id = state.start_run(conn, run_type)
    ctx = RunContext(
        run_id=run_id,
        run_type=run_type,
        now=datetime.now(UTC),
        engine=engine,
        settings=settings,
        config=config,
        universe=universe,
    )
    try:
        meta = fn(ctx) or {}
        with engine.begin() as conn:
            state.finish_run(conn, run_id, "ok", meta=meta)
        log.info("run finished", run_type=run_type, run_id=run_id, **meta)
        return 0
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        log.error("run failed", run_type=run_type, run_id=run_id, error=err)
        traceback.print_exc(file=sys.stderr)
        try:
            with engine.begin() as conn:
                state.finish_run(conn, run_id, "failed", error=err[:2000])
        finally:
            send_alert(f"{run_type} FAILED (no trades, fail closed)", err[:800])
        return 1
