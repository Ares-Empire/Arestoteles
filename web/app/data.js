/* Arestoteles — read-only data layer (window.AresData).

   Mirrors the shape of the live Arestoteles API (/portfolio, /positions,
   /positions/{ticker}, /performance, /health) so the shell works now and fills
   in when the brain trades. Phase 1 is a $100k paper book with ZERO positions —
   that is the default. A realistic semiconductor / AI-infra demo book is generated
   procedurally (seeded, deterministic) and exposed behind AresData.setEmpty(false).

   All money is USD. P&L green #34E27A (up) / red #FF2D4B (down). */
(function () {
  "use strict";

  // ---------- seeded RNG (deterministic so the mock never jitters) ----------
  function mulberry(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // a smooth-ish random walk of length n, ending near `end`, starting near `start`
  function walk(seed, n, start, end, vol) {
    const r = mulberry(seed);
    const out = [];
    let v = start;
    for (let i = 0; i < n; i++) {
      const drift = (end - start) / n;
      const shock = (r() - 0.5) * 2 * vol;
      // mild mean-pull toward the straight-line path so it lands near `end`
      const target = start + drift * i;
      v = v + drift + shock + (target - v) * 0.06;
      out.push(v);
    }
    // pin the last point exactly to `end`
    const adj = end - out[out.length - 1];
    for (let i = 0; i < n; i++) out[i] += adj * (i / (n - 1));
    return out;
  }

  const INCEPTION = "2026-01-02";
  const NAV0 = 100000;

  // ---------- demo book: 9 semiconductor / AI-infrastructure names ----------
  // shares & avgCost are the "paper" entries; price is "now". day% is today's move.
  const DEMO = [
    { ticker: "NVDA", name: "NVIDIA Corp.",          shares: 58,  avgCost: 121.40, price: 168.92, day: 2.14,  buy: "2026-01-08", seed: 11, vol: 2.6, conv: "High" },
    { ticker: "TSM",  name: "Taiwan Semiconductor",  shares: 96,  avgCost: 178.20, price: 211.55, day: 1.02,  buy: "2026-01-08", seed: 22, vol: 2.1, conv: "High" },
    { ticker: "AVGO", name: "Broadcom Inc.",         shares: 41,  avgCost: 232.10, price: 286.40, day: -0.61, buy: "2026-01-15", seed: 33, vol: 3.0, conv: "Medium" },
    { ticker: "ASML", name: "ASML Holding",          shares: 9,   avgCost: 742.00, price: 808.13, day: 0.44,  buy: "2026-02-02", seed: 44, vol: 4.2, conv: "High" },
    { ticker: "AMD",  name: "Advanced Micro Devices",shares: 64,  avgCost: 152.80, price: 141.27, day: -1.83, buy: "2026-01-22", seed: 55, vol: 3.4, conv: "Medium" },
    { ticker: "MRVL", name: "Marvell Technology",    shares: 110, avgCost: 78.40,  price: 92.05,  day: 0.77,  buy: "2026-02-18", seed: 66, vol: 3.1, conv: "Medium" },
    { ticker: "VRT",  name: "Vertiv Holdings",       shares: 130, avgCost: 88.60,  price: 119.34, day: 3.05,  buy: "2026-02-26", seed: 77, vol: 4.6, conv: "Medium" },
    { ticker: "MU",   name: "Micron Technology",     shares: 88,  avgCost: 104.20, price: 98.61,  day: -0.42, buy: "2026-03-09", seed: 88, vol: 3.8, conv: "Low"    },
    { ticker: "ARM",  name: "Arm Holdings",          shares: 35,  avgCost: 138.50, price: 151.80, day: 1.61,  buy: "2026-03-20", seed: 99, vol: 4.0, conv: "Medium" },
  ];

  // theses (Phase 2+ data) — fully populated for the demo book; pending otherwise.
  const THESES = {
    NVDA: {
      conviction: "High", horizonDays: 90, dayN: 23,
      claim: "Accelerator demand stays supply-constrained through the next data-center build cycle; Blackwell ramp protects gross margin above 70%.",
      reason: "Hyperscaler capex guides revised up three quarters running while lead times stay long. Pricing power has not cracked.",
      falsifiers: [
        { t: "Data-center revenue decelerates two quarters running", done: false },
        { t: "Gross margin prints below 68%", done: false },
        { t: "A credible merchant-silicon alternative ships at scale", done: false },
      ],
      exit: "Trim 25% if weight exceeds 22% of NAV; full exit on a thesis-breaking margin miss or a >35% drawdown from cost.",
      citations: [
        { t: "Q1 FY27 earnings call transcript", href: "#" },
        { t: "Hyperscaler capex tracker — Mar 2026", href: "#" },
      ],
    },
    TSM: {
      conviction: "High", horizonDays: 120, dayN: 41,
      claim: "Leading-edge foundry is a structural toll booth on the entire AI compute stack; 2nm pre-bookings de-risk 2027 revenue.",
      reason: "No second source for sub-3nm at volume. Pricing increases accepted by every major fabless customer.",
      falsifiers: [
        { t: "2nm yield ramp slips more than two quarters", done: false },
        { t: "A customer credibly dual-sources at the leading edge", done: false },
        { t: "Taiwan-strait risk premium forces a re-rate", done: true },
      ],
      exit: "Hold through cycle; trim only on a >30% premium to 5-yr avg P/E.",
      citations: [{ t: "2nm capacity roadmap", href: "#" }],
    },
    VRT: {
      conviction: "Medium", horizonDays: 60, dayN: 9,
      claim: "Liquid cooling and power distribution are the bottleneck of the AI build-out; Vertiv captures spend regardless of which chip wins.",
      reason: "Backlog and book-to-bill both expanding; picks-and-shovels exposure with less single-vendor risk than the chipmakers.",
      falsifiers: [
        { t: "Book-to-bill falls below 1.0", done: false },
        { t: "Hyperscaler capex guides cut", done: false },
      ],
      exit: "Momentum trade — exit on a close below the 50-day or at +40% from cost.",
      citations: [{ t: "Order backlog disclosure", href: "#" }],
    },
  };

  const TRADING_DAYS = 112;            // since inception (~5.5 months of weekdays)
  const labelEvery = TRADING_DAYS;

  function dateLabels(n, endOffsetDays) {
    // n weekday labels ending today
    const out = [];
    const d = new Date("2026-06-12T00:00:00");
    let count = 0;
    while (out.length < n) {
      const wd = d.getDay();
      if (wd !== 0 && wd !== 6) {
        out.unshift(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
        count++;
      }
      d.setDate(d.getDate() - 1);
    }
    return out;
  }
  const DAY_LABELS = dateLabels(TRADING_DAYS);

  // per-ticker daily price series since inception → used to derive ranges
  function dailySeries(p) {
    const start = p.avgCost * (0.98 + (mulberry(p.seed)() * 0.04));
    return walk(p.seed, TRADING_DAYS, start, p.price, p.price * p.vol / 100);
  }
  // intraday 1D series (39 half-hour-ish ticks) ending at price
  function intraday(p) {
    const open = p.price / (1 + p.day / 100);
    return walk(p.seed + 7, 40, open, p.price, p.price * 0.004);
  }
  function buyIndex(p) {
    // index into the daily series where the buy happened
    const buy = new Date(p.buy + "T00:00:00");
    const today = new Date("2026-06-12T00:00:00");
    const days = Math.round((today - buy) / 86400000);
    const weekdays = Math.round(days * 5 / 7);
    return Math.max(0, TRADING_DAYS - weekdays);
  }

  const RANGES = ["1D", "1W", "1M", "1Y", "ALL", "Buy"];
  function rangeWindow(range, len, p) {
    // returns {sliceFrom} into the daily series, plus a labels generator
    switch (range) {
      case "1W": return Math.max(0, len - 5);
      case "1M": return Math.max(0, len - 22);
      case "1Y": return 0;     // we only have since-inception (<1yr) → show ALL
      case "ALL": return 0;
      case "Buy": return buyIndex(p);
      default: return 0;
    }
  }

  // ---------- portfolio aggregation ----------
  function marketValue(p) { return p.shares * p.price; }
  function costValue(p) { return p.shares * p.avgCost; }

  let EMPTY = true;   // Phase 1 default

  const API = {
    get empty() { return EMPTY; },
    setEmpty(v) { EMPTY = !!v; },
    inception: INCEPTION,
    nav0: NAV0,
    ranges: RANGES,
    pnlFlip: 1,           // tweak hook: multiply all P&L by this (-1 flips the book red/green)
    thesisPending: false, // tweak hook: force the clean "thesis pending" state everywhere

    health() { return { status: "ok", mode: "paper", asOf: "2026-06-12T20:00:00Z", marketOpen: false }; },

    // /portfolio
    portfolio() {
      if (EMPTY) {
        return { mode: "paper", nav: NAV0, cash: NAV0, invested: 0,
          dayAbs: 0, dayPct: 0, sinceAbs: 0, sincePct: 0,
          asOf: "Jun 12, 2026 · 4:00 PM ET", marketOpen: false, positions: 0 };
      }
      const invested = DEMO.reduce((s, p) => s + marketValue(p), 0);
      const cost = DEMO.reduce((s, p) => s + costValue(p), 0);
      const cash = NAV0 - cost;              // remaining buying power
      const nav = invested + cash;
      // today's $ move = sum of each position's day move
      const dayAbs = DEMO.reduce((s, p) => s + marketValue(p) * (p.day / 100) / (1 + p.day / 100), 0) * this.pnlFlip;
      const dayPct = (dayAbs / (nav - dayAbs)) * 100;
      const sinceAbs = (nav - NAV0) * this.pnlFlip;
      const sincePct = (sinceAbs / NAV0) * 100;
      return { mode: "paper", nav: nav + (this.pnlFlip < 0 ? 0 : 0), cash, invested,
        dayAbs, dayPct, sinceAbs, sincePct,
        asOf: "Jun 12, 2026 · 4:00 PM ET", marketOpen: false, positions: DEMO.length };
    },

    // /positions
    positions() {
      if (EMPTY) return [];
      const totalMV = DEMO.reduce((s, p) => s + marketValue(p), 0);
      return DEMO.map((p) => {
        const mv = marketValue(p);
        const series = dailySeries(p);
        return {
          ticker: p.ticker, name: p.name, shares: p.shares,
          avgCost: p.avgCost, price: p.price,
          day: p.day * this.pnlFlip,
          weight: (mv / totalMV) * 100,
          mv, buy: p.buy,
          sincePct: ((p.price - p.avgCost) / p.avgCost) * 100 * this.pnlFlip,
          sinceAbs: (p.price - p.avgCost) * p.shares * this.pnlFlip,
          spark: series.slice(-26),
          conv: p.conv,
        };
      });
    },

    // /positions/{ticker}
    position(ticker) {
      const p = DEMO.find((x) => x.ticker === ticker);
      if (!p) return null;
      const series = dailySeries(p);
      const bi = buyIndex(p);
      return {
        ticker: p.ticker, name: p.name, shares: p.shares,
        avgCost: p.avgCost, price: p.price, buy: p.buy,
        day: p.day * this.pnlFlip,
        dayAbs: (p.price - p.price / (1 + p.day / 100)) * p.shares * this.pnlFlip,
        sincePct: ((p.price - p.avgCost) / p.avgCost) * 100 * this.pnlFlip,
        sinceAbs: (p.price - p.avgCost) * p.shares * this.pnlFlip,
        weight: 0, buyIndex: bi,
        daily: series, intraday: intraday(p),
        labels: DAY_LABELS,
        thesis: this.thesisPending ? null : (THESES[p.ticker] || null),
      };
    },

    // price series + labels for a given range on a position
    priceRange(pos, range) {
      if (range === "1D") {
        const pts = pos.intraday;
        const labels = pts.map((_, i) => {
          const h = 9.5 + (i / (pts.length - 1)) * 6.5; // 9:30 → 16:00
          const hr = Math.floor(h); const mn = Math.round((h - hr) * 60);
          return `${((hr + 11) % 12) + 1}:${String(mn).padStart(2, "0")}`;
        });
        return { points: pts, labels, buyIdx: null };
      }
      const from = rangeWindow(range, pos.daily.length, DEMO.find((x) => x.ticker === pos.ticker));
      const points = pos.daily.slice(from);
      const labels = pos.labels.slice(from);
      const buyIdx = range === "ALL" || range === "1Y" ? (pos.buyIndex - from) : (range === "Buy" ? 0 : null);
      return { points, labels, buyIdx: buyIdx != null && buyIdx >= 0 && buyIdx < points.length ? buyIdx : null };
    },

    // /performance — NAV vs SOXX vs equal-weight benchmark, indexed to 100 at inception → $
    performance() {
      const n = TRADING_DAYS;
      if (EMPTY) {
        const flat = new Array(n).fill(NAV0);
        return { labels: DAY_LABELS,
          series: [
            { key: "nav",  label: "NAV",          points: flat },
            { key: "soxx", label: "SOXX",         points: flat.slice() },
            { key: "eqw",  label: "Equal-weight", points: flat.slice() },
          ] };
      }
      const pf = this.portfolio();
      const nav = walk(2026, n, NAV0, pf.nav, NAV0 * 0.011);
      const soxx = walk(2031, n, NAV0, NAV0 * 1.142, NAV0 * 0.013);
      const eqw  = walk(2099, n, NAV0, NAV0 * 1.088, NAV0 * 0.009);
      return { labels: DAY_LABELS,
        series: [
          { key: "nav",  label: "NAV",          points: nav },
          { key: "soxx", label: "SOXX",         points: soxx },
          { key: "eqw",  label: "Equal-weight", points: eqw },
        ] };
    },
  };

  // formatters
  window.fmtUsd = (v) => "$" + Math.round(v).toLocaleString("en-US");
  window.fmtUsd2 = (v) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  window.fmtPct = (v) => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  window.fmtSigned = (v) => (v >= 0 ? "+" : "−") + "$" + Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

  window.AresData = API;
})();
