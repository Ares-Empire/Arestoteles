/* Arestoteles — shared pieces: Sparkline, PositionsList + empty state, ConvictionBadge,
   RangeTabs, StatRow, and the AI ThesisCard (full + pending). Exposed on window for the
   other Babel scripts (which share one global lexical scope). */
(function () {
  const { useState } = React;
  const UP = "#34E27A", DOWN = "#FF2D4B";

  // ---- mini sparkline (no axes) ----
  function Sparkline({ points, w = 66, h = 26, up }) {
    if (!points || points.length < 2) return <svg width={w} height={h} />;
    let lo = Infinity, hi = -Infinity;
    points.forEach((v) => { lo = Math.min(lo, v); hi = Math.max(hi, v); });
    const span = (hi - lo) || 1;
    const color = up ? UP : DOWN;
    const X = (i) => (i / (points.length - 1)) * (w - 2) + 1;
    const Y = (v) => h - 3 - ((v - lo) / span) * (h - 6);
    let d = "";
    points.forEach((v, i) => { d += (i === 0 ? "M" : "L") + X(i).toFixed(1) + " " + Y(v).toFixed(1); });
    const area = d + ` L ${X(points.length - 1).toFixed(1)} ${h} L ${X(0).toFixed(1)} ${h} Z`;
    const gid = "sg" + Math.round(points[0] * 1000) + (up ? "u" : "d");
    return (
      <svg className="spark" width={w} height={h} style={{ display: "block" }}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gid})`} />
        <path d={d} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    );
  }

  function ConvictionBadge({ level, small }) {
    const map = { High: "high", Medium: "med", Low: "low" };
    const cls = map[level] || "med";
    return <span className={"conv-badge conv-" + cls + (small ? " sm" : "")}>{small ? "" : "Conviction "}{level}</span>;
  }

  // ---- live watchlist (real quotes, NOT held) — shown in the empty side-card ----
  function WatchList({ quotes, asOf, onOpen }) {
    return (
      <div className="watch">
        <div className="watch-note">
          <span className="watch-mark"><window.Bust size={30} /></span>
          <div className="watch-note-t">
            <div className="watch-note-h">No positions yet · 100% cash</div>
            <div className="watch-note-p">Paper book, awaiting the brain's first trade. Below — the sector watchlist, <b>live</b> and <b>not held</b>.</div>
          </div>
        </div>
        <div className="watch-sub-row">
          <span>Live market · semis &amp; AI infra</span>
          <span className="watch-asof">{asOf || "—"}</span>
        </div>
        <div className="pos-list watch-list">
          {quotes.map((q) => {
            const up = (q.day || 0) >= 0;
            const spark = q.spark && q.spark.length > 1 ? q.spark : [q.price, q.price];
            return (
              <button key={q.ticker} className="pos-row watch-row" onClick={() => onOpen && onOpen(q.ticker)}>
                <div className="pos-main">
                  <div className="pos-id">
                    <span className="pos-ticker">{q.ticker}</span>
                    <span className="pos-name">{q.name}</span>
                  </div>
                </div>
                <div className="pos-spark"><Sparkline points={spark} up={spark[spark.length - 1] >= spark[0]} /></div>
                <div className="pos-num">
                  <span className="pos-price">{window.fmtPrice(q.price)}</span>
                  <span className={"pos-day " + (up ? "up" : "down")}>{window.fmtPct(q.day || 0)}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  // ---- positions list (glass side-card body) ----
  function PositionsList({ positions, onOpen, onWatch, watch }) {
    if (!positions.length) {
      // if a live watchlist feed is present, show real quotes instead of the bare empty card
      if (watch && watch.quotes && watch.quotes.length) {
        return <WatchList quotes={watch.quotes} asOf={watch.asOfLabel} onOpen={onWatch} />;
      }
      return (
        <div className="pos-empty">
          <div className="pos-empty-mark"><window.Bust size={46} /></div>
          <div className="pos-empty-h">No positions yet</div>
          <div className="pos-empty-p">The book is 100% cash in paper mode. Arestoteles will open positions here once the brain starts trading.</div>
          <div className="pos-empty-chip"><span className="dot-live paper" /> Paper · awaiting first trade</div>
        </div>
      );
    }
    return (
      <div className="pos-list">
        <div className="pos-head-row">
          <span>Position</span><span className="pos-h-trend">30d</span><span className="pos-h-right">Last · Day</span>
        </div>
        {positions.map((p) => {
          const up = p.day >= 0;
          return (
            <button key={p.ticker} className="pos-row" onClick={() => onOpen(p.ticker)}>
              <div className="pos-main">
                <div className="pos-id">
                  <span className="pos-ticker">{p.ticker}</span>
                  <span className="pos-name">{p.name}</span>
                </div>
                <div className="pos-weight">
                  <span className="pos-weight-bar"><span className="pos-weight-fill" style={{ width: Math.min(100, p.weight) + "%" }} /></span>
                  <span className="pos-weight-n">{p.weight.toFixed(1)}%</span>
                </div>
              </div>
              <div className="pos-spark"><Sparkline points={p.spark} up={p.spark[p.spark.length - 1] >= p.spark[0]} /></div>
              <div className="pos-num">
                <span className="pos-price">{window.fmtPrice(p.price)}</span>
                <span className={"pos-day " + (up ? "up" : "down")}>{window.fmtPct(p.day)}</span>
              </div>
            </button>
          );
        })}
      </div>
    );
  }

  // ---- range tabs (segmented control) ----
  function RangeTabs({ ranges, value, onChange }) {
    return (
      <div className="rangetabs" role="tablist">
        {ranges.map((r) => (
          <button key={r} role="tab" aria-selected={value === r}
            className={"rangetab" + (value === r ? " on" : "")} onClick={() => onChange(r)}>
            {r === "Buy" ? "Since buy" : r}
          </button>
        ))}
      </div>
    );
  }

  // ---- AI thesis side-card ----
  function ThesisCard({ pos }) {
    const t = pos && pos.thesis;
    if (!t) {
      return (
        <div className="thesis">
          <div className="thesis-head">
            <span className="thesis-kicker">AI Thesis</span>
          </div>
          <div className="thesis-pending">
            <div className="thesis-pending-ic" dangerouslySetInnerHTML={{ __html: window.lucideSvg("FileClock") }} />
            <div className="thesis-pending-h">Thesis pending</div>
            <div className="thesis-pending-p">The reasoning record for {pos ? pos.ticker : "this position"} — claim, conviction, falsifiers and planned exit — populates here once the brain logs its rationale. <span className="thesis-phase">Phase 2+</span></div>
          </div>
        </div>
      );
    }
    const pct = Math.min(100, (t.dayN / t.horizonDays) * 100);
    return (
      <div className="thesis">
        <div className="thesis-head">
          <span className="thesis-kicker">AI Thesis</span>
          <ConvictionBadge level={t.conviction} />
        </div>
        <div className="thesis-body">
          <div className="thesis-claim">“{t.claim}”</div>
          <div className="thesis-reason">{t.reason}</div>

          <div className="thesis-block">
            <div className="thesis-block-h">Horizon</div>
            <div className="thesis-horizon">
              <div className="thesis-horizon-bar"><span style={{ width: pct + "%" }} /></div>
              <div className="thesis-horizon-lbl">Day <b>{t.dayN}</b> of {t.horizonDays}</div>
            </div>
          </div>

          <div className="thesis-block">
            <div className="thesis-block-h">Falsifiers</div>
            <ul className="thesis-fals">
              {t.falsifiers.map((f, i) => (
                <li key={i} className={f.done ? "tripped" : ""}>
                  <span className="fals-box">{f.done
                    ? <svg viewBox="0 0 16 16" width="12" height="12"><path d="M3 8.5 L6.5 12 L13 4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    : null}</span>
                  <span className="fals-t">{f.t}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="thesis-block">
            <div className="thesis-block-h">Planned exit</div>
            <div className="thesis-exit">{t.exit}</div>
          </div>

          <div className="thesis-block">
            <div className="thesis-block-h">Citations</div>
            <div className="thesis-cites">
              {t.citations.map((c, i) => (
                <a key={i} href={c.href} className="thesis-cite" onClick={(e) => e.preventDefault()}>
                  <span className="thesis-cite-ic" dangerouslySetInnerHTML={{ __html: window.lucideSvg("Link") }} />
                  {c.t}
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  Object.assign(window, { Sparkline, PositionsList, ConvictionBadge, RangeTabs, ThesisCard });
})();
