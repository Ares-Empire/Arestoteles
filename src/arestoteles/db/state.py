"""app_state flags (kill switch, per-ticker pauses) and runs bookkeeping."""

import json
from typing import Any

from sqlalchemy import Connection, text

# --- app_state ---------------------------------------------------------------


def get_state(conn: Connection, key: str, default: Any = None) -> Any:
    row = conn.execute(text("SELECT value FROM app_state WHERE key = :k"), {"k": key}).fetchone()
    return default if row is None else row[0]


def set_state(conn: Connection, key: str, value: Any) -> None:
    conn.execute(
        text(
            "INSERT INTO app_state (key, value, updated_at) "
            "VALUES (:k, CAST(:v AS jsonb), now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
        ),
        {"k": key, "v": json.dumps(value)},
    )


def is_halted(conn: Connection) -> bool:
    return bool(get_state(conn, "halted", default=False))


def set_halted(conn: Connection, halted: bool) -> None:
    set_state(conn, "halted", halted)


def paused_tickers(conn: Connection) -> set[str]:
    return set(get_state(conn, "paused_tickers", default=[]))


# --- runs --------------------------------------------------------------------


def start_run(conn: Connection, run_type: str) -> int:
    row = conn.execute(
        text("INSERT INTO runs (run_type) VALUES (:t) RETURNING id"), {"t": run_type}
    ).fetchone()
    assert row is not None
    return int(row[0])


def finish_run(
    conn: Connection,
    run_id: int,
    status: str,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Close a runs row; token/cost totals are aggregated from api_costs."""
    conn.execute(
        text(
            "UPDATE runs SET "
            "  ended_at = now(), status = :s, error = :e, "
            "  meta = meta || CAST(:m AS jsonb), "
            "  input_tokens = COALESCE("
            "    (SELECT sum(input_tokens) FROM api_costs WHERE run_id = :id), 0), "
            "  output_tokens = COALESCE("
            "    (SELECT sum(output_tokens) FROM api_costs WHERE run_id = :id), 0), "
            "  cost_eur = COALESCE((SELECT sum(cost_eur) FROM api_costs WHERE run_id = :id), 0) "
            "WHERE id = :id"
        ),
        {"id": run_id, "s": status, "e": error, "m": json.dumps(meta or {})},
    )


def last_run(conn: Connection, run_type: str | None = None) -> dict[str, Any] | None:
    if run_type:
        row = conn.execute(
            text(
                "SELECT id, run_type, started_at, ended_at, status, error FROM runs "
                "WHERE run_type = :t ORDER BY started_at DESC LIMIT 1"
            ),
            {"t": run_type},
        ).fetchone()
    else:
        row = conn.execute(
            text(
                "SELECT id, run_type, started_at, ended_at, status, error FROM runs "
                "ORDER BY started_at DESC LIMIT 1"
            )
        ).fetchone()
    return dict(row._mapping) if row else None
