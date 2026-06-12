# 09 — Aresium Integration

Goal: view Arestoteles' work inside Aresium — every position **with the thesis that justified
it (why it was bought), source references, planned holding period, and review status** — plus
performance and running costs, next to the rest of Patrik's finances.

## Decision: read-only REST API (not a shared database)

Arestoteles (Python/FastAPI) exposes a versioned read-only API; Aresium (TS/Prisma) consumes
it server-side and renders. Rejected alternative — Aresium reading Arestoteles' Postgres
directly — couples two codebases' migrations and gives Aresium's surface area access to the
trading DB. Both run on the same Hetzner host, so transport is the internal Docker network
(or localhost), auth is a static bearer token (`ARESIUM_API_TOKEN` in both `.env`s), nothing
is exposed publicly.

## API contract v1 (`GET /api/v1/...`, JSON, all read-only)

| Endpoint | Returns |
|---|---|
| `/portfolio` | NAV, cash %, since-inception & daily P&L, mode (paper/live), halted flag |
| `/positions` | array: ticker, qty, avg_cost, market_value, weight_pct, unrealized_pnl, opened_at, **thesis_id** |
| `/theses/{id}` (and `/theses?status=active`) | the explainability payload — see example |
| `/decisions?since=…` | decision log: action, conviction, risk_grade, skeptic_verdict, approval, order/fill refs, evidence_ids |
| `/performance?granularity=daily` | NAV series + the three benchmark series (`docs/02 §4`) |
| `/costs?month=…` | API cost €/mo by stage, broker fees — so Aresium can show true net |
| `/health` | last run id/status/time — lets Aresium show "data as of …" |

Thesis payload (the part the user explicitly asked for — why bought, references, how long):

```json
{
  "id": "th_2026_07_anet_01",
  "ticker": "ANET",
  "status": "active",
  "claim": "Hyperscaler FY26 capex guidance raises imply >20% networking spend growth; ANET backlog commentary not yet reflecting it.",
  "conviction": 74,
  "risk_grade": "med",
  "opened_at": "2026-07-02",
  "horizon_days": 90,
  "review_at": "2026-08-01",
  "planned_exit": "Confirm on Q2 earnings call commentary; exit if deferred-revenue growth < 10% YoY (falsifier F2).",
  "falsifiers": [
    {"id": "F1", "text": "Any top-3 hyperscaler cuts FY26 capex guidance"},
    {"id": "F2", "text": "ANET deferred revenue growth < 10% YoY at next report"}
  ],
  "evidence": [
    {"id": "ev_812", "claim": "MSFT raised FY26 capex guidance to …", "url": "https://…",
     "publisher": "Reuters", "published_at": "2026-06-28", "quote": "…exact quote…"}
  ],
  "history": [
    {"at": "2026-07-02", "event": "opened 5.0% @ 312.40", "decision_id": "dec_99"}
  ]
}
```

## Aresium-side plan (its repo, later)

1. `ARESTOTELES_URL` + token in Aresium env; thin typed client; data fetched server-side
   (token never reaches the browser).
2. New **"Investments"** page: portfolio header (NAV, P&L vs. benchmarks sparkline), position
   table, expandable **thesis cards** (claim, conviction badge, falsifiers as checklist,
   citations as links, horizon progress bar "day 23 of 90"), decision log timeline, costs
   widget (API+fees vs. P&L = honest net).
3. Mark the page clearly **paper/live**.
4. Later (v2): Arestoteles → Aresium webhook on each executed decision; Aresium notification
   center entry. Pull-based v1 is enough (Aresium fetches on page load + 5-min cache).

## Versioning & stability

The JSON shapes above are the contract; additive changes only within v1, breaking changes ⇒
`/api/v2`. Arestoteles ships an OpenAPI schema (FastAPI gives it free) so Aresium can generate
its TS types from it — single source of truth, no drift.
