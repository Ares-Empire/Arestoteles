/* Arestoteles — AnimatedChart (adapted from Aresium).

   Same SVG line/area chart whose lines morph between datasets via rAF interpolation
   in pixel space, so switching range tabs / drilling between screens feels like ONE
   chart breathing into a new form. Painted straight onto the wall — no card.

   Arestoteles additions over the Aresium original:
     • USD axis + tooltip formatting (with optional per-chart formatter)
     • guides[]  — horizontal dashed reference lines (e.g. dashed cost-basis at avg entry)
     • markers[] — vertical markers at a data index (e.g. the buy-date flag)
*/
const { useRef, useState, useEffect, useLayoutEffect, useCallback } = React;

const RES = 80;
const DUR = 760;
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const hexToRgb = (c) => {
  if (Array.isArray(c)) return c.slice();
  let h = String(c).replace("#", "");
  if (h.length === 3) h = h.split("").map((x) => x + x).join("");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
};
const rgbStr = (a) => `rgb(${a[0] | 0},${a[1] | 0},${a[2] | 0})`;
const lerpRgb = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

function lucideSvg(name) {
  const lib = window.lucide && window.lucide.icons;
  const node = lib && (lib[name] || lib.Circle);
  if (!node) return "";
  const children = node[2] || [];
  const inner = children.map(([tag, attrs]) =>
    "<" + tag + " " + Object.entries(attrs).map(([k, v]) => k + '="' + v + '"').join(" ") + "></" + tag + ">"
  ).join("");
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>";
}
window.lucideSvg = lucideSvg;

function useSize(ref) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    let iv = null;
    const measure = () => {
      const w = el.clientWidth, h = el.clientHeight;
      setSize((s) => (s.w !== w || s.h !== h ? { w, h } : s));
      if (w > 0 && h > 0 && iv) { clearInterval(iv); iv = null; }
    };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    let tries = 0;
    iv = setInterval(() => { measure(); if (++tries > 60) { clearInterval(iv); iv = null; } }, 100);
    return () => { ro.disconnect(); if (iv) clearInterval(iv); };
  }, [ref]);
  return size;
}

// $ axis tick: compact for large NAV ($100k), exact-ish for prices
const fmtAxis = (v) => {
  const a = Math.abs(v);
  if (a >= 1000) return "$" + (v / 1000).toFixed(a >= 100000 ? 0 : a >= 10000 ? 0 : 1) + "k";
  return "$" + (a >= 100 ? Math.round(v) : v.toFixed(0));
};
const fmtFull = (v) => "$" + v.toLocaleString("en-US", { maximumFractionDigits: 0 });
const fmtPrice = (v) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function niceMax(v) {
  if (v <= 0) return 10;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}

