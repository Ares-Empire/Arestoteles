"""Morning sweep (07:30 Berlin, docs/03 §3): overnight Asia/EU news + filings since
close. Phase 1 scope: ingest only; Phase 2 adds Haiku triage + urgency flags.

Runs every weekday regardless of US market holidays — news detection needs no
market and no Alpaca keys (the trading-gated runs are main_run/post_close)."""

import argparse

from arestoteles.runs.ingest_steps import ingest_free_layer
from arestoteles.runs.runner import RunContext, execute_run


def run(ctx: RunContext) -> dict:
    return ingest_free_layer(ctx, since_days=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    return execute_run("morning_sweep", run, require_market_day=False)


if __name__ == "__main__":
    raise SystemExit(main())
