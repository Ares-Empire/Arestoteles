/* Arestoteles — app shell (desktop/tablet): header, NAV overview, per-stock detail.
   Black-wall layout: chart painted on the wall (left), glass side-card (right).
   Reads the read-only data layer (window.AresData). */
const { useState: useS, useEffect: useE, useCallback: useC, useMemo: useM, useRef: useR } = React;

const NAV_COLORS = { nav: "#f4f5f9", soxx: "#aaa49a", eqw: "#6f6a62" };  // marble whites/greys
const UP = "#34E27A", DOWN = "#FF2D4B";

function deltaClass(v) { return v >= 0 ? "up" : "down"; }

// header: brand + crumb + hub link + mode toggle
function TopBar({ crumb, onHome, onMode, mode }) {
  return (
    <header className="topbar">
      <div className="brand">
        <button className="brand-btn" onClick={onMode} aria-label="Arestoteles — toggle Ares mode" title={mode === "red" ? "Exit Ares mode" : "Enter Ares mode"}>
          <span className="brand-mark"><window.Bust size={30} /></span>
          <span className="brand-name">Arestoteles</span>
        </button>
        <nav className="crumbs">
          <span className="crumb-wrap"><button className="crumb crumb-link" onClick={onHome}>Overview</button></span>
          {crumb && <span className="crumb-wrap"><span className="crumb-sep">/</span><span className="crumb crumb-cur">{crumb}</span></span>}
        </nav>
      </div>
      <div className="actions">
        {/* Ares Empire hub link — the empire home / future SSO hub. Logo lands later
            (see ares-empire/); until then it's the wordmark. No status dot / chevron. */}
        <a className="hub-link" href="#ares-empire" onClick={(e) => e.preventDefault()} title="The Ares Empire">
          Ares Empire
        </a>
        <button className="btn-mode" onClick={onMode} aria-label="Toggle Ares mode" title={mode === "red" ? "Exit Ares mode" : "Enter Ares mode"}>
          {mode === "red"
            ? <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M11.5 4.5 L4.5 11.5 M4.5 4.5 L11.5 11.5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" /></svg>
            : <svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M20 14.5 A8 8 0 1 1 9.5 4 A6.2 6.2 0 0 0 20 14.5 Z" fill="currentColor" /></svg>}
        </button>
        <button className="btn-mode" onClick={() => { window.location.href = "/logout"; }} aria-label="Log out" title="Log out">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M14 4 H7 a2 2 0 0 0 -2 2 v12 a2 2 0 0 0 2 2 h7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /><path d="M17 8 l4 4 -4 4 M21 12 H10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
      </div>
    </header>
  );
}

function MetaChips({ pf }) {
  return (
    <div className="meta-chips">
      <span className={"chip-mode " + pf.mode}>{pf.mode === "paper" ? "Paper" : "Live"}</span>
      <span className="meta-asof">Data as of {pf.asOf}</span>
      <span className="meta-mkt"><span className={"dot-live " + (pf.marketOpen ? "open" : "closed")} />{pf.marketOpen ? "Market open" : "Market closed"}</span>
    </div>
  );
}

// big NAV summary (overview)
function NavSummary({ pf }) {
  return (
    <div className="summary">
      <div className="summary-main">
        <div className="summary-kicker">Net asset value</div>
        <div className="summary-nav">{window.fmtUsd2(pf.nav)}</div>
      </div>
      <div className="summary-deltas">
        <div className="delta">
          <span className="delta-lbl">Today</span>
          <span className={"delta-val " + deltaClass(pf.dayAbs)}>{window.fmtSigned(pf.dayAbs)} <span className="delta-pct">{window.fmtPct(pf.dayPct)}</span></span>
        </div>
        <div className="delta">
          <span className="delta-lbl">Since inception</span>
          <span className={"delta-val " + deltaClass(pf.sinceAbs)}>{window.fmtSigned(pf.sinceAbs)} <span className="delta-pct">{window.fmtPct(pf.sincePct)}</span></span>
        </div>
      </div>
      <MetaChips pf={pf} />
    </div>
  );
}

function Legend({ series, hidden, onToggle }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <button key={s.key} className={"legend-item" + (hidden[s.key] ? " off" : "")} onClick={() => onToggle(s.key)}>
          <span className="dot" style={{ background: s.color }} />{s.label}
        </button>
      ))}
    </div>
  );
}

