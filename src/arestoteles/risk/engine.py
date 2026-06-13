"""The deterministic risk engine (docs/05 Tier 2). Pure functions, no I/O, no AI.

Every DecisionDraft passes through validate_decision; nothing the model writes can
override these checks, because the model never calls this code — the runner does.

Interpretation notes (decided at implementation, documented for review):
- factual_error from the skeptic auto-rejects ANY non-hold draft (docs/04 Layer 6
  says auto-reject without carve-outs). Mechanical safety exits (hard stops) never
  travel through drafts, so capital return stays unimpeded.
- The order-frequency caps (3/day, 10/week) gate buys/adds only: docs/05 makes
  "leaving is always allowed" explicit, and anti-churn is a deployment concern.
  Exits past the cap are approved and flagged in notes for the post-mortem.
- min_subclusters_when_invested=k is encoded as: after a buy that opens a position,
  distinct subclusters >= min(number_of_positions, k). The min() prevents the
  small-book deadlock (a 2-position book cannot span 3 clusters) while forcing
  early diversification across chain links.
- Stop-loss prices are computed from the planned limit price; the execution module
  re-bases them on the actual fill (Phase 3).
"""

import hashlib
import math
from datetime import date, timedelta

from arestoteles.config import RiskConfig
from arestoteles.risk.models import (
    BreakerTier,
    MarketCtx,
    OrderPlan,
    PortfolioState,
    Position,
    Verdict,
)
from arestoteles.schemas import DecisionDraft, SkepticReview

MAX_PRICE_AGE = timedelta(minutes=15)  # docs/03 §6: refuse to decide on stale prices
MIN_ORDER_NOTIONAL_USD = 1.0  # below this, caps have sized the order away


def breaker_tier(nav: float, high_water_mark: float, cfg: RiskConfig) -> BreakerTier:
    """Portfolio circuit breakers from NAV drawdown vs. high-water mark (docs/05)."""
    if high_water_mark <= 0:
        return "none"
    # round before comparing: 1 - 80_000/100_000 is 19.999...% in floats and must trip -20%
    drawdown_pct = round(max(0.0, (1.0 - nav / high_water_mark) * 100.0), 9)
    cb = cfg.circuit_breakers
    if drawdown_pct >= cb.full_halt_at_pct:
        return "full_halt"
    if drawdown_pct >= cb.no_new_buys_at_pct:
        return "no_new_buys"
    if drawdown_pct >= cb.halve_sizes_at_pct:
        return "halve_sizes"
    return "none"


def effective_conviction(
    draft: DecisionDraft, skeptic: SkepticReview | None, cfg: RiskConfig
) -> int:
    """Skeptic `weakened` caps conviction below the buy gate (docs/04 Layer 6)."""
    if skeptic is not None and skeptic.verdict == "weakened":
        return min(draft.conviction, cfg.conviction_cap_when_skeptic_weakened)
    return draft.conviction


def check_invariants(portfolio: PortfolioState) -> tuple[str, ...]:
    """Impossible states. Any hit must be treated as a bug -> immediate halt (docs/05)."""
    problems: list[str] = []
    if portfolio.nav <= 0:
        problems.append(f"nav_not_positive:{portfolio.nav}")
    if portfolio.cash < -0.01:
        problems.append(f"negative_cash:{portfolio.cash}")
    if portfolio.high_water_mark < portfolio.nav - 0.01:
        problems.append("hwm_below_nav (caller must update HWM before validation)")
    for p in portfolio.positions:
        if p.qty <= 0:
            problems.append(f"non_positive_qty:{p.ticker}")
        if p.market_value < 0:
            problems.append(f"negative_market_value:{p.ticker}")
    if portfolio.nav > 0:
        total = portfolio.cash + sum(p.market_value for p in portfolio.positions)
        if abs(total - portfolio.nav) > max(1.0, portfolio.nav * 0.01):
            problems.append(f"nav_mismatch:components={total:.2f},nav={portfolio.nav:.2f}")
    return tuple(problems)


def drift_trim_candidates(portfolio: PortfolioState, cfg: RiskConfig) -> list[tuple[str, float]]:
    """Positions drifted past the trim threshold -> (ticker, excess weight pct)."""
    out = []
    for p in portfolio.positions:
        weight = p.market_value / portfolio.nav * 100.0 if portfolio.nav > 0 else 0.0
        if weight > cfg.trim_threshold_pct_nav:
            out.append((p.ticker, weight - cfg.max_position_pct_nav))
    return out


