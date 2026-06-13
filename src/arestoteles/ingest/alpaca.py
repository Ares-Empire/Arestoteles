"""Read-only Alpaca market data + clock/calendar (docs/03, docs/06).

Phase 1 scope: prices, clock, calendar, snapshots — enough for the schedule gate,
staleness checks, ADV liquidity caps, benchmark series, and >6% move detection.
Order placement lives in the Phase 3 execution module, NOT here.

The wrapper converts SDK objects to frozen local models immediately so the rest of
the codebase (and the risk engine) never touches alpaca-py types. Conversions are
pure functions, unit-tested with stubs; the live round trip is tests/test_alpaca_live.py
(pytest -m live, needs ALPACA_PAPER_KEY/SECRET).
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from arestoteles.ingest.models import IngestEvent, dedup_hash
from arestoteles.log import get_logger

log = get_logger(__name__)


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MarketClock(FrozenModel):
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime


class TradingDay(FrozenModel):
    day: date
    open: datetime
    close: datetime


class DailyBar(FrozenModel):
    ticker: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class Snapshot(FrozenModel):
    ticker: str
    latest_price: float
    latest_at: datetime
    prev_close: float | None

    @property
    def pct_move_from_prev_close(self) -> float | None:
        if not self.prev_close:
            return None
        return (self.latest_price - self.prev_close) / self.prev_close * 100.0


class BrokerPosition(FrozenModel):
    ticker: str
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pnl: float


class AccountState(FrozenModel):
    equity: float  # NAV
    cash: float
    positions: tuple[BrokerPosition, ...] = ()


# --- pure conversions & math (unit-tested with stubs) -------------------------


def clock_from(raw: Any) -> MarketClock:
    return MarketClock(
        timestamp=raw.timestamp,
        is_open=raw.is_open,
        next_open=raw.next_open,
        next_close=raw.next_close,
    )


def trading_day_from(raw: Any) -> TradingDay:
    return TradingDay(day=raw.date, open=raw.open, close=raw.close)


def bar_from(ticker: str, raw: Any) -> DailyBar:
    ts = raw.timestamp
    return DailyBar(
        ticker=ticker,
        day=ts.date() if isinstance(ts, datetime) else ts,
        open=float(raw.open),
        high=float(raw.high),
        low=float(raw.low),
        close=float(raw.close),
        volume=float(raw.volume),
    )


def snapshot_from(ticker: str, raw: Any) -> Snapshot | None:
    trade = getattr(raw, "latest_trade", None)
    prev = getattr(raw, "previous_daily_bar", None)
    if trade is None or trade.price is None:
        return None
    return Snapshot(
        ticker=ticker,
        latest_price=float(trade.price),
        latest_at=trade.timestamp,
        prev_close=float(prev.close) if prev is not None and prev.close else None,
    )


def adv20_usd(bars: list[DailyBar]) -> float | None:
    """20-day average daily dollar volume (risk engine liquidity cap input)."""
    recent = sorted(bars, key=lambda b: b.day)[-20:]
    if len(recent) < 5:  # too little history to call it liquidity data
        return None
    return sum(b.close * b.volume for b in recent) / len(recent)


def big_move_events(
    snapshots: dict[str, Snapshot], threshold_pct: float, now: datetime
) -> list[IngestEvent]:
    """>threshold% moves vs. previous close -> events (docs/03 event triggers)."""
    events = []
    for ticker, snap in sorted(snapshots.items()):
        move = snap.pct_move_from_prev_close
        if move is None or abs(move) < threshold_pct:
            continue
        events.append(
            IngestEvent(
                source="price_move",
                feed="alpaca:moves",
                url="",
                headline=f"{ticker} moved {move:+.1f}% vs prev close "
                f"({snap.prev_close} -> {snap.latest_price})",
                published_at=snap.latest_at,
                tickers=(ticker,),
                # one event per ticker per direction per day
                dedup_hash=dedup_hash(
                    "price_move", ticker, now.date().isoformat(), "up" if move > 0 else "down"
                ),
                raw={"pct_move": round(move, 2)},
            )
        )
    return events


# --- the client ----------------------------------------------------------------


class AlpacaData:
    """Thin read-only wrapper. Paper endpoint only — live keys must not exist
    anywhere until Phase 5 (CLAUDE.md guardrail #6)."""

    def __init__(self, key: str, secret: str) -> None:
        if not key or not secret:
            raise RuntimeError(
                "ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET missing — add the paper keys to .env"
            )
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        self._trading = TradingClient(key, secret, paper=True)
        self._data = StockHistoricalDataClient(key, secret)

    def clock(self) -> MarketClock:
        return clock_from(self._trading.get_clock())

    def calendar(self, start: date, end: date) -> list[TradingDay]:
        from alpaca.trading.requests import GetCalendarRequest

        raw = self._trading.get_calendar(GetCalendarRequest(start=start, end=end))
        return [trading_day_from(d) for d in raw]

    def daily_bars(self, tickers: list[str], days: int = 30) -> dict[str, list[DailyBar]]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        req = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame.Day,
            start=datetime.now(UTC) - timedelta(days=days * 2),  # weekends/holidays margin
            feed="iex",  # free tier
        )
        raw = self._data.get_stock_bars(req)
        return {t: [bar_from(t, b) for b in raw.data.get(t, [])] for t in tickers}

    def snapshots(self, tickers: list[str]) -> dict[str, Snapshot]:
        from alpaca.data.requests import StockSnapshotRequest

        raw = self._data.get_stock_snapshot(
            StockSnapshotRequest(symbol_or_symbols=tickers, feed="iex")
        )
        out: dict[str, Snapshot] = {}
        for t in tickers:
            snap = snapshot_from(t, raw[t]) if t in raw else None
            if snap is not None:
                out[t] = snap
        return out

    def account_state(self) -> AccountState:
        """Broker truth for snapshots/reconciliation. Read-only — order placement
        is the Phase 3 execution module, never this class."""
        acct = self._trading.get_account()
        raw_positions = self._trading.get_all_positions()
        positions = tuple(
            BrokerPosition(
                ticker=p.symbol,
                qty=float(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                market_value=float(p.market_value or 0),
                unrealized_pnl=float(p.unrealized_pl or 0),
            )
            for p in raw_positions
        )
        return AccountState(equity=float(acct.equity), cash=float(acct.cash), positions=positions)
