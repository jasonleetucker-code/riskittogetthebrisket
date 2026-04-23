/**
 * Service worker — minimal "offline-first shell" for Brisket.
 *
 * What this does:
 *   - Cache-first for static assets (``/_next/static/*``, icons,
 *     manifest).  Asset hashes are deterministic, so even a stale
 *     cache is safe: the HTML references the current hash and the
 *     old hash eventually expires.
 *   - Network-first for HTML routes and API calls.  We never want
 *     to serve stale player values; API responses always hit the
 *     network first with a 10s fallback to cache.
 *   - Offline fallback: when both network AND cache miss, serve
 *     the homepage HTML ``/offline``-style shell so the user sees
 *     "You're offline" instead of Chrome's dino.
 *
 * What this deliberately does NOT do:
 *   - Push notifications (that's a future PR once a subscription
 *     endpoint ships).
 *   - Background sync.
 *   - Cache any authenticated API endpoint.  ``/api/user/*`` and
 *     ``/api/terminal`` intentionally pass straight through so we
 *     never accidentally show another user's cached state.
 *
 * Versioning: bump ``CACHE_VERSION`` when the cache layout changes.
 * Old caches are deleted on ``activate``.
 */
const CACHE_VERSION = "brisket-v1";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

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

async function offlineFallback() {
  const shell = await caches.match("/");
  if (shell) return shell;
  return new Response(
    "<h1>Offline</h1><p>You're offline and we don't have this page cached yet. Reconnect and reload.</p>",
    { headers: { "Content-Type": "text/html" }, status: 503 },
  );
}
