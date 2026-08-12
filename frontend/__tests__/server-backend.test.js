// The server-side backend fetch must be BOUNDED.
//
// The 2026-08-12 production incident: the FastAPI process exhausted its
// file descriptors, so it accepted TCP connections and answered nothing.
// Every server component fetched it with `try { await fetch(…) } catch`,
// which handles a REFUSED connection and not silence — Node's fetch
// bounds the connect phase, not the response. `next build` hung
// generating /league, gave up after 3 x 60 s, and failed the deploy.
//
// The full-build acceptance test lives in
// `scripts/hanging-backend.mjs` + `npm run build`; it takes minutes and
// is recorded in the incident PR. This file is the cheap gate that runs
// on every PR: it pins the property that made the build hang, not the
// build.

import { describe, expect, it, afterEach, vi } from "vitest";

import { backendOrigin, fetchBackendJson } from "../lib/server-backend.js";

const REAL_FETCH = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = REAL_FETCH;
  delete process.env.BACKEND_API_URL;
  delete process.env.BACKEND_SERVER_FETCH_TIMEOUT_MS;
  vi.restoreAllMocks();
});

describe("the request carries a bound", () => {
  it("passes an AbortSignal on every call", async () => {
    let seen = null;
    globalThis.fetch = async (_url, init) => {
      seen = init;
      return { ok: true, json: async () => ({ league: {} }) };
    };
    await fetchBackendJson("/api/public/league/overview", { revalidate: 60 });
    expect(seen?.signal).toBeInstanceOf(AbortSignal);
  });

  it("still asks Next to cache — the bound is not a cache opt-out", async () => {
    let seen = null;
    globalThis.fetch = async (_url, init) => {
      seen = init;
      return { ok: true, json: async () => ({ league: {} }) };
    };
    await fetchBackendJson("/api/public/league/overview", { revalidate: 60 });
    expect(seen?.next).toEqual({ revalidate: 60 });
  });

  it("gives up on a backend that accepts and never answers", async () => {
    process.env.BACKEND_SERVER_FETCH_TIMEOUT_MS = "40";
    // The incident, in one line: a promise that never settles on its
    // own. Only the signal can end this.
    globalThis.fetch = (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener("abort", () => reject(init.signal.reason));
      });
    vi.spyOn(console, "warn").mockImplementation(() => {});

    const started = Date.now();
    const out = await fetchBackendJson("/api/public/league/overview");
    const elapsed = Date.now() - started;

    expect(out).toBeNull();
    expect(elapsed).toBeLessThan(2000);
  });
});

describe("failure is one answer, not four", () => {
  it("returns null when the connection is refused", async () => {
    globalThis.fetch = async () => {
      throw Object.assign(new Error("connect ECONNREFUSED"), { name: "TypeError" });
    };
    vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(await fetchBackendJson("/api/public/league/overview")).toBeNull();
  });

  it("returns null on a non-ok status", async () => {
    globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({}) });
    vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(await fetchBackendJson("/api/public/league/overview")).toBeNull();
  });

  it("returns null on a body that is not JSON", async () => {
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => {
        throw new SyntaxError("Unexpected token <");
      },
    });
    vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(await fetchBackendJson("/api/public/league/overview")).toBeNull();
  });

  it("passes a healthy payload through untouched", async () => {
    const payload = { contractVersion: "x", league: { leagueName: "L" }, data: {} };
    globalThis.fetch = async () => ({ ok: true, json: async () => payload });
    expect(await fetchBackendJson("/api/public/league/overview")).toEqual(payload);
  });
});

describe("the origin is derived, not concatenated", () => {
  it("keeps protocol and host and drops any path", () => {
    process.env.BACKEND_API_URL = "http://10.0.0.4:8000/api/leftover";
    expect(backendOrigin()).toBe("http://10.0.0.4:8000");
  });

  it("falls back to loopback on an unparseable value", () => {
    process.env.BACKEND_API_URL = "not a url";
    expect(backendOrigin()).toBe("http://127.0.0.1:8000");
  });
});
