// Early base-contract request for the routes whose first useful state IS the
// board (Rankings, Trade).
//
// WHY
// ---
// `useDynastyData` can only ask for the contract once React has hydrated —
// after every page chunk has downloaded and executed. Production attribution
// (docs/performance/CURRENT_ARCHITECTURE.md, #1338) measured that request
// starting ~960–1,080 ms into a cold load while the HTML itself arrived at
// ~290 ms, and the request then taking ~500–650 ms. Nothing about the request
// depends on React: its key is the path, the active league (localStorage) and
// the view (always "compact" on these two routes). So a tiny inline script in
// the document head starts it during HTML parse, overlapping it with the
// chunk download and hydration, and the fetch layer ADOPTS that in-flight
// response instead of issuing its own.
//
// WHAT IT IS NOT
// --------------
// Not a second fetch path and not a cache: exactly one request is made, with
// the same URL, the same `cache: "no-cache"` revalidation and the same
// cookies as the normal path; everything after `fetch()` resolves (status
// classification, 401/503 handling, JSON, caching) is the existing code in
// `lib/dynasty-data.js`. The response is adopted at most once, only for an
// identical key and only while fresh; otherwise it is dropped and the normal
// request runs. Anonymous visitors never reach it: the middleware redirects
// private routes to /login before any HTML is served.

/** Active-league localStorage key (the one `useLeague` writes). */
export const LEAGUE_LOCAL_KEY = "next_active_league_v1";

/** The routes whose useful state is the board, and the view they request. */
export const EARLY_CONTRACT_ROUTES = Object.freeze({ "/rankings": "compact", "/trade": "compact" });

/** A response that ARRIVED longer ago than this is not adopted (the same
 * base-contract TTL `lib/dynasty-data.js` applies from arrival). A request
 * still in flight is adopted whatever its age — exactly as the fetch layer
 * joins its own in-flight request — so a slow network never pays twice. */
export const EARLY_CONTRACT_MAX_AGE_MS = 30_000;

const GLOBAL = "__riskitEarlyContract";

/**
 * The inline head script. Built from the constants above so the key it
 * records cannot drift from the key `_fetchBaseContract` looks up; parity is
 * pinned by `__tests__/early-contract.test.js`.
 */
export const EARLY_CONTRACT_SCRIPT = `(function(){try{var v=${JSON.stringify(EARLY_CONTRACT_ROUTES)}[location.pathname];if(!v||!window.fetch)return;var lk="";try{lk=localStorage.getItem(${JSON.stringify(LEAGUE_LOCAL_KEY)})||""}catch(e){}var q=new URLSearchParams();if(lk)q.set("leagueKey",lk);q.set("view",v);var p=fetch("/api/dynasty-data?"+q.toString(),{cache:"no-cache"});var r={key:lk+"|"+v,promise:p};var d=function(){r.arrivedAt=Date.now()};p.then(d,d);window[${JSON.stringify(GLOBAL)}]=r}catch(e){}})();`;

/**
 * The early request for `cacheKey` as `{ promise, arrivedAt() }`, consumed at
 * most once. `arrivedAt()` is when its response settled (undefined while in
 * flight) — the caller stamps its cache from THAT, never later, so an adopted
 * response is not treated as fresher than it is. Returns null when there is
 * none, the key differs, or it arrived too long ago; the caller then makes
 * the normal request.
 */
export function takeEarlyContract(cacheKey, now = Date.now()) {
  if (typeof window === "undefined") return null;
  const early = window[GLOBAL];
  if (!early) return null;
  // Consumed or not, it is spent: a mismatched early request is never
  // retried for a different key.
  window[GLOBAL] = undefined;
  if (early.key !== cacheKey || !early.promise) return null;
  const arrived = early.arrivedAt;
  if (arrived !== undefined && !(now - arrived >= 0 && now - arrived < EARLY_CONTRACT_MAX_AGE_MS)) {
    return null;
  }
  return { promise: early.promise, arrivedAt: () => early.arrivedAt };
}
