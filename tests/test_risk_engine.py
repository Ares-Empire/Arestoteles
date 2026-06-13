"""Risk-engine unit tests (docs/08 §1: every limit, breaker, sizing path, staleness,
idempotency — written before the engine is wired to anything).

The RiskConfig used here is the real one from config.example.toml: the example
file IS the v1 spec, so the tests pin the spec values too."""

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from arestoteles.config import load_config
from arestoteles.risk.engine import (
    breaker_tier,
    check_invariants,
    drift_trim_candidates,
    effective_conviction,
    idempotency_key,
    validate_decision,
)
from arestoteles.risk.models import MarketCtx, PortfolioState, Position, TickerMarket
from arestoteles.schemas import DecisionDraft, Falsifier, SkepticReview

CFG = load_config().risk
NOW = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)  # a Monday
TODAY = NOW.date()

CLUSTERS = {
    "NVDA": "compute-silicon",
    "AVGO": "networking",
    "ANET": "networking",
    "CRDO": "networking",
    "MU": "memory",
    "TSM": "foundry",
    "AMAT": "equipment",
    "LRCX": "equipment",
    "SNPS": "eda",
    "DELL": "dc-builder",
    "VRT": "power-cooling",
    "TXN": "analog",
}
UNIVERSE = frozenset(CLUSTERS)

OK = SkepticReview(verdict="ok")
WEAKENED = SkepticReview(verdict="weakened", notes="bear case is strong")
FACTUAL_ERROR = SkepticReview(verdict="factual_error", notes="misquoted the filing")


def draft(**kw) -> DecisionDraft:
    base = dict(
        ticker="NVDA",
        action="buy",
        conviction=80,
        risk_grade="med",
        horizon_days=60,
        chain="MSFT capex raise -> dc buildout -> accelerator demand -> NVDA",
        priced_in_check="Name moved 2% on the news; forward multiple within 1y range.",
        falsifiers=(Falsifier(id="F1", text="Any top-3 hyperscaler cuts FY capex guidance"),),
        evidence_ids=(1, 2),
        rationale="Capex flows downstream.",
    )
    base.update(kw)
    return DecisionDraft(**base)


def market(ticker="NVDA", price=100.0, analysis=100.0, asof=None, adv=50_000_000.0, dte=None):
    return MarketCtx(
        now=NOW,
        by_ticker={
            ticker: TickerMarket(
                current_price=price,
                analysis_price=analysis,
                price_asof=asof or NOW,
                adv20_usd=adv,
                trading_days_to_earnings=dte,
            )
        },
    )


def position(ticker="NVDA", mv=5_000.0, qty=50.0, cluster=None, last_buy=None):
    return Position(
        ticker=ticker,
        qty=qty,
        avg_cost=mv / qty,
        market_value=mv,
        opened_at=TODAY - timedelta(days=30),
        last_buy_date=last_buy,
        subcluster=cluster or CLUSTERS.get(ticker, "compute-silicon"),
    )


def portfolio(nav=100_000.0, cash=None, hwm=None, positions=(), **kw):
    positions = tuple(positions)
    if cash is None:
        cash = nav - sum(p.market_value for p in positions)
    return PortfolioState(
        nav=nav,
        cash=cash,
        high_water_mark=hwm if hwm is not None else nav,
        positions=positions,
        **kw,
    )


def validate(d, skeptic=OK, pf=None, mkt=None, **kw):
    return validate_decision(
        d,
        skeptic,
        pf if pf is not None else portfolio(),
        mkt if mkt is not None else market(d.ticker),
        CFG,
        allowed_tickers=UNIVERSE,
        subcluster_by_ticker=CLUSTERS,
        **kw,
    )


# --- holds & action shape -----------------------------------------------------


def test_hold_always_approved_without_order():
    v = validate(draft(action="hold"), skeptic=None)
    assert v.approved and v.order is None


def test_buy_when_already_held_is_rejected():
    v = validate(draft(), pf=portfolio(positions=[position("NVDA")]))
    assert not v.approved and "buy_already_held_use_add" in v.reasons


def test_add_without_position_is_rejected():
    v = validate(draft(action="add", conviction=70))
    assert not v.approved and "add_without_position_use_buy" in v.reasons


def test_exit_without_position_is_rejected():
    v = validate(draft(action="exit"), skeptic=None)
    assert not v.approved and "no_position_to_reduce" in v.reasons


