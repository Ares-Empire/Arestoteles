"""execute_run fail-closed semantics against a real Postgres (pytest -m live)."""

import os

import pytest
from sqlalchemy import create_engine, text

import arestoteles.runs.runner as runner_mod
from arestoteles.db import state
from arestoteles.db.migrate import migrate
from arestoteles.runs.runner import execute_run

pytestmark = pytest.mark.live

TEST_DB_URL = os.environ.get(
    "ARESTOTELES_TEST_DATABASE_URL",
    "postgresql+psycopg://arestoteles:arestoteles@localhost:55432/arestoteles",
)


@pytest.fixture()
def engine(monkeypatch):
    eng = create_engine(TEST_DB_URL)
    migrate(eng)
    monkeypatch.setattr(runner_mod, "get_engine", lambda: eng)
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(runner_mod, "send_alert", lambda t, b: alerts.append((t, b)))
    eng.alerts = alerts  # type: ignore[attr-defined]
    yield eng
    with eng.begin() as conn:
        state.set_halted(conn, False)
    eng.dispose()


def _last_run(eng, run_type):
    with eng.begin() as conn:
        row = conn.execute(
            text("SELECT status, error, meta FROM runs WHERE run_type=:t ORDER BY id DESC LIMIT 1"),
            {"t": run_type},
        ).fetchone()
    return row


def test_ok_run_records_meta(engine):
    rc = execute_run("adhoc", lambda ctx: {"items": 3}, require_market_day=False)
    assert rc == 0
    row = _last_run(engine, "adhoc")
    assert row.status == "ok" and row.meta["items"] == 3
    assert engine.alerts == []


def test_halt_flag_skips_run_before_anything_else(engine):
    with engine.begin() as conn:
        state.set_halted(conn, True)
    called = []
    rc = execute_run("adhoc", lambda ctx: called.append(1), require_market_day=False)
    assert rc == 0 and called == []
    assert _last_run(engine, "adhoc").status == "skipped_halted"


def test_exception_fails_closed_with_alert(engine):
    def boom(ctx):
        raise ValueError("synthetic failure")

    rc = execute_run("adhoc", boom, require_market_day=False)
    assert rc == 1
    row = _last_run(engine, "adhoc")
    assert row.status == "failed" and "synthetic failure" in row.error
    assert engine.alerts and "FAILED" in engine.alerts[0][0]


def test_market_gate_without_alpaca_keys_fails_closed(engine, monkeypatch):
    from arestoteles.config import Settings

    monkeypatch.setattr(runner_mod, "load_settings", lambda: Settings(_env_file=None))
    called = []
    rc = execute_run("adhoc", lambda ctx: called.append(1), require_market_day=True)
    assert rc == 1 and called == []
    row = _last_run(engine, "adhoc")
    assert row.status == "failed" and "market gate" in row.error
    assert engine.alerts
