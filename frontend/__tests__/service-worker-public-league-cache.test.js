import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const SERVICE_WORKER_SOURCE = fs.readFileSync(
  path.join(ROOT, "public", "sw.js"),
  "utf8",
);

function loadServiceWorker({ cachedResponse, networkResponse, networkError = null }) {
  const listeners = {};
  const cache = {
    addAll: vi.fn(async () => {}),
    match: vi.fn(async () => cachedResponse),
    put: vi.fn(async () => {}),
  };
  const caches = {
    delete: vi.fn(async () => true),
    keys: vi.fn(async () => []),
    match: vi.fn(async () => null),
    open: vi.fn(async () => cache),
  };
  const fetch = networkError
    ? vi.fn(async () => {
        throw networkError;
      })
    : vi.fn(async () => networkResponse);
  const self = {
    addEventListener: vi.fn((name, handler) => {
      listeners[name] = handler;
    }),
    clients: { claim: vi.fn(async () => {}) },
    location: { origin: "https://chaseupside.com" },
    registration: { showNotification: vi.fn(async () => {}) },
    skipWaiting: vi.fn(),
  };

  vm.runInNewContext(SERVICE_WORKER_SOURCE, {
    URL,
    caches,
    clearTimeout,
    fetch,
    self,
    setTimeout,
  });

  return { cache, caches, fetch, listeners };
}

function dispatchPublicLeagueFetch(listener) {
  let responsePromise;
  listener({
    request: {
      method: "GET",
      url: "https://chaseupside.com/api/public/league/conduct",
    },
    respondWith(value) {
      responsePromise = value;
    },
  });
  return responsePromise;
}

describe("public-league service-worker cache", () => {
  it("returns the network payload instead of a cached pre-formula schema", async () => {
    const stale = { ok: true, schema: "pre-formula" };
    const fresh = {
      ok: true,
      schema: "scored",
      clone: vi.fn(() => ({ ok: true, schema: "scored-copy" })),
    };
    const { cache, caches, fetch, listeners } = loadServiceWorker({
      cachedResponse: stale,
      networkResponse: fresh,
    });

    await expect(dispatchPublicLeagueFetch(listeners.fetch)).resolves.toBe(fresh);

    expect(fetch).toHaveBeenCalledOnce();
    expect(cache.match).not.toHaveBeenCalled();
    expect(cache.put).toHaveBeenCalledOnce();
    expect(caches.open).toHaveBeenCalledWith("chaseupside-v8-public-league");
  });

  it("uses the public-league cache only when the network is unavailable", async () => {
    const cached = { ok: true, schema: "last-known-good" };
    const { cache, listeners } = loadServiceWorker({
      cachedResponse: cached,
      networkError: new Error("offline"),
    });

    await expect(dispatchPublicLeagueFetch(listeners.fetch)).resolves.toBe(cached);
    expect(cache.match).toHaveBeenCalledOnce();
    expect(cache.put).not.toHaveBeenCalled();
  });
});
