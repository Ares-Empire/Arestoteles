# 11 — Web Front-end (the Arestoteles portal)

The standalone Arestoteles site: an epic, broker-grade portal that shares the Ares design
language with Aresium (`docs/09`). This doc is the design brief + the prompt to hand to a design
pass, plus references. Data contract is in `docs/09`; build sequencing (shell now, fills at
Phase 2) is there too.

## Non-negotiables (read before any design work)

1. **Match Aresium's design system verbatim — do not invent a new aesthetic.** Same tokens
   (`/root/aresium/web/public/index.html` `<style>`), fonts (**Space Grotesk** + **JetBrains
   Mono**), glass side-cards, **charts painted straight on the wall (no card/border/shadow — only
   side panels get the glass treatment)**, the big wordmark band at the bottom, tabular-nums on
   every figure, tight negative letter-spacing. This is what guarantees "same level or better" and
   keeps the empire coherent.
2. **It must not look soft or AI-generated.** Aresium's look is hand-tuned and opinionated
   (physically-grounded motion, editorial density, monospace numerics). Explicit **don'ts**: no
   generic SaaS gradients, no purple/indigo startup palette, no Inter/system-font body, no
   centered-hero-with-three-feature-cards, no emoji, no rounded-pill-everything, no glassmorphism
   overload, no drop shadows on everything. Dense, data-first, terminal-grade.
3. **Stack = Aresium's zero-build pattern**: React 18 UMD + Babel-standalone from CDN, `.jsx`
   served static by the FastAPI `api` service. Reuse Aresium's `AnimatedChart` (SVG line/area with
   rAF morphing) as the chart base. No bundler.

## Brand & palette

- **Mark**: the Aristotle/Aristoteles marble bust (the Telegram avatar asset already exists in
  `assets/`). White/grey marble on a black wall is the signature.
- **Wordmark**: `ARESTOTELES` in the exact ARESIUM band style (`.aresium-word`), spread across the
  full width at the bottom; gradient text-fill.
- **Color**: keep Aresium's black wall + typography. Brand neutral = **marble white/grey** (the
  bust). P&L uses Aresium's existing **green `#34E27A` (up)** / **red `#FF2D4B` (down)** — intuitive
  for a broker and already in the family. Avoid introducing a new hue.

## The intro (epic, plays once per session — `sessionStorage`; honor `prefers-reduced-motion`)

Technique = Aresium's `aresium-intro.js` (self-contained full-screen overlay, Web Animations API,
theme/handoff under cover). The bust moves in **depth (z)**, not just top-to-bottom. Sequence:
1. Black wall. The **marble bust starts BIG and close** to the camera (filling much of the
   viewport, slightly soft/foreground).
2. It **falls back onto the wall** — receding into the scene, so it **scales down** to its resting
   size as it drops to low-center. **Impact** = a screen-shake (small global transform jitter).
3. A **crater** forms where it lands: radial **cracks draw outward** in white/light-grey (SVG paths
   animated via `stroke-dashoffset`), with a dust/displacement puff. The bust settles in.
4. The **ARESTOTELES wordmark appears below the bust** (reuse the enter-keyframe vibration from
   `aresium-intro.js`) and settles into the bottom band.
5. **Crossfade to the interface** (the overlay hands off to the real bust-mark + band, seamless).
Reduced-motion / repeat-visit: skip straight to the interface.

**Build the motion, not just the final frame.** The design pass must produce the **intro as a
working, self-contained animated module** (same shape as `aresium-intro.js`) *and* the interface —
the drop→recede→crater→wordmark is the centerpiece. Keep it isolated so it can be iterated without
touching the app. (Aresium has **no** load intro today — `aresium-intro.js` only fires on its
red-mode toggle — so this bust-drop is net-new; reuse it only as the animation *technique*.)

## Screens

**Overview (the wall):**
- **Top header**: total NAV (big, tabular-nums), **today Δ** and **since-inception Δ** (green/red),
  mode chip (paper/live), "data as of …", a market-open dot. Bust-mark + "Arestoteles" top-left;
  Ares switcher + range controls top-right.
- **Main chart on the wall**: portfolio NAV over time with the benchmark overlay (SOXX +
  equal-weight), multi-line like Aresium's overview, clickable legend.
