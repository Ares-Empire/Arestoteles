"""Pure snapshot/benchmark math for the post-close run (testable without broker)."""

from arestoteles.log import get_logger

log = get_logger(__name__)

MIN_BENCH_COVERAGE = 0.7  # below this share of universe closes, the level is a lie


def equal_weight_level(base_closes: dict[str, float], closes: dict[str, float]) -> float | None:
    """Equal-weight buy-and-hold index of our own universe, base = 100 on the first
    snapshot day (docs/02 §4 primary benchmark). Uses the tickers present in both
    base and today; None when coverage is too thin to be honest."""
    common = [t for t in base_closes if t in closes and base_closes[t] > 0]
    if not base_closes or len(common) / len(base_closes) < MIN_BENCH_COVERAGE:
        return None
    return sum(closes[t] / base_closes[t] for t in common) / len(common) * 100.0


def digest_text(
    *,
    nav: float,
    cash: float,
    n_positions: int,
    events_today: int,
    month_cost_eur: float,
    runs_today: list[tuple[str, str]],
    mode: str,
) -> str:
    from arestoteles.notify.telegram import escape

    cash_pct = cash / nav * 100.0 if nav > 0 else 0.0
    lines = [
        f"📊 <b>Arestoteles daily digest</b> ({escape(mode)})",
        f"NAV ${nav:,.2f} | cash {cash_pct:.1f}% | positions {n_positions}",
        f"events today: {events_today} | API cost this month: €{month_cost_eur:.2f}",
    ]
    if runs_today:
        runs_str = ", ".join(f"{escape(t)}:{escape(s)}" for t, s in runs_today)
        lines.append(f"runs: {runs_str}")
    return "\n".join(lines)
