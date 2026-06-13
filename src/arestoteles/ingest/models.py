"""Shared shape for detected items from the free layer (docs/04 Layer 1)."""

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


def dedup_hash(*parts: str) -> str:
    """Stable identity for an item across polls. Prefer the source's own id (GUID,
    accession number); fall back to url+headline."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="replace"))
        h.update(b"\x1f")
    return h.hexdigest()


class IngestEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str  # rss | edgar | edgar_fts | price_move
    feed: str  # e.g. "rss:techcrunch", "edgar:NVDA"
    url: str
    headline: str
    published_at: datetime | None
    tickers: tuple[str, ...] = ()
    dedup_hash: str
    raw: dict[str, Any] = {}
