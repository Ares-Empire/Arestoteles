# 03 — Architecture & Workflow

## 1. Division of labor — who does what

**Core principle: the AI proposes, code disposes.** Claude never touches the broker.

| Responsibility | Owner |
|---|---|
| Detect events (RSS/EDGAR/prices) | Python (free, deterministic) |
| Score materiality, decide what's worth a paid search | Claude **Haiku 4.5** (triage) |
| Research triggered topics via web search, build evidence packs | Claude **Sonnet 4.6** + `web_search_20260209` (whitelisted) |
| Write/maintain theses, propose decisions (structured JSON) | Claude **Sonnet 4.6** (structured outputs) |
| Attack each proposal (skeptic pass) | Claude **Sonnet 4.6**, separate adversarial prompt |
| Weekly deep review, post-mortems | Claude **Opus 4.8** via Batch API (−50 %) |
| Validate decisions against hard limits | **Python risk engine** (pure functions, unit-tested) |
| Size positions, build orders, place/cancel them | **Python execution module** → Alpaca API |
| Approve trades (v1) | **Human**, via Telegram inline buttons |
| Ledger, P&L, cost accounting, Aresium API | Python + Postgres |

## 2. Pipeline (the daily pre-open run)

```
        FREE LAYER                       PAID AI LAYER                      CODE LAYER
┌────────────────────────┐   ┌──────────────────────────────────┐   ┌─────────────────────────┐
│ S1 INGEST              │   │ S2 TRIAGE (Haiku)                │   │ S5 RISK ENGINE          │
│ RSS feeds              │──▶│ score events 0–10 materiality,   │   │ hard limits, sizing,    │
│ EDGAR filings          │   │ map to tickers, pick ≤N topics   │   │ staleness, idempotency  │
│ prices/cal (Alpaca)    │   │ worth paid research              │   │  pass │ reject          │
│ portfolio state        │   └────────────┬─────────────────────┘   └───┬───┴─────────────────┘
└────────────────────────┘                ▼                             ▼
                              ┌──────────────────────────────────┐   ┌─────────────────────────┐
                              │ S3 RESEARCH (Sonnet + websearch) │   │ S6 APPROVAL (Telegram)  │
                              │ whitelisted domains, max_uses,   │   │ human taps ✅/❌ (v1)    │
                              │ output = EVIDENCE PACK w/ cites  │   └───┬─────────────────────┘
                              └────────────┬─────────────────────┘       ▼
                              ┌────────────▼─────────────────────┐   ┌─────────────────────────┐
                              │ S4 ANALYST → DecisionDrafts      │   │ S7 EXECUTE (Alpaca)     │
                              │ update theses; skeptic pass      │   │ limit orders, log fills │
                              │ must cite evidence IDs           │   │ → DB → Aresium API      │
                              └──────────────────────────────────┘   └─────────────────────────┘
```

Every stage writes to Postgres; a run is a `runs` row with status + cost. Any failure ⇒ run
ends with **no decisions** (fail closed) + Telegram alert.

## 3. Run types & schedule (server TZ Europe/Berlin, market TZ America/New_York)

| Run | When | Model use | Purpose |
|---|---|---|---|
| Morning sweep | 07:30 Mo–Fr | Haiku only | Overnight Asia/EU news, TSMC monthly rev, filings since close; flag urgencies |
| **Main run** | 13:30 Mo–Fr (≈ 1 h before NY open; code checks Alpaca `/clock` for DST/holidays) | full pipeline | Decisions + approvals; orders queued as limit orders, released ≥ 5 min after open |
| Post-close snapshot | 22:15 Mo–Fr | none | P&L snapshot, stop checks vs. closes, Telegram digest |
| Event trigger | on 8-K / halt / >6 % move in a holding | triage → maybe research | Mid-day thesis-break detection (rate-limited: ≤ 2/day) |
| Weekly deep review | Sa 10:00 | Opus 4.8 (Batch) | Thesis maintenance, post-mortems, lessons, cost report |
| Monthly review | 1st Sa | Opus 4.8 (Batch) | Universe/dossier refresh, prompt-regression suite, parameter review |

Scheduling = **systemd timers** on the Hetzner host running `docker compose run --rm app
python -m arestoteles.runs.<name>` (oneshot, like FlatSniper's pattern). The job exits silently
if Alpaca says the market is closed (holidays).

## 4. Tech stack

- **Python 3.12 + uv**; `pydantic` (all AI I/O schemas), `httpx`, `feedparser`, `anthropic`,
  `alpaca-py`, `python-telegram-bot`, `FastAPI` (Aresium-facing read-only API), `pytest`,
  `SQLAlchemy`/psycopg3, `structlog`.
- **Postgres 16** in the same Docker compose. **Docker compose** services: `app` (oneshot
  runs), `api` (FastAPI, always on), `bot` (Telegram, always on), `db`.
- Claude API usage: prompt caching on the stable system prompt + universe dossiers (Sonnet 4.6
  min cacheable prefix 2048 tokens — easily met); structured outputs for DecisionDrafts;
  Batch API for weekly/monthly jobs; every response's `usage` is written to `api_costs`.

## 5. Data model (schema sketch — finalize in Phase 1)

| Table | Key contents |
|---|---|
| `runs` | id, type, started/ended, status, tokens, cost_eur, error |
| `events` | raw detected items (feed/EDGAR), ticker(s), triage score, dedup hash |
| `evidence` | id, run_id, ticker, claim, quote, url, publisher, published_at — the citation store |
| `theses` | ticker, status(draft/active/exited), claim, horizon, target_weight, conviction, risk_grade, falsifiers[], review_at, created/updated |
| `decisions` | run_id, ticker, action(buy/add/trim/exit/hold), conviction, sizing, evidence_ids[], skeptic_verdict, risk_engine_verdict, approval_status |
| `orders` / `fills` | broker ids, idempotency_key, limits, status, fill px/qty |
| `positions_daily` / `pnl_daily` | snapshots; NAV, per-position MV, benchmark series |
| `api_costs` | per call: model, tokens in/out/cached, searches, eur |
| `lessons` | post-mortem outputs the weekly prompt re-reads (the system's memory) |

This DB is the single source of truth for the Aresium API (`docs/09`): a position is always
joinable to its thesis, its decisions, and the evidence (with URLs) behind them.

## 6. Deployment & ops (Hetzner)

- Repo deployed via git pull (later: GitHub Actions → ssh). `.env` (chmod 600) holds
  `ANTHROPIC_API_KEY`, `ALPACA_PAPER_KEY/SECRET`, `TELEGRAM_*`, `ARESIUM_API_TOKEN`,
  `DATABASE_URL`. Live keys absent until Phase 5.
- Observability: structured logs to journald; Telegram for alerts/digests; optional
  healthchecks.io ping per timer; weekly cost report from `api_costs`.
- Failure policy: retries with backoff inside a stage (3×); a failed stage fails the run
  (no trades) and alerts. Stale-data guards: refuse to decide if prices older than 15 min or
  portfolio state can't be fetched. Duplicate-order protection via idempotency keys checked
  against the broker's open orders on every start.
- Kill switch: Telegram `/halt` sets a DB flag every run checks first; `/resume` clears it.
