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

  function load() {
    fetch("live.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => {
        window.AresLive = Object.assign({ loaded: true }, d);
        // nudge the React shell to re-read (App listens for 'ares-tweak')
        window.dispatchEvent(new CustomEvent("ares-tweak"));
      })
      .catch((e) => {
        // no feed yet → no watchlist; everything else still works
        if (window.console) console.warn("Arestoteles: live watchlist unavailable —", e.message);
      });
  }

  load();
  // the feed is regenerated server-side on a timer; refresh while the tab is open
  setInterval(load, 5 * 60 * 1000);
})();
