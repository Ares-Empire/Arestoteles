"""Preflight orchestration: outcome -> CheckResult mapping and overall verdict.
The real network probes are exercised by the dockerized run, not here."""

from arestoteles.config import Settings
from arestoteles.preflight import CheckResult, overall_ok, run_checks


def _settings() -> Settings:
    return Settings(_env_file=None)  # ignore any local .env; values are irrelevant here


def test_outcomes_map_to_ok_skip_fail():
    def ok(_):
        return "all good"

    def skip(_):
        return None

    def boom(_):
        raise RuntimeError("unreachable")

    results = run_checks([("a", ok), ("b", skip), ("c", boom)], _settings())

    assert [(r.name, r.status) for r in results] == [("a", "ok"), ("b", "skip"), ("c", "fail")]
    assert results[0].detail == "all good"
    assert results[1].detail == "not configured"
    assert "RuntimeError: unreachable" in results[2].detail


def test_overall_ok_ignores_skips_but_not_fails():
    assert overall_ok([CheckResult("x", "ok", ""), CheckResult("y", "skip", "")])
    assert not overall_ok([CheckResult("x", "ok", ""), CheckResult("y", "fail", "")])
