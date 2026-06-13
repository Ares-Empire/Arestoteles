"""Deploy preflight: confirm every configured service is reachable.

Run after filling `.env` (locally or on the Hetzner host) to verify wiring before
enabling the timers — no message is sent and no state is written, so it is safe to
run anytime:

    docker compose run --rm app python -m arestoteles.preflight

Each check is side-effect-free (Telegram uses getMe, not a send) and never raises:
a configured-but-unreachable service is reported `fail`, an unconfigured one `skip`
(e.g. ANTHROPIC_API_KEY stays empty until Phase 2). Exit code is non-zero iff any
check failed, so it doubles as a systemd `ExecStartPre` gate.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import text

from arestoteles.config import Settings, load_config, load_settings, load_universe
from arestoteles.log import get_logger, setup_logging

log = get_logger(__name__)

TELEGRAM_GETME_URL = "https://api.telegram.org/bot{token}/getMe"
NVDA_CIK = 1045810  # a stable, always-present registrant for the EDGAR reachability probe


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "ok" | "skip" | "fail"
    detail: str


def _check_config(_: Settings) -> str:
    universe = load_universe()
    load_config()  # validates config.toml / config.example.toml against the frozen models
    return f"universe: {len(universe.traded)} traded, {len(universe.monitored_only)} monitored"


def _check_database(_: Settings) -> str:
    from arestoteles.db.engine import get_engine

    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
        migrations = conn.execute(text("SELECT count(*) FROM schema_migrations")).scalar_one()
    if not migrations:
        raise RuntimeError("connected but no migrations applied — run arestoteles.db.migrate")
    return f"connected; {migrations} migration(s) applied"


def _check_alpaca(s: Settings) -> str | None:
    if not (s.alpaca_paper_key and s.alpaca_paper_secret):
        return None
    from arestoteles.ingest.alpaca import AlpacaData

    clock = AlpacaData(s.alpaca_paper_key, s.alpaca_paper_secret).clock()
    state = "open" if clock.is_open else "closed"
    return f"paper clock ok; market {state}; next open {clock.next_open:%Y-%m-%d %H:%M %Z}"


def _check_telegram(s: Settings) -> str | None:
    if not (s.telegram_bot_token and s.telegram_chat_id):
        return None
    resp = httpx.get(TELEGRAM_GETME_URL.format(token=s.telegram_bot_token), timeout=10)
    resp.raise_for_status()
    return f"getMe ok: @{resp.json()['result']['username']}"


def _check_finnhub(s: Settings) -> str | None:
    if not s.finnhub_api_key:
        return None
    from arestoteles.ingest.earnings import fetch_earnings_dates

    async def probe() -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            return await fetch_earnings_dates(client, s.finnhub_api_key, ["NVDA"], horizon_days=7)

    asyncio.run(probe())  # a 200 (even with no rows) proves the key authenticates
    return "earnings calendar endpoint ok"


def _check_edgar(s: Settings) -> str | None:
    if not s.edgar_user_agent:
        return None
    from arestoteles.ingest import edgar

    async def probe() -> int:
        async with edgar.make_client(s.edgar_user_agent) as client:
            resp = await client.get(edgar.SUBMISSIONS_URL.format(cik=NVDA_CIK))
            resp.raise_for_status()
            return resp.status_code

    asyncio.run(probe())
    return "data.sec.gov reachable (User-Agent accepted)"


DEFAULT_CHECKS: list[tuple[str, Callable[[Settings], str | None]]] = [
    ("config", _check_config),
    ("database", _check_database),
    ("alpaca", _check_alpaca),
    ("telegram", _check_telegram),
    ("finnhub", _check_finnhub),
    ("edgar", _check_edgar),
]


def run_checks(
    checks: list[tuple[str, Callable[[Settings], str | None]]],
    settings: Settings,
) -> list[CheckResult]:
    """Run each check, mapping its outcome to a CheckResult (None detail => skip,
    any exception => fail). Never raises — the report is the product."""
    results: list[CheckResult] = []
    for name, fn in checks:
        try:
            detail = fn(settings)
        except Exception as exc:  # a failing probe must not abort the report
            results.append(CheckResult(name, "fail", f"{type(exc).__name__}: {exc}"))
        else:
            if detail is None:
                results.append(CheckResult(name, "skip", "not configured"))
            else:
                results.append(CheckResult(name, "ok", detail))
    return results


def overall_ok(results: list[CheckResult]) -> bool:
    return all(r.status != "fail" for r in results)


_ICON = {"ok": "✅", "skip": "⚪", "fail": "❌"}


def main() -> int:
    setup_logging()
    results = run_checks(DEFAULT_CHECKS, load_settings())
    print("Arestoteles preflight")
    for r in results:
        print(f"  {_ICON[r.status]} {r.name:<9} {r.detail}")
    ok = overall_ok(results)
    print("all configured checks passed" if ok else "PREFLIGHT FAILED — see ❌ above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
