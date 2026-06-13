# 09 — Aresium Integration & the Ares Empire

Goal: view Arestoteles' work — every position **with the thesis that justified it (why it was
bought), source references, planned holding period, and review status** — plus performance and
running costs, in a portal that feels like the rest of Patrik's "Ares" tools.

## Decision: separate Arestoteles site + a compact overview card in Aresium

Arestoteles gets its **own front-end at its own subdomain** (an "epic" stock-broker-style
portal, see `docs/11-web-frontend.md`), **not** a page rendered inside Aresium. Aresium keeps a
small **Investments overview card** (NAV, today's P&L, top positions sparkline) that deep-links
into the Arestoteles site. This supersedes the earlier "render the Investments view inside
Aresium" plan.

Why separate site over fully embedded:
- **Different stack, different surface.** Aresium is TS/Node; Arestoteles is Python. Cramming a
  second rich domain (positions, theses, candle charts, AI reasoning) into Aresium's codebase and
  breadcrumb navigation fights both. Arestoteles serves its own UI from its own FastAPI.
- **The intro wants the viewport.** The bust-drop + crater hero (`docs/11`) is a full-page
  experience — natural for a standalone site, awkward as an Aresium sub-route.
- **Independent deploy/iteration**, and the API was coming anyway (this pulls the Phase-4 API
  forward as the data layer for the site).
- **It reads as an "empire."** A family of sibling apps under one visual language, each at its
  own domain (`aresium.de`, `arestoteles.de`, …), cross-linked from a consistent place — more
  empire than one monolith.

### The Ares Empire model (shared design language, separate apps)
All Ares tools share one identity so the constellation feels deliberate, not assorted:
- **A central Ares manager** (adopted direction; specifics TBD) — a small hub site that launches
  every Ares app and acts as the **identity/SSO provider** (see SSO below). It is the empire's home
  and the clean answer to "everything in one place" without one bloated monolith.
- **Design system** — the exact Aresium tokens (`web/public/index.html` `<style>`): black wall,
  Space Grotesk + JetBrains Mono, glass side-cards, **charts painted straight on the wall** (no
  card), the big wordmark band at the bottom, tabular-nums everywhere. Arestoteles reuses these
  verbatim (`docs/11`).
- **A dropping intro** per app (Aresium's `aresium-intro.js` is the *animation technique*, not an
  existing load intro — Aresium only animates the wordmark on its red-mode toggle today).
  Arestoteles' load intro: a marble bust drops onto the wall + crater, then the ARESTOTELES wordmark.
- **An Ares switcher / link to the manager** — reachable from each app's header. Do **not** hijack
  Aresium's top-left brand button — single-click there stays the red "Ares mode" easter egg.

## Decision: read-only REST API (not a shared database)

Unchanged. Arestoteles (Python/FastAPI) exposes a versioned read-only API; both the Aresium
overview card **and** the standalone Arestoteles site consume it. Rejected alternative — anything
reading Arestoteles' Postgres directly — couples two codebases' migrations and widens the trading
DB's surface. Same Hetzner host, so transport is the internal Docker network / gateway; auth is a
static bearer token (`ARESIUM_API_TOKEN` in both `.env`s, **server-to-server only** — never in a
browser). The browser-facing site authenticates users separately (see SSO below).

## API contract v1 (`GET /api/v1/...`, JSON, all read-only)

| Endpoint | Returns |
|---|---|
| `/portfolio` | NAV, cash %, since-inception & daily P&L, mode (paper/live), halted flag |
| `/positions` | array: ticker, qty, avg_cost, market_value, weight_pct, unrealized_pnl, opened_at, **thesis_id** |
| `/positions/{ticker}/bars?range=1D\|1W\|1M\|1Y\|ALL\|since` | **OHLC/price series for the per-stock graph** (Alpaca bars; `since` = since opened_at, with the avg-cost guide level) |
| `/theses/{id}` (and `/theses?status=active`) | the explainability payload — see example |
| `/decisions?since=…` | decision log: action, conviction, risk_grade, skeptic_verdict, approval, order/fill refs, evidence_ids |
| `/performance?granularity=daily` | NAV series + the three benchmark series (`docs/02 §4`) |
| `/costs?month=…` | API cost €/mo by stage, broker fees — so the portal can show true net |
| `/health` | last run id/status/time — lets the portal show "data as of …" |

The `/positions/{ticker}/bars` endpoint is **new vs. the original contract** — it's what feeds the
1D/1W/1M/1Y/ALL/Since-purchase range tabs on the per-stock detail screen.

Thesis payload (why bought, references, how long) — **Phase 2+ data**; until the brain trades,
positions render with a "thesis pending — fills when the brain goes live" state:

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

## Deployment seam (same shared host as Aresium — `aresium-deploy` patterns apply)

A new `api` service in the Arestoteles compose (already foreshadowed in `docker-compose.yml`)
serves **both** the JSON API and the static front-end. To reach it from the public edge it follows
the exact Aresium pattern, with the same gotchas:
- **Domain** `arestoteles.de` (its own registrable domain). Needs A/AAAA DNS records → the server,
  an additive `arestoteles.conf` server block in `insureai_nginx`'s `conf.d`, and a cert via the
  shared certbot webroot (same mechanism as `aresium.conf`).
- The `api` container binds the docker-bridge **gateway** (`172.18.0.1:<port>`) like Aresium, or
  joins `insureai_network` — either way needs the `ufw allow from 172.18.0.0/16` rule and inherits
  the **hardcoded-gateway fragility** noted in the Aresium deploy memory.
- nginx reload via `docker kill --signal=HUP insureai_nginx` (validate config first).

### Cross-app auth / SSO (the empire login)
Aresium authenticates with an HMAC-signed session cookie (`AUTH_SESSION_SECRET`, HttpOnly +
Secure + SameSite=Lax; `src/web/auth.ts`). Because `aresium.de` and `arestoteles.de` are **separate
registrable domains**, a shared parent-domain cookie can't span them — so SSO needs a real
mechanism:
- **Target — the central Ares manager as the SSO provider.** Sign in once at the hub; it mints a
  short-lived signed token that each app exchanges (on a redirect) for its own session cookie. This
  is the clean cross-domain answer and the reason the hub is worth building.
- **Now — Arestoteles' own custom login.** Port Aresium's pattern (`src/web/login-page.ts` +
  `auth.ts`: scrypt password + HMAC cookie) to the FastAPI service, reskinned with the bust. No
  design pass needed. Independent login until the hub exists; then fold it behind hub-SSO.

## Sequencing & honest caveat

The portal needs (a) the read API and (b) **actual positions to show**. In Phase 1 the system is
HOLD-only paper (NAV $100k, **zero positions**), and theses don't exist until Phase 2. So:
- **Build the shell now** — intro, layout, portfolio header, empty-state ("no open positions yet"),
  benchmark line — against the live paper `/portfolio` + `/performance`.
- It **populates as the brain trades (Phase 2)**: position rows, per-stock graphs, thesis cards.

This is consistent with the project's honest framing — build the cathedral first; it fills with
meaning when the brain goes live.

## Versioning & stability

The JSON shapes above are the contract; additive changes only within v1, breaking changes ⇒
`/api/v2`. Arestoteles ships an OpenAPI schema (FastAPI gives it free) so Aresium's overview card
can generate its TS types from it — single source of truth, no drift.

## Aresium-side plan (its repo, later — see Aresium `docs/INVESTMENTS-INTEGRATION.md`)

1. `ARESTOTELES_URL` + token in Aresium env; thin typed client; data fetched **server-side**
   (token never reaches the browser).
2. A compact **Investments overview card** on the Aresium overview: NAV, daily & since-inception
   P&L, a benchmark sparkline, top-N positions — with a button into the Arestoteles site. Marked
   clearly **paper/live**.
3. The **Ares switcher** (launcher) for cross-app navigation as the empire grows.
4. Later (v2): Arestoteles → Aresium webhook on each executed decision; Aresium notification entry.
   Pull-based v1 is enough (fetch on load + 5-min cache).
