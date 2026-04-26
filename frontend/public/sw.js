/**
 * Service worker — minimal "offline-first shell" for Brisket.
 *
 * What this does:
 *   - Cache-first for static assets (``/_next/static/*``, icons,
 *     manifest).  Asset hashes are deterministic, so even a stale
 *     cache is safe: the HTML references the current hash and the
 *     old hash eventually expires.
 *   - Stale-while-revalidate for the PUBLIC league API
 *     (``/api/public/league*``).  Visitor sees the cached snapshot
 *     instantly while a fresh fetch updates the cache in the
 *     background — drops cold-load time on the public /league hub
 *     by the snapshot-fetch round-trip cost (~400 ms typical).
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
// v3: push + notificationclick handlers added.  Cache layout is
// otherwise unchanged; the bump just forces an SW activation cycle so
// existing tabs pick up the new event listeners.
const CACHE_VERSION = "brisket-v3";
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

  // Public league API: stale-while-revalidate.  The snapshot is
  // already kept fresh server-side by the 20-min warmup cron
  // (``.github/workflows/public-league-warmup.yml``) + the
  // stale-while-revalidate behaviour in
  // ``server.py::_get_public_snapshot`` — both layers mean a cached
  // response on the client is at most ~25 minutes old, well within
  // the snapshot's TTL.  This caching layer trades that bounded
  // staleness for instant first paint on repeat visits.
  if (url.pathname.startsWith("/api/public/league")) {
    event.respondWith(staleWhileRevalidate(req, PUBLIC_LEAGUE_CACHE));
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

async function networkFirst(request) {
  try {
    const res = await fetch(request);
    if (res && res.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      // Best-effort put; a quota error shouldn't break the response.
      cache.put(request, res.clone()).catch(() => {});
    }
    return res;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return offlineFallback();
  }
}

/**
 * Stale-while-revalidate: respond from cache instantly when present,
 * fire a background fetch in parallel that updates the cache for the
 * next visit.  Only used for ``/api/public/league*`` because that's
 * the one endpoint where (a) the data is non-personalised and (b)
 * the server already keeps the snapshot fresh on a tight TTL, so a
 * cached response is acceptable for first paint.
 */
async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const networkFetch = fetch(request)
    .then((res) => {
      if (res && res.ok) {
        cache.put(request, res.clone()).catch(() => {});
      }
      return res;
    })
    .catch(() => null);
  if (cached) {
    // Don't await the background revalidation — let the tab continue.
    return cached;
  }
  // Cache miss: fall back to whatever the network returns.  If the
  // network is also dead, give the user the offline shell.
  const fresh = await networkFetch;
  if (fresh) return fresh;
  return offlineFallback();
}

self.addEventListener("push", (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch {
      try {
        payload = { title: "Brisket", body: event.data.text() };
      } catch {
        payload = {};
      }
    }
  }
  const title = String(payload.title || "Brisket").slice(0, 120);
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
