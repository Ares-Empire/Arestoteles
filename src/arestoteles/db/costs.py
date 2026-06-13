"""api_costs accounting — every AI call writes a row here (CLAUDE.md convention).

Phase 1 ships the ledger + budget queries; Phase 2 (first AI calls) must pass each
response's `usage` through record_api_cost. Price-per-token tables are deliberately
NOT hardcoded here — the caller computes cost from the model's current pricing at
call time (re-checked on model upgrades, docs/07).
"""

from datetime import UTC, datetime

from sqlalchemy import Connection, text


def record_api_cost(
    conn: Connection,
    *,
    run_id: int | None,
    stage: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    web_searches: int = 0,
    cost_usd: float = 0.0,
    cost_eur: float = 0.0,
) -> None:
    conn.execute(
        text(
            "INSERT INTO api_costs (run_id, stage, model, input_tokens, output_tokens, "
            "  cache_read_tokens, cache_write_tokens, web_searches, cost_usd, cost_eur) "
            "VALUES (:run_id, :stage, :model, :in_t, :out_t, :cr_t, :cw_t, :ws, :usd, :eur)"
        ),
        {
            "run_id": run_id,
            "stage": stage,
            "model": model,
            "in_t": input_tokens,
            "out_t": output_tokens,
            "cr_t": cache_read_tokens,
            "cw_t": cache_write_tokens,
            "ws": web_searches,
            "usd": cost_usd,
            "eur": cost_eur,
        },
    )


def month_cost_eur(conn: Connection, now: datetime | None = None) -> float:
    """Current calendar-month spend — checked against budgets.max_api_eur_per_month."""
    now = now or datetime.now(UTC)
    row = conn.execute(
        text(
            "SELECT COALESCE(sum(cost_eur), 0) FROM api_costs "
            "WHERE date_trunc('month', created_at) = date_trunc('month', CAST(:now AS timestamptz))"
        ),
        {"now": now},
    ).fetchone()
    assert row is not None
    return float(row[0])


def searches_today(conn: Connection, now: datetime | None = None) -> int:
    """UTC-day web-search count — checked against budgets.max_searches_per_day."""
    now = now or datetime.now(UTC)
    row = conn.execute(
        text(
            "SELECT COALESCE(sum(web_searches), 0) FROM api_costs "
            "WHERE created_at >= date_trunc('day', CAST(:now AS timestamptz)) "
            "  AND created_at < date_trunc('day', CAST(:now AS timestamptz)) + interval '1 day'"
        ),
        {"now": now},
    ).fetchone()
    assert row is not None
    return int(row[0])
