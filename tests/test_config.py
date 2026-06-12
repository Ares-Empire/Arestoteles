"""The example config and universe must always parse — they double as the v1 spec."""

from arestoteles.config import load_config, load_universe


def test_example_config_parses_and_matches_spec():
    cfg = load_config()
    assert cfg.mode.trading_mode == "paper"
    assert cfg.mode.approval_mode == "human_v1"
    # spot-check the enforcement table against docs/05
    assert cfg.risk.max_position_pct_nav == 10.0
    assert cfg.risk.min_cash_pct == 15.0
    assert cfg.risk.min_conviction_new_buy == 70
    assert cfg.risk.max_size_pct_by_risk_grade == {"low": 10.0, "med": 7.0, "high": 4.0}
    assert cfg.risk.circuit_breakers.full_halt_at_pct == 20.0
    assert cfg.budgets.max_searches_per_day == 40


def test_universe_parses_with_complete_subclusters():
    uni = load_universe()
    assert len(uni.traded) == 24
    assert "NVDA" in uni.traded_tickers
    assert "SMCI" not in uni.traded_tickers  # deliberately excluded
    assert uni.monitored_tickers == {"MSFT", "GOOGL", "AMZN", "META"}
    # every traded name needs a subcluster for the correlated-cluster cap (docs/05)
    clusters = uni.subcluster_by_ticker
    assert set(clusters) == set(uni.traded_tickers)
    assert clusters["VRT"] == "power-cooling"
    assert clusters["TXN"] == "analog"
    # several distinct clusters must exist or min_subclusters_when_invested is unsatisfiable
    assert len(set(clusters.values())) >= 5


def test_whitelist_flattens():
    uni = load_universe()
    domains = uni.all_whitelist_domains
    assert "sec.gov" in domains
    assert "reuters.com" in domains
    assert len(domains) > 30
