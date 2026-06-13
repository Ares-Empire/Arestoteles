"""events table writes/reads. Dedup happens here: ON CONFLICT (dedup_hash) DO NOTHING,
so pollers can re-see the same item across runs without creating duplicates."""

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from arestoteles.ingest.models import IngestEvent

_INSERT = text(
    "INSERT INTO events "
    "  (source, feed, url, headline, published_at, tickers, dedup_hash, raw, run_id) "
    "VALUES (:source, :feed, :url, :headline, :published_at, :tickers, :dedup_hash, "
    "        CAST(:raw AS jsonb), :run_id) "
    "ON CONFLICT (dedup_hash) DO NOTHING"
)


def insert_events(
    conn: Connection, events: Iterable[IngestEvent], run_id: int | None = None
) -> int:
    """Insert new events; returns how many were actually new."""
    inserted = 0
    for ev in events:
        result = conn.execute(
            _INSERT,
            {
                "source": ev.source,
                "feed": ev.feed,
                "url": ev.url,
                "headline": ev.headline,
                "published_at": ev.published_at,
                "tickers": list(ev.tickers),
                "dedup_hash": ev.dedup_hash,
                "raw": json.dumps(ev.raw, default=str),
                "run_id": run_id,
            },
        )
        inserted += result.rowcount or 0
    return inserted


def recent_events(
    conn: Connection, since: datetime, tickers: list[str] | None = None
) -> list[dict[str, Any]]:
    if tickers:
        rows = conn.execute(
            text(
                "SELECT id, source, feed, url, headline, published_at, tickers, triage_score "
                "FROM events WHERE first_seen_at >= :since AND tickers && CAST(:tickers AS text[]) "
                "ORDER BY published_at DESC NULLS LAST"
            ),
            {"since": since, "tickers": tickers},
        ).fetchall()
    else:
        rows = conn.execute(
            text(
                "SELECT id, source, feed, url, headline, published_at, tickers, triage_score "
                "FROM events WHERE first_seen_at >= :since "
                "ORDER BY published_at DESC NULLS LAST"
            ),
            {"since": since},
        ).fetchall()
    return [dict(r._mapping) for r in rows]
