# 06 — Brokers & Execution

## Decision

- **Sandbox / Phases 1–4: Alpaca paper trading.** Free, no funding, no residency hurdle, and
  the paper API is byte-identical to live — code written now is live-ready.
- **Live / Phase 5: Alpaca international account *or* Interactive Brokers (IBKR)** — final
  pick deferred to Phase 5 with one concrete homework item: compare *funding* costs from a
  German bank (details below). The execution module is written against a thin
  `Broker` interface so the adapter is swappable.

## Comparison (checked June 2026 — re-verify at Phase 5)

| | **Alpaca** | **IBKR** | Trade Republic / Scalable | lemon.markets |
|---|---|---|---|---|
| Public trading API | First-class REST/SDK (`alpaca-py`) | Yes (TWS API / Web API) — powerful but heavier (gateway process, auth dance) | None → disqualified | Pivoted B2B; not a retail option |
| Paper trading | Yes, identical API, free | Yes (data subscriptions extra) | — | — |
| German residents | International accounts supported in many countries (verify in signup); Alpaca also acquired WealthKernel → "Alpaca Europe" entity, Xetra trading launching | Yes (IBKR Ireland entity), mature | — | — |
| US stock commissions | $0 (+ regulatory cents on sells) | Tiered ~$0.0035/share, min $0.35/order | — | — |
| Fractional shares | Yes | Yes (US stocks) | — | — |
| Funding from Germany | **USD only**; international wire (bank fees apply; Alpaca withdrawal wire $25 domestic / $50 international) or Rapyd | **SEPA EUR transfer free**, FX EUR→USD ≈ 0.002 %, min $2 | — | — |
| Market data (free tier) | IEX real-time + 15-min-delayed SIP — sufficient for our horizon | Delayed free; real-time = paid subscriptions | — | — |
| Protection | US FINRA/SIPC ($500k) | SIPC/Irish scheme | — | — |

The funding line is why the live decision is deferred: for a €1–3k account, a $25–50 wire +
bank FX fees is 1–3 % drag at Alpaca, while IBKR's SEPA+cheap-FX path costs ~€2 — but IBKR's
API is more work. If Alpaca Europe's EUR rails are live by Phase 5, that may resolve it.

## Rules & mechanics to encode

- **PDT rule:** US margin accounts < $25k equity may make max 3 day trades per 5 business
  days. We don't day trade and the risk engine forbids same-day round trips, so this is a
  belt-and-suspenders constraint, but the execution module must still track it (paper account
  simulates it).
- **Settlement is T+1** (US, since May 2024). With a cash-account mindset + 15 % cash buffer,
  unsettled-funds rejections shouldn't occur; handle the error case anyway.
- **Order policy:** marketable limit orders only (±0.3 % of last trade), DAY for entries,
  GTC for stop-losses (held at broker so they survive our downtime), no orders in the first
  5 min after open, no overnight/extended-hours orders in v1.
- **Partial fills:** accept; remainder cancelled at EOD; position math always from broker
  truth (`/positions`), never from our intent.
- **Corporate actions** (splits, dividends): Alpaca adjusts positions; we reconcile nightly
  snapshot vs. broker and log dividends as cash-flow rows so Aresium P&L stays honest.
- **Reconciliation:** every run starts by diffing DB state vs. broker state; any mismatch ⇒
  halt + alert (this catches both bugs and forgotten manual interventions).
- **W-8BEN** at signup (15 % US dividend withholding). Keep full fill history exportable for
  the German tax return (Anlage KAP) — `fills` table is designed for that.

## Market data plan

Free tiers suffice end-to-end for a swing system: Alpaca IEX real-time quotes for staleness
checks + execution banding; daily bars for stops/benchmarks; EDGAR for fundamentals events;
earnings calendar via Alpaca/Finnhub free. No paid data subscription unless the strategy ever
needs full-SIP intraday (it shouldn't — by design we don't compete intraday).
