/* Arestoteles — mobile (≤620px). Its own flow, not a reflow of the desktop grid.
   Header (bust + ARESTOTELES) · NAV summary with Day/Total toggle · positions list ·
   tap a position → on-the-wall graph + figures + thesis · big ARESTOTELES band.
   Exposes window.ArestotelesMobile (mounted by Root below the 620px breakpoint). */
(function () {
  const { useState, useEffect, useCallback, useMemo, useRef } = React;
  const UP = "#34E27A", DOWN = "#FF2D4B";
  const D = window.AresData;

  function MobLogo() { return <window.Bust size={26} />; }

  function MobileApp() {
    const [mode, setMode] = useState("dark");
    const [nav, setNav] = useState({ screen: "list" });
    const [showTotal, setShowTotal] = useState(false);   // day Δ vs total Δ on rows
    const [range, setRange] = useState("ALL");
    const [ver, setVer] = useState(0);
    const fadeRef = useRef(null);
    const busy = useRef(false);

    useEffect(() => { document.documentElement.setAttribute("data-theme", mode); }, [mode]);
    useEffect(() => {
      const fn = () => setVer((v) => v + 1);
      window.addEventListener("ares-tweak", fn);
      return () => window.removeEventListener("ares-tweak", fn);
    }, []);

    const pf = useMemo(() => D.portfolio(), [ver]);
    const positions = useMemo(() => D.positions(), [ver]);
    const empty = D.empty;

    const toggleMode = useCallback(() => {
      if (mode === "red") {
        const f = fadeRef.current; if (f) { f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 460); }
        setTimeout(() => setMode("dark"), 160);
        return;
      }
      if (busy.current) return;
      if (window.AresShatter) {
        busy.current = true;
        window.AresShatter.toRed({ onSwap: () => setMode("red"), onDone: () => { busy.current = false; } });
      } else {
        const f = fadeRef.current; if (f) { f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 460); }
        setTimeout(() => setMode("red"), 160);
      }
    }, [mode]);

    const openStock = useCallback((t) => { setRange("ALL"); setNav({ screen: "stock", ticker: t }); }, []);
    const back = useCallback(() => setNav({ screen: "list" }), []);

    const pos = nav.screen === "stock" ? D.position(nav.ticker) : null;
    const rng = pos ? D.priceRange(pos, range) : null;

    return (
      <div className="mobile-app">
        <div className="mode-fade" ref={fadeRef} aria-hidden="true" />
        <header className="mob-top">
          {nav.screen === "stock" ? (
            <button className="mob-icon-btn" onClick={back} aria-label="Back">
              <svg width="17" height="17" viewBox="0 0 16 16" fill="none"><path d="M10 3 L5 8 L10 13" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
          ) : (
            <span className="mob-brand" onClick={toggleMode} role="button" tabIndex={0} aria-label="Toggle Ares mode"><MobLogo /></span>
          )}
          <div className="mob-head-title">
            <div className="mob-h1"><span className="mob-h1-tx">{nav.screen === "stock" ? nav.ticker : "Arestoteles"}</span></div>
            <div className="mob-h2">{nav.screen === "stock" ? (pos && pos.name) : "Semiconductor · AI infrastructure"}</div>
          </div>
          <button className="mob-icon-btn" onClick={toggleMode} aria-label="Toggle Ares mode">
            {mode === "red"
              ? <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M11.5 4.5 L4.5 11.5 M4.5 4.5 L11.5 11.5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" /></svg>
              : <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M20 14.5 A8 8 0 1 1 9.5 4 A6.2 6.2 0 0 0 20 14.5 Z" fill="currentColor" /></svg>}
          </button>
        </header>

        <main className="mob-main">
          {nav.screen === "list" && (
            <React.Fragment>
              <div className="mob-summary">
                <div className="mob-sum-kicker">Net asset value</div>
                <div className="mob-sum-nav">{window.fmtUsd2(pf.nav)}</div>
                <div className="mob-sum-row">
                  <span className={"mob-sum-delta " + (pf.dayAbs >= 0 ? "up" : "down")}>{window.fmtSigned(pf.dayAbs)} <span>{window.fmtPct(pf.dayPct)}</span></span>
                  <span className="mob-sum-chip"><span className={"chip-mode " + pf.mode}>{pf.mode === "paper" ? "Paper" : "Live"}</span></span>
                </div>
              </div>

              {!empty && (
                <div className="mob-listbar">
                  <span className="mob-listbar-h">{positions.length} positions</span>
                  <div className="modeseg" role="tablist">
                    <button className={"modeseg-btn" + (!showTotal ? " on" : "")} onClick={() => setShowTotal(false)}>Day</button>
                    <button className={"modeseg-btn" + (showTotal ? " on" : "")} onClick={() => setShowTotal(true)}>Total</button>
                  </div>
                </div>
              )}

              {empty ? (
                <div className="pos-empty mob">
                  <div className="pos-empty-mark"><window.Bust size={52} /></div>
                  <div className="pos-empty-h">No positions yet</div>
                  <div className="pos-empty-p">The book is 100% cash in paper mode. Holdings appear here once the brain starts trading.</div>
                  <div className="pos-empty-chip"><span className="dot-live paper" /> Paper · awaiting first trade</div>
                </div>
              ) : (
                <div className="mob-pos-list">
                  {positions.map((p) => {
                    const v = showTotal ? p.sincePct : p.day;
                    const up = v >= 0;
                    return (
                      <button key={p.ticker} className="mob-pos-row" onClick={() => openStock(p.ticker)}>
                        <div className="mob-pos-id">
                          <span className="mob-pos-ticker">{p.ticker}</span>
                          <span className="mob-pos-name">{p.name}</span>
                        </div>
                        <div className="mob-pos-spark"><window.Sparkline points={p.spark} up={p.spark[p.spark.length - 1] >= p.spark[0]} w={54} h={24} /></div>
                        <div className="mob-pos-num">
                          <span className="mob-pos-price">{window.fmtPrice(p.price)}</span>
                          <span className={"mob-pos-delta " + (up ? "up" : "down")}>{window.fmtPct(v)}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </React.Fragment>
          )}

          {nav.screen === "stock" && pos && (
            <div className="mob-stock">
              <div className="mob-stock-head">
                <div className="mob-stock-price">{window.fmtPrice(pos.price)}</div>
                <div className="mob-stock-deltas">
                  <span className={"mob-sd " + (pos.dayAbs >= 0 ? "up" : "down")}>Today {window.fmtPct(pos.day)}</span>
                  <span className={"mob-sd " + (pos.sinceAbs >= 0 ? "up" : "down")}>Since buy {window.fmtPct(pos.sincePct)}</span>
                </div>
              </div>
              <window.RangeTabs ranges={D.ranges} value={range} onChange={setRange} />
              <div className="mob-stock-graph">
                <window.AnimatedChart
                  key={nav.ticker + "-" + range}
                  animKey={nav.ticker + "-" + range}
                  series={[{ key: "px", label: nav.ticker, color: pos.day >= 0 ? UP : DOWN, fill: true, points: rng.points }]}
                  xLabels={rng.labels} xLabel="" yLabel="USD"
                  guides={[{ value: pos.avgCost, color: "var(--guide)", label: "Cost " + window.fmtPrice(pos.avgCost) }]}
                  markers={rng.buyIdx != null ? [{ index: rng.buyIdx, color: "#b9b4ab", label: "Buy" }] : []}
                  priceMode={true} clickable={false} />
              </div>
              <div className="mob-thesis"><window.ThesisCard pos={pos} /></div>
            </div>
          )}
        </main>

        <window.LegalLinks className="mob-legal" />
        <div className="mob-band" aria-hidden="true"><window.Wordmark /></div>
      </div>
    );
  }

  window.ArestotelesMobile = MobileApp;
})();
