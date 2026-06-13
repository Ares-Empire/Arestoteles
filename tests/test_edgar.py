"""EDGAR parsing against recorded fixtures (live shapes captured 2026-06-13)."""

import json
from datetime import UTC, date
from pathlib import Path

import httpx
import pytest
import respx

from arestoteles.config import load_universe
from arestoteles.ingest.edgar import (
    FTS_URL,
    MATERIAL_FORMS,
    make_client,
    parse_submissions,
    search_fulltext,
    universe_ciks,
)

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
NVDA_SUBMISSIONS = json.loads((FIXTURES / "nvda_submissions.json").read_text())


def test_parse_submissions_filters_to_material_forms():
    events = parse_submissions("NVDA", NVDA_SUBMISSIONS, since=date(2020, 1, 1))
    assert events  # the trimmed fixture holds ~60 recent filings incl. Form 4s
    assert all(ev.raw["form"] in MATERIAL_FORMS for ev in events)
    all_forms = set(NVDA_SUBMISSIONS["filings"]["recent"]["form"])
    assert "4" in all_forms  # fixture really contained immaterial forms to filter out


def test_parse_submissions_event_shape():
    events = parse_submissions("NVDA", NVDA_SUBMISSIONS, since=date(2020, 1, 1))
    ev = events[0]
    assert ev.source == "edgar" and ev.feed == "edgar:NVDA"
    assert ev.tickers == ("NVDA",)
    assert ev.url.startswith("https://www.sec.gov/Archives/edgar/data/1045810/")
    assert ev.published_at is not None and ev.published_at.tzinfo is not None
    assert "NVIDIA" in ev.headline
    assert len({e.dedup_hash for e in events}) == len(events)


def test_parse_submissions_recency_window():
    assert parse_submissions("NVDA", NVDA_SUBMISSIONS, since=date(2099, 1, 1)) == []


def test_universe_ciks_fails_closed_on_missing_ticker():
    uni = load_universe()
    with pytest.raises(RuntimeError, match="no CIK"):
        universe_ciks({"NVDA": 1045810}, uni)  # everyone else missing


def test_make_client_requires_user_agent():
    with pytest.raises(RuntimeError, match="EDGAR_USER_AGENT"):
        make_client("")


@respx.mock
async def test_search_fulltext_parses_real_shape():
    fixture = (FIXTURES / "fts_nvidia.json").read_bytes()
    respx.get(FTS_URL).mock(return_value=httpx.Response(200, content=fixture))
    async with httpx.AsyncClient() as client:
        events = await search_fulltext(client, "NVIDIA", since=date(2026, 6, 6))
    assert len(events) == 3
    for ev in events:
        assert ev.source == "edgar_fts"
        assert ev.url.startswith("https://www.sec.gov/Archives/edgar/data/")
        assert ev.published_at is not None and ev.published_at.tzinfo == UTC
        assert ev.raw["adsh"]
