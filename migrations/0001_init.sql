-- Arestoteles initial schema (docs/03 §5).
-- Single source of truth for the Aresium read-only API (docs/09): a position is
-- always joinable to its thesis, its decisions, and the evidence behind them.

CREATE TABLE runs (
    id            bigserial PRIMARY KEY,
    run_type      text        NOT NULL,  -- morning_sweep|main_run|post_close|weekly_review|monthly_review|event_trigger|adhoc
    started_at    timestamptz NOT NULL DEFAULT now(),
    ended_at      timestamptz,
    status        text        NOT NULL DEFAULT 'running',  -- running|ok|failed|skipped_market_closed|skipped_halted
    error         text,
    input_tokens  bigint      NOT NULL DEFAULT 0,
    output_tokens bigint      NOT NULL DEFAULT 0,
    cost_eur      numeric(12, 4) NOT NULL DEFAULT 0,
    meta          jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX runs_started_idx ON runs (started_at DESC);
CREATE INDEX runs_type_idx ON runs (run_type, started_at DESC);

-- Raw detected items from the free layer (RSS / EDGAR / price moves).
CREATE TABLE events (
    id            bigserial PRIMARY KEY,
    source        text        NOT NULL,  -- rss|edgar|edgar_fts|price_move
    feed          text,                  -- feed key, e.g. "rss:techcrunch" or "edgar:NVDA"
    url           text,
    headline      text,
    published_at  timestamptz,
    tickers       text[]      NOT NULL DEFAULT '{}',
    dedup_hash    text        NOT NULL UNIQUE,
    raw           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    run_id        bigint REFERENCES runs (id),
    triage_score  smallint,              -- 0-10, filled by Phase 2 triage
    triaged_at    timestamptz
);
CREATE INDEX events_published_idx ON events (published_at DESC);
CREATE INDEX events_first_seen_idx ON events (first_seen_at DESC);
CREATE INDEX events_tickers_idx ON events USING gin (tickers);
CREATE INDEX events_untriaged_idx ON events (id) WHERE triaged_at IS NULL;

-- The citation store (docs/04 Layer 4): every downstream judgment references these ids.
CREATE TABLE evidence (
    id           bigserial PRIMARY KEY,
    run_id       bigint REFERENCES runs (id),
    ticker       text        NOT NULL,
    claim        text        NOT NULL,
    exact_quote  text        NOT NULL,
    url          text        NOT NULL,
    publisher    text        NOT NULL,
    published_at timestamptz,
    relevance    text,
    quote_verified boolean,             -- string-match spot check result, null = not checkable
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_ticker_idx ON evidence (ticker, created_at DESC);

CREATE TABLE theses (
    id                bigserial PRIMARY KEY,
    public_id         text UNIQUE,       -- e.g. th_2026_07_anet_01 (Aresium API id)
    ticker            text        NOT NULL,
    status            text        NOT NULL DEFAULT 'draft',  -- draft|active|exited
    claim             text        NOT NULL,
    horizon_days      integer,
    target_weight_pct numeric(6, 2),
    conviction        smallint,
    risk_grade        text,              -- low|med|high
    falsifiers        jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [{id, text}]
    review_at         date,
    opened_at         date,
    closed_at         date,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX theses_ticker_idx ON theses (ticker, status);

CREATE TABLE decisions (
    id                   bigserial PRIMARY KEY,
    run_id               bigint REFERENCES runs (id),
    thesis_id            bigint REFERENCES theses (id),
    ticker               text        NOT NULL,
    action               text        NOT NULL,  -- buy|add|trim|exit|hold
    conviction           smallint,
    risk_grade           text,
    horizon_days         integer,
    target_weight_pct    numeric(6, 2),
    chain                text,                  -- explicit causal path (docs/04 Layer 5)
    priced_in_check      text,
    rationale            text,
    falsifiers           jsonb       NOT NULL DEFAULT '[]'::jsonb,
    evidence_ids         bigint[]    NOT NULL DEFAULT '{}',
    skeptic_verdict      text,                  -- ok|weakened|factual_error
    skeptic_notes        text,
    risk_engine_verdict  text,                  -- pass|reject
    risk_engine_reasons  text[]      NOT NULL DEFAULT '{}',
    approval_status      text,                  -- pending|approved|rejected|expired|auto
    approved_at          timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX decisions_run_idx ON decisions (run_id);
CREATE INDEX decisions_ticker_idx ON decisions (ticker, created_at DESC);

CREATE TABLE orders (
    id              bigserial PRIMARY KEY,
    decision_id     bigint REFERENCES decisions (id),
    broker_order_id text UNIQUE,
    idempotency_key text        NOT NULL UNIQUE,
    ticker          text        NOT NULL,
    side            text        NOT NULL,  -- buy|sell
    qty             numeric(18, 6),
    notional_usd    numeric(14, 2),
    limit_price     numeric(14, 4),
    stop_price      numeric(14, 4),
    order_type      text        NOT NULL,  -- limit|stop
    time_in_force   text        NOT NULL,  -- day|gtc
    status          text        NOT NULL DEFAULT 'new',  -- new|submitted|partially_filled|filled|cancelled|rejected|expired
    submitted_at    timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    raw             jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX orders_ticker_idx ON orders (ticker, updated_at DESC);

CREATE TABLE fills (
    id             bigserial PRIMARY KEY,
    order_id       bigint      NOT NULL REFERENCES orders (id),
    broker_fill_id text UNIQUE,
    qty            numeric(18, 6) NOT NULL,
    price          numeric(14, 4) NOT NULL,
    filled_at      timestamptz NOT NULL,
    raw            jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX fills_order_idx ON fills (order_id);

-- Nightly snapshots; full fill history stays exportable for the tax return (docs/06).
CREATE TABLE positions_daily (
    id             bigserial PRIMARY KEY,
    snapshot_date  date        NOT NULL,
    ticker         text        NOT NULL,
    qty            numeric(18, 6) NOT NULL,
    avg_cost       numeric(14, 4),
    market_value   numeric(14, 2),
    unrealized_pnl numeric(14, 2),
    weight_pct     numeric(6, 2),
    UNIQUE (snapshot_date, ticker)
);

CREATE TABLE pnl_daily (
    snapshot_date      date PRIMARY KEY,
    nav                numeric(14, 2) NOT NULL,
    cash               numeric(14, 2) NOT NULL,
    unrealized_pnl     numeric(14, 2),
    realized_pnl_day   numeric(14, 2),
    -- benchmark closing levels, normalized later in queries (docs/02 §4)
    bench_equal_weight numeric(14, 4),
    bench_soxx         numeric(14, 4),
    bench_qqq          numeric(14, 4)
);

-- Every AI call logs tokens + cost (CLAUDE.md convention; budget checks read this).
CREATE TABLE api_costs (
    id                 bigserial PRIMARY KEY,
    run_id             bigint REFERENCES runs (id),
    stage              text        NOT NULL,  -- triage|research|analyst|skeptic|deep_review|other
    model              text        NOT NULL,
    input_tokens       bigint      NOT NULL DEFAULT 0,
    output_tokens      bigint      NOT NULL DEFAULT 0,
    cache_read_tokens  bigint      NOT NULL DEFAULT 0,
    cache_write_tokens bigint      NOT NULL DEFAULT 0,
    web_searches       integer     NOT NULL DEFAULT 0,
    cost_usd           numeric(12, 6) NOT NULL DEFAULT 0,
    cost_eur           numeric(12, 6) NOT NULL DEFAULT 0,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX api_costs_created_idx ON api_costs (created_at);
CREATE INDEX api_costs_run_idx ON api_costs (run_id);

-- Post-mortem outputs the weekly prompt re-reads — the system's memory (docs/08 §5).
CREATE TABLE lessons (
    id         bigserial PRIMARY KEY,
    source     text        NOT NULL,  -- weekly_review|monthly_review|postmortem|manual
    ticker     text,
    title      text        NOT NULL,
    body       text        NOT NULL,
    tags       text[]      NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Small key/value flags every run checks first (kill switch, per-ticker pauses, ...).
CREATE TABLE app_state (
    key        text PRIMARY KEY,
    value      jsonb       NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO app_state (key, value) VALUES ('halted', 'false'::jsonb);
INSERT INTO app_state (key, value) VALUES ('paused_tickers', '[]'::jsonb);
