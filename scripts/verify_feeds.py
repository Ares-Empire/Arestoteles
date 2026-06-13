"""Live verification of every feed URL (CLAUDE.md verify-before-use; re-run at the
quarterly review, docs/08 §5).

    uv run python scripts/verify_feeds.py [--full]

Default: all sector feeds + per-ticker feeds for a 3-ticker sample.
--full: every per-ticker feed for the whole universe (slower, ~50 requests).
"""

import asyncio
import sys

import feedparser
import httpx

from arestoteles.config import load_universe
from arestoteles.ingest.feeds import SECTOR_FEEDS, USER_AGENT, per_ticker_feeds

SAMPLE_TICKERS = ("NVDA", "VRT", "ON")


async def check(client: httpx.AsyncClient, sem: asyncio.Semaphore, key: str, url: str):
    try:
        async with sem:
            resp = await client.get(url)
        n_entries = len(feedparser.parse(resp.content).entries)
        ok = resp.status_code == 200 and n_entries > 0
        return key, url, resp.status_code, n_entries, ok
    except Exception as exc:
        return key, url, None, 0, f"EXC {type(exc).__name__}: {exc}"


async def main() -> int:
    uni = load_universe()
    feeds = {f"rss:{k}": v for k, v in SECTOR_FEEDS.items()}
    ticker_feeds = per_ticker_feeds(uni)
    if "--full" in sys.argv:
        feeds.update(ticker_feeds)
    else:
        feeds.update({k: v for k, v in ticker_feeds.items() if k.split(":")[1] in SAMPLE_TICKERS})

    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(
        timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        rows = await asyncio.gather(*(check(client, sem, k, u) for k, u in feeds.items()))

    failures = 0
    for key, url, status, n, ok in sorted(rows):
        mark = "OK " if ok is True else "FAIL"
        if ok is not True:
            failures += 1
        print(f"{mark} {key:24} status={status} entries={n:4}  {url if ok is not True else ''}")
    print(f"\n{len(rows) - failures}/{len(rows)} feeds OK")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
