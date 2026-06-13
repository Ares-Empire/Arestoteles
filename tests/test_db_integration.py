"""Real-Postgres integration tests (excluded from CI; run with `pytest -m live`).

Needs a running Postgres and ARESTOTELES_TEST_DATABASE_URL (or the default below,
matching the throwaway container in deploy/README)."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from arestoteles.db import costs, events, state
from arestoteles.db.migrate import migrate
from arestoteles.ingest.models import IngestEvent, dedup_hash

pytestmark = pytest.mark.live

TEST_DB_URL = os.environ.get(
    "ARESTOTELES_TEST_DATABASE_URL",
    "postgresql+psycopg://arestoteles:arestoteles@localhost:55432/arestoteles",
)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    migrate(eng)
    yield eng
    eng.dispose()


def test_migrations_idempotent(engine):
    assert migrate(engine) == []  # second call applies nothing


def test_halt_flag_roundtrip(engine):
    with engine.begin() as conn:
        assert state.is_halted(conn) is False
        state.set_halted(conn, True)
        assert state.is_halted(conn) is True
        state.set_halted(conn, False)
        assert state.is_halted(conn) is False


def test_run_lifecycle_aggregates_costs(engine):
    with engine.begin() as conn:
        run_id = state.start_run(conn, "adhoc")
        costs.record_api_cost(
            conn,
            run_id=run_id,
            stage="triage",
            model="claude-haiku-4-5",
            input_tokens=1000,
            output_tokens=200,
            web_searches=2,
            cost_usd=0.004,
            cost_eur=0.0037,
        )
        state.finish_run(conn, run_id, "ok", meta={"events": 5})
        row = conn.execute(
            text(
                "SELECT status, input_tokens, output_tokens, cost_eur, meta FROM runs WHERE id=:i"
            ),
            {"i": run_id},
        ).fetchone()
    assert row is not None
    assert row.status == "ok"
    assert row.input_tokens == 1000
    assert row.output_tokens == 200
    assert float(row.cost_eur) > 0
    assert row.meta["events"] == 5
    with engine.begin() as conn:
        assert costs.month_cost_eur(conn) > 0
        assert costs.searches_today(conn) >= 2


def test_event_dedup(engine):
    unique = uuid.uuid4().hex
    ev = IngestEvent(
        source="rss",
        feed="rss:test",
        url=f"https://example.com/{unique}",
        headline="NVDA does a thing",
        published_at=datetime.now(UTC),
        tickers=("NVDA",),
        dedup_hash=dedup_hash("test", unique),
        raw={"k": "v"},
    )
    with engine.begin() as conn:
        assert events.insert_events(conn, [ev]) == 1
        assert events.insert_events(conn, [ev]) == 0  # same hash -> deduped
        rows = events.recent_events(conn, since=datetime(2020, 1, 1, tzinfo=UTC), tickers=["NVDA"])
    assert any(r["url"] == ev.url for r in rows)
