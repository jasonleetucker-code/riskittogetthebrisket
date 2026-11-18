/**
 * Service-worker API policy (audit remediation, Task 9).
 *
 *  - An API request is NEVER answered with HTML, online or offline.
 *  - `/api/*` is cached only on an explicit allowlist (public league API);
 *    every other API path - including the ones the old deny-list forgot
 *    (/api/terminal, /api/roster/intelligence, /api/draft-capital) - is not
 *    intercepted at all.
 *  - The worker version was bumped so installed workers update and evict the
 *    caches the old rules filled.
 */
import fs from "node:fs";
import path from "node:path";
import * as url from "node:url";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");
const SW_SOURCE = fs.readFileSync(path.join(ROOT, "public", "sw.js"), "utf8");
const ORIGIN = "https://chaseupside.com";

class FakeResponse {
  constructor(body, init = {}) {
    this.body = body;
    this.status = init.status ?? 200;
    this.headers = new Map(Object.entries(init.headers || {}));
    this.ok = this.status >= 200 && this.status < 300;
  }
  clone() {
    return this;
  }
  static error() {
    const r = new FakeResponse(null, { status: 0 });
    r.type = "error";
    return r;
  }
}

function loadSW({ shell = null } = {}) {
  const listeners = {};
  const cache = {
    addAll: vi.fn(async () => {}),
    match: vi.fn(async () => undefined),
    put: vi.fn(async () => {}),
  };
  const caches = {
    delete: vi.fn(async () => true),
    keys: vi.fn(async () => []),
    match: vi.fn(async (key) => (key === "/" ? shell : undefined)),
    open: vi.fn(async () => cache),
  };
  const fetch = vi.fn(async () => {
    throw new TypeError("Failed to fetch");
  });
  const self = {
    addEventListener: vi.fn((name, handler) => {
      listeners[name] = handler;
    }),
    clients: { claim: vi.fn(async () => {}) },
    location: { origin: ORIGIN },
    registration: { showNotification: vi.fn(async () => {}) },
    skipWaiting: vi.fn(),
  };
  vm.runInNewContext(SW_SOURCE, {
    URL,
    Response: FakeResponse,
    caches,
    clearTimeout,
    fetch,
    self,
    setTimeout,
  });
  return { cache, caches, fetch, listeners };
}

function dispatch(listeners, pathAndQuery, { mode = "cors", accept = "*/*" } = {}) {
  let responsePromise = null;
  const respondWith = vi.fn((v) => {
    responsePromise = v;
  });
  listeners.fetch({
    request: {
      method: "GET",
      url: `${ORIGIN}${pathAndQuery}`,
      mode,
      headers: { get: (k) => (k.toLowerCase() === "accept" ? accept : null) },
    },
    respondWith,
  });
  return { respondWith, responsePromise };
}

describe("service worker version", () => {
  it("was bumped past v10 so old caches are evicted on activate", () => {
    expect(SW_SOURCE).toContain('const CACHE_VERSION = "chaseupside-v11"');
  });
});

describe("private API paths are not intercepted or cached", () => {
  it.each([
    "/api/terminal",
    "/api/roster/intelligence?leagueKey=dynasty_main",
    "/api/draft-capital",
    "/api/waiver/advisor",
    "/api/dynasty-data?view=compact",
    "/api/data",
    "/api/user/settings",
    "/api/trade/analyze",
    "/api/brand-new-private-endpoint",
    "/api/public/league/trade-advisor/teams",
    "/api/public/waiver-compare",
  ])("%s -> passthrough (no respondWith, no cache access)", (p) => {
    const { listeners, caches, cache, fetch } = loadSW();
    const { respondWith } = dispatch(listeners, p);
    expect(respondWith).not.toHaveBeenCalled();
    expect(caches.open).not.toHaveBeenCalled();
    expect(cache.put).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("an API request never receives HTML", () => {
  it("allowlisted public API, offline, cache miss -> JSON 503 {error:'offline'} even with a cached homepage shell", async () => {
    const shell = new FakeResponse("<html>cached home</html>", { headers: { "Content-Type": "text/html" } });
    const { listeners } = loadSW({ shell });
    const { responsePromise } = dispatch(listeners, "/api/public/league/overview", { accept: "application/json" });
    const res = await responsePromise;
    expect(res).not.toBe(shell);
    expect(res.status).toBe(503);
    expect(res.headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(res.body)).toMatchObject({ error: "offline" });
    expect(String(res.body)).not.toMatch(/<\s*html|<h1/i);
  });

  it("holds even when the Accept header asks for text/html", async () => {
    const { listeners } = loadSW();
    const { responsePromise } = dispatch(listeners, "/api/public/league/overview", { accept: "text/html" });
    const res = await responsePromise;
    expect(res.headers.get("Content-Type")).toBe("application/json");
  });

  it("no cached payload for a never-cached private API means the browser's own failure (nothing to respond with)", () => {
    const { listeners } = loadSW();
    const { respondWith } = dispatch(listeners, "/api/terminal");
    expect(respondWith).not.toHaveBeenCalled();
  });
});

describe("offline fallback by request kind", () => {
  it("a page navigation still gets the cached homepage shell", async () => {
    const shell = new FakeResponse("<html>home</html>");
    const { listeners } = loadSW({ shell });
    const { responsePromise } = dispatch(listeners, "/rankings", { mode: "navigate", accept: "text/html" });
    await expect(responsePromise).resolves.toBe(shell);
  });

  it("a navigation with no shell cached gets the offline HTML page (503)", async () => {
    const { listeners } = loadSW({ shell: null });
    const { responsePromise } = dispatch(listeners, "/rankings", { mode: "navigate", accept: "text/html" });
    const res = await responsePromise;
    expect(res.status).toBe(503);
    expect(res.body).toMatch(/Offline/);
  });

  it("a failed static chunk is a network error, not an HTML document", async () => {
    const shell = new FakeResponse("<html>home</html>");
    const { listeners } = loadSW({ shell });
    const { responsePromise } = dispatch(listeners, "/_next/static/chunks/app/page-abc.js", { accept: "*/*" });
    const res = await responsePromise;
    expect(res).not.toBe(shell);
    expect(res.type).toBe("error");
  });
});

describe("the allowlist is explicit", () => {
  it("only the public league API is cacheable", () => {
    const m = SW_SOURCE.match(/const API_CACHE_ALLOWLIST = (\[[^\]]*\]);/);
    expect(m).not.toBeNull();
    expect(JSON.parse(m[1])).toEqual(["/api/public/league"]);
  });
});
