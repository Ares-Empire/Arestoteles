/* Arestoteles — live watchlist feed (window.AresLive).

   Fetches web/live.json (written server-side by scripts/refresh_quotes.py from
   Alpaca's read-only IEX feed) and exposes it to the React shell. This is a
   *watchlist* of real company performance — explicitly NOT the paper book's
   holdings, which stay at the honest Phase-1 state (zero positions) until the
   brain trades. Fails soft: if the feed is missing the watchlist simply doesn't
   render and the rest of the app is unaffected. */
(function () {
  "use strict";

  window.AresLive = { quotes: [], asOfLabel: null, marketOpen: false, loaded: false };
  let lastSig = null;

  function quoteSig(d) {
    // signature of the prices only (not the timestamp) so we re-render the shell
    // when quotes actually move, not on every poll while the market is closed
    return (d.quotes || []).map((q) => q.ticker + ":" + q.price + ":" + q.day).join("|");
  }

  function load() {
    fetch("live.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => {
        window.AresLive = Object.assign({ loaded: true }, d);
        const sig = quoteSig(d);
        if (sig !== lastSig) {
          lastSig = sig;
          // nudge the React shell to re-read (App listens for 'ares-tweak')
          window.dispatchEvent(new CustomEvent("ares-tweak"));
        }
      })
      .catch((e) => {
        // no feed yet → no watchlist; everything else still works
        if (window.console) console.warn("Arestoteles: live watchlist unavailable —", e.message);
      });
  }

  load();
  // belt-and-suspenders: if the data landed before the React shell mounted its
  // listener, re-emit once everything is loaded (harmless if already shown)
  window.addEventListener("load", () => {
    if (window.AresLive.loaded) window.dispatchEvent(new CustomEvent("ares-tweak"));
  });
  // the feed is regenerated server-side on a timer; refresh while the tab is open
  setInterval(load, 5 * 60 * 1000);
})();
