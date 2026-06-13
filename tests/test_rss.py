"""RSS parsing against recorded fixtures (docs/08 §1: no live calls in CI) and the
headline->ticker matcher's precision cases."""

from pathlib import Path

import httpx
import pytest
import respx

from arestoteles.ingest.feeds import tickers_in_text
from arestoteles.ingest.rss import parse_feed, poll_feeds

FIXTURES = Path(__file__).parent / "fixtures" / "rss"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- parsing fixtures ----------------------------------------------------------


def test_google_news_fixture_parses_with_hint():
    events = parse_feed("gnews:NVDA", load("gnews_nvda.xml"), ticker_hint="NVDA")
    assert len(events) == 8
    for ev in events:
        assert "NVDA" in ev.tickers
        assert ev.headline and ev.url.startswith("http")
        assert ev.published_at is not None and ev.published_at.tzinfo is not None
        assert ev.source == "rss" and ev.feed == "gnews:NVDA"


def test_yahoo_fixture_parses():
    events = parse_feed("yahoo:VRT", load("yahoo_vrt.xml"), ticker_hint="VRT")
    assert len(events) == 8
    assert all("VRT" in ev.tickers for ev in events)


def test_sector_feed_parses_without_hint():
    events = parse_feed("rss:the_register", load("the_register.atom"))
    assert len(events) == 8
    assert all(ev.published_at is not None for ev in events)


def test_dedup_hashes_unique_and_stable():
    a = parse_feed("gnews:NVDA", load("gnews_nvda.xml"), ticker_hint="NVDA")
    b = parse_feed("gnews:NVDA", load("gnews_nvda.xml"), ticker_hint="NVDA")
    assert [e.dedup_hash for e in a] == [e.dedup_hash for e in b]
    assert len({e.dedup_hash for e in a}) == len(a)


def test_malformed_entries_are_skipped():
    xml = b"<rss><channel><item><title>No link here</title></item></channel></rss>"
    assert parse_feed("rss:x", xml) == []


# --- ticker matcher precision ----------------------------------------------------


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("Nvidia and Marvell rally on AI capex hopes", ("MRVL", "NVDA")),
        ("Micron guides HBM sold out through 2027", ("MU",)),
        ("Turn on the lights: grid demand soars", ()),
        ("Nvidia moves to annual release cadence", ("NVDA",)),  # not CDNS
        ("Cadence and Synopsys gain on EDA export news", ("CDNS", "SNPS")),
        ("TSMC monthly revenue jumps 30%", ("TSM",)),
        ("Taiwan Semiconductor expands Arizona fab", ("TSM",)),
        ("Microsoft raises FY27 capex guidance", ("MSFT",)),
        ("ASML and KLA report strong bookings", ("ASML", "KLAC")),
        ("ON Semiconductor wins auto design", ("ON",)),
        ("Onsemi shares jump", ("ON",)),
        ("Arista wins hyperscaler order", ("ANET",)),
        ("Oracle commits $40bn to datacenters", ("ORCL",)),
        ("SK Hynix boosts memory output", ()),  # not in universe
    ],
)
def test_tickers_in_text(headline, expected):
    assert tickers_in_text(headline) == expected


# --- poll fail-closed semantics ---------------------------------------------------


@respx.mock
async def test_poll_tolerates_minority_feed_failures():
    feeds = {
        "rss:a": "https://feeds.test/a",
        "rss:b": "https://feeds.test/b",
        "rss:c": "https://feeds.test/c",
    }
    respx.get(feeds["rss:a"]).mock(return_value=httpx.Response(200, content=load("yahoo_vrt.xml")))
    respx.get(feeds["rss:b"]).mock(return_value=httpx.Response(200, content=load("gnews_nvda.xml")))
    respx.get(feeds["rss:c"]).mock(return_value=httpx.Response(500))
    result = await poll_feeds(None, feeds=feeds)  # universe unused when feeds given
    assert len(result.feeds_ok) == 2
    assert "rss:c" in result.feeds_failed
    assert len(result.events) == 16


@respx.mock
async def test_poll_fails_closed_when_majority_fail():
    feeds = {
        "rss:a": "https://feeds.test/a",
        "rss:b": "https://feeds.test/b",
        "rss:c": "https://feeds.test/c",
    }
    respx.get(feeds["rss:a"]).mock(return_value=httpx.Response(200, content=load("yahoo_vrt.xml")))
    respx.get(feeds["rss:b"]).mock(return_value=httpx.Response(403))
    respx.get(feeds["rss:c"]).mock(return_value=httpx.Response(500))
    with pytest.raises(RuntimeError, match="failed closed"):
        await poll_feeds(None, feeds=feeds)
