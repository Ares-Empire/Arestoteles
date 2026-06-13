"""Main pre-open run (13:30 Berlin ≈ 1h before NY open, docs/03 §2-3).

Phase 1 scope: free-layer ingestion only. Phase 2 wires the brain behind it
(triage → research → analyst → skeptic → risk engine → approvals), strictly in
shadow (--no-orders) first per docs/08. This entrypoint is the seam where that
pipeline will attach; nothing here may ever place an order directly."""

import argparse

from arestoteles.log import get_logger
from arestoteles.runs.ingest_steps import ingest_free_layer
from arestoteles.runs.runner import RunContext, execute_run

log = get_logger(__name__)


def run(ctx: RunContext) -> dict:
    meta = ingest_free_layer(ctx, since_days=2)
    log.info(
        "ingest complete — decision pipeline is Phase 2 (not built); default action HOLD",
        **meta,
    )
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="run even if the US market is closed today"
    )
    args = parser.parse_args()
    return execute_run("main_run", run, require_market_day=True, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