// ---- overview screen ----
function Overview({ onOpen, onWatch, ver }) {
  const pf = useM(() => window.AresData.portfolio(), [ver]);
  const positions = useM(() => window.AresData.positions(), [ver]);
  const perf = useM(() => window.AresData.performance(), [ver]);
  const [hidden, setHidden] = useS({});
  const toggle = useC((k) => setHidden((h) => ({ ...h, [k]: !h[k] })), []);

  const series = perf.series.map((s) => ({ ...s, color: NAV_COLORS[s.key] })).filter((s) => !hidden[s.key]);
  const empty = window.AresData.empty;
  const live = window.AresLive;
  const hasWatch = empty && live && live.quotes && live.quotes.length > 0;

  return (
    <React.Fragment>
      <NavSummary pf={pf} />
      <main className="grid grid-overview">
        <section className="chart-card">
          <div className="chart-card-head">
            <div className="chart-titles">
              <h1 className="chart-title">Portfolio NAV</h1>
              <p className="chart-sub">{empty ? "Flat at inception — paper book, no positions" : "Since inception · vs SOXX & equal-weight benchmark"}</p>
            </div>
            <Legend series={perf.series.map((s) => ({ ...s, color: NAV_COLORS[s.key] }))} hidden={hidden} onToggle={toggle} />
          </div>
          <div className="chart-host">
            <window.AnimatedChart
              key={"nav-" + ver}
              animKey={"nav-" + ver + "-" + Object.keys(hidden).filter((k) => hidden[k]).join("")}
              series={series} xLabels={perf.labels} xLabel="" yLabel="USD"
              clickable={false} priceMode={!empty} />
          </div>
        </section>
        <aside className="side-card">
          <div className="side-head">
            <div className="side-titles">
              <div className="side-title">Positions</div>
              <div className="side-sub">{empty ? (hasWatch ? "0 holdings · live watchlist" : "0 holdings · 100% cash") : positions.length + " holdings · " + window.fmtUsd(pf.invested) + " invested"}</div>
            </div>
            {!empty && <span className="side-count">{positions.length}</span>}
          </div>
          <div className="side-body">
            <window.PositionsList positions={positions} onOpen={onOpen} onWatch={onWatch} watch={empty ? live : null} />
          </div>
          {!empty && (
            <div className="side-foot">
              <span>Cash</span><span className="side-foot-v">{window.fmtUsd(pf.cash)}</span>
            </div>
          )}
        </aside>
      </main>
    </React.Fragment>
  );
}

// ---- per-stock detail ----
function StockDetail({ ticker, ver }) {
  const pos = useM(() => window.AresData.position(ticker), [ticker, ver]);
  const [range, setRange] = useS("ALL");
  const rng = useM(() => window.AresData.priceRange(pos, range), [pos, range]);
  if (!pos) return null;
  const up = pos.day >= 0;
  const sinceUp = pos.sinceAbs >= 0;

  const guides = [{ value: pos.avgCost, color: "var(--guide)", label: "Cost " + window.fmtPrice(pos.avgCost) }];
  const markers = rng.buyIdx != null ? [{ index: rng.buyIdx, color: "#b9b4ab", label: "Buy" }] : [];

  return (
    <React.Fragment>
      <div className="summary summary-stock">
        <div className="summary-main">
          <div className="summary-kicker">{pos.name} · {pos.shares} sh @ {window.fmtPrice(pos.avgCost)}</div>
          <div className="summary-nav">{window.fmtPrice(pos.price)}</div>
        </div>
        <div className="summary-deltas">
          <div className="delta">
            <span className="delta-lbl">Today</span>
            <span className={"delta-val " + deltaClass(pos.dayAbs)}>{window.fmtSigned(pos.dayAbs)} <span className="delta-pct">{window.fmtPct(pos.day)}</span></span>
          </div>
          <div className="delta">
            <span className="delta-lbl">Since purchase</span>
            <span className={"delta-val " + deltaClass(pos.sinceAbs)}>{window.fmtSigned(pos.sinceAbs)} <span className="delta-pct">{window.fmtPct(pos.sincePct)}</span></span>
          </div>
        </div>
        <window.RangeTabs ranges={window.AresData.ranges} value={range} onChange={setRange} />
      </div>
      <main className="grid grid-stock">
        <section className="chart-card">
          <div className="chart-card-head">
            <div className="chart-titles">
              <h1 className="chart-title">{ticker} <span className="chart-title-sub">price</span></h1>
              <p className="chart-sub">{range === "Buy" ? "Since first buy" : range === "ALL" ? "Since inception" : range} · dashed line = average cost</p>
            </div>
          </div>
          <div className="chart-host">
            <window.AnimatedChart
              key={ticker + "-" + range}
              animKey={ticker + "-" + range}
              series={[{ key: "px", label: ticker, color: up ? UP : DOWN, fill: true, points: rng.points }]}
              xLabels={rng.labels} xLabel="" yLabel="USD"
              guides={guides} markers={markers} priceMode={true} clickable={false} />
          </div>
        </section>
        <aside className="side-card thesis-card">
          <window.ThesisCard pos={pos} />
        </aside>
      </main>
    </React.Fragment>
  );
}

