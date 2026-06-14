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
        <a className="hub-link" href="#ares-hub" onClick={(e) => e.preventDefault()} title="Back to the Ares hub">
          <span className="hub-dot" /> Ares hub
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><path d="M6 3 L11 8 L6 13" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </a>
        <button className="btn-mode" onClick={onMode} aria-label="Toggle Ares mode" title={mode === "red" ? "Exit Ares mode" : "Enter Ares mode"}>
          {mode === "red"
            ? <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M11.5 4.5 L4.5 11.5 M4.5 4.5 L11.5 11.5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" /></svg>
            : <svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M20 14.5 A8 8 0 1 1 9.5 4 A6.2 6.2 0 0 0 20 14.5 Z" fill="currentColor" /></svg>}
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
function Overview({ onOpen, ver }) {
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
            <window.PositionsList positions={positions} onOpen={onOpen} watch={empty ? live : null} />
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
  const home = useC(() => setNav({ screen: "overview" }), []);

  return (
    <div className="app">
      <div className="mode-fade" ref={fadeRef} aria-hidden="true" />
      <TopBar crumb={nav.screen === "stock" ? nav.ticker : null} onHome={home} onMode={toggleMode} mode={mode} />
      {nav.screen === "overview"
        ? <Overview onOpen={openStock} ver={ver} />
        : <StockDetail ticker={nav.ticker} ver={ver} />}
      <div className="ares-band" aria-hidden="true"><window.Wordmark /></div>
    </div>
  );
}

window.ArestotelesApp = App;