- **Positions** (glass side-card or wall rows): each row = ticker (mono), company name, a
  **mini-sparkline**, last price, **day %** (green/red), weight %. Click → detail. Empty-state when
  no positions yet ("Phase 1: no open positions — the brain trades from Phase 2").
- **Bottom**: the big `ARESTOTELES` wordmark band. Page scrolls if many positions.

**Per-stock detail (click a position):**
- **Range tabs** `1D · 1W · 1M · 1Y · ALL · Since buy` (segmented control like Aresium's `modeseg`).
- **Chart on the wall** (no card): price line/candles for the range. A **dashed cost-basis guide
  line** at avg entry (uses `--guide`); a **marker at the buy date**. Hover tooltip like Aresium's.
- **Figures**: big current price + **day Δ** (abs + %) and **since-purchase Δ** (abs + %), all
  green/red tabular-nums.
- **Thesis card** (glass side-card, from `/theses/{id}` — Phase 2+): the claim, a **conviction
  badge**, a **horizon progress bar** ("day 23 of 90"), **falsifiers as a checklist**, **planned
  exit / strategy**, **citations as links**. Until Phase 2: "thesis pending" state.

**Mobile (≤620px — its own flow, like Aresium's `mobile.jsx`, not a reflow):**
- Header: bust-mark + ARESTOTELES. A **list of positions**, each showing **day Δ** (a toggle flips
  to total Δ). Tap a position → reveals the **on-the-wall graph** + the detail figures + thesis.
- Big `ARESTOTELES` band at the bottom. Intro plays scaled-down. Keep it calm, not overwhelming.

## "Cool broker portal" touches (in-family, optional ones marked v2)
- Tabular-nums monospace for every number; tickers in mono; color-coded P&L throughout.
- Per-row sparklines; a cost-basis guide line on detail charts; buy-date markers.
- A live "as of HH:MM" + market-open indicator.
- *(v2, distinctive)* a small **value-chain node map** — Arestoteles' whole thesis is the
  value-chain graph (`docs/04`); a mini chain viz on the overview would be unique and on-brand.

## References (the three to orient at, + the source of truth)
Tell the design pass to orient itself at these **three**:
- **Robinhood** — the canonical per-stock view: one big line, cost-basis, green/red, the
  `1D/1W/1M/1Y/ALL` range tabs. The detail screen mirrors this.
- **Bloomberg Terminal** — the dense, monospace, data-first end; the best anti-reference for "not
  AI-generated." Borrow numeric density and discipline, not the clutter.
- **Linear** — the craft bar for dark, opinionated, non-generic UI (the level of finish to hit).

And above all: **Aresium itself** is the single source of truth for the look — attach its files
(below) and mimic it.

## Files to attach so the design pass matches the *real* Aresium
(The standing Aresium design project may be stale — attach the current files.) In priority order:
1. `web/public/index.html` — the **entire design system** (tokens, themes, component CSS, fonts).
2. `web/public/app/chart.jsx` — the on-the-wall `AnimatedChart` engine.
3. `web/public/app/app.jsx` — the shell/layout (wall grid, header, glass side-cards).
4. `web/public/app/aresium-intro.js` — the animation *technique* for the intro.
5. `web/public/app/mobile.jsx` — the mobile flow pattern.
6. The **bust image asset** (`assets/`) — so it uses the real mark.

---

## Prompt to hand to the design pass (copy-paste)

> Build the front-end for **Arestoteles** (domain **arestoteles.de**), a personal AI-run stock
> portfolio portal for the semiconductor / AI-infrastructure sector. It is a **sibling of Aresium**
> (a finance tracker) in the same "Ares" family and **must share its exact design language**.
> **To orient yourself, study the attached Aresium files** — `index.html` (the whole design system:
> tokens, themes, component CSS, fonts), `chart.jsx` (the on-the-wall chart engine), `app.jsx` (the
> shell/layout), `aresium-intro.js` (the animation technique), `mobile.jsx` (the mobile flow), and
> the bust image. They are the source of truth; mimic them. Same CSS tokens and themes, same fonts
> (**Space Grotesk** for text, **JetBrains Mono** for all numbers), same glass side-cards, the same
> approach of **painting charts directly onto the black wall with no card/border/shadow** (only side
> panels get the glass treatment), the same big wordmark band at the bottom, tabular-nums
> everywhere, tight negative letter-spacing. Reuse Aresium's `AnimatedChart` (CDN React 18 UMD +
> Babel-standalone, zero build) as the chart engine and its `mobile.jsx` device-routing pattern.
>
> **This must look like a premium, hand-built stock-broker terminal — NOT a soft, generic,
> AI-generated SaaS site.** Hard don'ts: no generic gradients, no purple/indigo startup palette, no
> Inter/system body font, no centered hero with three feature cards, no emoji, no
> pill-everything, no glassmorphism overload, no drop shadows everywhere. Dense, editorial,
> data-first, opinionated. **Orient yourself at three references: Robinhood** (the per-stock view +
> range tabs), **Bloomberg Terminal** (numeric density + the anti-AI-generated bar), and **Linear**
> (dark, opinionated craft) — all rendered in Aresium's exact skin.
>
> **Brand**: the mark is the Aristotle marble **bust** (asset in `assets/`), white/grey marble on a
> black wall; the wordmark is **ARESTOTELES** in Aresium's `.aresium-word` band style. Palette =
> Aresium's black wall + typography, brand neutral marble white/grey, P&L in Aresium's green
> `#34E27A` (up) / red `#FF2D4B` (down). Do not introduce a new hue.
>
> **Intro — build it as working motion, not just a final frame** (full-screen, once per session via
> sessionStorage, honor prefers-reduced-motion; use the `aresium-intro.js` Web-Animations technique —
> note Aresium has no load intro today, that file only animates its red-mode toggle, so this is
> net-new). The bust moves in **depth (z)**: it **starts BIG and close** to the camera (filling much
> of the viewport), then **falls back onto the wall** — receding, so it **scales down** to its
> resting size as it drops to low-center; **impact** triggers a screen-shake; a **crater forms and
> white/light-grey cracks draw outward** (SVG `stroke-dashoffset`) with a dust puff; the bust settles
> in; then the **ARESTOTELES wordmark appears below it and vibrates** into the bottom band; finally
> **crossfade to the interface**. Deliver the intro as a **self-contained, separately iterable
> module**. Reduced-motion / repeat visits skip straight to the UI.
>
> **Overview**: top header with total NAV (big, mono), today Δ and since-inception Δ (green/red),
> a paper/live chip, "data as of …", market-open dot, bust-mark + "Arestoteles" top-left, an "Ares"
> app-switcher top-right. The main chart on the wall = portfolio NAV over time with SOXX +
> equal-weight benchmark overlay and a clickable legend. A positions list (ticker in mono, company
> name, mini-sparkline, last price, day %, weight %); empty-state when there are no positions yet.
> Big ARESTOTELES band at the bottom; the page scrolls when there are many positions.
>
> **Per-stock detail** (click a position): range tabs `1D · 1W · 1M · 1Y · ALL · Since buy`
> (segmented control). The price chart sits on the wall with a **dashed cost-basis guide line at
> avg entry** and a **buy-date marker**; Aresium-style hover tooltip. Show big current price, day Δ
> (abs+%), and since-purchase Δ (abs+%) in green/red mono. A glass **thesis side-card**: the AI's
> claim/reason for buying, a conviction badge, a horizon progress bar ("day 23 of 90"), falsifiers
> as a checklist, the planned-exit strategy, and citations as links. (Thesis data is Phase 2+ —
> render a clean "thesis pending" state until then.)
>
> **Mobile (≤620px)**: its own flow (not a reflow), like Aresium's `mobile.jsx`. Header with
> bust-mark + ARESTOTELES; a list of positions each showing day Δ with a toggle to total Δ; tap a
> position to reveal its on-the-wall graph + figures + thesis. Big ARESTOTELES band at the bottom;
> scaled-down intro. Keep it calm and easy to navigate, not overwhelming.
>
> **Data**: read-only JSON from the Arestoteles FastAPI (`docs/09`): `/portfolio`, `/positions`,
> `/positions/{ticker}/bars?range=…`, `/theses/{id}`, `/performance`, `/health`. Build against the
> live paper portfolio (NAV $100k, zero positions in Phase 1) so the shell works now and fills in
> when the brain trades.
>
> **Out of scope for you**: the login screen (handled separately by porting Aresium's existing
> `/login` page + auth) and the central "Ares" manager/hub site. Just include a small header link/
> switcher pointing back to the hub.
