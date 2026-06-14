/* Arestoteles — brand marks (window.Bust, window.Wordmark).

   The brand mark is the Aristotle marble bust. The real artwork isn't in the project
   yet, so Bust renders a premium marble-toned placeholder AND probes for the real file
   at brand/aristotle-bust.png — the instant that file exists it swaps in automatically,
   everywhere (header mark, intro hero, mobile), with no code change.

   Wordmark renders the ARESTOTELES letters for the bottom band / intro overlay. */
(function () {
  const { useState } = React;

  const BUST_SRC = "brand/aristotle-bust.png";

  // marble placeholder: layered stone gradients + faint veining + carved bevel
  function MarblePlaceholder({ label }) {
    return (
      <div className="bust-ph" aria-hidden="true">
        <div className="bust-ph-vein" />
        {label && <div className="bust-ph-cap">{label}</div>}
      </div>
    );
  }

  function Bust({ size = 30, hero = false, label = null }) {
    const [state, setState] = useState("probe"); // probe → real | ph
    const style = hero
      ? { width: "100%", height: "100%" }
      : { width: size, height: Math.round(size * 1.27) };
    return (
      <div className={"bust" + (hero ? " bust-hero" : "")} style={style}>
        {state !== "real" && <img
            className="bust-img"
            src={BUST_SRC}
            alt="Arestoteles"
            style={{ opacity: 0 }}
            onLoad={() => setState("real")}
            onError={() => setState("ph")}
          />}
        {state === "real" && <img className="bust-img" src={BUST_SRC} alt="Arestoteles" style={{ opacity: 1 }} />}
        {state === "ph" && <MarblePlaceholder label={hero ? (label || "ARISTOTLE") : null} />}
      </div>
    );
  }

  function Wordmark({ text = "ARESTOTELES", className = "" }) {
    return (
      <div className={"ares-word " + className} aria-hidden="true">
        {text.split("").map((ch, i) => <span key={i}>{ch}</span>)}
      </div>
    );
  }

  window.Bust = Bust;
  window.Wordmark = Wordmark;
})();
