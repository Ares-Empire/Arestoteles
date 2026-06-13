"""Pure parts of the runs framework: benchmark math + digest formatting."""

import pytest

from arestoteles.runs.snapshots import digest_text, equal_weight_level


def test_equal_weight_level_base_is_100():
    base = {"A": 100.0, "B": 200.0}
    assert equal_weight_level(base, base) == pytest.approx(100.0)


def test_equal_weight_level_mixed_moves():
    base = {"A": 100.0, "B": 200.0}
    closes = {"A": 110.0, "B": 220.0}
    assert equal_weight_level(base, closes) == pytest.approx(110.0)
    closes = {"A": 120.0, "B": 180.0}  # +20% and -10% -> +5%
    assert equal_weight_level(base, closes) == pytest.approx(105.0)


def test_equal_weight_level_fails_honest_on_thin_coverage():
    base = {"A": 100.0, "B": 200.0, "C": 50.0, "D": 10.0}
    assert equal_weight_level(base, {"A": 100.0}) is None  # 25% coverage
    assert equal_weight_level(base, {"A": 100.0, "B": 200.0, "C": 50.0}) is not None  # 75%
    assert equal_weight_level({}, {"A": 1.0}) is None


def test_digest_text():
    txt = digest_text(
        nav=100_000.0,
        cash=15_000.0,
        n_positions=3,
        events_today=42,
        month_cost_eur=12.34,
        runs_today=[("morning_sweep", "ok"), ("main_run", "failed")],
        mode="paper",
    )
    assert "$100,000.00" in txt
    assert "15.0%" in txt
    assert "42" in txt and "12.34" in txt
    assert "main_run:failed" in txt and "(paper)" in txt
