"""SEC EDGAR detection (docs/04 Layer 1): canonical, free, minutes-fresh.

Sources:
- data.sec.gov/submissions/CIK##########.json per company — the structured
  successor of the per-company Atom feeds named in docs/04 (same freshness,
  no HTML/XML scraping). Covers filings BY the company (8-K, 10-Q/K, 6-K, ...).
- efts.sec.gov full-text search — universe keyword queries; also the net that
  catches SC 13D/G *about* our names filed by third parties.

SEC fair-use: descriptive User-Agent with contact (EDGAR_USER_AGENT in .env)
and modest request rates. We poll ~28 companies a few times per day.
"""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import httpx

from arestoteles.config import Universe
from arestoteles.ingest.models import IngestEvent, dedup_hash
from arestoteles.log import get_logger

log = get_logger(__name__)

CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FTS_URL = "https://efts.sec.gov/LATEST/search-index"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"

# Material form types (docs/04). FPIs (TSM/ASML/ARM) file 6-K/20-F instead of 8-K/10-K.
MATERIAL_FORMS = {
    "8-K",
    "10-Q",
    "10-K",
    "20-F",
    "6-K",
    "S-8",
    "SC 13D",
    "SC 13G",
    "8-K/A",
    "10-Q/A",
    "10-K/A",
    "20-F/A",
    "6-K/A",
    "SC 13D/A",
    "SC 13G/A",
}

FETCH_TIMEOUT = 30.0
MAX_CONCURRENCY = 5


def make_client(user_agent: str) -> httpx.AsyncClient:
    if not user_agent:
        raise RuntimeError("EDGAR_USER_AGENT is required (SEC fair-use policy) — set it in .env")
    return httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
    )


async def fetch_cik_map(client: httpx.AsyncClient) -> dict[str, int]:
    """ticker -> CIK for ALL SEC registrants (filter to universe at the call site)."""
    resp = await client.get(CIK_MAP_URL)
    resp.raise_for_status()
    data = resp.json()
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def universe_ciks(cik_map: dict[str, int], universe: Universe) -> dict[str, int]:
    """CIKs for traded + monitored tickers; missing ones are a hard error (fail closed
    beats silently not watching a company's filings)."""
    wanted = sorted(universe.traded_tickers | universe.monitored_tickers)
    missing = [t for t in wanted if t not in cik_map]
    if missing:
        raise RuntimeError(f"no CIK found for universe tickers: {missing}")
    return {t: cik_map[t] for t in wanted}


def parse_submissions(ticker: str, payload: dict[str, Any], since: date) -> list[IngestEvent]:
    """Turn a submissions JSON into events for material recent filings."""
    recent = payload.get("filings", {}).get("recent", {})
    company = payload.get("name", ticker)
    cik = int(payload["cik"])
    events: list[IngestEvent] = []
    forms = recent.get("form", [])
    for i, form in enumerate(forms):
        if form not in MATERIAL_FORMS:
            continue
        filing_date = date.fromisoformat(recent["filingDate"][i])
        if filing_date < since:
            continue
        accession = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i] or ""
        url = FILING_URL.format(cik=cik, accession_nodash=accession.replace("-", ""), doc=doc)
        acceptance = recent.get("acceptanceDateTime", [None] * len(forms))[i]
        published = (
            datetime.fromisoformat(acceptance.replace("Z", "+00:00"))
            if acceptance
            else datetime(filing_date.year, filing_date.month, filing_date.day, tzinfo=UTC)
        )
        items = recent.get("items", [""] * len(forms))[i]
        headline = f"{form}: {company} ({ticker})" + (f" — items {items}" if items else "")
        events.append(
            IngestEvent(
                source="edgar",
                feed=f"edgar:{ticker}",
                url=url,
                headline=headline,
                published_at=published,
                tickers=(ticker,),
                dedup_hash=dedup_hash("edgar", accession, ticker),
                raw={"form": form, "accession": accession, "items": items},
            )
        )
    return events


async def poll_filings(
    client: httpx.AsyncClient,
    ciks: dict[str, int],
    since: date,
) -> list[IngestEvent]:
    """Fetch recent material filings for every universe company. Fails closed if more
    than half the companies can't be fetched."""
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def one(ticker: str, cik: int) -> list[IngestEvent] | Exception:
        try:
            async with sem:
                resp = await client.get(SUBMISSIONS_URL.format(cik=cik))
            resp.raise_for_status()
            return parse_submissions(ticker, resp.json(), since)
        except Exception as exc:
            log.warning("edgar submissions failed", ticker=ticker, error=str(exc))
            return exc

    results = await asyncio.gather(*(one(t, c) for t, c in ciks.items()))
    failures = sum(1 for r in results if isinstance(r, Exception))
    if failures > len(ciks) / 2:
        raise RuntimeError(f"edgar poll failed closed: {failures}/{len(ciks)} companies failed")
    events = [ev for r in results if isinstance(r, list) for ev in r]
    log.info("edgar poll done", companies=len(ciks), failures=failures, filings=len(events))
    return events


async def search_fulltext(
    client: httpx.AsyncClient,
    query: str,
    since: date,
    forms: str | None = None,
    max_hits: int = 20,
) -> list[IngestEvent]:
    """EDGAR full-text search (filings since 2001). Secondary net — e.g. third-party
    SC 13D/G about our names, or universe keywords in any filing body."""
    params: dict[str, str] = {
        "q": f'"{query}"',
        "dateRange": "custom",
        "startdt": since.isoformat(),
        "enddt": date.today().isoformat(),
    }
    if forms:
        params["forms"] = forms
    resp = await client.get(FTS_URL, params=params)
    resp.raise_for_status()
    hits = resp.json().get("hits", {}).get("hits", [])[:max_hits]
    events: list[IngestEvent] = []
    for hit in hits:
        src = hit.get("_source", {})
        doc_id = hit.get("_id", "")  # "0001493152-26-028370:ex99-1.htm"
        adsh = src.get("adsh") or doc_id.split(":", 1)[0]
        doc = doc_id.split(":", 1)[1] if ":" in doc_id else ""
        cik_list = src.get("ciks") or []
        display_names = src.get("display_names") or []
        form = src.get("form", "")
        file_date = src.get("file_date", "")
        published = datetime.fromisoformat(file_date).replace(tzinfo=UTC) if file_date else None
        if cik_list and adsh:
            url = FILING_URL.format(
                cik=int(cik_list[0]), accession_nodash=adsh.replace("-", ""), doc=doc
            )
        else:
            url = "https://efts.sec.gov/LATEST/search-index?q=" + query
        events.append(
            IngestEvent(
                source="edgar_fts",
                feed=f"edgar_fts:{query}",
                url=url,
                headline=f"FTS[{query}] {form}: {'; '.join(display_names) or adsh}",
                published_at=published,
                tickers=(),
                dedup_hash=dedup_hash("edgar_fts", adsh, doc_id, query),
                raw={"adsh": adsh, "form": form, "display_names": display_names},
            )
        )
    return events
