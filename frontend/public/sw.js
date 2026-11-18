/**
 * Service worker — minimal "offline-first shell" for Chase Upside.
 *
 * What this does:
 *   - Cache-first for static assets (``/_next/static/*``, icons,
 *     manifest).  Asset hashes are deterministic, so even a stale
 *     cache is safe: the HTML references the current hash and the
 *     old hash eventually expires.
 *   - Network-first for the PUBLIC league API
 *     (``/api/public/league*``), with CacheStorage used only as an
 *     offline fallback.  The backend already owns the short-lived
 *     snapshot cache; serving an unbounded browser-cache entry first
 *     can preserve an obsolete API schema across a deployment.
 *   - Network-first for page navigations and other non-API GETs.
 *   - ``/api/*`` is NEVER cached except the explicit allowlist in
 *     "Request policy" below (today: the public league API only; it is
 *     cache-warmed every 20 min by ``public-league-warmup.yml``).
 *     Every other API request is not intercepted at all.
 *   - Offline fallback depends on WHAT was requested: a page navigation
 *     gets the homepage shell ("You're offline" instead of Chrome's
 *     dino); an API request gets a JSON 503 ``{"error":"offline"}``,
 *     never HTML; a script/image/font gets a network error.
 *
 * Push (`push` + `notificationclick`):
 *   - On `push`, parses the JSON payload (`{title, body, url, tag}`)
 *     and shows a notification.  Falls back to a generic title +
 *     body if the payload is malformed (some test pushes are empty).
 *   - On `notificationclick`, focuses an existing tab on the same
 *     origin (the `url` field if provided) or opens a new one.
 *
 * What this deliberately does NOT do:
 *   - Background sync.
 *   - Cache any authenticated API endpoint.  Allow-list, not deny-list:
 *     a new private endpoint is uncached by default.
 *
 * Versioning: bump ``CACHE_VERSION`` when the cache layout changes.
 * Old caches are deleted on ``activate``.
 */
// v5: bump (2026-04-29) — second iOS PWA report of the per-source
// winner table missing on mobile.  v4 already shipped the fix; the
// affected users were still pinned to a pre-v4 cache that hadn't
// activated (iOS Safari delays SW activation until every PWA tab on
// the origin closes — easy to skip if a backgrounded tab survives
// device reboots).  This bump forces another activation cycle on
// hosts where v4 never won the race, evicting the pre-fix bundle and
// pulling fresh chunks containing the always-rendered breakdown card.
// v4: bump (2026-04-27) to evict stale PWA caches that pre-date the
// per-source winner table on /trade (PR #335).  iOS PWA users reported
// the table missing on mobile because their cached HTML referenced
// the old chunk hashes and the SW served them from cache; an
// activation cycle that wipes prior caches forces the next page load
// to fetch fresh chunks containing TradeSourceBreakdown.
// v3: push + notificationclick handlers added.  Cache layout is
// otherwise unchanged; the bump just forces an SW activation cycle so
// existing tabs pick up the new event listeners.
// v7: /api/data + /api/dynasty-data added to NEVER_CACHE (stop the
// per-navigation multi-MB cache.put of the private contract).  Bump
// evicts runtime caches that may still hold contract payloads.
// v8: public-league API reads moved from stale-while-revalidate to
// network-first.  The old cache could return a pre-formula conduct
// payload after deployment, and the rankings UI interpreted its
// missing score fields as real zeroes.  The version bump evicts every
// such payload already stored on visitors' devices.
// v9: /api/auction/ added to NEVER_CACHE.  The rookie auction room's
// responses carry private balances, private maximum bids and live room
// state; the network-first fallback would otherwise store them at rest
// and could replay a stale balance offline as if it were current.  The
// bump evicts anything already stored.
// v10: /api/public/league/trade-advisor added to NEVER_CACHE (review
// R2-7 / privacy F-2).  The Brisket Trade Advisor's team and asset lists
// and its analyze answers are served `no-store`, but the public-league
// network-first branch below put every GET into CacheStorage regardless.
// Nothing in them is a value, yet "no cache holding" is the advisor's
// contract and an offline replay of a stale roster list would build a
// trade against rosters that no longer exist.  The bump evicts anything
// already stored.
// v11: API caching inverted from a deny-list to an ALLOW-list (see "Request
// policy" below) and the offline fallback made type-aware.  The deny-list
// omitted /api/terminal, /api/roster/intelligence, /api/draft-capital and
// every later private endpoint, so they were written to CacheStorage by the
// generic network-first branch; and an offline API miss was answered with
// the homepage HTML.  The bump evicts everything the old rules stored.
const CACHE_VERSION = "chaseupside-v11";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;
const PUBLIC_LEAGUE_CACHE = `${CACHE_VERSION}-public-league`;

