# 07 — Costs & Capital

*API prices verified 2026-06 (Anthropic): Haiku 4.5 $1/$5, Sonnet 4.6 $3/$15, Opus 4.8 $5/$25
per M tokens; **web search $10 per 1,000 searches** + retrieved content billed as input tokens;
Batch API −50 %; prompt-cache reads ≈ 0.1×. EUR figures assume ≈ 1.08 USD/EUR.*

## 1. Why cadence is the whole cost story

| Cadence (search+analyze) | Searches/mo | Rough API cost/mo | Edge gained at our horizon |
|---|---|---|---|
| Every minute (market hours) | ~8,200+ | **€550–2,800** (tokens dominate) | none — HFT already arbitraged it |
| Hourly | ~1,400 | €230–320 | none |
| **Daily + event triggers (chosen)** | ~300–500 | **€45–80** | full — news diffuses into our holdings over days |
| Weekly only ("cheap mode") | ~80 | €10–20 | most of it, with slower thesis-break reaction |

This table is the quantitative half of the day-trading rejection in `docs/02`.

## 2. Standard-mode monthly budget (the planning number)

| Item | Assumption | $/day | €/month |
|---|---|---|---|
| Detection layer (RSS/EDGAR/Alpaca) | free APIs | 0 | 0 |
| Triage (Haiku): ~45k in / 3k out | weekdays | 0.06 | ~1.2 |
| Research (Sonnet): 10–25 searches + ~150k in / 8k out | weekdays | 0.85 | ~17 |
| Analyst+skeptic (Sonnet): ~100k in (heavily cached) / 10k out | weekdays | 0.55 | ~11 |
| Morning sweep + event triggers | amortized | 0.25 | ~5 |
| Weekly deep review (Opus 4.8, Batch −50 %): ~300k in / 25k out | 4–5×/mo | — | ~8 |
| Monthly review + prompt-regression replays | 1×/mo | — | ~4 |
| Retries / overruns margin (+25 %) | — | — | ~12 |
| **API total** | | **≈ $2.3/trading day** | **≈ €58 (range 45–80)** |
| Broker (paper) | Alpaca | | 0 |
| Broker (live, later) | Alpaca $0 + reg. cents; IBKR ~$0.35–1 × ~10 orders | | 0–10 |
| Server | existing Hetzner, marginal | | 0 |
| Data | free tiers | | 0 |

**Annual: ≈ €700 standard mode (range €550–1,000); cheap mode ≈ €150–250.**
Controls that keep it there (all enforced in config): daily search cap 40 (hard stop →
free-feeds-only mode), monthly EUR cap, Haiku-first triage, prompt caching, Batch for
everything not time-critical, per-run token budgets, RSS-prefilter so no-news days cost ≈ €0.5.
The `api_costs` table makes drift visible in the weekly digest.

## 3. How much capital would the system need to "pay for itself"?

Define edge = annual return above the benchmark (equal-weight universe / SOXX). Costs ≈
€900/yr standard (worst-case planning number), €250/yr cheap mode.

| Sustained edge | Capital where edge covers €900/yr | …covers €250/yr (cheap) |
|---|---|---|
| +1 % | €90,000 | €25,000 |
| +2 % | €45,000 | €12,500 |
| +3 % | €30,000 | €8,300 |
| +5 % | €18,000 | €5,000 |
| +8 % (not a planning case) | €11,250 | €3,100 |

Context for what's plausible: most professionals sustain **0 %** or negative edge after costs.
If this system earns +2–3 % vs. its sector benchmark over a full year, that is a *great*
result — and still needs €30–45k to break even on standard-mode costs.

**Direct answer to "how much money so that it covers all costs and still makes extra profit":
realistically €20–50k at an optimistic-but-conceivable edge — i.e., not at current student
scale.** The framing that actually works now:

1. **Phases 1–4 (paper):** cost = API only (€45–80/mo). Decide consciously that this is hobby/
   education spend, like a course subscription.
2. **Phase 5 (live, optional):** start with **€1,000–3,000** and a pre-committed view that
   expected net outcome ≈ −€500…+€200/yr — tuition with upside. Run cheap mode if the daily
   cadence isn't earning its bill.
3. **Scale-up rule (pre-registered):** only add capital after ≥ 12 months live with positive
   alpha vs. the equal-weight benchmark *and* max drawdown inside limits. At that point the
   breakeven table above becomes the sizing guide.

## 4. Hidden / irregular costs to remember

One-off: funding wire fees (€10–50 if Alpaca-via-wire; ~€0 via IBKR SEPA), FX conversion on
deposit/withdrawal. Live-mode frictions: bid-ask spread ≈ 1–4 bp on our names, slippage on
limit orders mostly ≈ 0, regulatory sell fees (SEC/TAF, cents). Taxes on gains (26.375 % —
only a "cost" in good years). Time: ~1–2 h/week of human review during paper phase; the
weekly digest is designed to keep it that low.
