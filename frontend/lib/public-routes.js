/**
 * public-routes.js — THE definition of which pages are reachable
 * without a session.
 *
 * One predicate, three consumers:
 *   • middleware.js       — server-side redirect for anonymous visitors
 *   • AppShellWrapper.jsx — which nav destinations a logged-out visitor sees
 *   • robots.js           — what search engines may index
 *
 * It lives here, pure and dependency-free, because those three used to
 * disagree.  The shell's list was an EXACT-match Set, so `/league` was
 * public but `/league/activity` — a League nav item backed by the same
 * public pipeline — was treated as private and vanished from the
 * logged-out nav.  Prefix matching is the correct semantic for a
 * public subtree, and stating it once removes the drift.
 *
 * Note what is NOT here: `/trades`.  It was declared public in three
 * places while rendering proprietary trade grades and per-side value
 * gains off the private `/api/data` contract — so logged-out visitors
 * got a permanently empty page and authenticated ones got competitive
 * intelligence on a "public" URL.  The public league hub has its own
 * community-facing Trades tab; this route is private.
 */

/** Pages with no private data at all, matched exactly. */
const PUBLIC_EXACT = new Set([
  "/", // marketing landing when logged out; terminal when logged in
  "/login",
  "/draft-capital", // legacy shim → /league?tab=draft-capital
]);

/**
 * Public subtrees, matched as prefixes.  `/league` is served by the
 * isolated public pipeline in src/public_league/ and never reads the
 * private contract.
 */
const PUBLIC_PREFIXES = ["/league"];

/**
 * Paths the auth gate must never touch: framework internals, the API
 * (which enforces its own default-deny gate server-side), and the
 * crawler/PWA metadata files.
 */
const ALWAYS_ALLOWED_PREFIXES = ["/_next", "/api", "/static"];

const ALWAYS_ALLOWED_EXACT = new Set([
  "/robots.txt",
  "/sitemap.xml",
  "/manifest.webmanifest",
  "/favicon.ico",
  "/sw.js",
]);

/**
 * Routes that moved, mapped old → new.
 *
 * These are served by the middleware rather than by a page-level
 * `redirect()` shim.  A shim under `/league` does NOT produce an HTTP
 * redirect: `app/league/loading.jsx` gives that segment a Suspense
 * boundary, so Next streams a 200 and performs the redirect in the RSC
 * payload — fine in a browser, useless to curl, crawlers, and link
 * unfurlers, and it would leave a 200 sitting on a URL whose content
 * moved behind auth.  Middleware answers with a real 308 before any of
 * that.  (`/draft-capital`'s page-level shim still works because its
 * segment has no loading boundary; it is left alone.)
 */
export const MOVED_ROUTES = new Map([["/league/phases", "/phases"]]);

/** Is this a framework/metadata path that auth must not intercept? */
export function isInfrastructurePath(pathname) {
  if (!pathname) return false;
  if (ALWAYS_ALLOWED_EXACT.has(pathname)) return true;
  if (ALWAYS_ALLOWED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return true;
  }
  // Route-segment metadata files (opengraph-image, icon, apple-icon…)
  // are generated per dynamic route and must stay reachable so link
  // unfurls work for shared public-league URLs.
  return /\/(opengraph-image|twitter-image|icon|apple-icon)(-[\w]+)?(\/\d+)?$/.test(pathname);
}

/** Is this page reachable without a session? */
export function isPublicPath(pathname) {
  if (!pathname) return false;
  if (isInfrastructurePath(pathname)) return true;
  if (PUBLIC_EXACT.has(pathname)) return true;
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

export { PUBLIC_EXACT, PUBLIC_PREFIXES };
