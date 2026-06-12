# 02 — Strategy: horizon, universe, benchmarks

## 1. Day trading vs. portfolio manager vs. "completely free"

**Decision: thesis-driven swing/position portfolio manager.** Typical holding period
**2 weeks – 6 months**, decisions made once per day (pre-US-open) plus event-triggered checks.
Not day trading, not unconstrained.

| Criterion | Day trading | **Swing/position (chosen)** | Fully free |
|---|---|---|---|
| Competes on | Speed (vs. HFT, μs–ms) | Synthesis over days–weeks | Undefined |
| LLM latency (10–60 s/analysis) | Disqualifying | Irrelevant | — |
| API cost at required cadence | ~€600–3,000/mo (minute/hourly search, `docs/07`) | €45–80/mo | Unbounded |
| US PDT rule | Needs ≥ $25k equity on margin accounts | Irrelevant (we rarely round-trip same day; risk engine forbids it) | Risky |
| Fees/slippage | Eat the edge (100s of trades) | Negligible (5–15 trades/mo, $0 commission, liquid names) | — |
| Evaluability | Noisy, thousands of trades needed | Theses are inspectable, post-mortemable | Untestable |
| Where LLMs are actually good | Nowhere intraday | Reading filings/news, reasoning, writing falsifiable theses | — |

Profit-wise the comparison isn't close either: at our reaction speed, intraday signals are
exhausted before we act, so day trading would mean paying maximal costs to harvest zero edge.
"Completely free" is rejected because an unconstrained agent cannot be risk-bounded, tested, or
explained — three properties this project treats as non-negotiable (`CLAUDE.md`).

**Cadence:** one full research+decision run before US market open (≈ 13:30 CET), a cheap
post-close snapshot (≈ 22:15 CET), a deep weekly review (Saturday), and **event triggers**
(an 8-K, halt, or > 6 % intraday move in a holding may fire an extra triaged run). Holding
periods stay weeks–months; the daily cadence exists to *react to thesis-breaking news*, not to
churn. Anti-churn rules in `docs/05` (max 3 trades/day, 10/week, re-entry cooldown).

## 2. Industry focus — is one industry right?

**Yes for v1, and narrower than "tech": semiconductors + AI infrastructure.**

Why focusing beats going broad (implementation-wise):
- A small fixed universe lets us keep a **curated source whitelist** and a maintained
  per-company dossier — this is the single biggest hallucination reducer (`docs/04`).
- Prompts, materiality rubrics, and the analyst's "mental model" can be deep instead of generic.
- Cost: searches scale with universe size; ~23 names keeps the budget at €45–80/mo.

Why this subsector specifically (profit-wise, relative to other choices):
- **Linked supply chain = analyzable second-order effects** diffusing over days–weeks — the one
  timescale where we can plausibly act (see `docs/01 §3`). Examples: hyperscaler capex →
  ANET/VRT/AVGO; TSMC monthly revenue (public, ~10th each month) → AMAT/LRCX/ASML; export
  controls → NVDA/AMD China exposure.
- **Best public-information ecosystem of any sector**: SEC filings, mandatory monthly revenue
  disclosures (Taiwan), deep specialist trade press (SemiAnalysis, Tom's Hardware, The Next
  Platform, DCD), hyperscaler earnings as a quarterly demand census.
- **High but tradeable volatility** in very liquid names → opportunities without execution
  problems; everything is shortlist-quality for limit orders.
- User interest and domain familiarity (CS student) — maintenance of dossiers stays fun.

**The core method — big-picture structural reasoning, not standalone company analysis.** The
system's primary job is *not* "is NVDA cheap on its own numbers?" (every screener and quant does
that instantly and better). It is to reason across the value chain: trace where demand and
capital flow (AI-lab / hyperscaler capex → who builds the datacenters → who supplies the chips,
power, cooling, interconnect, memory), identify **structural moats** that make a winner durable
(e.g. a compute leader that has locked up the only advanced-packaging capacity, so a rival's
better chip still can't be *built* fast enough), and watch for **systemic/regime risk** (circular
financing between AI vendors and their customers, the gap between capex/valuations and
end-revenue, dot-com rhymes) that should turn the whole book cautious. For an LLM this is a
*better-suited* edge than financial-metric evaluation — synthesizing many sources into a causal
map is what the model is genuinely good at, and second/third-order nodes diffuse into prices more
slowly than the headline name. **But it only becomes an edge through discipline** (`docs/04`
Layer 5): the same fluency that builds a correct bullish chain builds an equally-coherent wrong
or already-priced one, so every chain must clear three bars — is it already in the price? does it
name a *specific, dated, non-obvious* beneficiary (usually downstream, not the announced node)?
what would falsify it? Without those, big-picture reasoning is *more* dangerous than dull
analysis, because compelling narratives breed overconfidence.

