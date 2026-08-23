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
 *   - Network-first for everything else (HTML routes, private
 *     API calls).  We never want to serve stale private contract
 *     data; the public hub is the only API safe to read from cache
 *     because the snapshot is intentionally cache-warmed every
 *     20 min by ``public-league-warmup.yml``.
 *   - Offline fallback: when both network AND cache miss, serve
 *     the homepage HTML ``/offline``-style shell so the user sees
 *     "You're offline" instead of Chrome's dino.
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
 *   - Cache any authenticated API endpoint.  ``/api/user/*`` and
 *     ``/api/terminal`` intentionally pass straight through so we
 *     never accidentally show another user's cached state.
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
const CACHE_VERSION = "chaseupside-v8";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;
const PUBLIC_LEAGUE_CACHE = `${CACHE_VERSION}-public-league`;

const PRECACHE_URLS = [
  "/",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

// Paths we NEVER cache.  Keep this list short and explicit.
const NEVER_CACHE = [
  "/api/user/",
  "/api/auth/",
  "/api/trade/simulate",
  "/api/signal-alerts/",
  "/api/rankings/overrides",
  // The multi-MB private contract: networkFirst wrote it to
  // CacheStorage on EVERY navigation but only ever read it back when
  // offline — pure write cost per page load, plus private data at
  // rest.  The in-memory data layer + HTTP ETag revalidation own this
  // payload's caching now.
  "/api/data",
  "/api/dynasty-data",
];

function isNeverCache(url) {
  return NEVER_CACHE.some((prefix) => url.pathname.startsWith(prefix));
}

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
  if (isNeverCache(url)) return;

  // Static assets (``/_next/static/*``, ``/icons/*``): cache-first.
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // Public league API: network-first, cached only for offline use.
  // CacheStorage does not enforce the backend response's max-age, so
  // stale-while-revalidate here could return an arbitrarily old API
  // schema before its background refresh completed.  The backend and
  // Next server already own bounded caches for this data.
  if (url.pathname.startsWith("/api/public/league")) {
    event.respondWith(networkFirst(req, PUBLIC_LEAGUE_CACHE));
    return;
  }

  // Everything else: network-first with cache fallback.
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
    return offlineFallback();
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
    return offlineFallback();
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
  const url = typeof payload.url === "string" ? payload.url : "/";
  const tag = typeof payload.tag === "string" ? payload.tag : undefined;
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url },
      tag,
      renotify: !!tag,
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
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

async function offlineFallback() {
  const shell = await caches.match("/");
  if (shell) return shell;
  return new Response(
    "<h1>Offline</h1><p>You're offline and we don't have this page cached yet. Reconnect and reload.</p>",
    { headers: { "Content-Type": "text/html" }, status: 503 },
  );
}
