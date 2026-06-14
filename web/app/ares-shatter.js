/* Arestoteles — shatter transition (window.AresShatter).

   DARK → RED entry. The Aristotle bust drops onto the LIVE portfolio (the page background
   stays put — NOT the black-wall intro). On impact, jagged cracks GROW out from the impact
   point toward the screen edges over a couple of seconds — main fissures reaching outward,
   smaller branch cracks splintering off them. The cracks are real WINDOWS: a mask cuts slits
   in the dark layer so the red portfolio (already swapped in underneath) shows through them.
   After the cracks settle for a beat, the dark surface breaks into pieces that fall away in a
   few staggered waves, revealing the red portfolio.

   AresShatter.toRed({ onSwap, onDone })
     onSwap  — flip the live app to red here (it stays hidden behind the dark pieces).
     onDone  — called after the overlay is torn down.

   Honors prefers-reduced-motion. */
(function () {
  "use strict";

  const BUST_SRC = "brand/aristotle-bust.png";
  const NS = "http://www.w3.org/2000/svg";
  let uid = 0;
  let prefersReduced = false;
  try { prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_) {}

  const el = (tag, cls, css) => { const e = document.createElement(tag); if (cls) e.className = cls; if (css) Object.assign(e.style, css); return e; };
  const svgEl = (tag, attrs) => { const e = document.createElementNS(NS, tag); if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  const rnd = (a, b) => a + Math.random() * (b - a);

  // dark-theme body backdrop (glow1 · glow2 · base), painted opaque behind every piece so the
  // falling glass keeps reading as the dark UI after html has flipped to red.
  const DARK_BACKDROP =
    "radial-gradient(72% 52% at 50% -12%, rgba(216,26,52,0.30), transparent 60%)," +
    "radial-gradient(58% 50% at 90% 120%, rgba(150,14,38,0.20), transparent 56%)," +
    "#050507";

  // a jagged polyline of `segs` points from (ix,iy) out along `ang` to length L. Measured
  // radially (so it always reaches the edge for piece coverage) but with lateral wander AND the
  // occasional sharp KINK so the edge is broken, never a clean line.
  function jaggedRay(ix, iy, ang, L, segs, jAng, jRad) {
    const pts = [[ix, iy]];
    for (let s = 1; s <= segs; s++) {
      const t = s / segs;
      const r = (s === segs) ? L : L * t + (Math.random() - 0.5) * jRad * L;
      let da = (Math.random() - 0.5) * jAng * (0.4 + t);
      if (Math.random() < 0.42) da += (Math.random() < 0.5 ? -1 : 1) * jAng * rnd(0.7, 1.5);  // sharp kink
      const a = ang + da;
      pts.push([ix + Math.cos(a) * r, iy + Math.sin(a) * r]);
    }
    return pts;
  }
  // an organic crack WALK (for branches / loose fissures): steps from the previous point with a
  // drifting heading and frequent sharp turns, gently biased back outward so it still travels.
  function crackWalk(sx, sy, ang, L, segs, jAng) {
    const pts = [[sx, sy]];
    let x = sx, y = sy, heading = ang;
    const step = L / segs;
    for (let s = 1; s <= segs; s++) {
      heading += (Math.random() - 0.5) * jAng;
      if (Math.random() < 0.36) heading += (Math.random() < 0.5 ? -1 : 1) * jAng * rnd(1.3, 2.5);
      heading += (ang - heading) * 0.16;
      const st = step * rnd(0.5, 1.5);
      x += Math.cos(heading) * st; y += Math.sin(heading) * st;
      pts.push([x, y]);
    }
    return pts;
  }
  // a jagged segment between two fixed points (for the concentric ring cracks between pieces)
  function jaggedSeg(p0, p1, n, amp) {
    const pts = [p0];
    const dx = p1[0] - p0[0], dy = p1[1] - p0[1], len = Math.hypot(dx, dy) || 1, nx = -dy / len, ny = dx / len;
    for (let s = 1; s < n; s++) { const t = s / n; const off = (Math.random() - 0.5) * amp; pts.push([p0[0] + dx * t + nx * off, p0[1] + dy * t + ny * off]); }
    pts.push(p1); return pts;
  }
  const pathD = (pts) => "M " + pts.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" L ");
  const lerpPt = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

  function toRed(opts) {
    opts = opts || {};
    const swap = opts.onSwap || function () {};
    const done = opts.onDone || function () {};

    if (prefersReduced) { swap(); setTimeout(done, 20); return; }
    if (document.querySelector(".shx-overlay")) return;

    const appEl = [".app", ".mobile-app"].map((s) => document.querySelector(s)).find((e) => e && e.offsetParent !== null) || document.querySelector(".app");
    if (!appEl) { swap(); setTimeout(done, 20); return; }

    const W = window.innerWidth, H = window.innerHeight;
    const ix = W * 0.5, iy = H * 0.46;
    const id = "shx" + (++uid);

    const overlay = el("div", "shx-overlay", { position: "fixed", inset: "0", zIndex: "9600", overflow: "hidden", perspective: "1500px", pointerEvents: "auto" });
    const stage = el("div", "shx-stage", { position: "absolute", inset: "0" });
    overlay.appendChild(stage);
    document.body.appendChild(overlay);

    // ---- bust ----
    const bustH = Math.min(H * 0.42, W * 0.72);
    const bustW = bustH * 0.785;
    const bust = el("div", "shx-bust", { position: "absolute", height: bustH + "px", width: bustW + "px", left: (ix - bustW / 2) + "px", top: "0px", transformOrigin: "center", willChange: "transform, opacity", zIndex: "8" });
    const bimg = el("img", null, { width: "100%", height: "100%", objectFit: "contain", filter: "drop-shadow(0 26px 50px rgba(0,0,0,.7))" });
    bimg.src = BUST_SRC; bimg.alt = "";
    bust.appendChild(bimg);
    stage.appendChild(bust);

    const restY = iy - bustH * 0.5;
    const fall = 780;
    bust.animate([
      { transform: `translate(0, ${(0.16 * H - bustH / 2).toFixed(1)}px) scale(1.5)`, filter: "blur(1.4px)" },
      { transform: `translate(0, ${restY.toFixed(1)}px) scale(1)`, filter: "blur(0px)" },
    ], { duration: fall, easing: "cubic-bezier(.45,.05,.6,1)", fill: "both" });

    setTimeout(() => { try { impact(); } catch (e) { swap(); if (overlay.parentNode) overlay.parentNode.removeChild(overlay); done(); } }, fall);

    function impact() {
      const snap = appEl.cloneNode(true);
      // the chart SVG is by far the heaviest subtree — strip it from the per-piece clones (the
      // chart area still falls as a panel) so building ~16 shards stays cheap and smooth.
      snap.querySelectorAll(".chart-host").forEach((h) => { h.innerHTML = ""; });
      snap.querySelectorAll("canvas").forEach((c) => c.remove());

      // ---- geometry: A jagged rays from the impact; each sector splits into inner+outer pieces
      const A = 8, SEG = 9, K = 5;
      const corners = [[0, 0], [W, 0], [W, H], [0, H]];
      let maxR = 0; corners.forEach((c) => { maxR = Math.max(maxR, Math.hypot(c[0] - ix, c[1] - iy)); });
      const L = maxR * 1.34;

      const rays = [];
      for (let i = 0; i < A; i++) {
        const ang = (Math.PI * 2 * i) / A + rnd(-0.4, 0.4) * (Math.PI / A);
        rays.push({ ang, pts: jaggedRay(ix, iy, ang, L, SEG, 0.26, 0.18) });
      }

      // crack definitions (drawn into the mask AND the glow): main rays · branches · sub-branches · loose fissures
      const cracks = [];  // { d, w, delay, dur }
      const rayDur = [], rayDelay = [];
      rays.forEach((ray, i) => {
        const dur = 920 + rnd(0, 460), delay = i * 42 + rnd(0, 80);
        rayDur[i] = dur; rayDelay[i] = delay;
        cracks.push({ d: pathD(ray.pts), w: rnd(5, 7.5), delay, dur });
      });
      let rayMax = 0; rays.forEach((_, i) => { rayMax = Math.max(rayMax, rayDelay[i] + rayDur[i]); });
      // branches peel off the main rays, sub-branches peel off those, and a few loose fissures
      // fill the field — so the whole screen reads as a dense, living crack network.
      rays.forEach((ray, i) => {
        const nb = 2 + Math.floor(Math.random() * 2);   // 2–3 branches per ray
        for (let b = 0; b < nb; b++) {
          const seg = 1 + Math.floor(Math.random() * (SEG - 1));
          const f = rnd(0.1, 0.9);
          const origin = lerpPt(ray.pts[seg], ray.pts[seg + 1] || ray.pts[seg], f);
          const side = Math.random() < 0.5 ? -1 : 1;
          const bang = ray.ang + side * rnd(0.4, 1.05);
          const blen = L * rnd(0.16, 0.44);
          const bsegs = 4 + Math.floor(Math.random() * 3);
          const bpts = crackWalk(origin[0], origin[1], bang, blen, bsegs, 0.55);
          const arriveT = (seg + f) / SEG;
          const bdelay = rayDelay[i] + arriveT * rayDur[i] + rnd(40, 150);
          const bdur = 420 + rnd(0, 300);
          cracks.push({ d: pathD(bpts), w: rnd(2.4, 4.2), delay: bdelay, dur: bdur });
          // sub-branch off the branch
          if (Math.random() < 0.75) {
            const ss = 1 + Math.floor(Math.random() * (bsegs - 1));
            const so = bpts[ss];
            const sang = bang + (Math.random() < 0.5 ? -1 : 1) * rnd(0.4, 0.95);
            const spts = crackWalk(so[0], so[1], sang, blen * rnd(0.4, 0.72), 3 + Math.floor(Math.random() * 2), 0.6);
            cracks.push({ d: pathD(spts), w: rnd(1.6, 2.8), delay: bdelay + (ss / bsegs) * bdur + rnd(30, 120), dur: 340 + rnd(0, 240) });
          }
        }
      });
      // loose hairline fissures scattered through the field for density
      for (let e = 0; e < 7; e++) {
        const a = rnd(0, Math.PI * 2);
        const r0 = maxR * rnd(0.12, 0.42);
        const spts = crackWalk(ix + Math.cos(a) * r0, iy + Math.sin(a) * r0, a, L * rnd(0.2, 0.5), 4 + Math.floor(Math.random() * 3), 0.6);
        cracks.push({ d: pathD(spts), w: rnd(1.5, 3), delay: rnd(180, rayMax * 0.85), dur: 360 + rnd(0, 260) });
      }
      // concentric ring cracks along the inner/outer piece split, so EVERY piece boundary is a
      // lit crack (the pieces that fall are exactly the cells these cracks enclose)
      for (let i = 0; i < A; i++) {
        const p0 = rays[i].pts[K], p1 = rays[(i + 1) % A].pts[K];
        const rpts = jaggedSeg(p0, p1, 4, Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * 0.16);
        cracks.push({ d: pathD(rpts), w: rnd(3.4, 5), delay: rayDelay[i] + (K / SEG) * rayDur[i] + rnd(0, 90), dur: 380 + rnd(0, 200) });
      }

      // ---- pieces (dark glass) ----
      const darkWrap = el("div", "shx-darkwrap", { position: "absolute", inset: "0", zIndex: "4" });
      darkWrap.setAttribute("data-theme", "dark");
      const pieces = [];
      function addPiece(poly, ring) {
        const cx = poly.reduce((s, p) => s + p[0], 0) / poly.length;
        const cy = poly.reduce((s, p) => s + p[1], 0) / poly.length;
        const grow = 0.8;
        const clip = poly.map((p) => {
          const dx = p[0] - cx, dy = p[1] - cy, m = Math.hypot(dx, dy) || 1;
          return `${(p[0] + dx / m * grow).toFixed(1)}px ${(p[1] + dy / m * grow).toFixed(1)}px`;
        }).join(",");
        const pc = el("div", "shx-shard", {
          position: "absolute", inset: "0", background: DARK_BACKDROP,
          clipPath: `polygon(${clip})`, WebkitClipPath: `polygon(${clip})`,
          transformOrigin: `${cx.toFixed(1)}px ${cy.toFixed(1)}px`, willChange: "transform, opacity",
          overflow: "hidden", contain: "layout paint", backfaceVisibility: "hidden",
        });
        const inner = snap.cloneNode(true);
        Object.assign(inner.style, { position: "absolute", left: "0", top: "0", width: W + "px", height: H + "px", margin: "0" });
        pc.appendChild(inner);
        darkWrap.appendChild(pc);
        pieces.push({ pc, cx, cy, ring, d: Math.hypot(cx - ix, cy - iy) });
      }
      for (let i = 0; i < A; i++) {
        const a = rays[i].pts, b = rays[(i + 1) % A].pts;
        addPiece(a.slice(0, K + 1).concat(b.slice(0, K + 1).reverse()), 0);   // inner
        addPiece(a.slice(K).concat(b.slice(K).reverse()), 1);                 // outer
      }
      stage.appendChild(darkWrap);

      // ---- red glow living UNDER the dark layer (shows through the crack slits) ----
      const glow = svgEl("svg", { class: "shx-cracks", viewBox: `0 0 ${W} ${H}` });
      Object.assign(glow.style, { position: "absolute", inset: "0", width: "100%", height: "100%", zIndex: "3", pointerEvents: "none", overflow: "visible" });
      // ---- mask that punches the cracks OUT of the dark layer (black stroke = hole) ----
      const defs = svgEl("svg", { width: "0", height: "0" });
      defs.style.position = "absolute";
      const mask = svgEl("mask", { id: id + "-m", maskUnits: "userSpaceOnUse", maskContentUnits: "userSpaceOnUse", x: "0", y: "0", width: W, height: H });
      mask.appendChild(svgEl("rect", { x: "0", y: "0", width: W, height: H, fill: "#fff" }));
      defs.appendChild(mask);
      stage.appendChild(defs);

      const animPairs = [];
      cracks.forEach((ck) => {
        const gp = svgEl("path", { d: ck.d, class: "shx-crack", "stroke-width": (ck.w * 0.55).toFixed(2) });
        glow.appendChild(gp);
        const mp = svgEl("path", { d: ck.d, fill: "none", stroke: "#000", "stroke-width": (ck.w * 1.75).toFixed(2), "stroke-linecap": "round", "stroke-linejoin": "round" });
        mask.appendChild(mp);
        animPairs.push({ gp, mp, delay: ck.delay, dur: ck.dur });
      });
      stage.appendChild(glow);
      darkWrap.style.webkitMaskImage = `url(#${id}-m)`;
      darkWrap.style.maskImage = `url(#${id}-m)`;
      darkWrap.style.webkitMask = `url(#${id}-m)`;
      darkWrap.style.mask = `url(#${id}-m)`;

      // grow every crack outward from the impact (stroke draws from the path's start point)
      let crackEnd = 0;
      animPairs.forEach(({ gp, mp, delay, dur }) => {
        crackEnd = Math.max(crackEnd, delay + dur);
        [gp, mp].forEach((p) => {
          const len = p.getTotalLength();
          p.style.strokeDasharray = len; p.style.strokeDashoffset = len;
          p.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { duration: dur, delay, easing: "cubic-bezier(.22,.62,.35,1)", fill: "both" });
        });
      });

      // swap the live app to red now (hidden behind the dark pieces; peeks through the cracks)
      swap();

      const HOLD = 420;
      const shatterStart = crackEnd + HOLD;

      // impact bloom (right at landing)
      const fl = el("div", "shx-flash", {
        position: "absolute", left: ix + "px", top: iy + "px", width: bustW * 1.5 + "px", height: bustW * 1.5 + "px",
        transform: "translate(-50%,-50%)", borderRadius: "50%", zIndex: "6", pointerEvents: "none",
        background: "radial-gradient(closest-side, rgba(255,255,255,.92), rgba(255,64,88,.6) 36%, rgba(255,40,70,0) 72%)",
      });
      stage.appendChild(fl);
      fl.animate([
        { opacity: 0, transform: "translate(-50%,-50%) scale(.4)" },
        { opacity: 1, transform: "translate(-50%,-50%) scale(1)", offset: .25 },
        { opacity: 0, transform: "translate(-50%,-50%) scale(1.9)" },
      ], { duration: 660, easing: "ease-out", fill: "both" });

      // dust + a sharp screen-shake on landing, then a smaller jolt when it shatters
      for (let i = 0; i < 8; i++) {
        const sz = rnd(bustH * 0.18, bustH * 0.44);
        const du = el("div", "shx-dust", {
          position: "absolute", left: (ix + rnd(-1, 1) * bustW * 0.5) + "px", top: (iy + rnd(-12, 6)) + "px",
          width: sz + "px", height: sz + "px", borderRadius: "50%", transform: "translate(-50%,-50%)", zIndex: "5",
          background: "radial-gradient(closest-side, rgba(78,10,20,.55), rgba(130,18,34,.14) 55%, transparent 76%)",
        });
        stage.appendChild(du);
        du.animate([
          { opacity: 0, transform: "translate(-50%,-50%) scale(.3) translateY(0)" },
          { opacity: .55, offset: .2 },
          { opacity: 0, transform: `translate(-50%,-50%) scale(1.8) translateY(-${40 + Math.random() * 60}px)` },
        ], { duration: 1100 + Math.random() * 500, easing: "cubic-bezier(.2,.6,.3,1)", fill: "both" });
      }
      const shakeKf = (amp) => { const kf = []; for (let i = 0; i <= 8; i++) { const dd = 1 - i / 8; kf.push({ transform: `translate(${rnd(-1, 1) * amp * dd}px, ${rnd(-1, 1) * amp * dd}px)` }); } kf.push({ transform: "translate(0,0)" }); return kf; };
      stage.animate(shakeKf(16), { duration: 440, easing: "ease-out", fill: "both" });
      try { appEl.animate(shakeKf(16).map((k) => ({ transform: k.transform })), { duration: 440, easing: "ease-out" }); } catch (_) {}
      setTimeout(() => { stage.animate(shakeKf(9), { duration: 360, easing: "ease-out" }); try { appEl.animate(shakeKf(9).map((k) => ({ transform: k.transform })), { duration: 360, easing: "ease-out" }); } catch (_) {} }, shatterStart);

      // At the shatter the mask is dropped, but every piece immediately backs apart so its lit
      // cracks turn into real GAPS (red showing through) — the glow lingers briefly to cover the
      // hand-off so the cracks never visually "disappear".
      setTimeout(() => { darkWrap.style.webkitMask = "none"; darkWrap.style.mask = "none"; darkWrap.style.webkitMaskImage = "none"; darkWrap.style.maskImage = "none"; }, shatterStart);
      glow.animate([{ opacity: 1, offset: 0 }, { opacity: 1, offset: 0.45 }, { opacity: 0, offset: 1 }], { duration: 560, delay: shatterStart, easing: "ease-in", fill: "both" });

      // ---- the shatter ----
      // Each piece: cover → back off so its crack-gaps open (spreading out from the impact) →
      // HOLD there, so pieces still waiting keep showing their cracks as red gaps → then fall.
      // Pieces let go in ring + angular waves a few beats apart, so the red reveal only grows.
      const SEP = 3;
      let maxEnd = 0, lastLetGo = 0;
      pieces.forEach(({ pc, cx, cy, ring, d }) => {
        const ang = Math.atan2(cy - iy, cx - ix);
        const angT = (ang + Math.PI) / (Math.PI * 2);
        const dN = Math.min(1, d / maxR);
        const openDelay = shatterStart + dN * 150 + rnd(0, 50);     // gaps crack open from the impact outward
        const GAP = 160, HOLD_AFTER = 240;
        const wave = ring * 320 + Math.floor(angT * 3) * 120 + rnd(0, 160);
        const fallRel = GAP + HOLD_AFTER + wave;                    // when (from openDelay) this piece lets go
        const dur = 920 + rnd(0, 540);
        const total = fallRel + dur;
        const sepTf = `translate(${(Math.cos(ang) * SEP).toFixed(1)}px, ${(Math.sin(ang) * SEP).toFixed(1)}px) scale(0.976) rotate(0deg)`;
        const driftX = (cx - ix) * 0.12 + rnd(-70, 70);
        const fallY = H * 0.82 + rnd(0, H * 0.5);
        const rot = rnd(-1, 1) * 74;
        pc.animate([
          { transform: "translate(0,0) scale(1) rotate(0deg)", opacity: 1, offset: 0, easing: "cubic-bezier(.25,.85,.4,1)" },
          { transform: sepTf, opacity: 1, offset: GAP / total, easing: "linear" },
          { transform: sepTf, opacity: 1, offset: fallRel / total, easing: "cubic-bezier(.5,.02,.86,.36)" },
          { transform: `translate(${driftX.toFixed(1)}px, ${fallY.toFixed(1)}px) scale(0.9) rotate(${rot.toFixed(1)}deg)`, opacity: 0, offset: 1 },
        ], { duration: total, delay: openDelay, fill: "both" });
        maxEnd = Math.max(maxEnd, openDelay + total);
        lastLetGo = Math.max(lastLetGo, openDelay + fallRel);
      });

      // the bust is the last thing standing — it crumbles away with the final pieces
      bust.animate([
        { opacity: 1, transform: `translate(0, ${restY.toFixed(1)}px) scale(1)` },
        { opacity: 0, transform: `translate(0, ${(restY + H * 0.2).toFixed(1)}px) scale(.9)` },
      ], { duration: 780, delay: lastLetGo - 120, easing: "cubic-bezier(.5,.02,.86,.36)", fill: "both" });

      const finishAt = Math.max(maxEnd, lastLetGo - 120 + 780);
      const cleanup = () => { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); done(); };
      setTimeout(() => {
        overlay.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: "ease", fill: "both" }).finished.then(cleanup).catch(cleanup);
      }, finishAt + 120);
    }
  }

  window.AresShatter = { toRed };
})();
