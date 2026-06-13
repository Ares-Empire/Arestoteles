"""RSS/Atom poller (docs/04 Layer 1): free, deterministic detection.

Fail-closed semantics: individual dead feeds are logged and tolerated (a single
publisher outage must not blind the whole sweep), but if more than half of all
feeds fail, the poll raises and the run fails closed."""

import asyncio
import calendar
from datetime import UTC, datetime

import feedparser
import httpx

from arestoteles.config import Universe
from arestoteles.ingest.feeds import USER_AGENT, all_feeds, tickers_in_text
from arestoteles.ingest.models import IngestEvent, dedup_hash
from arestoteles.log import get_logger

log = get_logger(__name__)

FETCH_TIMEOUT = 20.0
MAX_CONCURRENCY = 6
RETRIES = 2


class PollResult:
    def __init__(self) -> None:
        self.events: list[IngestEvent] = []
        self.feeds_ok: list[str] = []
        self.feeds_failed: dict[str, str] = {}


def _entry_datetime(entry: feedparser.FeedParserDict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
    return None


def parse_feed(feed_key: str, content: bytes, ticker_hint: str | None = None) -> list[IngestEvent]:
    """Parse one fetched feed into events. Pure given bytes — fixture-testable."""
    parsed = feedparser.parse(content)
    events: list[IngestEvent] = []
    for entry in parsed.entries:
        headline = (entry.get("title") or "").strip()
        url = (entry.get("link") or "").strip()
        if not headline or not url:
            continue
        guid = entry.get("id") or url
        tickers = set(tickers_in_text(headline))
        if ticker_hint:
            tickers.add(ticker_hint)
        events.append(
            IngestEvent(
                source="rss",
                feed=feed_key,
                url=url,
                headline=headline,
                published_at=_entry_datetime(entry),
                tickers=tuple(sorted(tickers)),
                dedup_hash=dedup_hash("rss", guid),
                raw={"summary": (entry.get("summary") or "")[:500]},
            )
        )
    return events


async def _fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, key: str, url: str) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            async with sem:
                resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # feed errors are data, not bugs
            last_exc = exc
            if attempt < RETRIES:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"feed fetch failed after retries: {key}: {last_exc}")


async def poll_feeds(universe: Universe, feeds: dict[str, str] | None = None) -> PollResult:
    feeds = feeds if feeds is not None else all_feeds(universe)
    result = PollResult()
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        tasks = {key: _fetch(client, sem, key, url) for key, url in feeds.items()}
        fetched = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for key, content in zip(tasks.keys(), fetched, strict=True):
        if isinstance(content, BaseException):
            result.feeds_failed[key] = str(content)
            log.warning("feed failed", feed=key, error=str(content))
            continue
        ticker_hint = key.split(":", 2)[1] if key.startswith(("gnews:", "yahoo:")) else None
        try:
            events = parse_feed(key, content, ticker_hint=ticker_hint)
        except Exception as exc:  # malformed XML etc.
            result.feeds_failed[key] = f"parse: {exc}"
            log.warning("feed parse failed", feed=key, error=str(exc))
            continue
        result.feeds_ok.append(key)
        result.events.extend(events)

    if len(result.feeds_failed) > len(feeds) / 2:
        raise RuntimeError(
            f"rss poll failed closed: {len(result.feeds_failed)}/{len(feeds)} feeds failed "
            f"({sorted(result.feeds_failed)[:5]}...)"
        )
    log.info(
        "rss poll done",
        feeds_ok=len(result.feeds_ok),
        feeds_failed=len(result.feeds_failed),
        events=len(result.events),
    )
    return result