const PRECACHE_URLS = [
  "/",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

// ── Request policy ─────────────────────────────────────────────────────
// Two fail-safe rules (pinned by __tests__/service-worker-public-league-
// cache.test.js):
//   1. `/api/*` is NEVER cached unless its prefix is on API_CACHE_ALLOWLIST.
//      A new endpoint is uncached by default.  The old deny-list let every
//      private endpoint nobody remembered to list (terminal, roster
//      intelligence, draft capital, waiver, trade analyze ...) fall into the
//      generic network-first-and-put branch.
//   2. An API request never receives HTML (see offlineFallback).
//
// The only API reads safe to hold in CacheStorage: the PUBLIC league
// snapshot (cache-warmed server side, nothing roster-state dependent),
// network-first and used only as an offline fallback.
const API_CACHE_ALLOWLIST = ["/api/public/league"];
// Public but served no-store / live: carved out of the allowlist.
const API_CACHE_DENY_WITHIN_ALLOWLIST = ["/api/public/league/trade-advisor"];
// Non-API pages never at rest (invite / reset / verification URLs carry
// one-time tokens).
const PAGE_NEVER_CACHE = ["/auction"];

function startsWithAny(pathname, prefixes) {
  return prefixes.some((prefix) => pathname.startsWith(prefix));
}

function isApiPath(pathname) {
  return pathname === "/api" || pathname.startsWith("/api/");
}

// "passthrough" = not intercepted (the browser's own network path and its own
// failure apply); "cache-first" = immutable static assets;
// "network-first-public" = allowlisted public API; "network-first" = page
// navigations and other non-API GETs.
function routeFor(pathname) {
  if (isApiPath(pathname)) {
    return startsWithAny(pathname, API_CACHE_ALLOWLIST) &&
      !startsWithAny(pathname, API_CACHE_DENY_WITHIN_ALLOWLIST)
      ? "network-first-public"
      : "passthrough";
  }
  if (startsWithAny(pathname, PAGE_NEVER_CACHE)) return "passthrough";
  if (pathname.startsWith("/_next/static/") || pathname.startsWith("/icons/")) {
    return "cache-first";
  }
  return "network-first";
}

// What an offline CACHE MISS answers with: "json" for an API path (a JSON
// 503, never markup), "shell" for a page navigation, "error" for anything
// else (a failed script/image/font is not "answered" with an HTML document).
function offlineKindFor(pathname, mode, accept) {
  if (isApiPath(pathname)) return "json";
  const wantsHtml = typeof accept === "string" && accept.includes("text/html");
  if (mode === "navigate" || wantsHtml) return "shell";
  return "error";
}

const OFFLINE_JSON_BODY = JSON.stringify({
  error: "offline",
  message: "You appear to be offline and this response is not available from the cache.",
});

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE_URLS).catch(() => {})),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => !k.startsWith(CACHE_VERSION))
          .map((k) => caches.delete(k)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }
  // Cross-origin — let the browser handle it.
  if (url.origin !== self.location.origin) return;
  const route = routeFor(url.pathname);

  // Private / unlisted API and one-time-token pages: not intercepted at all.
  // A network failure propagates as the browser's own fetch error, never as
  // a cached or synthesized HTML page.
  if (route === "passthrough") return;

  // Static assets (``/_next/static/*``, ``/icons/*``): cache-first.
  if (route === "cache-first") {
    event.respondWith(cacheFirst(req));
    return;
  }

  // Public league API (the only cacheable API): network-first, cached only
  // for offline use.  CacheStorage does not enforce the backend response's
  // max-age, so stale-while-revalidate here could return an arbitrarily old
  // API schema before its background refresh completed.
  if (route === "network-first-public") {
    event.respondWith(networkFirst(req, PUBLIC_LEAGUE_CACHE));
    return;
  }

  // Everything else (page navigations, non-API GETs): network-first.
  event.respondWith(networkFirst(req));
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const res = await fetch(request);
    if (res && res.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, res.clone()).catch(() => {});
    }
    return res;
  } catch {
    // No network + no cache → fall through to offline shell.
    return offlineFallback(request);
  }
}

async function networkFirst(request, cacheName = RUNTIME_CACHE) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(request);
    if (res && res.ok) {
      // Best-effort put; a quota error shouldn't break the response.
      cache.put(request, res.clone()).catch(() => {});
    }
    return res;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return offlineFallback(request);
  }
}

self.addEventListener("push", (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch {
      try {
        payload = { title: "Chase Upside", body: event.data.text() };
      } catch {
        payload = {};
      }
    }
  }
  const title = String(payload.title || "Chase Upside").slice(0, 120);
  const body = String(payload.body || "").slice(0, 300);
  const url = safeNotificationPath(payload.url);
  const tag = typeof payload.tag === "string" ? payload.tag : undefined;
  const timestamp = Number.isFinite(payload.ts) ? payload.ts : undefined;
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url },
      tag,
      renotify: !!tag,
      timestamp,
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Only ever open a same-origin PATH.  A tap navigates; it never acts
  // (no bid, no trade acceptance) — the page it opens is authenticated.
  const target = safeNotificationPath(event.notification.data && event.notification.data.url);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        try {
          const u = new URL(c.url);
          if (u.origin === self.location.origin && "focus" in c) {
            c.navigate?.(target);
            return c.focus();
          }
        } catch { /* ignore malformed client url */ }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(target);
      }
    }),
  );
});

function safeNotificationPath(raw) {
  // Resolve exactly as the browser will, then require our own origin — a
  // string prefix check is not enough ("/\t/evil.com" resolves off-origin).
  if (typeof raw !== "string" || raw.length > 300) return "/";
  try {
    const u = new URL(raw, self.location.origin);
    if (u.origin !== self.location.origin) return "/";
    return u.pathname + u.search + u.hash;
  } catch {
    return "/";
  }
}

async function offlineFallback(request) {
  let pathname = "/";
  try {
    pathname = new URL(request.url).pathname;
  } catch {
    // keep "/"
  }
  const kind = offlineKindFor(
    pathname,
    request.mode,
    request.headers && request.headers.get && request.headers.get("accept"),
  );
  if (kind === "json") {
    return new Response(OFFLINE_JSON_BODY, {
      status: 503,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
  if (kind === "error") return Response.error();
  const shell = await caches.match("/");
  if (shell) return shell;
  return new Response(
    "<h1>Offline</h1><p>You're offline and we don't have this page cached yet. Reconnect and reload.</p>",
    { headers: { "Content-Type": "text/html" }, status: 503 },
  );
}
