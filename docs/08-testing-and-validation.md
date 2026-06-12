# 08 — Testing & Validation

## 0. The uncomfortable truth first: no classical backtest

A normal quant strategy is validated by backtesting. **We can't, honestly:** Claude's training
data contains the historical outcomes of every stock in our universe up to its cutoff. Feed it
2024 headlines and it "predicts" 2024 because it remembers 2024. Any backtested performance
number for an LLM strategy on pre-cutoff data is optimistic garbage, and post-cutoff history is
only weeks long. Therefore validation is **forward-only** (shadow → paper → tiny live), and the
plan budgets the months that takes.

What we *can* simulate validly:
- **Risk-rule stress tests on price history** (signal-agnostic): replay 2000–2025 sector
  prices with random entries under our sizing/stop/breaker rules → distribution of drawdowns,
  probability of hitting breakers, ruin probability. Validates the *risk envelope*, not alpha.
- **Replay harness for prompts**: every evidence pack + decision is stored; after any prompt
  change, re-run stored packs and diff decisions ("golden tests"). Catches prompt regressions
  without look-ahead bias because packs were captured live.

## 1. Test pyramid (code)

| Layer | What | Bar |
|---|---|---|
| Unit | Risk engine (pure functions): every limit, breaker, sizing path, staleness, idempotency | ~100 % branch coverage; written before wiring |
| Unit | Order builder, position math, P&L/benchmark calc | property-based where cheap (e.g. sizing never exceeds caps) |
| Parsers | RSS/EDGAR/Alpaca parsing against **recorded fixtures** (vcr-style cassettes) | no live calls in CI |
| Schema | Every AI output validated by pydantic; malformed ⇒ stage fails closed | fuzz with broken JSON |
| Integration | Alpaca paper round trip: submit limit → poll → cancel; clock/calendar; reconciliation diff | run nightly, not in CI |
| End-to-end dry run | Full pipeline with `--no-orders` flag on live data | the Phase 2 exit test |

## 2. Shadow mode (≥ 4 weeks) — Phase 2 gate

Full pipeline daily, **no orders of any kind** (not even paper). Measures:
- Reliability: ≥ 95 % of scheduled runs complete; zero unhandled exceptions in final week.
- Cost: daily API spend within budget (`docs/07`); search cap never breached.
- **Hallucination audit:** human-check ~15 decisions/week against their evidence packs —
  every claim must trace to a real, correctly-quoted source. Target: 0 fabricated citations
  (a single fabricated citation that survives the pipeline is a blocking bug).
- Decision sanity: actions are explainable; skeptic pass catches planted errors (test by
  injecting a fake evidence item in a controlled run).

## 3. Paper trading (≥ 12 weeks) — Phase 3 gate, criteria pre-registered **now**

Against the three benchmarks of `docs/02 §4`, measured from `pnl_daily`:

| Criterion (pre-registered 2026-06-13) | Pass bar |
|---|---|
| Uptime / runs completed | ≥ 99 % of trading days |
| Risk-engine violations reaching the broker | 0 |
| Max drawdown | within breaker design (never past −15 % without halt firing) |
| Turnover | ≤ 10 orders/week average (anti-churn working) |
| Process quality (weekly thesis post-mortems) | ≥ 80 % of decisions judged "reasonable given evidence then" |
| Performance vs. equal-weight universe | ≥ benchmark − 3 % (i.e., not clearly destroying value) |
| Conviction calibration | hit-rate(conviction ≥ 80) > hit-rate(70–79) |

**Statistical honesty:** 12 weeks ≈ 60 trading days cannot *prove* alpha (noise dominates;
a t-test on weekly excess returns will be hopelessly underpowered). The paper gate therefore
validates *process, safety, and non-disaster* — not skill. Skill is judged after ≥ 12 months
(live-small), and the scale-up rule in `docs/07 §3` depends on it.

## 4. Go-live gate (Phase 5) and rollback

Go-live requires: all Phase 3 criteria passed, broker funding decision made (`docs/06`),
capital + monthly loss cap fixed in writing, live keys added by the user, v1 approval mode on.
**Rollback triggers (automatic where possible):** −20 % from live high-water mark, 3 critical
bugs, any unexplained broker/DB mismatch, or costs > 2× budget for 2 consecutive months ⇒
flatten to cash (exits only), revoke live keys, return to paper, write the post-mortem.

## 5. Continuous validation (forever)

Weekly Opus review post-mortems closed theses (thesis vs. outcome vs. luck) → `lessons` table
→ injected into future analyst prompts (the system's compounding memory). Monthly
prompt-regression replay over stored packs before any prompt edit ships. Quarterly: re-verify
broker facts, feed URLs, whitelist quality (dead domains, paywall changes), and re-read
`docs/01` to keep expectations honest.
