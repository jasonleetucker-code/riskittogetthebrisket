/**
 * Contract-fetch resilience (audit remediation, Task 9).
 *
 * Pins, for the shared player-contract fetch and its hook:
 *   1. a stalled backend hits a CLIENT deadline and surfaces as a
 *      recoverable "timed out" failure (not "offline"), and the failed
 *      request is not cached;
 *   2. a 503 surfaces as a classified failure with a working retry;
 *   3. unmounting while the request is in flight sets NO error state;
 *   4. the four trade tools render the shared FailureState with the hook's
 *      `retry` (no page keeps a private banner or a retry-less message).
 */
import fs from "node:fs";
import path from "node:path";
import * as url from "node:url";
import React from "react";
import { act, render, renderHook, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BASE_CONTRACT_TIMEOUT_MS,
  _resetBaseContractCache,
  fetchDynastyData,
} from "@/lib/dynasty-data.js";
import {
  classifyContractTimeout,
  failureForDisplay,
} from "@/lib/contract-failure";
import { FailureState } from "@/components/ds";

vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, hydrated: true }),
}));

const GOOD = {
  ok: true,
  source: "backend",
  data: {
    playersArray: [
      { displayName: "A", canonicalName: "A", position: "QB", team: "X", canonicalConsensusRank: 1, rankDerivedValue: 9000, sourceRanks: { ktc: 1 } },
    ],
  },
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  _resetBaseContractCache();
});
beforeEach(() => {
  _resetBaseContractCache();
});

describe("client deadline on the contract request", () => {
  it("is well above the measured ~0.5-0.65 s and well below nginx's 300 s", () => {
    expect(BASE_CONTRACT_TIMEOUT_MS).toBeGreaterThanOrEqual(15_000);
    expect(BASE_CONTRACT_TIMEOUT_MS).toBeLessThanOrEqual(60_000);
  });

  it("a request that never answers rejects with timedOut and aborts the fetch", async () => {
    vi.useFakeTimers();
    let signal = null;
    const fetchMock = vi.fn((_url, init) => {
      signal = init?.signal || null;
      return new Promise(() => {}); // never settles
    });
    vi.stubGlobal("fetch", fetchMock);
    const p = fetchDynastyData({});
    // The layer lazily imports device-profile before it issues the request;
    // the deadline timer starts only once the request is on the wire.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const settled = p.then(
      () => ({ ok: true }),
      (e) => ({ err: e }),
    );
    await vi.advanceTimersByTimeAsync(BASE_CONTRACT_TIMEOUT_MS + 10);
    const out = await settled;
    expect(out.err?.timedOut).toBe(true);
    expect(out.err?.status).toBeNull();
    expect(signal?.aborted).toBe(true);
  });

  it("a timed-out request is not cached: the next call goes back to the network", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockImplementationOnce(async () => ({ ok: true, json: async () => structuredClone(GOOD) }));
    vi.stubGlobal("fetch", fetchMock);
    const first = fetchDynastyData({}).catch((e) => e);
    await vi.advanceTimersByTimeAsync(BASE_CONTRACT_TIMEOUT_MS + 10);
    expect((await first).timedOut).toBe(true);
    const second = await fetchDynastyData({});
    expect(second.data.playersArray).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a fast response clears the timer (no late abort of a finished request)", async () => {
    vi.useFakeTimers();
    let signal = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_u, init) => {
        signal = init?.signal || null;
        return { ok: true, json: async () => structuredClone(GOOD) };
      }),
    );
    await fetchDynastyData({});
    await vi.advanceTimersByTimeAsync(BASE_CONTRACT_TIMEOUT_MS * 2);
    expect(signal?.aborted).toBe(false);
  });
});

describe("timeout classification", () => {
  it("is its own retryable kind, not 'offline'", () => {
    const f = classifyContractTimeout();
    expect(f.kind).toBe("timeout");
    expect(f.retryable).toBe(true);
    expect(f.message).toMatch(/too long/i);
  });

  it("FailureState renders it with Try again wired to onRetry", () => {
    const onRetry = vi.fn();
    render(<FailureState failure={classifyContractTimeout()} onRetry={onRetry} />);
    expect(screen.getByText(/timed out/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("failureForDisplay never returns null for a bare error string", () => {
    expect(failureForDisplay(null, "boom")).toMatchObject({ kind: "error", retryable: true, message: "boom" });
    expect(failureForDisplay(null, "")).toBeNull();
    const f = { kind: "degraded", message: "x" };
    expect(failureForDisplay(f, "boom")).toBe(f);
  });
});

describe("useDynastyData failure states", () => {
  async function loadHook() {
    vi.resetModules();
    return (await import("@/components/useDynastyData")).useDynastyData;
  }

  it("503 -> classified failure; retry() refetches and recovers", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) {
          return { ok: false, status: 503, text: async () => JSON.stringify({ error: "data_not_ready" }) };
        }
        return { ok: true, json: async () => structuredClone(GOOD) };
      }),
    );
    const useDynastyData = await loadHook();
    const { result } = renderHook(() => useDynastyData());
    await waitFor(() => expect(result.current.failure?.kind).toBe("degraded"));
    expect(result.current.error).toBeTruthy();
    await act(async () => {
      result.current.retry();
    });
    await waitFor(() => expect(result.current.failure).toBeNull());
    expect(result.current.rows.length).toBe(1);
  });

  it("deadline -> 'timeout' failure with Retry", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const useDynastyData = await loadHook();
    const { result } = renderHook(() => useDynastyData());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BASE_CONTRACT_TIMEOUT_MS + 100);
    });
    await waitFor(() => expect(result.current.failure?.kind).toBe("timeout"));
    expect(typeof result.current.retry).toBe("function");
  });

  it("unmounting mid-flight sets no error state and logs no failure", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const useDynastyData = await loadHook();
    const seen = [];
    const { result, unmount } = renderHook(() => {
      const r = useDynastyData();
      seen.push({ error: r.error, failure: r.failure });
      return r;
    });
    expect(result.current.loading).toBe(true);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BASE_CONTRACT_TIMEOUT_MS + 100);
    });
    expect(seen.every((s) => !s.error && !s.failure)).toBe(true);
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });
});

describe("trade tools use the shared FailureState with the hook's retry", () => {
  const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
  const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

  it.each([
    ["app/trade/page.jsx", "onRetry={retry}"],
    ["app/arbitrage/page.jsx", "onRetry={retryData}"],
    ["app/angle/page.jsx", "onRetry={retryData}"],
    ["app/edge/page.jsx", "onRetry={retry}"],
  ])("%s renders <FailureState ... %s>", (rel, retryProp) => {
    const src = read(rel);
    expect(src).toMatch(/<FailureState\b/);
    expect(src).toContain(retryProp);
    expect(src).toContain("failureForDisplay(");
  });

  it("/trade no longer prints the raw error under a retry-less banner", () => {
    expect(read("app/trade/page.jsx")).not.toContain("Couldn't load the player pool");
  });
});
