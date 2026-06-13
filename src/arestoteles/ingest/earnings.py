"""Earnings calendar via Finnhub free tier (docs/04 Layer 1 'recurring known signals').

The risk engine fails closed on buys when a name's next earnings date is unknown
(missing_earnings_calendar), so this feed is required before Phase 3 paper trading.
Free key: https://finnhub.io — FINNHUB_API_KEY in .env.
"""

from datetime import date

import httpx

from arestoteles.log import get_logger

log = get_logger(__name__)

CALENDAR_URL = "https://finnhub.io/api/v1/calendar/earnings"


async def fetch_earnings_dates(
    client: httpx.AsyncClient, api_key: str, tickers: list[str], horizon_days: int = 45
) -> dict[str, date]:
    """ticker -> next confirmed earnings date within the horizon."""
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY missing — needed for the earnings blackout rule")
    from datetime import timedelta

    today = date.today()
    resp = await client.get(
        CALENDAR_URL,
        params={
            "from": today.isoformat(),
            "to": (today + timedelta(days=horizon_days)).isoformat(),
            "token": api_key,
        },
    )
    resp.raise_for_status()
    wanted = set(tickers)
    out: dict[str, date] = {}
    for row in resp.json().get("earningsCalendar", []):
        symbol = (row.get("symbol") or "").upper()
        when = row.get("date")
        if symbol in wanted and when:
            d = date.fromisoformat(when)
            if symbol not in out or d < out[symbol]:
                out[symbol] = d
    return out


def trading_days_until(target: date, today: date, trading_days: list[date]) -> int | None:
    """Trading days strictly after `today`, up to and including `target` — the dte
    input of the earnings-blackout rule. 0 = earnings today (or already past).
    None when the supplied calendar window doesn't reach the target (unknown)."""
    if target <= today:
        return 0
    if not trading_days or target > max(trading_days):
        return None
    return sum(1 for d in trading_days if today < d <= target)
