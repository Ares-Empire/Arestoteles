/* Arestoteles — Tweaks controller. Lives once (mounted by Root), drives the read-only
   data singleton (window.AresData) and broadcasts 'ares-tweak' so both the desktop and
   mobile trees re-aggregate. Also owns the intro variant + replay. */
(function () {
  const { useEffect } = React;
  const { useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakSelect, TweakButton, TweakToggle } = window;

  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "portfolio": "empty",
    "thesis": "populated",
    "pnl": "actual",
    "introVariant": "impact"
  }/*EDITMODE-END*/;

  function broadcast() { window.dispatchEvent(new CustomEvent("ares-tweak")); }

  function TweaksController() {
    const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

    useEffect(() => {
      window.AresData.setEmpty(t.portfolio === "empty");
      window.AresData.thesisPending = (t.thesis === "pending");
      window.AresData.pnlFlip = (t.pnl === "down") ? -1 : 1;
      window.__introVariant = t.introVariant;
      try { localStorage.setItem("ares-intro-variant", t.introVariant); } catch (_) {}
      broadcast();
    }, [t.portfolio, t.thesis, t.pnl, t.introVariant]);

    const replay = () => {
      try { sessionStorage.removeItem("ares-intro-seen"); } catch (_) {}
      if (window.ArestotelesIntro) window.ArestotelesIntro.play({ variant: t.introVariant });
    };

    return (
      <TweaksPanel title="Tweaks">
        <TweakSection label="Portfolio" />
        <TweakRadio label="Book" value={t.portfolio}
          options={["empty", "demo"]} onChange={(v) => setTweak("portfolio", v)} />
        <TweakRadio label="P&L" value={t.pnl}
          options={["actual", "down"]} onChange={(v) => setTweak("pnl", v)} />

        <TweakSection label="Thesis card" />
        <TweakRadio label="State" value={t.thesis}
          options={["populated", "pending"]} onChange={(v) => setTweak("thesis", v)} />

        <TweakSection label="Intro" />
        <TweakSelect label="Treatment" value={t.introVariant}
          options={["impact", "descent", "fracture"]} onChange={(v) => setTweak("introVariant", v)} />
        <TweakButton label="Replay intro" onClick={replay}>Play ▶</TweakButton>
      </TweaksPanel>
    );
  }

  window.ArestotelesTweaks = TweaksController;
})();
