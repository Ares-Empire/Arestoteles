/* Arestoteles — boot. Device routing (phones get their own tree) + first-load intro
   (plays once per session via sessionStorage; honors prefers-reduced-motion via reducedOk;
   the variant is whatever the Tweaks panel last chose). */
(function () {
  const { useState, useEffect } = React;
  const MQ = "(max-width: 620px)";

  function Root() {
    const [isMobile, setIsMobile] = useState(() => window.matchMedia(MQ).matches);
    useEffect(() => {
      const m = window.matchMedia(MQ);
      const fn = (e) => setIsMobile(e.matches);
      m.addEventListener ? m.addEventListener("change", fn) : m.addListener(fn);
      return () => { m.removeEventListener ? m.removeEventListener("change", fn) : m.removeListener(fn); };
    }, []);

    useEffect(() => {
      let seen = false;
      try { seen = sessionStorage.getItem("ares-intro-seen"); } catch (_) {}
      if (!seen) {
        try { sessionStorage.setItem("ares-intro-seen", "1"); } catch (_) {}
        let variant = "impact";
        try { variant = localStorage.getItem("ares-intro-variant") || "impact"; } catch (_) {}
        if (window.ArestotelesIntro) window.ArestotelesIntro.play({ variant, reducedOk: true });
      }
    }, []);

    const Mobile = window.ArestotelesMobile;
    const Desktop = window.ArestotelesApp;
    const Tweaks = window.ArestotelesTweaks;
    return (
      <React.Fragment>
        {isMobile && Mobile ? <Mobile /> : <Desktop />}
        {Tweaks ? <Tweaks /> : null}
      </React.Fragment>
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
})();
