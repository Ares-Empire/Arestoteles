/* Arestoteles — intro module (window.ArestotelesIntro).  SELF-CONTAINED, separately iterable.

   Reuses the Aresium intro *technique* (a self-built fullscreen overlay animated with the
   Web Animations API) but is net-new motion. The Aristotle bust moves in DEPTH: it starts
   BIG and close to the camera, then falls back onto the black wall — receding, scaling down
   to its resting size as it drops to low-center. Impact triggers a screen-shake; a crater
   forms and white/light-grey cracks draw outward (SVG stroke-dashoffset) with a dust puff;
   the bust settles; the ARESTOTELES wordmark vibrates into the bottom band; crossfade to UI.

   Three treatments to choose from:
     A "impact"   — the full cinematic spec (fall · crater · cracks · dust · shake · vibrate)
     B "descent"  — restrained & premium: slow z-recession, soft ground-glow, wordmark rises
     C "fracture" — heavier: hard slam, white flash, crack network across the wall, snap-in word

   play({ variant, onDone, onReveal, onSettled, container, reducedOk })
     variant    "impact" | "descent" | "fracture"   (default "impact")
     onDone      called when the intro finishes (caller crossfades to the UI)
     container   optional element to mount inside (Intro Lab); omitted → fixed fullscreen
     reducedOk   if true, honor prefers-reduced-motion by skipping to onDone
     onSettled   fires once the big motion is over → a good moment to build the app underneath

   Smoothness (2026-10-23): the intro starts only once the bust is downloaded AND decoded and the
   fonts are ready (never without the bust; skipped if it can't load). The scene is drawn once,
   invisibly, before it moves. Only cheap properties animate per frame: no animated blur, and the
   crack halo is a wide faint stroke under each crack instead of per-path drop-shadow filters.

   Honors prefers-reduced-motion. Tunables in geometry below. */