def idempotency_key(trade_date: date, ticker: str, side: str) -> str:
    """Deterministic: at most one buy and one sell per ticker per day can ever reach
    the broker; a re-run of the same day reproduces the same key and is rejected
    against open/filled orders."""
    raw = f"{trade_date.isoformat()}|{ticker.upper()}|{side}"
    return "arst-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _round_qty(qty: float) -> float:
    return math.floor(qty * 10_000) / 10_000  # fractional shares, conservative rounding


def validate_decision(
    draft: DecisionDraft,
    skeptic: SkepticReview | None,
    portfolio: PortfolioState,
    market: MarketCtx,
    cfg: RiskConfig,
    *,
    allowed_tickers: frozenset[str],
    subcluster_by_ticker: dict[str, str],
    paused_tickers: frozenset[str] = frozenset(),
    release_after_open_minutes: int = 5,
) -> Verdict:
    """Validate one draft against every hard limit; size the order if it passes.

    Collects ALL violations instead of failing fast — the audit trail and the
    weekly post-mortem want the complete picture.
    """
    reasons: list[str] = []
    notes: list[str] = []
    ticker = draft.ticker
    today = market.now.date()

    if draft.action == "hold":
        return Verdict(ticker=ticker, action="hold", approved=True)

    invariants = check_invariants(portfolio)
    if invariants:
        return Verdict(
            ticker=ticker,
            action=draft.action,
            approved=False,
            reasons=tuple(f"invariant:{p}" for p in invariants),
        )

    tier = breaker_tier(portfolio.nav, portfolio.high_water_mark, cfg)
    is_deploy = draft.action in ("buy", "add")
    position = portfolio.position_for(ticker)

    # --- gates that apply to every non-hold draft -----------------------------
    if tier == "full_halt":
        reasons.append("breaker_full_halt")
    if skeptic is not None and skeptic.verdict == "factual_error":
        reasons.append("skeptic_factual_error")
    if ticker in paused_tickers:
        reasons.append("ticker_paused")

    md = market.by_ticker.get(ticker)
    if md is None:
        reasons.append("missing_market_data")
    else:
        age = market.now - md.price_asof
        if age > MAX_PRICE_AGE:
            reasons.append(f"stale_price_data:{int(age.total_seconds())}s")
        if md.analysis_price > 0:
            drift = abs(md.current_price - md.analysis_price) / md.analysis_price * 100.0
            if drift > cfg.staleness_max_price_drift_pct:
                reasons.append(f"price_drift_exceeded:{drift:.2f}pct")

    # --- action-shape checks ---------------------------------------------------
    if draft.action == "buy" and position is not None:
        reasons.append("buy_already_held_use_add")
    if draft.action == "add" and position is None:
        reasons.append("add_without_position_use_buy")
    if draft.action in ("trim", "exit") and position is None:
        reasons.append("no_position_to_reduce")

    # --- capital-deployment gates (buy/add only; docs/05 asymmetry) ------------
    if is_deploy:
        if ticker not in allowed_tickers:
            reasons.append("ticker_not_in_universe")
        if tier == "no_new_buys":
            reasons.append("breaker_no_new_buys")
        if skeptic is None:
            reasons.append("missing_skeptic_review")
        conviction = effective_conviction(draft, skeptic, cfg)
        floor = cfg.min_conviction_new_buy if draft.action == "buy" else cfg.min_conviction_add
        if conviction < floor:
            reasons.append(f"conviction_below_gate:{conviction}<{floor}")
        if md is not None:
            dte = md.trading_days_to_earnings
            if dte is None:
                # unknown earnings date = the blackout rule can't be honored -> fail closed
                reasons.append("missing_earnings_calendar")
            elif 0 <= dte <= cfg.earnings_blackout_days:
                reasons.append(f"earnings_blackout:{dte}d")
            if md.adv20_usd is None:
                reasons.append("missing_liquidity_data")
        days_since_stop = portfolio.trading_days_since_stop.get(ticker)
        if days_since_stop is not None and days_since_stop < cfg.reentry_cooldown_trading_days:
            reasons.append(f"reentry_cooldown:{days_since_stop}d")
        if ticker in portfolio.tickers_sold_today:
            reasons.append("same_day_round_trip")
        if draft.action == "buy" and len(portfolio.positions) >= cfg.max_positions:
            reasons.append("max_positions_reached")
        if portfolio.orders_today >= cfg.max_orders_per_day:
            reasons.append("max_orders_per_day")
        if portfolio.orders_this_week >= cfg.max_orders_per_week:
            reasons.append("max_orders_per_week")
        subcluster = subcluster_by_ticker.get(ticker)
        if subcluster is None:
            reasons.append("unknown_subcluster")
        elif draft.action == "buy":
            clusters_after = {p.subcluster for p in portfolio.positions} | {subcluster}
            n_after = len(portfolio.positions) + 1
            required = min(n_after, cfg.min_subclusters_when_invested)
            if len(clusters_after) < required:
                reasons.append(
                    f"insufficient_subcluster_diversity:{len(clusters_after)}<{required}"
                )
    else:
        # capital return: same-day round trip is the only absolute order-side ban
        if position is not None and position.last_buy_date == today:
            reasons.append("same_day_round_trip")
        if portfolio.orders_today >= cfg.max_orders_per_day:
            notes.append("frequency_cap_exceeded_exit_allowed")

    if reasons:
        return Verdict(
            ticker=ticker, action=draft.action, approved=False, reasons=tuple(sorted(reasons))
        )

    # --- sizing (all caps simultaneously; the tightest one wins) ---------------
    assert md is not None
    if is_deploy:
        conviction = effective_conviction(draft, skeptic, cfg)
        nav = portfolio.nav
        held_mv = position.market_value if position else 0.0
        subcluster = subcluster_by_ticker[ticker]

        target = nav * cfg.base_position_pct / 100.0 * (conviction / 100.0)
        if tier == "halve_sizes":
            target /= 2.0
            notes.append("size_halved_breaker")

        grade_cap = nav * cfg.max_size_pct_by_risk_grade[draft.risk_grade] / 100.0 - held_mv
        position_cap = nav * cfg.max_position_pct_nav / 100.0 - held_mv
        cluster_cap = nav * cfg.max_subcluster_pct_nav / 100.0 - portfolio.cluster_market_value(
            subcluster
        )
        daily_capital_cap = (
            nav * cfg.max_new_capital_per_day_pct / 100.0 - portfolio.new_capital_deployed_today
        )
        cash_floor_cap = portfolio.cash - nav * cfg.min_cash_pct / 100.0
        assert md.adv20_usd is not None  # rejected above otherwise
        adv_cap = md.adv20_usd * cfg.max_order_pct_adv20 / 100.0

        caps = {
            "risk_grade_cap": grade_cap,
            "max_position_cap": position_cap,
            "subcluster_cap": cluster_cap,
            "daily_new_capital_cap": daily_capital_cap,
            "cash_floor_cap": cash_floor_cap,
            "adv_liquidity_cap": adv_cap,
        }
        notional = min(target, *caps.values())
        for name, value in caps.items():
            if value < target and value == notional:
                notes.append(f"sized_down_by:{name}")

        if notional < MIN_ORDER_NOTIONAL_USD:
            binding = min(caps, key=lambda k: caps[k])
            return Verdict(
                ticker=ticker,
                action=draft.action,
                approved=False,
                reasons=(f"sized_to_zero:{binding}",),
                notes=tuple(notes),
            )

        limit_price = md.current_price * (1.0 + cfg.limit_band_pct / 100.0)
        qty = _round_qty(notional / limit_price)
        if qty <= 0:
            return Verdict(
                ticker=ticker, action=draft.action, approved=False, reasons=("qty_rounds_to_zero",)
            )
        order = OrderPlan(
            ticker=ticker,
            side="buy",
            qty=qty,
            limit_price=round(limit_price, 4),
            notional_usd=round(qty * limit_price, 2),
            stop_loss_price=round(limit_price * (1.0 - cfg.hard_stop_loss_pct / 100.0), 4),
            release_after_open_minutes=release_after_open_minutes,
            idempotency_key=idempotency_key(today, ticker, "buy"),
        )
        return Verdict(
            ticker=ticker, action=draft.action, approved=True, notes=tuple(notes), order=order
        )

    # trim / exit
    assert position is not None
    limit_price = md.current_price * (1.0 - cfg.limit_band_pct / 100.0)
    if draft.action == "exit":
        qty = position.qty
    else:
        target_weight = (
            draft.target_weight_pct
            if draft.target_weight_pct is not None
            else cfg.max_position_pct_nav
        )
        current_weight = position.market_value / portfolio.nav * 100.0
        excess_pct = max(0.0, current_weight - target_weight)
        qty = _round_qty(min(position.qty, portfolio.nav * excess_pct / 100.0 / limit_price))
        if qty <= 0:
            return Verdict(
                ticker=ticker,
                action=draft.action,
                approved=False,
                reasons=("trim_target_not_below_current",),
            )
    order = OrderPlan(
        ticker=ticker,
        side="sell",
        qty=qty,
        limit_price=round(limit_price, 4),
        notional_usd=round(qty * limit_price, 2),
        release_after_open_minutes=release_after_open_minutes,
        idempotency_key=idempotency_key(today, ticker, "sell"),
    )
    return Verdict(
        ticker=ticker, action=draft.action, approved=True, notes=tuple(notes), order=order
    )


def position_weight_pct(position: Position, nav: float) -> float:
    return position.market_value / nav * 100.0 if nav > 0 else 0.0