// ---- watchlist detail (a live, NOT-held name) ----
// Driven entirely by the live.json watchlist feed (window.AresLive): real price + the
// trailing ~30 daily closes. No cost basis / thesis — this is a market quote, not a holding.
function WatchDetail({ ticker, ver }) {
  const live = window.AresLive;
  const q = useM(() => (live.quotes || []).find((x) => x.ticker === ticker), [ticker, ver, live]);
  if (!q) return null;
  const up = (q.day || 0) >= 0;
  const spark = q.spark && q.spark.length > 1 ? q.spark : [q.price, q.price];
  const labels = spark.map((_, i) => (i === 0 ? "~30 sessions" : i === spark.length - 1 ? "now" : ""));
  const first = spark[0], last = spark[spark.length - 1];
  const sinceAbs = last - first;
  const sincePct = first ? (sinceAbs / first) * 100 : 0;
  const sinceUp = sinceAbs >= 0;

  return (
    <React.Fragment>
      <div className="summary summary-stock">
        <div className="summary-main">
          <div className="summary-kicker">{q.name} · live watchlist · not held</div>
          <div className="summary-nav">{window.fmtPrice(q.price)}</div>
        </div>
        <div className="summary-deltas">
          <div className="delta">
            <span className="delta-lbl">Today</span>
            <span className={"delta-val " + deltaClass(q.day || 0)}>{window.fmtPct(q.day || 0)}</span>
          </div>
          <div className="delta">
            <span className="delta-lbl">~30 sessions</span>
            <span className={"delta-val " + deltaClass(sinceAbs)}>{window.fmtSigned(sinceAbs)} <span className="delta-pct">{window.fmtPct(sincePct)}</span></span>
          </div>
        </div>
        <MetaChips pf={{ mode: "paper", asOf: live.asOfLabel || "—", marketOpen: !!live.marketOpen }} />
      </div>
      <main className="grid grid-stock">
        <section className="chart-card">
          <div className="chart-card-head">
            <div className="chart-titles">
              <h1 className="chart-title">{ticker} <span className="chart-title-sub">price</span></h1>
              <p className="chart-sub">Trailing daily closes · live market data, watchlist only</p>
            </div>
          </div>
          <div className="chart-host">
            <window.AnimatedChart
              key={"watch-" + ticker + "-" + ver}
              animKey={"watch-" + ticker}
              series={[{ key: "px", label: ticker, color: sinceUp ? UP : DOWN, fill: true, points: spark }]}
              xLabels={labels} xLabel="" yLabel="USD"
              priceMode={true} clickable={false} />
          </div>
        </section>
        <aside className="side-card thesis-card">
          <div className="thesis">
            <div className="thesis-head">
              <span className="thesis-kicker">Watchlist</span>
              <span className="conv-badge conv-med">Not held</span>
            </div>
            <div className="thesis-pending">
              <div className="thesis-pending-ic" dangerouslySetInnerHTML={{ __html: window.lucideSvg("Activity") }} />
              <div className="thesis-pending-h">Live, not held</div>
              <div className="thesis-pending-p">{q.name} ({ticker}) is on the sector watchlist — real quotes from the live market feed, <b>not</b> a position in the paper book. A thesis appears here only once the brain opens a position. <span className="thesis-phase">Phase 2+</span></div>
            </div>
          </div>
        </aside>
      </main>
    </React.Fragment>
  );
}

function App() {
  const [mode, setMode] = useS("dark");        // dark | red
  const [nav, setNav] = useS({ screen: "overview" });
  const [ver, setVer] = useS(0);
  const fadeRef = useR(null);
  const busy = useR(false);

  useE(() => { document.documentElement.setAttribute("data-theme", mode); }, [mode]);
  // tweak bridge: data toggles dispatch 'ares-tweak'
  useE(() => {
    const fn = () => setVer((v) => v + 1);
    window.addEventListener("ares-tweak", fn);
    return () => window.removeEventListener("ares-tweak", fn);
  }, []);

  // dark → red: the bust drops onto the live portfolio and the dark UI shatters away to red
  const enterRed = useC(() => {
    if (busy.current) return;
    if (window.AresShatter) {
      busy.current = true;
      window.AresShatter.toRed({ onSwap: () => setMode("red"), onDone: () => { busy.current = false; } });
    } else {
      const f = fadeRef.current; if (f) { f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 460); }
      setTimeout(() => setMode("red"), 180);
    }
  }, []);
  // red → dark: quiet crossfade back
  const exitRed = useC(() => {
    const f = fadeRef.current; if (f) { f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 460); }
    setTimeout(() => setMode("dark"), 180);
  }, []);
  const toggleMode = useC(() => { (mode === "red" ? exitRed : enterRed)(); }, [mode, enterRed, exitRed]);

  const openStock = useC((t) => setNav({ screen: "stock", ticker: t }), []);
  const openWatch = useC((t) => setNav({ screen: "watch", ticker: t }), []);
  const home = useC(() => setNav({ screen: "overview" }), []);

  return (
    <div className="app">
      <div className="mode-fade" ref={fadeRef} aria-hidden="true" />
      <TopBar crumb={nav.screen === "overview" ? null : nav.ticker} onHome={home} onMode={toggleMode} mode={mode} />
      {nav.screen === "overview"
        ? <Overview onOpen={openStock} onWatch={openWatch} ver={ver} />
        : nav.screen === "watch"
          ? <WatchDetail ticker={nav.ticker} ver={ver} />
          : <StockDetail ticker={nav.ticker} ver={ver} />}
      <div className="ares-band" aria-hidden="true"><window.Wordmark /></div>
    </div>
  );
}

window.ArestotelesApp = App;
