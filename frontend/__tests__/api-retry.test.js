import { describe, it, expect, beforeEach, vi } from "vitest";
import { fetchWithRetry } from "../lib/api-retry.js";


function mockFetch(responses) {
  let i = 0;
  globalThis.fetch = vi.fn(async () => {
    const next = responses[Math.min(i, responses.length - 1)];
    i++;
    if (typeof next === "function") return next();
    return next;
  });
}


function _jsonResponse(status, body) {
  return {
    ok: 200 <= status && status < 300,
    status,
    json: async () => body,
  };
}


describe("fetchWithRetry", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("returns ok on 200", async () => {
    mockFetch([_jsonResponse(200, { hello: "world" })]);
    const r = await fetchWithRetry("/api/x");
    expect(r.ok).toBe(true);
    expect(r.data).toEqual({ hello: "world" });
  });

  it("does not retry on 4xx", async () => {
    mockFetch([
      _jsonResponse(404, { error: "not_found" }),
      _jsonResponse(200, { hello: "world" }),
    ]);
    const r = await fetchWithRetry("/api/x", { retries: 3 });
    expect(r.ok).toBe(false);
    expect(r.status).toBe(404);
    expect(globalThis.fetch.mock.calls.length).toBe(1);
  });

  it("retries on 5xx and succeeds", async () => {
    mockFetch([
      _jsonResponse(500, { error: "oops" }),
      _jsonResponse(200, { hello: "ok" }),
    ]);
    const r = await fetchWithRetry("/api/x", { retries: 1, retryDelayBaseMs: 1 });
    expect(r.ok).toBe(true);
    expect(r.data).toEqual({ hello: "ok" });
    expect(globalThis.fetch.mock.calls.length).toBe(2);
  });

  it("retries on 5xx until exhausted", async () => {
    mockFetch([_jsonResponse(502, null), _jsonResponse(502, null), _jsonResponse(502, null)]);
    const r = await fetchWithRetry("/api/x", { retries: 2, retryDelayBaseMs: 1 });
    expect(r.ok).toBe(false);
    expect(r.status).toBe(502);
  });

  it("times out after timeoutMs", async () => {
    globalThis.fetch = vi.fn((_url, init) => {
      return new Promise((_resolve, reject) => {
        // Simulate an aborted fetch.
        init.signal.addEventListener("abort", () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    const r = await fetchWithRetry("/api/x", { timeoutMs: 10 });
    expect(r.ok).toBe(false);
    expect(r.error).toBe("timeout");
  });

  it("handles network error gracefully", async () => {
    globalThis.fetch = vi.fn(() => {
      throw new Error("network down");
    });
    const r = await fetchWithRetry("/api/x");
    expect(r.ok).toBe(false);
    expect(r.error).toBe("network down");
  });

  it("returns safe default on non-JSON response", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => { throw new Error("not json"); },
    }));
    const r = await fetchWithRetry("/api/x");
    expect(r.ok).toBe(true);
    expect(r.data).toBe(null);
  });
});
