/* Arestoteles — boot. Device routing (phones get their own tree) + first-load intro
   (plays once per session via sessionStorage; honors prefers-reduced-motion via reducedOk;
   the variant is whatever the Tweaks panel last chose). */
(function () {
  const { useState, useEffect } = React;
  const MQ = "(max-width: 620px)";

  // Decide SYNCHRONOUSLY (before the first paint) whether the intro will play, so we can
  // hide the app behind the bust-drop and never flash the portfolio first. Desktop only —
  // the intro overlay is display:none on phones, so hiding the app there would just blank
  // the screen for the intro's duration.
  let willPlayIntro = false;
  try {
    willPlayIntro = !sessionStorage.getItem("ares-intro-seen") && !window.matchMedia(MQ).matches;
  } catch (_) {}
  if (willPlayIntro) document.documentElement.classList.add("ares-booting");
  const revealApp = () => document.documentElement.classList.remove("ares-booting");

  function Root() {
    const [isMobile, setIsMobile] = useState(() => window.matchMedia(MQ).matches);
    // While the intro plays, the app isn't built yet: building it at the same time made the
    // bust's fall stutter. It is built (and drawn, under the intro) once the big motion is over.
    const [appOn, setAppOn] = useState(!willPlayIntro || !window.ArestotelesIntro);
    useEffect(() => {
      const m = window.matchMedia(MQ);
      const fn = (e) => setIsMobile(e.matches);
      m.addEventListener ? m.addEventListener("change", fn) : m.addListener(fn);
      return () => { m.removeEventListener ? m.removeEventListener("change", fn) : m.removeListener(fn); };
    }, []);

    useEffect(() => {
      if (!willPlayIntro) return;
      try { sessionStorage.setItem("ares-intro-seen", "1"); } catch (_) {}
      let variant = "impact";
      try { variant = localStorage.getItem("ares-intro-variant") || "impact"; } catch (_) {}
      if (window.ArestotelesIntro) {
        // onReveal fires as the intro starts its crossfade → the overlay dissolves
        // straight into the live app. onDone is a belt-and-suspenders reveal (e.g. the
        // reduced-motion path, which skips straight to the end).
        window.ArestotelesIntro.play({
          variant, reducedOk: true,
          onSettled: () => { setAppOn(true); requestAnimationFrame(revealApp); },
          onReveal: () => { setAppOn(true); revealApp(); },
          onDone: revealApp,
        });
      } else {
        setAppOn(true);
        revealApp();
      }
    }, []);

    const Mobile = window.ArestotelesMobile;
    const Desktop = window.ArestotelesApp;
    const Tweaks = window.ArestotelesTweaks;
    if (!appOn) return null;
    return (
      <React.Fragment>
        {isMobile && Mobile ? <Mobile /> : <Desktop />}
        {Tweaks ? <Tweaks /> : null}
      </React.Fragment>
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
})();
