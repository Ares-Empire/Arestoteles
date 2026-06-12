# 10 — Roadmap & Future Improvements

## Phases

| Phase | Scope | Exit criteria | Effort guess |
|---|---|---|---|
| **0 — Plan** | These docs, universe, config spec | done 2026-06-13 | — |
| **1 — Skeleton + free layer** | Repo scaffold (uv, compose, postgres), Alpaca paper hookup (read-only), RSS+EDGAR pollers, DB schema, cost accounting, Telegram bot (`/status`, `/halt`), risk-engine unit tests | pollers run 1 week unattended on Hetzner; risk engine green | 1–2 weekends |
| **2 — Brain in shadow** | Triage→research→evidence→analyst→skeptic chain, dossiers for all names, replay harness, `--no-orders` end-to-end | `docs/08 §2` shadow criteria over ≥ 4 weeks | 2–3 weekends + 4 wk wall-clock |
| **3 — Paper trading** | Execution module vs. paper API, approvals via Telegram, stops, reconciliation, daily digest | `docs/08 §3` criteria over ≥ 12 weeks | 1–2 weekends + 12 wk wall-clock |
| **4 — Aresium integration** (parallel to 3) | FastAPI per `docs/09`, Aresium Investments page | theses visible in Aresium with citations | 1–2 weekends |
| **5 — Live, small (optional)** | Broker decision (`docs/06`), funding, live keys, v1 approval mode, €1–3k | go-live gate `docs/08 §4` | 1 weekend + ongoing |
| **6 — Earned autonomy** | v2 then v3 approval modes (`docs/05`) | gates in `docs/05` | ongoing |

Calendar reality: live money is plausible **Q1 2027 at the earliest** — the wall-clock weeks
are the validation, not the coding. Shortcutting them deletes the only honest evidence we get.

## Improvement backlog (post-base, roughly prioritized)

1. **Earnings-call transcript ingestion** — diff guidance language QoQ per name; the highest
   info-density source we don't yet parse (transcripts via free sources; verify availability).
2. **Lessons memory v2** — embed post-mortems; retrieve "similar past setups" into the analyst
   prompt ("last 3 times we bought on capex headlines, the move was already priced in").
3. **Conviction calibration loop** — auto-tune the gate from realized hit rates.
4. **Regime filter** — scale gross exposure on VIX/rates/sector-breadth signals (code-side,
   not AI), e.g. halve sizes when SOXX < 200-day MA. Cheap and historically defensible.
5. **Sleeve B: second sector** (e.g. defense) with its own whitelist — tests whether the
   architecture generalizes or we just overfit to semis.
6. **Valuation sanity module** — EDGAR XBRL-based bands (EV/S vs. 5-yr range) as a code-side
   input the analyst must acknowledge when buying at extremes.
7. **IBKR adapter** behind the `Broker` interface (if Phase 5 picks IBKR, this moves up).
8. **Multi-agent debate** — bull/bear/judge instead of single skeptic; measure vs. cost.
9. **Auto-throttle budget governor** — degrade cadence dynamically as monthly spend approaches
   cap (currently: hard stop).
10. **Weekly research memo** — Opus writes a human-readable sector letter from the week's
    evidence; nice artifact, zero trading risk.
11. **Options hedging** — explicitly *far future*, only ever for hedging (puts on holdings),
    only after ≥ 1 year live, separate risk doc required.
12. **Aresium v2** — webhooks, mobile notifications, what-if view ("system vs. your manual
    portfolio").

## Standing maintenance

Monthly: universe & dossier review, whitelist pruning, prompt-regression replay, cost report.
Quarterly: broker/fee/feed re-verification, `docs/01` re-read (expectation hygiene), model
upgrades (newer Claude models: re-run replay harness before switching — model swaps invalidate
prompt caches and may shift decision behavior; treat like a prompt change).
