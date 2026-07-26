// A transient failure on /api/auth/status must NOT be reported as a
// signed-out user.
//
// The bug these pin: the hook capped the probe at 5s with an
// AbortController and, on timeout with no cached flag, resolved
// authenticated = false with no retry.  A valid session was then
// stranded on the anonymous shell for the entire life of the page —
// no nav, no search, no team switcher — until a manual reload.
//
// These are deliberately driven by SIMULATED aborts/failures and fake
// timers rather than real elapsed time: the defect is timing-dependent,
// and asserting on wall-clock behaviour would be slow and flaky.
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAuth } from "@/components/useAuth";

function authResponse(authenticated) {
  return { ok: true, status: 200, json: async () => ({ authenticated }) };
}

/** What fetch does when an AbortController fires — what the 5s cap produces. */
function abortError() {
  const err = new Error("The operation was aborted.");
  err.name = "AbortError";
  return err;
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  try {
    sessionStorage.clear();
  } catch {
    /* jsdom always has it; guard anyway */
  }
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useAuth — a timeout is not a sign-out", () => {
  it("stays UNKNOWN (not false) when the probe aborts", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw abortError(); }));

    const { result } = renderHook(() => useAuth());
    await flush();

    // The load-bearing assertion.  Pre-fix this was `false`, which
    // consumers render as a genuine signed-out user.
    expect(result.current.authenticated).toBeNull();
    expect(result.current.authUnknown).toBe(true);
    // ...and the UI must never be left wedged on "checking".
    expect(result.current.checking).toBe(false);
  });

  it("recovers a valid session on its own after transient aborts", async () => {
    const failing = vi.fn(async () => { throw abortError(); });
    vi.stubGlobal("fetch", failing);

    const { result } = renderHook(() => useAuth());
    await flush();
    expect(result.current.authenticated).toBeNull();
    const attemptsWhileDown = failing.mock.calls.length;

    // Backend recovers.  No remount, no user action — the scheduled
    // retry must pick it up.
    vi.stubGlobal("fetch", vi.fn(async () => authResponse(true)));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    expect(result.current.authenticated).toBe(true);
    expect(result.current.authUnknown).toBe(false);
    expect(attemptsWhileDown).toBeGreaterThan(0);
  });

  it("keeps retrying with backoff across repeated failures", async () => {
    const failing = vi.fn(async () => { throw abortError(); });
    vi.stubGlobal("fetch", failing);

    renderHook(() => useAuth());
    await flush();
    const afterFirst = failing.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    const afterBackoff = failing.mock.calls.length;

    // Pre-fix there was exactly one probe, ever.
    expect(afterBackoff).toBeGreaterThan(afterFirst);
  });

  it("treats a 5xx as infrastructure, not as an answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 502, json: async () => ({}) })),
    );

    const { result } = renderHook(() => useAuth());
    await flush();

    expect(result.current.authenticated).toBeNull();
    expect(result.current.authUnknown).toBe(true);
  });

  it("keeps painting an optimistic session through a blip", async () => {
    sessionStorage.setItem("next_auth_checked_v1", "true");
    vi.stubGlobal("fetch", vi.fn(async () => { throw abortError(); }));

    const { result } = renderHook(() => useAuth());
    await flush();

    // A cached "was signed in" must not be torn down by a blip.
    expect(result.current.authenticated).toBe(true);
    expect(result.current.authUnknown).toBe(true);
  });
});

describe("useAuth — a real answer is still authoritative", () => {
  it("commits false when the backend actually says signed out", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => authResponse(false)));

    const { result } = renderHook(() => useAuth());
    await flush();

    // Genuine sign-out must remain distinguishable from unknown.
    expect(result.current.authenticated).toBe(false);
    expect(result.current.authUnknown).toBe(false);
    expect(result.current.checking).toBe(false);
  });

  it("signs out a stale cached session when the cookie is gone", async () => {
    // The regression the original stale-while-revalidate guarded:
    // a cached true + a real 'no' must end as false, not stay true.
    sessionStorage.setItem("next_auth_checked_v1", "true");
    vi.stubGlobal("fetch", vi.fn(async () => authResponse(false)));

    const { result } = renderHook(() => useAuth());
    await flush();

    expect(result.current.authenticated).toBe(false);
    expect(sessionStorage.getItem("next_auth_checked_v1")).toBeNull();
  });

  it("stops probing once an authoritative answer lands", async () => {
    const ok = vi.fn(async () => authResponse(true));
    vi.stubGlobal("fetch", ok);

    renderHook(() => useAuth());
    await flush();
    const settled = ok.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(ok.mock.calls.length).toBe(settled);
  });
});
