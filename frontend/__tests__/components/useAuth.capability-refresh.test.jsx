// The nav capability map must not be pinned for the life of a tab.
//
// Owner report 2026-11-03 (MD-35): signed in on desktop, /waivers showed
// neither the My Team "Waiver Advisor" / "Weekly IDP Streaming" entries
// nor the Related links, until a hard reload — while the server's
// /api/auth/status answered both capabilities `available: true`.  useAuth
// probed once on mount and never again after a 200, so a transient answer
// (backend restart mid-deploy, a board not loaded yet) stuck.
//
// Fake timers fake Date.now too, so "older than 60 s" is driven exactly.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen } from "@testing-library/react";
import { REFRESH_INTERVAL_MS, REFRESH_MIN_AGE_MS, useAuth } from "@/components/useAuth";
import { relatedNavItems } from "@/lib/nav-model";

const OFF = { waiverAdvisor: { available: false }, idpStreaming: { available: false } };
const ON = { waiverAdvisor: { available: true }, idpStreaming: { available: true } };

function status(body) {
  return { ok: true, status: 200, json: async () => body };
}
const signedIn = (features) => status({ authenticated: true, features });

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function setVisibility(state) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
}

async function focusWindow() {
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setVisibility("visible");
  try {
    sessionStorage.clear();
  } catch {
    /* jsdom always has it */
  }
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setVisibility("visible");
});

describe("useAuth capability refresh (MD-35)", () => {
  it("a stale tab re-probes on focus after 60 s and the gated items appear", async () => {
    const fetchMock = vi.fn(async () => signedIn(OFF));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAuth());
    await flush();
    expect(result.current.authenticated).toBe(true);
    expect(relatedNavItems(["/waiver-advisor"], { capabilities: result.current.features })).toEqual([]);

    // The server now answers available (board loaded / deploy finished).
    fetchMock.mockImplementation(async () => signedIn(ON));
    await flush(REFRESH_MIN_AGE_MS + 1);
    await focusWindow();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.features).toEqual(ON);
    expect(
      relatedNavItems(["/waiver-advisor", "/waiver-advisor?mode=streaming"], {
        capabilities: result.current.features,
      }).map((i) => i.label),
    ).toEqual(["Waiver Advisor", "Weekly IDP Streaming"]);
  });

  it("the nav re-renders from the refreshed map with no reload", async () => {
    // End to end through a consumer: the menus/drawer/palette/Related
    // rows all read the hook's `features` state (AppShellWrapper ->
    // AuthContext / AppShell capabilities), so a state change is enough.
    const fetchMock = vi.fn(async () => signedIn(OFF));
    vi.stubGlobal("fetch", fetchMock);
    function Probe() {
      const { features } = useAuth();
      const items = relatedNavItems(["/waiver-advisor"], { capabilities: features });
      return <p>{items.map((i) => i.label).join(",") || "none"}</p>;
    }
    render(<Probe />);
    await flush();
    expect(screen.getByText("none")).toBeInTheDocument();
    fetchMock.mockImplementation(async () => signedIn(ON));
    await flush(REFRESH_MIN_AGE_MS + 1);
    await focusWindow();
    expect(screen.getByText("Waiver Advisor")).toBeInTheDocument();
  });

  it("re-probes on the interval while visible", async () => {
    const fetchMock = vi.fn(async () => signedIn(OFF));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAuth());
    await flush();
    fetchMock.mockImplementation(async () => signedIn(ON));
    await flush(REFRESH_INTERVAL_MS);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.features).toEqual(ON);
  });

  it("a failed re-probe keeps the previous authoritative state", async () => {
    const fetchMock = vi.fn(async () => signedIn(ON));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAuth());
    await flush();
    // sessionStorage cache gone too: the old code would have fallen to
    // unknown (null) here, tearing down the signed-in shell.
    sessionStorage.clear();

    fetchMock.mockImplementation(async () => ({ ok: false, status: 502, json: async () => ({}) }));
    await flush(REFRESH_MIN_AGE_MS + 1);
    await focusWindow();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.authenticated).toBe(true);
    expect(result.current.features).toEqual(ON);

    // ...and the existing backoff retries, recovering on its own.
    fetchMock.mockImplementation(async () => signedIn(ON));
    await flush(1500);
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(result.current.authenticated).toBe(true);
  });

  it("a network error on re-probe also keeps the state", async () => {
    const fetchMock = vi.fn(async () => signedIn(ON));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAuth());
    await flush();
    fetchMock.mockImplementation(async () => {
      throw new TypeError("Failed to fetch");
    });
    await flush(REFRESH_MIN_AGE_MS + 1);
    await focusWindow();
    expect(result.current.authenticated).toBe(true);
    expect(result.current.features).toEqual(ON);
  });

  it("does not re-probe while the tab is hidden", async () => {
    const fetchMock = vi.fn(async () => signedIn(OFF));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useAuth());
    await flush();
    setVisibility("hidden");
    await flush(REFRESH_INTERVAL_MS * 2);
    await focusWindow();
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Becoming visible again (stale by now) re-probes once.
    setVisibility("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not thrash on repeated focus inside 60 s", async () => {
    const fetchMock = vi.fn(async () => signedIn(OFF));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useAuth());
    await flush();
    for (let i = 0; i < 5; i += 1) {
      await flush(5_000);
      await focusWindow();
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await flush(REFRESH_MIN_AGE_MS);
    await focusWindow();
    await focusWindow();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("signed out: a refresh carries no features, even if the body sends some", async () => {
    const fetchMock = vi.fn(async () => status({ authenticated: false, features: ON }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAuth());
    await flush();
    expect(result.current.authenticated).toBe(false);
    expect(result.current.features).toBeNull();
    await flush(REFRESH_MIN_AGE_MS + 1);
    await focusWindow();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.authenticated).toBe(false);
    expect(result.current.features).toBeNull();
  });

  it("an authoritative sign-out on re-probe is still committed (session expired)", async () => {
    const fetchMock = vi.fn(async () => signedIn(ON));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAuth());
    await flush();
    fetchMock.mockImplementation(async () => status({ authenticated: false }));
    await flush(REFRESH_MIN_AGE_MS + 1);
    await focusWindow();
    expect(result.current.authenticated).toBe(false);
    expect(result.current.features).toBeNull();
  });
});