(function () {
  "use strict";

  const BUST_SRC = "/brand/aristotle-bust.webp";
  const MAX_WAIT_MS = 6000; // give up on the intro (show the app) if the bust takes longer
  let prefersReduced = false;
  try { prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_) {}

  const VARIANTS = {
    impact:   { total: 3200, fallMs: 880, fallEase: "cubic-bezier(.45,.05,.6,1)", startScale: 2.7, startCenter: 0.33, restCenter: 0.50, shake: 16, crater: true, crackN: 30, flash: 0.20, dust: 1, wordStyle: "reveal" },
    descent:  { total: 3400, fallMs: 1500, fallEase: "cubic-bezier(.3,.0,.25,1)", startScale: 2.2, startCenter: 0.30, restCenter: 0.49, shake: 0,  crater: false, crackN: 0,  flash: 0,    dust: 0.4, wordStyle: "rise" },
    fracture: { total: 3300, fallMs: 760, fallEase: "cubic-bezier(.55,.04,.9,.7)", startScale: 3.0, startCenter: 0.34, restCenter: 0.51, shake: 26, crater: true, crackN: 42, flash: 0.85, dust: 1.5, wordStyle: "snap" },
  };

  function el(tag, cls, css) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (css) Object.assign(e.style, css);
    return e;
  }

  // build the bust DOM — real PNG, with the marble placeholder shown ONLY if it fails to load
  function buildBust() {
    const wrap = el("div", "intro-bust");
    const ph = el("div", "intro-bust-ph");
    ph.style.opacity = "0";                          // hidden unless the image errors (no card flash)
    ph.appendChild(el("div", "bust-ph-vein"));
    const cap = el("div", "bust-ph-cap"); cap.textContent = "ARISTOTLE";
    ph.appendChild(cap);
    const img = el("img", "intro-bust-img");
    img.alt = "Arestoteles";
    img.decoding = "sync"; // already downloaded + decoded by play(), so it shows on the first frame
    img.onerror = () => { img.remove(); ph.style.opacity = "1"; };
    img.src = BUST_SRC;
    wrap.appendChild(ph); wrap.appendChild(img);
    return wrap;
  }

  // jagged crack path from (cx,cy) outward at angle, length L
  function crackPath(cx, cy, ang, L, segs, jitter) {
    let d = `M ${cx.toFixed(1)} ${cy.toFixed(1)}`;
    let x = cx, y = cy;
    for (let i = 1; i <= segs; i++) {
      const t = i / segs;
      const r = L * t;
      const a = ang + (Math.random() - 0.5) * jitter;
      x = cx + Math.cos(a) * r;
      y = cy + Math.sin(a) * r;
      d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
    }
    return d;
  }

  function run(cfg, onDone, container, onReveal, onSettled) {
    const fixed = !container;
    const root = container || document.body;

    const overlay = el("div", "intro-overlay", fixed
      ? { position: "fixed", inset: "0", zIndex: "9000" }
      : { position: "absolute", inset: "0" });
    const shake = el("div", "intro-shake");
    const stage = el("div", "intro-stage");

    // measure
    const rect = root.getBoundingClientRect();
    const H = rect.height || window.innerHeight;
    const W = rect.width || window.innerWidth;
    const bustH = 0.42 * H;
    const bustW = bustH * 0.785;            // real bust aspect
    const halfH = bustH / 2;
    const cxPx = W / 2;
    const restCenterPx = cfg.restCenter * H;
    const craterCenterY = restCenterPx + halfH * 0.34;  // dent shading centred on the base of the bust
    const impactY = restCenterPx + halfH * 0.52;         // dust radiates from here
    const craterD = bustW * 3.2;                         // dented/cracked rock around the impact

    // crater — a shallow dished depression shaded darker into the rock, sitting under the bust
    let crater = null;
    if (cfg.crater) {
      crater = el("div", "intro-crater");
      Object.assign(crater.style, {
        position: "absolute", left: cxPx + "px", top: craterCenterY + "px",
        width: craterD + "px", height: craterD * 0.9 + "px", transform: "translate(-50%,-50%)",
      });
    }

    // cracks svg — a radial network of dark fissures bursting out from the bust footprint
    // (origin is an ellipse around the lower bust, so cracks emerge from its silhouette edges)
    let crackSvg = null, crackPaths = [];
    if (cfg.crater) {
      const SVGNS = "http://www.w3.org/2000/svg";
      crackSvg = document.createElementNS(SVGNS, "svg");
      crackSvg.setAttribute("class", "intro-cracks");
      crackSvg.setAttribute("viewBox", `0 0 ${W} ${H}`);

      const ox = cxPx, oy = craterCenterY;        // crack burst origin
      const rx = bustW * 0.40, ry = bustH * 0.34; // ellipse the cracks start from
      const base = bustW;                          // length scale
      const intensity = cfg.crackN || 30;

      // jagged outward walk; returns the path string + the points visited (for branching)
      function jaggedOut(sx, sy, ang, L, segs, jitter) {
        let d = `M ${sx.toFixed(1)} ${sy.toFixed(1)}`;
        let x = sx, y = sy;
        const pts = [{ x, y }];
        for (let i = 1; i <= segs; i++) {
          const t = i / segs;
          const step = (L / segs) * (0.7 + Math.random() * 0.6);
          const a = ang + (Math.random() - 0.5) * jitter * (0.5 + t);
          x += Math.cos(a) * step;
          y += Math.sin(a) * step;
          d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
          pts.push({ x, y });
        }
        return { d, pts };
      }
      function addPath(d, w) {
        // a wider faint dark stroke underneath = the halo (cheap, unlike a filter per path)
        const halo = document.createElementNS(SVGNS, "path");
        halo.setAttribute("d", d);
        halo.setAttribute("class", "intro-crack-halo");
        halo.setAttribute("stroke-width", (w + 3).toFixed(2));
        crackSvg.appendChild(halo);
        crackPaths.push(halo);
        const p = document.createElementNS(SVGNS, "path");
        p.setAttribute("d", d);
        p.setAttribute("class", "intro-crack");
        p.setAttribute("stroke-width", w.toFixed(2));
        crackSvg.appendChild(p);
        crackPaths.push(p);
      }

      for (let i = 0; i < intensity; i++) {
        const ang = (Math.PI * 2 * i) / intensity + (Math.random() - 0.5) * (Math.PI / intensity) * 1.6;
        const sx = ox + Math.cos(ang) * rx;
        const sy = oy + Math.sin(ang) * ry;
        const reach = 0.55 + Math.random() * 0.95;          // how far this finger travels
        const L = reach * base * 1.5;
        const segs = 5 + Math.floor(Math.random() * 4);
        const w = 2.4 + Math.random() * 2.0;
        const main = jaggedOut(sx, sy, ang, L, segs, 0.7);
        addPath(main.d, w);
        // 1–2 thinner branch fissures peeling off the main finger
        const nb = 1 + Math.floor(Math.random() * 2);
        for (let b = 0; b < nb; b++) {
          const k = 2 + Math.floor(Math.random() * (main.pts.length - 3));
          const bp = main.pts[k];
          const ba = ang + (Math.random() < 0.5 ? -1 : 1) * (0.35 + Math.random() * 0.55);
          const bl = L * (0.32 + Math.random() * 0.4);
          const br = jaggedOut(bp.x, bp.y, ba, bl, 3 + Math.floor(Math.random() * 3), 0.85);
          addPath(br.d, Math.max(0.8, w * (0.42 + Math.random() * 0.22)));
        }
      }
    }

    // dust puffs
    const dusts = [];
    if (cfg.dust > 0) {
      const dn = Math.round(7 * cfg.dust);
      for (let i = 0; i < dn; i++) {
        const d = el("div", "intro-dust", {
          left: (cxPx + (Math.random() - 0.5) * bustH * 0.9) + "px",
          top: (impactY - Math.random() * 20) + "px",
          width: (bustH * (0.18 + Math.random() * 0.3)) + "px",
          height: (bustH * (0.18 + Math.random() * 0.3)) + "px",
        });
        dusts.push(d);
      }
    }

    // ground glow (descent) — soft even ring where it settles
    let glow = null;
    if (!cfg.crater) {
      glow = el("div", "intro-glow", {
        left: cxPx + "px", top: craterCenterY + "px",
        width: craterD * 1.15 + "px", height: craterD * 1.15 + "px",
      });
    }

    // flash
    let flash = null;
    if (cfg.flash > 0) flash = el("div", "intro-flash");

    // bust
    const bust = buildBust();
    bust.style.height = bustH + "px";
    bust.style.left = cxPx + "px";
    bust.style.top = "0px";

    // wordmark band
    const band = el("div", "intro-band");
    const word = el("div", "ares-word intro-word");
    "ARESTOTELES".split("").forEach((ch) => { const s = el("span"); s.textContent = ch; word.appendChild(s); });
    band.appendChild(word);

    // z-order: crater · glow · cracks sit on the WALL (behind the bust); the bust lands
    // into them; dust + flash are in FRONT.
    if (crater) stage.appendChild(crater);
    if (glow) stage.appendChild(glow);
    if (crackSvg) stage.appendChild(crackSvg);
    stage.appendChild(bust);
    dusts.forEach((d) => stage.appendChild(d));
    if (flash) stage.appendChild(flash);
    stage.appendChild(band);
    shake.appendChild(stage);
    overlay.appendChild(shake);

    // ---- geometry helpers (transform-origin center; translateY positions box center) ----
    const tY = (centerFrac) => (centerFrac * H - halfH);
    const tf = (centerFrac, s) => `translate(-50%, ${tY(centerFrac).toFixed(1)}px) scale(${s})`;

    // Warm-up: put everything on screen (practically invisible) for two frames before anything
    // moves, so the browser draws the big bust, crater and dust once up front instead of in the
    // middle of the fall or the impact.
    bust.style.transform = tf(cfg.startCenter, cfg.startScale);
    // measure the cracks now too, so the first moving frame has no setup work left
    const crackLens = [];
    for (let i = 0; i < crackPaths.length; i += 2) crackLens.push(crackPaths[i].getTotalLength());
    stage.style.opacity = "0.001";
    stage.style.willChange = "opacity"; // stays its own layer, so ending the warm-up doesn't redraw it
    root.appendChild(overlay);
    requestAnimationFrame(() => requestAnimationFrame(() => { stage.style.opacity = ""; animate(); }));

    function animate() {

    const anims = [];
    const fall = cfg.fallMs;

    // 1) bust falls in depth
    anims.push(bust.animate([
      { transform: tf(cfg.startCenter, cfg.startScale) },
      { transform: tf(cfg.restCenter, 1), offset: 1 },
    ], { duration: fall, easing: cfg.fallEase, fill: "both" }));

    // settle micro-bounce after impact
    setTimeout(() => {
      bust.animate([
        { transform: tf(cfg.restCenter, 1) },
        { transform: `translate(-50%, ${(tY(cfg.restCenter) + 6).toFixed(1)}px) scale(1.012, 0.985)`, offset: 0.35 },
        { transform: tf(cfg.restCenter, 1) },
      ], { duration: 420, easing: "cubic-bezier(.34,1.56,.5,1)", fill: "both" });
    }, fall);

    // 2) screen shake
    if (cfg.shake > 0) {
      setTimeout(() => {
        const S = cfg.shake;
        const kf = [];
        const steps = 9;
        for (let i = 0; i <= steps; i++) {
          const d = (1 - i / steps);
          kf.push({ transform: `translate(${(Math.random() - 0.5) * 2 * S * d}px, ${(Math.random() - 0.5) * 2 * S * d}px)` });
        }
        kf.push({ transform: "translate(0,0)" });
        shake.animate(kf, { duration: 460, easing: "ease-out", fill: "both" });
      }, fall);
    }

    // 3) crater + glow
    if (crater) {
      // cracks the rock open sharply on impact, then a tiny settle
      crater.animate([
        { opacity: 0, transform: "translate(-50%,-50%) scale(0.78)" },
        { opacity: 1, transform: "translate(-50%,-50%) scale(1.05)", offset: 0.35 },
        { opacity: 1, transform: "translate(-50%,-50%) scale(0.99)", offset: 0.7 },
        { opacity: 1, transform: "translate(-50%,-50%) scale(1)" },
      ], { duration: 620, delay: fall, easing: "cubic-bezier(.18,.9,.3,1)", fill: "both" });
    }
    if (glow) {
      glow.animate([
        { opacity: 0, transform: "translate(-50%,-50%) scale(0.4)" },
        { opacity: 1, transform: "translate(-50%,-50%) scale(1)" },
      ], { duration: 900, delay: fall * 0.75, easing: "ease-out", fill: "both" });
    }

    // 4) cracks draw outward
    for (let i = 0; i < crackPaths.length; i += 2) {
      const len = crackLens[i / 2];
      const timing = { duration: 620 + Math.random() * 260, delay: fall + 20 + (i / 2) * 12, easing: "cubic-bezier(.2,.7,.2,1)", fill: "both" };
      [crackPaths[i], crackPaths[i + 1]].forEach((p) => {
        p.style.strokeDasharray = len; p.style.strokeDashoffset = len;
        p.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], timing);
      });
    }

    // 5) dust puffs
    dusts.forEach((d, i) => {
      d.animate([
        { opacity: 0, transform: "translate(-50%,-50%) scale(0.3) translateY(0)" },
        { opacity: 0.5, offset: 0.2 },
        { opacity: 0, transform: `translate(-50%,-50%) scale(1.8) translateY(-${40 + Math.random() * 60}px)` },
      ], { duration: 1100 + Math.random() * 500, delay: fall - 30, easing: "cubic-bezier(.2,.6,.3,1)", fill: "both" });
    });

    // 6) flash
    if (flash) {
      flash.animate([{ opacity: 0 }, { opacity: cfg.flash, offset: 0.12 }, { opacity: 0 }],
        { duration: 420, delay: fall - 20, easing: "ease-out", fill: "both" });
    }

    // 7) wordmark in
    const wordIn = fall + (cfg.crater ? 360 : 220);
    if (cfg.wordStyle === "reveal") {
      // all letters appear together — a clean fade-in
      const spans = word.querySelectorAll("span");
      band.style.opacity = "1";
      spans.forEach((s) => {
        s.animate([
          { opacity: 0 },
          { opacity: 1 },
        ], { duration: 560, delay: wordIn, easing: "cubic-bezier(.3,.7,.3,1)", fill: "both" });
      });
    } else if (cfg.wordStyle === "vibrate" || cfg.wordStyle === "snap") {
      const spans = word.querySelectorAll("span");
      band.style.opacity = "1";
      spans.forEach((s, i) => {
        const delay = wordIn + (cfg.wordStyle === "snap" ? i * 38 : i * 14);
        s.animate([
          { opacity: 0, transform: "translateY(26px) scale(.9)" },
          { opacity: 1, transform: "translateY(-2px)", offset: 0.6 },
          { opacity: 1, transform: "translateY(2px)", offset: 0.78 },
          { opacity: 1, transform: "translateY(0) scale(1)" },
        ], { duration: cfg.wordStyle === "snap" ? 360 : 520, delay, easing: "cubic-bezier(.3,1.4,.5,1)", fill: "both" });
      });
    } else {
      // rise: whole word fades + rises gently
      word.animate([
        { opacity: 0, transform: "translateY(34px)" },
        { opacity: 1, transform: "translateY(0)" },
      ], { duration: 760, delay: wordIn, easing: "cubic-bezier(.22,.7,.25,1)", fill: "both" });
      band.style.opacity = "1";
    }

    // 8) finish → crossfade out
    // jump any animation that hasn't finished yet (e.g. a background tab) to its end state;
    // normally all have finished by now, so this costs nothing (no restyle, no redraw)
    const forceFinal = () => {
      [bust, shake, crater, glow, flash, word, ...dusts, ...crackPaths, ...word.querySelectorAll("span")]
        .forEach((n) => { if (n) n.getAnimations().forEach((a) => { if (a.playState !== "finished") a.finish(); }); });
      band.style.opacity = "1";
    };

    // the big motion is over (impact, cracks, word) → let the app build AND draw underneath the
    // still-opaque overlay now, so the crossfade only has to blend two finished pictures
    if (fixed) setTimeout(() => { if (onSettled) { try { onSettled(); } catch (_) {} } }, Math.min(fall + 1300, cfg.total - 900));

    const cleanup = () => { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); if (onDone) onDone(); };
    setTimeout(() => {
      forceFinal();
      // reveal the live app *under* the still-opaque overlay, so the crossfade dissolves
      // the intro directly into the UI (no flash, no pop).
      if (onReveal) { try { onReveal(); } catch (_) {} }
      if (fixed) {
        overlay.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 520, easing: "ease", fill: "both" })
          .finished.then(cleanup).catch(cleanup);
      } else {
        // in the lab, hold the final "aftermath" frame (don't remove) and signal done
        if (onDone) onDone();
      }
    }, cfg.total - (fixed ? 520 : 0));
    } // animate()
  }

  window.ArestotelesIntro = {
    variants: Object.keys(VARIANTS),
    play(opts) {
      opts = opts || {};
      const cfg = VARIANTS[opts.variant] || VARIANTS.impact;
      if (opts.reducedOk && prefersReduced) { if (opts.onReveal) opts.onReveal(); if (opts.onDone) opts.onDone(); return; }
      // wait for the downloaded + decoded bust and the fonts, so the first frame already shows them
      let finished = false;
      const skip = () => { // no bust → no intro: show the app right away
        if (finished) return; finished = true;
        if (opts.onSettled) opts.onSettled(); if (opts.onReveal) opts.onReveal(); if (opts.onDone) opts.onDone();
      };
      const timer = setTimeout(skip, MAX_WAIT_MS);
      const im = new Image(); im.src = BUST_SRC;
      const fonts = document.fonts ? document.fonts.ready.catch(() => {}) : Promise.resolve();
      Promise.all([im.decode(), fonts]).then(() => {
        if (finished) return; finished = true; clearTimeout(timer);
        requestAnimationFrame(() => run(cfg, opts.onDone, opts.container || null, opts.onReveal, opts.onSettled));
      }, () => { clearTimeout(timer); skip(); });
    },
  };
})();