Honest downsides, accepted with mitigations: it's a **crowded, efficiently-priced** trade
(mitigation: we measure ourselves against a sector benchmark, not the S&P); it's **high-beta
and concentrated** — a sector crash hits everything at once (mitigation: min 15 % cash, position
caps, drawdown circuit breakers; and we acknowledge the system cannot diversify away sector
risk by design).

Alternatives considered and rejected for v1: **biotech** (binary FDA events = gambling for an
LLM), **energy** (macro/geopolitics-driven, weaker micro signal), **defense** (few public
signals, long contract cycles), **broad tech** (universe too big to curate; SaaS metrics are
quarterly-only → too few events between earnings). A second sector can become "sleeve B" later
to test generalization (`docs/10`).

## 3. The universe (source of truth: `config/universe.yaml`)

~23 traded names, all US-listed, liquid; roles: GPU/compute (NVDA, AMD, INTC, QCOM, ARM),
networking/custom silicon (AVGO, MRVL, ANET, ALAB, CRDO), memory (MU), analog/power (TXN, ADI,
ON), foundry (TSM), equipment (ASML, AMAT, LRCX, KLAC), EDA (SNPS, CDNS), AI systems/power
(DELL, VRT). **Monitored-only** (never traded, watched for signals): MSFT, GOOGL, AMZN, META,
ORCL — their capex commentary is the demand signal for everything we hold. SMCI is explicitly
excluded (accounting-controversy history → exactly the kind of name where news-driven AI gets
burned). Changes to the universe happen at review by default (urgent additions via the promotion gate, §3a).

### 3a. Dynamic universe within the theme

The edge is *discovering profitable dynamics*, so the system must be able to act on **every part
of a value chain it identifies**, not just a hand-picked list. The universe is therefore
**extensible**: the analyst may propose a new node (a power utility or REIT the buildout implies,
or anything the chain surfaces), and it becomes tradeable once it clears the **promotion gate**
(`universe.yaml` → `node_promotion_gate`): large/mid-cap + liquid only (the microcap/manipulation
defense stays non-negotiable), has a dossier and a whitelisted source, passes a structural thesis
(chain + priced-in check + falsifiers), and sits inside the AI-infrastructure theme. This grants
"trade any node of the chain" *without* dissolving into "trade anything" — the gate is what keeps
cost and hallucination discipline while letting the universe grow with what the system learns.
ORCL is the first promotion (2026-06-13).

## 4. Benchmarks (decided now so we can't move the goalposts later)

1. **Primary: equal-weight buy-and-hold of our own universe**, computed internally — the
   fairest "did the decisions add anything" test.
2. **SOXX** (iShares Semiconductor ETF) — the sector alternative a passive investor would buy.
3. **QQQ** — the "should we even be in this sector" sanity check.

We benchmark *returns, max drawdown, and Sharpe-style volatility-adjusted return* over the same
window, computed from daily snapshots (`pnl_daily` table). EU PRIIPs rules mean we couldn't buy
US ETFs ourselves anyway — fine, we only need them as yardsticks.

## 5. Entry/exit philosophy

- Every position exists because of a **written thesis**: claim, evidence (cited), expected
  horizon, target weight, and **falsifiers** ("what would prove me wrong"). Stored in DB,
  shown in Aresium.
- **Entries**: new thesis with conviction ≥ 70 *and* risk-engine pass *and* (v1) human approval.
- **Exits/trims**: falsifier triggered, hard stop hit (−18 % default), thesis horizon expired
  without confirmation, or better use of capital (max positions cap forces ranking).
- **Review triggers** per position: scheduled review date, earnings date, price move > 10 %
  against us, or any triaged high-materiality event.
- Absence of news is never a buy signal; default action every day is **HOLD**.

## 6. What the system never does (v1 hard scope)

No shorts, no leverage/margin, no options/derivatives, no crypto, no IPOs/SPACs, no
microcaps, no instruments outside the AI-infrastructure value chain or that haven't cleared the
promotion gate (§3a), no same-day round trips, no averaging down below a stopped position, no
trading in the first 5 minutes after the open, no market orders.