# --- the certainty gate ---------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "conviction", "ok_expected"),
    [("buy", 69, False), ("buy", 70, True), ("add", 64, False), ("add", 65, True)],
)
def test_conviction_gate(action, conviction, ok_expected):
    pf = portfolio(positions=[position("NVDA")]) if action == "add" else portfolio()
    v = validate(draft(action=action, conviction=conviction), pf=pf)
    assert v.approved is ok_expected
    if not ok_expected:
        assert any(r.startswith("conviction_below_gate") for r in v.reasons)


def test_weakened_skeptic_blocks_new_buys_even_at_high_conviction():
    v = validate(draft(conviction=95), skeptic=WEAKENED)
    assert not v.approved
    assert "conviction_below_gate:65<70" in v.reasons


def test_weakened_skeptic_still_allows_adds_at_the_cap():
    v = validate(
        draft(action="add", conviction=95),
        skeptic=WEAKENED,
        pf=portfolio(positions=[position("NVDA", mv=2_000.0)]),
    )
    assert v.approved  # capped to exactly min_conviction_add
    assert v.order is not None and v.order.notional_usd < 100_000 * 0.05 * 0.70


def test_factual_error_auto_rejects_everything():
    assert "skeptic_factual_error" in validate(draft(), skeptic=FACTUAL_ERROR).reasons
    v = validate(
        draft(action="exit"), skeptic=FACTUAL_ERROR, pf=portfolio(positions=[position("NVDA")])
    )
    assert "skeptic_factual_error" in v.reasons


def test_buy_without_skeptic_review_is_rejected():
    v = validate(draft(), skeptic=None)
    assert "missing_skeptic_review" in v.reasons


def test_exit_needs_no_skeptic_and_no_conviction():
    v = validate(
        draft(action="exit", conviction=0), skeptic=None, pf=portfolio(positions=[position("NVDA")])
    )
    assert v.approved and v.order is not None and v.order.side == "sell"


def test_effective_conviction_only_caps_on_weakened():
    assert effective_conviction(draft(conviction=90), OK, CFG) == 90
    assert effective_conviction(draft(conviction=90), WEAKENED, CFG) == 65
    assert effective_conviction(draft(conviction=50), WEAKENED, CFG) == 50


# --- universe / pause / market-data gates --------------------------------------


def test_ticker_outside_universe_cannot_be_bought():
    v = validate(draft(ticker="SMCI"), mkt=market("SMCI"))
    assert "ticker_not_in_universe" in v.reasons


def test_paused_ticker_is_rejected():
    v = validate(draft(), paused_tickers=frozenset({"NVDA"}))
    assert "ticker_paused" in v.reasons


def test_missing_market_data_fails_closed():
    v = validate(draft(), mkt=MarketCtx(now=NOW, by_ticker={}))
    assert "missing_market_data" in v.reasons


def test_stale_price_fails_closed():
    v = validate(draft(), mkt=market(asof=NOW - timedelta(minutes=16)))
    assert any(r.startswith("stale_price_data") for r in v.reasons)
    assert validate(draft(), mkt=market(asof=NOW - timedelta(minutes=14))).approved


def test_price_drift_guard():
    assert any(
        r.startswith("price_drift_exceeded")
        for r in validate(draft(), mkt=market(price=103.1, analysis=100.0)).reasons
    )
    assert validate(draft(), mkt=market(price=102.9, analysis=100.0)).approved


def test_missing_liquidity_data_blocks_buys_not_exits():
    assert "missing_liquidity_data" in validate(draft(), mkt=market(adv=None)).reasons
    v = validate(
        draft(action="exit"),
        skeptic=None,
        pf=portfolio(positions=[position("NVDA")]),
        mkt=market(adv=None),
    )
    assert v.approved


# --- timing gates ----------------------------------------------------------------


@pytest.mark.parametrize(("dte", "ok_expected"), [(0, False), (2, False), (3, True), (None, True)])
def test_earnings_blackout(dte, ok_expected):
    v = validate(draft(), mkt=market(dte=dte))
    assert v.approved is ok_expected


@pytest.mark.parametrize(("days", "ok_expected"), [(0, False), (9, False), (10, True)])
def test_reentry_cooldown_after_stop_out(days, ok_expected):
    v = validate(draft(), pf=portfolio(trading_days_since_stop={"NVDA": days}))
    assert v.approved is ok_expected


