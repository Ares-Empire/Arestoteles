"""Feed registry + headline->ticker matching (docs/04 Layer 1).

Every URL here was verified with a real request (scripts/verify_feeds.py) on
2026-06-13 per CLAUDE.md verify-before-use. Re-verify at the quarterly review:
    uv run python scripts/verify_feeds.py
"""

import re
from functools import lru_cache
from urllib.parse import quote_plus

from arestoteles.config import Universe, load_universe

USER_AGENT = "ArestotelesBot/0.1 (+https://github.com/carlsenares/Arestoteles)"

# Sector-wide feeds: detection only — research uses the search whitelist, not these.
SECTOR_FEEDS: dict[str, str] = {
    "cnbc_tech": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "techcrunch": "https://techcrunch.com/feed/",
    "ars_technica": "https://feeds.arstechnica.com/arstechnica/index",
    "toms_hardware": "https://www.tomshardware.com/feeds/all",
    "the_register": "https://www.theregister.com/headlines.atom",
    "semianalysis": "https://semianalysis.com/feed/",
    "next_platform": "https://www.nextplatform.com/feed/",
    "datacenter_dynamics": "https://www.datacenterdynamics.com/en/rss/",
}


def google_news_feed_url(ticker: str, company_name: str) -> str:
    """Per-ticker Google News query feed (last 7 days, US English)."""
    query = f'"{_clean_name(company_name)}" OR "{ticker}" stock when:7d'
    return (
        "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    )


def yahoo_finance_feed_url(ticker: str) -> str:
    """Per-ticker Yahoo Finance headline feed."""
    return (
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s="
        + quote_plus(ticker)
        + "&region=US&lang=en-US"
    )


def per_ticker_feeds(universe: Universe) -> dict[str, str]:
    """feed_key -> url for every traded ticker (Google News + Yahoo)."""
    feeds: dict[str, str] = {}
    for t in universe.traded:
        feeds[f"gnews:{t.ticker}"] = google_news_feed_url(t.ticker, t.name)
        feeds[f"yahoo:{t.ticker}"] = yahoo_finance_feed_url(t.ticker)
    return feeds


def all_feeds(universe: Universe) -> dict[str, str]:
    return {**{f"rss:{k}": v for k, v in SECTOR_FEEDS.items()}, **per_ticker_feeds(universe)}


# --- headline -> tickers ------------------------------------------------------

# Name variants beyond universe.yaml's `name` field. Matching stays CASE-SENSITIVE
# on purpose: "Cadence Design" is CDNS but "release cadence" is not, "ON Semiconductor"
# is ON but "turn on" is not. Headlines use natural casing, so aliases cover it.
_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "NVDA": ("Nvidia",),  # universe name is all-caps NVIDIA; press writes Nvidia
    "TSM": ("Taiwan Semiconductor",),
    "ON": ("ON Semiconductor", "Onsemi"),
    "ANET": ("Arista",),
    # monitored demand-signal names (universe.yaml gives them no `name` field)
    "MSFT": ("Microsoft",),
    "GOOGL": ("Alphabet", "Google"),
    "AMZN": ("Amazon",),
    "META": ("Meta", "Facebook"),
}
_AMBIGUOUS_TICKERS = {"ON", "ARM", "DELL", "MU"}  # bare-token match too noisy / name suffices


def _clean_name(name: str) -> str:
    return re.sub(r"\s*\(.*\)$", "", name).strip()  # "TSMC (ADR)" -> "TSMC"


@lru_cache(maxsize=1)
def _matcher() -> list[tuple[str, re.Pattern[str]]]:
    uni = load_universe()
    patterns: list[tuple[str, re.Pattern[str]]] = []
    names: dict[str, list[str]] = {}
    for t in uni.traded:
        names.setdefault(t.ticker, []).append(_clean_name(t.name))
    for m in uni.monitored_only:
        names.setdefault(m.ticker, [])
    for ticker, aliases in _EXTRA_ALIASES.items():
        names.setdefault(ticker, []).extend(aliases)
    for ticker, variants in names.items():
        parts = [re.escape(v) for v in variants if v]
        if ticker not in _AMBIGUOUS_TICKERS:
            parts.append(re.escape(ticker))
        if not parts:
            continue
        # names case-sensitive as written (Micron, onsemi); tickers uppercase-only
        patterns.append((ticker, re.compile(r"\b(" + "|".join(parts) + r")\b")))
    return patterns


def tickers_in_text(text: str) -> tuple[str, ...]:
    """All universe tickers (traded + monitored) referenced in a headline."""
    return tuple(sorted({ticker for ticker, pat in _matcher() if pat.search(text)}))
