"""Post-close snapshot (22:15 Berlin, docs/03 §3): P&L + positions snapshot from
broker truth, benchmark series, Telegram digest. No AI, no orders.

Requires Alpaca paper keys (broker truth is the whole point — fail closed without).
Stop checks vs. closes join in Phase 3 with the execution module."""

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from arestoteles.db import costs, state
from arestoteles.ingest.alpaca import AlpacaData
from arestoteles.log import get_logger
from arestoteles.runs.runner import RunContext, execute_run
from arestoteles.runs.snapshots import digest_text, equal_weight_level

log = get_logger(__name__)

BENCH_BASE_KEY = "bench_equal_weight_base"


def run(ctx: RunContext) -> dict[str, Any]:
    ctx.settings.require("alpaca_paper_key", "alpaca_paper_secret")
    alpaca = AlpacaData(ctx.settings.alpaca_paper_key, ctx.settings.alpaca_paper_secret)

    account = alpaca.account_state()
    tickers = sorted(ctx.universe.traded_tickers)
    bars = alpaca.daily_bars([*tickers, "SOXX", "QQQ"], days=10)
    closes = {t: tb[-1].close for t, tb in bars.items() if tb}
    snapshot_date = ctx.now.date()

    with ctx.engine.begin() as conn:
        base = state.get_state(conn, BENCH_BASE_KEY)
        if base is None:
            universe_closes = {t: c for t, c in closes.items() if t in ctx.universe.traded_tickers}
            base = {"date": snapshot_date.isoformat(), "closes": universe_closes}
            state.set_state(conn, BENCH_BASE_KEY, base)
            log.info("equal-weight benchmark base pinned", date=base["date"])
        bench_ew = equal_weight_level(base["closes"], closes)

        for p in account.positions:
            weight = p.market_value / account.equity * 100.0 if account.equity else None
            conn.execute(
                text(
                    "INSERT INTO positions_daily (snapshot_date, ticker, qty, avg_cost, "
                    "  market_value, unrealized_pnl, weight_pct) "
                    "VALUES (:d, :t, :q, :ac, :mv, :up, :w) "
                    "ON CONFLICT (snapshot_date, ticker) DO UPDATE SET qty = EXCLUDED.qty, "
                    "  avg_cost = EXCLUDED.avg_cost, market_value = EXCLUDED.market_value, "
                    "  unrealized_pnl = EXCLUDED.unrealized_pnl, weight_pct = EXCLUDED.weight_pct"
                ),
                {
                    "d": snapshot_date,
                    "t": p.ticker,
                    "q": p.qty,
                    "ac": p.avg_entry_price,
                    "mv": p.market_value,
                    "up": p.unrealized_pnl,
                    "w": weight,
                },
            )
        conn.execute(
            text(
                "INSERT INTO pnl_daily (snapshot_date, nav, cash, unrealized_pnl, "
                "  bench_equal_weight, bench_soxx, bench_qqq) "
                "VALUES (:d, :nav, :cash, :up, :ew, :soxx, :qqq) "
                "ON CONFLICT (snapshot_date) DO UPDATE SET nav = EXCLUDED.nav, "
                "  cash = EXCLUDED.cash, unrealized_pnl = EXCLUDED.unrealized_pnl, "
                "  bench_equal_weight = EXCLUDED.bench_equal_weight, "
                "  bench_soxx = EXCLUDED.bench_soxx, bench_qqq = EXCLUDED.bench_qqq"
            ),
            {
                "d": snapshot_date,
                "nav": account.equity,
                "cash": account.cash,
                "up": sum(p.unrealized_pnl for p in account.positions),
                "ew": bench_ew,
                "soxx": closes.get("SOXX"),
                "qqq": closes.get("QQQ"),
            },
        )

        events_today = conn.execute(
            text("SELECT count(*) FROM events WHERE first_seen_at >= :since"),
            {"since": datetime.now(UTC) - timedelta(hours=24)},
        ).scalar_one()
        runs_today = conn.execute(
            text(
                "SELECT run_type, status FROM runs "
                "WHERE started_at >= date_trunc('day', now()) AND id != :self ORDER BY started_at"
            ),
            {"self": ctx.run_id},
        ).fetchall()
        month_eur = costs.month_cost_eur(conn)

    from arestoteles.notify.telegram import send_message

    send_message(
        digest_text(
            nav=account.equity,
            cash=account.cash,
            n_positions=len(account.positions),
            events_today=int(events_today),
            month_cost_eur=month_eur,
            runs_today=[(r.run_type, r.status) for r in runs_today],
            mode=ctx.config.mode.trading_mode,
        )
    )
    return {
        "nav": account.equity,
        "positions": len(account.positions),
        "bench_equal_weight": bench_ew,
        "bench_soxx": closes.get("SOXX"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="run even if the US market is closed today"
    )
    args = parser.parse_args()
    return execute_run("post_close", run, require_market_day=True, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