def test_same_day_round_trip_blocked_both_directions():
    v = validate(draft(), pf=portfolio(tickers_sold_today=frozenset({"NVDA"})))
    assert "same_day_round_trip" in v.reasons
    v = validate(
        draft(action="exit"),
        skeptic=None,
        pf=portfolio(positions=[position("NVDA", last_buy=TODAY)]),
    )
    assert "same_day_round_trip" in v.reasons


# --- frequency & count limits ------------------------------------------------------


def test_max_positions_blocks_new_buys_but_not_adds():
    others = sorted(UNIVERSE - {"NVDA"})
    assert len(others) >= CFG.max_positions  # fixture sanity
    pf_full = portfolio(positions=[position(t, mv=2_000.0) for t in others[: CFG.max_positions]])
    v = validate(draft(), pf=pf_full)
    assert "max_positions_reached" in v.reasons
    pf_holding_nvda = portfolio(
        positions=[position(t, mv=2_000.0) for t in others[: CFG.max_positions - 1]]
        + [position("NVDA", mv=2_000.0)]
    )
    v = validate(draft(action="add", conviction=70), pf=pf_holding_nvda)
    assert "max_positions_reached" not in v.reasons


def test_order_frequency_caps_block_deployment_not_exits():
    v = validate(draft(), pf=portfolio(orders_today=CFG.max_orders_per_day))
    assert "max_orders_per_day" in v.reasons
    v = validate(draft(), pf=portfolio(orders_this_week=CFG.max_orders_per_week))
    assert "max_orders_per_week" in v.reasons
    v = validate(
        draft(action="exit"),
        skeptic=None,
        pf=portfolio(positions=[position("NVDA")], orders_today=CFG.max_orders_per_day),
    )
    assert v.approved and "frequency_cap_exceeded_exit_allowed" in v.notes


# --- circuit breakers ---------------------------------------------------------------


def test_breaker_tiers():
    assert breaker_tier(100.0, 100.0, CFG) == "none"
    assert breaker_tier(90.1, 100.0, CFG) == "none"
    assert breaker_tier(90.0, 100.0, CFG) == "halve_sizes"
    assert breaker_tier(85.0, 100.0, CFG) == "no_new_buys"
    assert breaker_tier(80.0, 100.0, CFG) == "full_halt"


def test_breaker_halves_sizes():
    full = validate(draft(conviction=80)).order
    halved = validate(draft(conviction=80), pf=portfolio(nav=90_000.0, hwm=100_000.0)).order
    assert full is not None and halved is not None
    # nav also shrank 10%, so halved size = full * 0.9 / 2
    assert halved.notional_usd == pytest.approx(full.notional_usd * 0.9 / 2, rel=0.01)


def test_breaker_no_new_buys_allows_exits():
    pf = portfolio(nav=85_000.0, hwm=100_000.0, positions=[position("NVDA")])
    assert "breaker_no_new_buys" in validate(draft(action="add", conviction=80), pf=pf).reasons
    assert validate(draft(action="exit"), skeptic=None, pf=pf).approved


def test_breaker_full_halt_rejects_even_exits():
    pf = portfolio(nav=80_000.0, hwm=100_000.0, positions=[position("NVDA")])
    assert "breaker_full_halt" in validate(draft(action="exit"), skeptic=None, pf=pf).reasons


# --- invariants -----------------------------------------------------------------------


def test_invariant_violations_reject_and_name_the_bug():
    bad = PortfolioState(
        nav=100_000.0,
        cash=-50.0,
        high_water_mark=100_000.0,
        positions=(position("NVDA", mv=100_050.0),),
    )
    v = validate(draft(), pf=bad)
    assert not v.approved and any(r.startswith("invariant:negative_cash") for r in v.reasons)
    assert check_invariants(portfolio()) == ()
    assert any("hwm_below_nav" in p for p in check_invariants(portfolio(nav=100.0, hwm=90.0)))
    assert any(
        "nav_mismatch" in p
        for p in check_invariants(portfolio(nav=100_000.0, cash=10_000.0, positions=[position()]))
    )


# --- sizing ----------------------------------------------------------------------------


