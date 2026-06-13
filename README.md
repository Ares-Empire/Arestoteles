# Arestoteles

An AI-assisted stock portfolio manager for the **semiconductor + AI-infrastructure** sector.
Claude (via API) researches a fixed universe of ~23 liquid US-listed stocks using curated web
sources, writes evidence-backed investment theses, and proposes buy/trim/exit decisions. A
deterministic Python risk engine validates every decision and places orders through a broker
API (Alpaca paper trading first; real money only after a long validation period). Runs on the
existing Hetzner server. Later integrates with **Aresium** (the finance tracker) so positions,
theses, citations, and planned holding periods are viewable there.

> **Honest framing (read `docs/01-feasibility.md`):** beating buy-and-hold is *unlikely*.
> This project is designed so that the downside is bounded, every decision is measurable,
> and the build itself is the guaranteed payoff. Any alpha is a bonus, not the plan.

## Key decisions (already made — see docs for reasoning)

| Question | Decision |
|---|---|
| Day trading vs. portfolio manager? | **Swing/position portfolio manager.** Typical hold 2 weeks – 6 months. Daily decision cadence + event triggers. Day trading rejected (see `docs/02`). |
| Who places orders? | **Python code** places orders. The AI only emits structured decision JSON; a code-level risk engine validates it; v1 requires human approval via Telegram. |
| Industry focus? | Yes — one sector. **Semiconductors + AI infrastructure** (subsector of tech), ~23 traded names + 5 monitored signal tickers. See `config/universe.yaml`. |
| Sandbox platform? | **Alpaca paper trading** (free, API identical to live). |
| Real-money platform? | Decide at Phase 5: **Alpaca international account or Interactive Brokers** (funding-fee check pending). See `docs/06`. |
| Websearch design? | Hybrid: free RSS/EDGAR/price feeds for *detection*, paid Claude `web_search` (domain-whitelisted) only when triggered. Evidence packs with mandatory citations. See `docs/04`. |
| Risk gating? | AI outputs conviction (0–100) + risk grade + falsifiers; code enforces hard limits (max position 10 %, min cash 15 %, stops, circuit breakers, conviction ≥ 70 for new buys). See `docs/05`. |
| Running cost / capital needed? | ~€45–80/month API + ~€0 broker (paper). Breakeven capital at a *plausible* +2–3 % edge: €30–45k. With student capital, treat costs as tuition. Full math in `docs/07`. |

## Document map

| File | Contents |
|---|---|
| `CLAUDE.md` | Instructions + state for future Claude Code sessions. **Read first.** |
| `docs/01-feasibility.md` | Can this work without pro experience? Critical profitability evaluation. Legal/tax notes. |
| `docs/02-strategy.md` | Horizon decision (not day trading), universe choice + alternatives, benchmarks, what the system never does. |
| `docs/03-architecture.md` | Workflow, components, schedule, who-does-what (AI vs. code), DB schema, Hetzner deployment. |
| `docs/04-research-pipeline.md` | The websearch system in detail: layers, sources, evidence packs, anti-hallucination + prompt-injection defenses, search budget. |
| `docs/05-risk-management.md` | Hard rules, conviction gate, skeptic pass, circuit breakers, human-in-the-loop stages. |
| `docs/06-brokers-and-execution.md` | Alpaca vs. IBKR, PDT rule, order policy, fees, market data, German tax notes. |
| `docs/07-costs-and-capital.md` | Full cost model (API/broker/server), cadence cost comparison, breakeven capital table. |
| `docs/08-testing-and-validation.md` | Unit/integration/prompt-regression tests, shadow mode, paper phase with pre-registered criteria, why classical backtests are invalid for LLMs. |
| `docs/09-aresium-integration.md` | Read-only REST API contract so Aresium can display positions, theses, citations, holding plans. |
| `docs/10-roadmap.md` | Phases 0–6 and the future-improvements backlog. |
| `config/universe.yaml` | The tradeable universe, monitored tickers, benchmarks. |
| `config/config.example.toml` | All tunable numbers (risk limits, budgets, schedule, models). Doubles as the v1 spec. |

## Status

- **Phase 0 (planning): complete** — 2026-06-13.
- **Phase 1 (skeleton + free ingestion): code complete** — 2026-06-13. Free-layer ingestion
  (RSS + EDGAR) runs and is smoke-tested locally; risk engine fully unit-tested. Remaining for
  the Phase 1 exit: add keys (Alpaca paper, Telegram, Finnhub) to `.env`, deploy to Hetzner per
  `deploy/README.md`, let the pollers run unattended for a week.
- **Phase 2 (brain in shadow): not started.** Needs `ANTHROPIC_API_KEY`.

## Relationship to Aresium

Aresium (`C:\Users\pab\aresium`) is the self-hosted finance tracker. Arestoteles will expose a
read-only REST API; Aresium gets an "Investments" view showing each position **with the thesis
that justified it, source citations, planned holding period, and review triggers**. Contract in
`docs/09-aresium-integration.md`. No shared database.
