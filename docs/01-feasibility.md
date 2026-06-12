# 01 — Feasibility & Profitability (critical evaluation)

*Written 2026-06-13. This is the document to re-read whenever the project feels like a money
printer. It is not one.*

## 1. Can this be built without professional trading experience?

**Yes — building it is the easy part.** Every component is standard engineering:
scheduled jobs, REST APIs (Alpaca/EDGAR), an LLM pipeline with structured outputs, a Postgres
ledger, a Telegram bot. Nothing requires a trading license (trading your own money in Germany
is private Vermögensverwaltung; a BaFin license only becomes a topic if you ever manage other
people's money — don't).

What professional experience would actually buy is *strategy judgment*: knowing which signals
are already priced in, how to size positions, when a backtest is lying. We substitute for that
with **constraints instead of judgment**: long-only, liquid mega/large caps, hard position
limits, code-enforced risk rules, human approval, and a long paper phase. The honest corollary:
professional experience would not make this reliably profitable either — the obstacle is the
market, not the missing diploma.

## 2. Why profitability is unlikely (state of the evidence)

- **Markets price public news in seconds-to-minutes.** Our pipeline reacts in hours-to-a-day.
  Anything a headline says about NVDA is in the price long before our daily run sees it. We
  therefore must not claim a *speed* edge — only a *synthesis-and-discipline* edge (see §3).
- **The competition is brutal.** Sell-side analysts, quant funds, and (since ~2023) every
  institutional desk running LLM news-synthesis pipelines cover exactly our universe —
  semis/AI is the single most-watched corner of the market. High info availability cuts both
  ways: great for building the system, bad for finding mispricings.
- **Base rates:** the large majority of professional active managers underperform their
  benchmark over 5+ years after costs. Retail algorithmic traders do worse. An LLM does not
  obviously change this; published experiments with LLM trading agents show inconsistent,
  regime-dependent results, and most "GPT beats the market" backtests are contaminated (next
  point).
- **LLM backtests are invalid.** Claude's training data includes what happened to these stocks
  through ~2025/26. Any simulated run over historical dates lets the model "predict" outcomes
  it has memorized. Consequence: **we cannot cheaply validate the strategy on history; only
  forward testing (shadow → paper → tiny live) counts.** This makes the iteration loop slow —
  months per experiment — which is itself a major feasibility cost. Details in `docs/08`.
- **Costs are certain, alpha is not.** ~€650–1,100/year running costs (see `docs/07`) are
  guaranteed; the edge needed to cover them at student-scale capital is not plausible (§4).

## 3. What edge are we even claiming?

Be precise, because "AI reads news and trades" is not an edge. The defensible claims, in
decreasing order of credibility:

1. **Slow-diffusion supply-chain synthesis.** In semis, cause→effect chains play out over days
   to weeks across *linked* companies: hyperscaler capex guidance → networking/power vendors;
   TSMC's monthly revenue (published ~10th of each month) → equipment makers; export-control
   news → specific exposure per name. A system that systematically maps first-order news onto
   second-order holdings within 24 h is doing something a casual investor doesn't and a fast
   quant doesn't bother to (too fundamental, too slow). This is our best shot, and it's still
   shared with thousands of professionals.
2. **Discipline.** No FOMO, no revenge trading, mechanical stops, forced thesis falsifiers,
   automatic post-mortems. For a *human hobbyist's own portfolio*, this alone often beats their
   discretionary self — note this compares us to "Patrik picking stocks", not to the index.
3. **Breadth + stamina.** Reading every 8-K, transcript summary, and trade-press item for 23
   companies daily is a full-time job a student won't do manually; the system will.

What is explicitly **not** an edge: reaction speed, private information, quant factor timing,
options flow, anything intraday.

## 4. The capital math (summary — full table in `docs/07`)

Running cost ≈ **€900/year** (mid estimate, standard mode). Capital needed for the *edge alone*
to cover costs:

| Sustained edge vs. benchmark | Capital where edge = costs |
|---|---|
| +1 %/yr | €90,000 |
| +2 %/yr | €45,000 |
| +3 %/yr | €30,000 |
| +5 %/yr (already heroic) | €18,000 |
| 0 % (most likely) | never — pure cost |

With €1–5k of student capital, even a heroic +5 % edge earns €50–250/yr against €900 of costs.
**Conclusion: at our scale this cannot pay for itself. It can still be worth doing** — as a
serious engineering project, as a forcing function to learn markets properly, and as
infrastructure that becomes rational if capital ever grows 10×. Budget it like a hobby
(≈ a gym membership), run "cheap mode" (€10–20/month, `docs/07`) when idle, and judge the
system on *process quality and measured alpha*, not on absolute euros.

## 5. Failure modes beyond "no alpha"

| Risk | Mitigation |
|---|---|
| Hallucinated facts → bad trades | Evidence packs with mandatory citations, numeric data only from APIs, skeptic pass, 2-source rule (`docs/04`) |
| Prompt injection / manipulative content (pump pieces, fake PRs) | Domain whitelist, content treated as data, no microcaps, wire-service cross-check (`docs/04`) |
| Software bug places wrong order | Risk engine invariants + idempotency keys + human approval in v1 + paper-first (`docs/05`, `docs/08`) |
| Slow bleed: many small losses + fees | Circuit breakers on drawdown, monthly cost/PnL report, pre-registered kill criteria (`docs/05`, `docs/08`) |
| Overfitting prompts to the paper period | Pre-registered evaluation criteria written *before* the paper phase starts (`docs/08`) |
| Motivation decay (the real killer of side projects) | v1 scope is deliberately small; Telegram digest keeps it visible daily |

## 6. Legal & tax notes (Germany — not advice, verify before Phase 5)

- Trading own money: no license needed. Automated trading via API on your own account is
  permitted by both Alpaca and IBKR terms.
- Taxes: capital gains for private investors ≈ 26.375 % (Abgeltungsteuer + Soli) above the
  €1,000 Sparer-Pauschbetrag. A **foreign broker withholds nothing** → gains must be declared
  in the Steuererklärung (Anlage KAP); keep the trade ledger export-ready (Arestoteles' DB
  already stores every fill). US dividend withholding drops to 15 % with the W-8BEN the broker
  files for you; it's creditable against German tax.
- German quirk: losses from stock *sales* offset only stock-sale gains (separate loss pot).
- High trade frequency as a private person is generally still private asset management, but if
  activity ever looks "commercial" (gewerblich), get advice. Our ~5–15 trades/month is far
  from that.

## 7. Verdict

**Build it — with the stated expectations.** The plan is feasible end-to-end without trading
experience; the architecture caps the damage any single component (including the AI) can do;
costs are bounded and known; and the validation path (shadow → paper → tiny live) means real
money is only ever exposed after months of measured evidence. The probability-weighted
financial outcome is a small net cost. The learning and infrastructure outcome is certain.
Proceed to `docs/02-strategy.md`.