def test_base_sizing_formula():
    v = validate(draft(conviction=80, risk_grade="med"))
    assert v.order is not None
    # 5% base * 0.80 conviction * 100k NAV = 4_000
    assert v.order.notional_usd == pytest.approx(4_000.0, rel=0.001)
    assert v.order.limit_price == pytest.approx(100.0 * 1.003)
    assert v.order.stop_loss_price == pytest.approx(100.3 * 0.82)
    assert v.order.release_after_open_minutes == 5
    assert v.order.qty * v.order.limit_price <= 4_000.0 + 0.01


@pytest.mark.parametrize(("grade", "max_pct"), [("low", 10.0), ("med", 7.0), ("high", 4.0)])
def test_risk_grade_caps_bind(grade, max_pct):
    v = validate(draft(conviction=100, risk_grade=grade), pf=portfolio(nav=1_000_000.0))
    assert v.order is not None
    base = 1_000_000.0 * 0.05  # conviction 100 -> full base size 5%
    expected = min(base, 1_000_000.0 * max_pct / 100.0)
    assert v.order.notional_usd <= expected + 0.01
    if grade == "high":
        assert "sized_down_by:risk_grade_cap" in v.notes


def test_add_headroom_respects_max_position_cap():
    pf = portfolio(positions=[position("NVDA", mv=9_500.0)])  # 9.5% of 100k held
    v = validate(draft(action="add", conviction=100, risk_grade="low"), pf=pf)
    assert v.order is not None
    assert v.order.notional_usd <= 500.0 + 0.01  # only 0.5% headroom to the 10% cap


def test_subcluster_cap_binds_across_chain_links():
    # networking cluster drifted to 34% of NAV across two names; book spans 3 clusters
    pf = portfolio(
        nav=100_000.0,
        positions=[
            position("AVGO", mv=17_000.0),
            position("ANET", mv=17_000.0),
            position("MU", mv=4_000.0),
            position("VRT", mv=4_000.0),
        ],
    )
    # a NEW networking name only gets the 1% cluster headroom, not its 5% base size
    v = validate(draft(ticker="CRDO", conviction=100, risk_grade="low"), pf=pf, mkt=market("CRDO"))
    assert v.order is not None
    assert v.order.notional_usd <= 1_000.0 + 0.01
    assert "sized_down_by:subcluster_cap" in v.notes
    # a different chain link is unconstrained by networking's cap
    v = validate(draft(ticker="TSM", conviction=100, risk_grade="low"), pf=pf, mkt=market("TSM"))
    assert v.order is not None and v.order.notional_usd > 4_000.0


def test_daily_new_capital_cap():
    pf = portfolio(new_capital_deployed_today=19_500.0)
    v = validate(draft(conviction=100, risk_grade="low"), pf=pf)
    assert v.order is not None and v.order.notional_usd <= 500.0 + 0.01


def test_cash_floor_blocks_when_no_headroom():
    pf = portfolio(cash=15_000.0, positions=[position("VRT", mv=85_000.0)])
    v = validate(draft(), pf=pf)
    assert not v.approved and "sized_to_zero:cash_floor_cap" in v.reasons


def test_adv_liquidity_cap():
    v = validate(draft(conviction=100, risk_grade="low"), mkt=market(adv=100_000.0))
    assert v.order is not None and v.order.notional_usd <= 1_000.0 + 0.01
    assert "sized_down_by:adv_liquidity_cap" in v.notes


def test_sizing_never_exceeds_any_cap_property():
    grades = ["low", "med", "high"]
    convictions = [70, 85, 100]
    navs = [10_000.0, 100_000.0]
    helds = [0.0, 3_000.0]
    deployed = [0.0, 15_000.0]
    for grade, conviction, nav, held_mv, dep in itertools.product(
        grades, convictions, navs, helds, deployed
    ):
        positions = [position("NVDA", mv=held_mv)] if held_mv else []
        pf = portfolio(nav=nav, positions=positions, new_capital_deployed_today=dep)
        action = "add" if held_mv else "buy"
        v = validate(draft(action=action, conviction=conviction, risk_grade=grade), pf=pf)
        if v.order is None:
            continue
        n = v.order.notional_usd
        assert n <= nav * CFG.max_size_pct_by_risk_grade[grade] / 100.0 - held_mv + 0.01
        assert n <= nav * CFG.max_position_pct_nav / 100.0 - held_mv + 0.01
        assert n <= nav * CFG.max_new_capital_per_day_pct / 100.0 - dep + 0.01
        assert pf.cash - n >= nav * CFG.min_cash_pct / 100.0 - 0.01
        assert n <= 50_000_000.0 * CFG.max_order_pct_adv20 / 100.0 + 0.01


