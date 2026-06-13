"""Inputs/outputs of the risk engine. Everything is frozen and I/O-free: callers
fetch broker/market state, the engine only computes (docs/05 Tier 2)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from arestoteles.schemas import Action


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Position(FrozenModel):
    ticker: str
    qty: float  # always > 0 (long-only)
    avg_cost: float
    market_value: float
    opened_at: date
    last_buy_date: date | None = None  # for the same-day round-trip ban
    subcluster: str


class PortfolioState(FrozenModel):
    """Broker truth + day/week counters, assembled by the caller before validation."""

    nav: float
    cash: float
    high_water_mark: float  # of NAV, for circuit breakers
    positions: tuple[Position, ...] = ()
    orders_today: int = 0
    orders_this_week: int = 0
    new_capital_deployed_today: float = 0.0  # USD spent on buys/adds today
    tickers_sold_today: frozenset[str] = frozenset()
    # ticker -> trading days since the stop-loss fired (for re-entry cooldown)
    trading_days_since_stop: dict[str, int] = {}

    def position_for(self, ticker: str) -> Position | None:
        for p in self.positions:
            if p.ticker == ticker:
                return p
        return None

    def cluster_market_value(self, subcluster: str) -> float:
        return sum(p.market_value for p in self.positions if p.subcluster == subcluster)


class TickerMarket(FrozenModel):
    """Per-ticker market data from structured APIs (never from web text)."""

    current_price: float
    analysis_price: float  # the price the analyst pass saw
    price_asof: datetime
    adv20_usd: float | None = None  # 20-day average daily dollar volume
    trading_days_to_earnings: int | None = None


class MarketCtx(FrozenModel):
    now: datetime
    by_ticker: dict[str, TickerMarket] = {}


BreakerTier = Literal["none", "halve_sizes", "no_new_buys", "full_halt"]


class OrderPlan(FrozenModel):
    """A fully-sized order the execution module may place after (v1) human approval."""

    ticker: str
    side: Literal["buy", "sell"]
    qty: float
    limit_price: float  # marketable limit, ±limit_band_pct
    notional_usd: float
    time_in_force: Literal["day"] = "day"
    stop_loss_price: float | None = None  # GTC stop placed after the buy fills
    release_after_open_minutes: int = 5  # never trade the first minutes (docs/05)
    idempotency_key: str = ""


class Verdict(FrozenModel):
    """The engine's binding answer for one DecisionDraft."""

    ticker: str
    action: Action
    approved: bool
    reasons: tuple[str, ...] = ()  # rejection codes (empty when approved)
    notes: tuple[str, ...] = ()  # non-fatal adjustments, for the audit trail
    order: OrderPlan | None = None  # None for hold (and for rejections)
