# 05 — Risk Management

Two-tier design, answering "should the AI evaluate risk?" with **yes — but its evaluation is
advisory; enforcement is code.**

- **Tier 1 (AI, advisory):** every DecisionDraft carries `conviction 0–100`, `risk_grade
  low|med|high` (defined below), and `falsifiers[]`. The skeptic pass stress-tests these.
- **Tier 2 (code, binding):** the risk engine — pure Python functions over config values —
  validates every draft. No prompt can override it. Values live in
  `config/config.example.toml` `[risk]`; changing them requires user approval (CLAUDE.md).

`risk_grade` rubric given to the model: **low** = thesis rests on filed/announced facts with
near-term confirmation events; **med** = depends on one forward assumption (demand follows
capex); **high** = depends on chained assumptions, contested narratives, or
binary upcoming events. Grade caps size (below).

## The certainty gate (answering "only allow a certain certainty")

New buys require **conviction ≥ 70** *and* skeptic verdict `ok`. Skeptic `weakened` caps
conviction at 65 ⇒ blocks entries. `factual_error` ⇒ auto-reject + log for post-mortem.
Adds to existing positions: ≥ 65. Exits/trims need **no** conviction floor — leaving is always
allowed (asymmetry is deliberate: the gate guards capital deployment, never capital return).
Calibration check: the monthly review compares stated conviction vs. realized hit rate
(does 80 mean more than 70? if not, retune the prompt, not the threshold).

## Hard limits (v1 values — the enforcement table)

| Rule | v1 value |
|---|---|
| Universe | only `universe.yaml` traded list |
| Direction / leverage | long-only; cash account semantics; no margin |
| Max single position (at cost) | 10 % of NAV (trim signal at 13 % after drift) |
| Max number of positions | 10 |
| Min cash buffer | 15 % of NAV |
| Base position size | 5 % NAV, scaled: ×(conviction/100), capped by risk grade — low ≤ 10 %, med ≤ 7 %, high ≤ 4 % |
| Max new capital deployed per day | 20 % of NAV |
| Trade frequency | ≤ 3 orders/day, ≤ 10/week (anti-churn) |
| Same-day round trip | forbidden (also keeps us clear of PDT) |
| Hard stop-loss | −18 % from entry (GTC stop order at broker + post-close check) |
| Thesis review trigger | −10 % from entry, or any falsifier event |
| Re-entry cooldown after stop-out | 10 trading days, only with a *new* thesis |
| Earnings blackout | no new entries/adds within 2 trading days before that name's earnings |
| Staleness guard | reject if current price deviates > 3 % from analysis-time price |
| Liquidity sanity | order ≤ 1 % of 20-day average daily volume (trivially true at our size) |
| Order type | limit only (marketable limit, ±0.3 % band); never market; never first 5 min after open |
| Idempotency | every order carries a unique key; duplicates rejected against open orders |

## Portfolio circuit breakers (from high-water mark of NAV)

| Trigger | Action |
|---|---|
| −10 % | New-position sizes halved; every order requires approval regardless of phase; Telegram alert |
| −15 % | **No new buys.** Only exits allowed. Weekly review must produce a written assessment before re-enabling |
| −20 % or 3 critical bugs | Full halt; if live, back to paper. Pre-registered, non-negotiable |
| Any risk-engine invariant violated at runtime (impossible state) | Immediate halt + alert — treat as a bug, not a market event |

The **regime dial** (`docs/04`) is the *discretionary, gradual* de-risking layer that sits **above**
these mechanical breakers: it trims the whole chain as theme-risk rises (circular financing,
revenue-gap, ROI deterioration). The breakers are the hard floor if the dial is wrong or too slow —
neither replaces the other.

## Concentration & correlated-cluster risk (the honest cost of a "golden chain")

Walking a profitable value chain node-to-node is the edge — but it builds the **most correlated
portfolio possible**: every node runs on the *same* AI-capex demand signal, so 10 positions on one
chain is closer to **one bet expressed ten ways** than to a diversified book. They gap together on
the same news. This is the central risk of the strategy, and it interacts badly with our one known
weakness — the system can read *rising* risk but can't *time the break* (`docs/04`). Concentration
removes the margin for that timing error: a −30% single-session gap (these names do that) outruns
any weekly regime read and any daily run; the stops fire, and on a maximally-correlated book
*everything* stops out together, at the bottom, on the same day. The more "golden" the chain, the
more your whole outcome rests on the one joint we agreed is least reliable.

So discovery walks the chain freely; **sizing does not.** Two guards, both *independent of the
regime dimmer* — they protect you precisely when it's late:
- **Sub-cluster cap** (`[risk] max_subcluster_pct_nav`, ~35%): no single correlated link
  (compute-silicon / networking / memory / power-cooling / equipment / EDA / foundry / dc-builder)
  dominates. Adjacent nodes on one path are near-identical trades; spread across links that break at
  *different* times (equipment cycles ≠ GPU demand ≠ power buildout).
- **Min distinct sub-clusters when invested** (`min_subclusters_when_invested`, 3): the book must
  span several links, not pile onto one golden path.

This is the honest answer to "risky if not diversified, but if detection is good enough it works":
good detection lets you run *more* concentrated than a blind book — not *un*diversified. Detection
reduces the timing error; it never eliminates it (gap-downs outrun any detector), and concentration
is what removes your cushion for the residual. The cap is the part that survives a late detector.

## Human-in-the-loop stages

- **v1 (paper + first live):** every non-HOLD order needs Telegram approval (✅/❌ buttons,
  expire at market close). Exits triggered by hard stops execute immediately, then notify —
  safety must not wait for a tap.
- **v2:** exits/trims auto-execute; new buys still approved.
- **v3 (earned, not scheduled):** full auto within limits, daily digest. Gate: ≥ 8 weeks of v2
  with zero risk-engine overrides and zero approval-reversals the human was right about.
- Always available: `/halt` (kill switch), `/pause NVDA` (per-ticker freeze), `/limits`
  (show current headroom).

## Why these numbers

10 %/position + 10 positions + 15 % cash ⇒ a single −50 % blowup costs ≤ 5 % of NAV; a sector
−30 % day costs ≈ −25 % NAV — which is why the −15 % breaker sits *inside* that path. The −18 %
stop is wide enough to survive normal semi volatility (these names swing ±8 % on earnings)
while bounding single-name damage to ≈ −1.6 % NAV at base size. Fractional shares (Alpaca)
make 5 %-of-small-NAV sizing exact. All values are config, expected to be tuned after the
paper phase — *with the change logged in `lessons` and never mid-drawdown.*