function AnimatedChart(props) {
  const { series, xLabels, xLabel, yLabel, animKey, clickable, onIndexClick, theme,
          guides = [], markers = [], priceMode = false, padBottom = false } = props;
  const wrapRef = useRef(null);
  const { w, h } = useSize(wrapRef);
  const displayRef = useRef({});
  const rafRef = useRef(0);
  const [, force] = useState(0);
  const [settle, setSettle] = useState(1);
  const [hover, setHover] = useState(null);

  const tipFmt = priceMode ? fmtPrice : fmtFull;

  const M = { l: 56, r: 18, t: 18, b: 44 };
  const plotW = Math.max(10, w - M.l - M.r);
  const plotH = Math.max(10, h - M.t - M.b);
  const x0 = M.l, y0 = M.t + plotH;

  // scales (shared y across all series)
  let yMin = Infinity, yMaxRaw = -Infinity;
  series.forEach((s) => s.points.forEach((v) => { yMaxRaw = Math.max(yMaxRaw, v); yMin = Math.min(yMin, v); }));
  guides.forEach((g) => { yMaxRaw = Math.max(yMaxRaw, g.value); yMin = Math.min(yMin, g.value); });
  if (!isFinite(yMin)) { yMin = 0; yMaxRaw = 10; }
  const span = (yMaxRaw - yMin) || yMaxRaw || 10;
  // price charts: pad a touch around the data instead of zeroing the baseline
  let lo, hi;
  if (priceMode) {
    lo = yMin - span * 0.12; hi = yMaxRaw + span * 0.12;
    if (lo < 0) lo = 0;
  } else {
    lo = yMin < 0 ? -niceMax(-yMin * 1.1) : 0;
    hi = niceMax(yMaxRaw * 1.08) || 10;
  }
  const yMaxV = hi, yMinV = lo;
  const mapY = (v) => y0 - ((v - yMinV) / (yMaxV - yMinV)) * plotH;
  const xAt = (i, n) => (n <= 1 ? x0 + plotW / 2 : x0 + (i / (n - 1)) * plotW);
  const sampleX = (f) => x0 + f * plotW;

  const buildTarget = useCallback((s) => {
    const n = s.points.length;
    const px = s.points.map((v, i) => ({ x: xAt(i, n), y: mapY(v) }));
    const out = new Float64Array(RES);
    for (let k = 0; k < RES; k++) {
      const sx = sampleX(k / (RES - 1));
      if (n === 1) { out[k] = px[0].y; continue; }
      let j = 0;
      while (j < px.length - 2 && px[j + 1].x < sx) j++;
      const a = px[j], b = px[j + 1];
      const t = b.x === a.x ? 0 : (sx - a.x) / (b.x - a.x);
      out[k] = a.y + (b.y - a.y) * Math.max(0, Math.min(1, t));
    }
    return out;
  }, [w, h, yMaxV, yMinV]);

  useEffect(() => {
    if (w === 0) return;
    cancelAnimationFrame(rafRef.current);
    const baseline = mapY(Math.max(yMinV, Math.min(yMaxV, priceMode ? yMinV : 0)));
    const byKey = {}; series.forEach((s) => (byKey[s.key] = s));
    const keys = Array.from(new Set([...Object.keys(displayRef.current), ...series.map((s) => s.key)]));
    const starts = {}, targets = {};
    keys.forEach((key) => {
      const cur = displayRef.current[key];
      const s = byKey[key];
      if (s) {
        const tc = hexToRgb(s.color);
        starts[key] = cur
          ? { y: Float64Array.from(cur.y), color: cur.color.slice(), op: cur.op }
          : { y: new Float64Array(RES).fill(baseline), color: tc.slice(), op: 0 };
        targets[key] = { y: buildTarget(s), color: tc, op: 1, fill: !!s.fill, label: s.label, alive: true };
      } else {
        starts[key] = { y: Float64Array.from(cur.y), color: cur.color.slice(), op: cur.op };
        targets[key] = { y: Float64Array.from(cur.y), color: cur.color.slice(), op: 0, fill: cur.fill, label: cur.label, alive: false };
      }
    });
    const apply = (e) => {
      keys.forEach((key) => {
        const a = starts[key], b = targets[key];
        const y = new Float64Array(RES);
        for (let k = 0; k < RES; k++) y[k] = a.y[k] + (b.y[k] - a.y[k]) * e;
        displayRef.current[key] = { y, color: lerpRgb(a.color, b.color, e), op: a.op + (b.op - a.op) * e, fill: b.fill, label: b.label };
      });
    };
    const finish = () => { keys.forEach((key) => { if (!targets[key].alive) delete displayRef.current[key]; }); };

    const t0 = performance.now();
    setSettle(0);
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / DUR);
      apply(easeInOut(p));
      setSettle(easeInOut(p));
      force((x) => x + 1);
      if (p < 1) rafRef.current = requestAnimationFrame(tick); else finish();
    };
    rafRef.current = requestAnimationFrame(tick);
    const finalTimer = setTimeout(() => { apply(1); finish(); setSettle(1); force((x) => x + 1); }, DUR + 90);
    return () => { cancelAnimationFrame(rafRef.current); clearTimeout(finalTimer); };
    // eslint-disable-next-line
  }, [animKey, w, h]);

  if (w === 0 || h === 0) return <div ref={wrapRef} className="chart-canvas" />;

  const byKey = {}; series.forEach((s) => (byKey[s.key] = s));
  const ysFor = (key) => {
    const d = displayRef.current[key];
    if (d) return d.y;
    const s = byKey[key]; return s ? buildTarget(s) : null;
  };
  const pathFor = (key) => {
    const a = ysFor(key); if (!a) return "";
    let d = "";
    for (let k = 0; k < RES; k++) d += (k === 0 ? "M" : "L") + sampleX(k / (RES - 1)).toFixed(1) + " " + a[k].toFixed(1);
    return d;
  };
  const areaFor = (key) => pathFor(key) + ` L ${(x0 + plotW).toFixed(1)} ${y0} L ${x0.toFixed(1)} ${y0} Z`;
  const styleFor = (key) => {
    const d = displayRef.current[key];
    if (d) return { color: rgbStr(d.color), op: d.op, fill: d.fill };
    const s = byKey[key]; return { color: s.color, op: 1, fill: !!s.fill };
  };
  const yAt = (key, i, n2) => {
    const a = ysFor(key); if (!a) return mapY(byKey[key].points[i]);
    const f = n2 <= 1 ? 0.5 : i / (n2 - 1);
    return a[Math.round(f * (RES - 1))];
  };
  const dKeys = Object.keys(displayRef.current);
  const renderKeys = dKeys.length ? dKeys : series.map((s) => s.key);

  const ticks = 4;
  const gridVals = [];
  for (let i = 0; i <= ticks; i++) gridVals.push(yMinV + ((yMaxV - yMinV) * i) / ticks);

  const n = xLabels.length;
  let tickIdx = [];
  if (n <= 12) tickIdx = xLabels.map((_, i) => i);
  else {
    const stepN = Math.ceil(n / 7);
    for (let i = 0; i < n; i += stepN) tickIdx.push(i);
    if (tickIdx[tickIdx.length - 1] !== n - 1) tickIdx.push(n - 1);
  }

  const onMove = (e) => {
    const rect = wrapRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const f = Math.max(0, Math.min(1, (mx - x0) / plotW));
    setHover(Math.round(f * (n - 1)));
  };

  const hoverX = hover != null ? xAt(hover, n) : 0;

  return (
    <div ref={wrapRef} className="chart-canvas" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg width={w} height={h} style={{ display: "block", overflow: "visible" }}>
        <defs>
          {renderKeys.map((key) => {
            const st = styleFor(key);
            return (
              <linearGradient key={key} id={`grad-${key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={st.color} stopOpacity={(st.fill ? 0.34 : 0.18) * st.op} />
                <stop offset="100%" stopColor={st.color} stopOpacity="0" />
              </linearGradient>
            );
          })}
        </defs>

        {/* y grid + labels */}
        {gridVals.map((gv, i) => {
          const gy = mapY(gv);
          return (
            <g key={i}>
              <line x1={x0} y1={gy} x2={x0 + plotW} y2={gy} stroke="var(--grid)" strokeWidth="1" />
              <text x={x0 - 10} y={gy + 4} textAnchor="end" className="axis-lbl">{fmtAxis(gv)}</text>
            </g>
          );
        })}

        {/* dashed guides (e.g. cost-basis at avg entry) */}
        {guides.map((g, gi) => {
          const gy = mapY(g.value);
          return (
            <g key={"guide" + gi} opacity={settle}>
              <line x1={x0} y1={gy} x2={x0 + plotW} y2={gy} stroke={g.color || "var(--guide)"} strokeWidth="1.3" strokeDasharray="5 5" opacity="0.85" />
              {g.label && (
                <g>
                  <rect x={x0 + plotW - 96} y={gy - 19} width="92" height="16" rx="4" fill="var(--card-2)" stroke="var(--line-soft)" />
                  <text x={x0 + plotW - 50} y={gy - 7} textAnchor="middle" className="guide-lbl" fill={g.color || "var(--ink-2)"}>{g.label}</text>
                </g>
              )}
            </g>
          );
        })}

        {/* vertical markers (e.g. buy-date flag) */}
        {markers.map((mk, mi) => {
          const mxp = xAt(mk.index, n);
          return (
            <g key={"mk" + mi} opacity={settle}>
              <line x1={mxp} y1={M.t} x2={mxp} y2={y0} stroke={mk.color || "var(--guide)"} strokeWidth="1.2" strokeDasharray="2 4" opacity="0.75" />
              <circle cx={mxp} cy={M.t + 1} r="3.4" fill={mk.color || "var(--ink-2)"} />
              {mk.label && <text x={mxp + 6} y={M.t + 5} className="guide-lbl" fill={mk.color || "var(--ink-2)"}>{mk.label}</text>}
            </g>
          );
        })}

        {/* hover guide */}
        {hover != null && (
          <line x1={hoverX} y1={M.t} x2={hoverX} y2={y0} stroke="var(--guide)" strokeWidth="1" strokeDasharray="3 4" />
        )}

        {/* x labels */}
        {tickIdx.map((i) => (
          <text key={i} x={xAt(i, n)} y={y0 + 18} textAnchor="middle" className="axis-lbl">{xLabels[i]}</text>
        ))}

        {/* clickable hit areas */}
        {clickable && xLabels.map((_, i) => {
          const cx = xAt(i, n);
          const half = plotW / Math.max(1, n - 1) / 2 || plotW / 2;
          return (
            <rect key={i} x={cx - (i === 0 ? 0 : half)} y={M.t}
              width={i === 0 || i === n - 1 ? half + 4 : half * 2} height={plotH}
              fill="transparent" style={{ cursor: "pointer" }}
              onClick={() => onIndexClick && onIndexClick(i)} />
          );
        })}

        {renderKeys.map((key) => (
          <path key={key + "-area"} d={areaFor(key)} fill={`url(#grad-${key})`} stroke="none" />
        ))}
        {renderKeys.map((key) => {
          const st = styleFor(key);
          return (
            <path key={key + "-line"} d={pathFor(key)} fill="none" stroke={st.color} opacity={st.op}
              strokeWidth="2.6" strokeLinejoin="round" strokeLinecap="round"
              style={{ filter: `drop-shadow(0 0 5px ${st.color})`, opacity: st.op }} />
          );
        })}

        {/* data dots — only when few points and not a filled area */}
        {series.filter((s) => !s.fill && s.points.length <= 16).map((s) =>
          s.points.map((v, i) => (
            <circle key={s.key + i} cx={xAt(i, n)} cy={yAt(s.key, i, n)} r={4}
              fill={s.color} opacity={settle}
              style={{ filter: `drop-shadow(0 0 4px ${s.color})` }} />
          ))
        )}

        {/* hover markers */}
        {hover != null && series.map((s) => {
          const cy = mapY(s.points[hover]);
          return <circle key={s.key} cx={hoverX} cy={cy} r="4.5" fill={s.color} stroke="var(--card)" strokeWidth="2" />;
        })}

        <text x={x0 + plotW / 2} y={y0 + 36} textAnchor="middle" className="axis-title">{xLabel}</text>
        <text x={x0 - 48} y={M.t - 6} textAnchor="start" className="axis-title">{yLabel}</text>
      </svg>

      {hover != null && (
        <div className="chart-tip" style={{ left: Math.min(Math.max(hoverX, 78), w - 78), top: M.t + 4 }}>
          <div className="chart-tip-x">{xLabels[hover]}</div>
          {series.map((s) => (
            <div key={s.key} className="chart-tip-row">
              <span className="dot" style={{ background: s.color }} />
              <span className="chart-tip-name">{s.label}</span>
              <span className="chart-tip-val">{tipFmt(s.points[hover])}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

window.AnimatedChart = AnimatedChart;
window.fmtFull = fmtFull;
window.fmtPrice = fmtPrice;