# --- subcluster diversification floor ----------------------------------------------


def test_first_and_second_position_must_differ_in_cluster():
    assert validate(draft()).approved  # empty book: anything goes
    pf = portfolio(positions=[position("AVGO")])  # networking held
    v = validate(draft(ticker="ANET"), mkt=market("ANET"), pf=pf)
    assert "insufficient_subcluster_diversity:1<2" in v.reasons
    assert validate(draft(ticker="MU"), mkt=market("MU"), pf=pf).approved


def test_third_position_must_open_third_cluster():
    pf = portfolio(positions=[position("AVGO"), position("MU")])
    v = validate(draft(ticker="ANET"), mkt=market("ANET"), pf=pf)  # networking again
    assert "insufficient_subcluster_diversity:2<3" in v.reasons
    assert validate(draft(ticker="VRT"), mkt=market("VRT"), pf=pf).approved


def test_fourth_position_may_double_up_a_cluster():
    pf = portfolio(positions=[position("AVGO"), position("MU"), position("VRT")])
    assert validate(draft(ticker="ANET"), mkt=market("ANET"), pf=pf).approved


# --- trims & exits ---------------------------------------------------------------------


def test_exit_sells_everything_with_marketable_limit():
    pf = portfolio(positions=[position("NVDA", mv=13_000.0, qty=130.0)])
    v = validate(draft(action="exit"), skeptic=None, pf=pf)
    assert v.order is not None
    assert v.order.qty == pytest.approx(130.0)
    assert v.order.side == "sell"
    assert v.order.limit_price == pytest.approx(100.0 * 0.997)


def test_trim_defaults_to_max_position_weight():
    pf = portfolio(positions=[position("NVDA", mv=13_000.0, qty=130.0)])
    v = validate(draft(action="trim"), skeptic=None, pf=pf)
    assert v.order is not None
    # 13% -> 10%: sell ~3% of NAV
    assert v.order.qty * v.order.limit_price == pytest.approx(3_000.0, rel=0.01)


def test_trim_to_explicit_target_weight():
    pf = portfolio(positions=[position("NVDA", mv=8_000.0, qty=80.0)])
    v = validate(draft(action="trim", target_weight_pct=5.0), skeptic=None, pf=pf)
    assert v.order is not None
    assert v.order.qty * v.order.limit_price == pytest.approx(3_000.0, rel=0.01)


def test_trim_above_current_weight_is_rejected():
    pf = portfolio(positions=[position("NVDA", mv=5_000.0, qty=50.0)])
    v = validate(draft(action="trim", target_weight_pct=8.0), skeptic=None, pf=pf)
    assert not v.approved and "trim_target_not_below_current" in v.reasons


def test_trim_never_oversells():
    pf = portfolio(positions=[position("NVDA", mv=2_000.0, qty=20.0)])
    v = validate(draft(action="trim", target_weight_pct=0.0), skeptic=None, pf=pf)
    assert v.order is not None and v.order.qty <= 20.0


def test_drift_trim_candidates():
    pf = portfolio(positions=[position("NVDA", mv=13_500.0), position("MU", mv=9_000.0)])
    cands = drift_trim_candidates(pf, CFG)
    assert cands == [("NVDA", pytest.approx(3.5))]


# --- idempotency -----------------------------------------------------------------------


def test_idempotency_key_deterministic_and_side_distinct():
    a = idempotency_key(TODAY, "NVDA", "buy")
    assert a == idempotency_key(TODAY, "nvda".upper(), "buy")
    assert a != idempotency_key(TODAY, "NVDA", "sell")
    assert a != idempotency_key(TODAY + timedelta(days=1), "NVDA", "buy")
    assert a.startswith("arst-")


def test_multiple_violations_all_reported():
    pf = portfolio(orders_today=CFG.max_orders_per_day, tickers_sold_today=frozenset({"NVDA"}))
    v = validate(draft(conviction=60), skeptic=WEAKENED, pf=pf, mkt=market(dte=1))
    for expected in (
        "max_orders_per_day",
        "same_day_round_trip",
        "earnings_blackout:1d",
        "conviction_below_gate:60<70",
    ):
        assert expected in v.reasons
