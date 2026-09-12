import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { useTerminal, invalidateTerminalCache } from "@/components/useTerminal";

const settings = vi.hoisted(() => ({ valuationMode: "market" }));
vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings }) }));
let pending;
let ignoreAbort;
beforeEach(() => {
  settings.valuationMode = "market";
  ignoreAbort = false;
  localStorage.clear();
  invalidateTerminalCache();
  pending = [];
  vi.stubGlobal("fetch", vi.fn((url, options) => new Promise((resolve, reject) => {
    pending.push({ url, options, resolve, reject });
    options.signal?.addEventListener("abort", () => { if (!ignoreAbort) reject(new DOMException("Aborted", "AbortError")); });
  })));
});
afterEach(() => { cleanup(); invalidateTerminalCache(); vi.unstubAllGlobals(); });
async function finish(index, value, status = 200) {
  await act(async () => pending[index].resolve(new Response(JSON.stringify({ authenticated: true, team: { ownerId: value }, teamAggregates: { totalValue: 0 } }), { status })));
}

it("separates an absent team name from the literal underscore name", async () => {
  const automatic = renderHook(() => useTerminal());
  await finish(0, "automatic-team");
  const explicit = renderHook(() => useTerminal({ teamName: "_" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(pending[1].url).toContain("teamName=_");
  expect(explicit.result.current.team).toBeNull();
  await finish(1, "underscore-team");
  expect(automatic.result.current.team.ownerId).toBe("automatic-team");
  expect(explicit.result.current.team.ownerId).toBe("underscore-team");
});

it("separates delimiter-bearing owner and name components", async () => {
  const first = renderHook(() => useTerminal({ ownerId: "a::b", teamName: "c" }));
  const second = renderHook(() => useTerminal({ ownerId: "a", teamName: "b::c" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(new URL(pending[0].url, "http://localhost").searchParams.get("team")).toBe("a::b");
  expect(new URL(pending[1].url, "http://localhost").searchParams.get("teamName")).toBe("b::c");
  await finish(0, "first");
  await finish(1, "second");
  expect(first.result.current.team.ownerId).toBe("first");
  expect(second.result.current.team.ownerId).toBe("second");
});

it("keeps one shared request alive when its first subscriber unmounts", async () => {
  const first = renderHook(() => useTerminal({ ownerId: "A" }));
  const second = renderHook(() => useTerminal({ ownerId: "A" }));
  expect(fetch).toHaveBeenCalledTimes(1);
  first.unmount();
  await finish(0, "A");
  expect(second.result.current.loading).toBe(false);
  expect(second.result.current.team.ownerId).toBe("A");
});

it("does not publish a joined old owner response after switching owner", async () => {
  renderHook(() => useTerminal({ ownerId: "A" }));
  const view = renderHook(({ ownerId }) => useTerminal({ ownerId }), { initialProps: { ownerId: "A" } });
  view.rerender({ ownerId: "B" });
  await finish(1, "B");
  await finish(0, "A");
  expect(view.result.current.team.ownerId).toBe("B");
});

it("clears old data while skipped and ignores joined completion", async () => {
  renderHook(() => useTerminal({ ownerId: "A" }));
  const view = renderHook(({ skip }) => useTerminal({ ownerId: "A", skip }), { initialProps: { skip: false } });
  view.rerender({ skip: true });
  await finish(0, "A");
  expect(view.result.current.team).toBeNull();
  expect(view.result.current.loading).toBe(true);
});

it("auth change invalidates cached private state and fetches again", async () => {
  const view = renderHook(() => useTerminal({ ownerId: "A" }));
  await finish(0, "session-one");
  act(() => window.dispatchEvent(new Event("auth:changed")));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(view.result.current.team).toBeNull();
  await finish(1, "session-two");
  expect(view.result.current.team.ownerId).toBe("session-two");
});

it("invalidated completion cannot replace the new same-key cache or delete its flight", async () => {
  ignoreAbort = true;
  const old = renderHook(() => useTerminal({ ownerId: "A" }));
  act(() => invalidateTerminalCache());
  old.unmount();
  const fresh = renderHook(() => useTerminal({ ownerId: "A" }));
  await finish(0, "old");
  const joined = renderHook(() => useTerminal({ ownerId: "A" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  await finish(1, "fresh");
  expect(fresh.result.current.team.ownerId).toBe("fresh");
  expect(joined.result.current.team.ownerId).toBe("fresh");
});

it("last subscriber cancellation cannot poison a replacement even when transport ignores abort", async () => {
  ignoreAbort = true;
  const old = renderHook(() => useTerminal({ ownerId: "A" }));
  old.unmount();
  expect(pending[0].options.signal.aborted).toBe(true);
  const fresh = renderHook(() => useTerminal({ ownerId: "A" }));
  await finish(0, "old");
  const joined = renderHook(() => useTerminal({ ownerId: "A" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  await finish(1, "fresh");
  expect(fresh.result.current.team.ownerId).toBe("fresh");
  expect(joined.result.current.team.ownerId).toBe("fresh");
});

it("clears cached session data on auth change while no subscriber is mounted", async () => {
  const old = renderHook(() => useTerminal({ ownerId: "A" }));
  await finish(0, "old-session");
  old.unmount();
  act(() => window.dispatchEvent(new Event("auth:changed")));
  const fresh = renderHook(() => useTerminal({ ownerId: "A" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fresh.result.current.team).toBeNull();
  await finish(1, "new-session");
  expect(fresh.result.current.team.ownerId).toBe("new-session");
});

it("retains the withdrawn valuation setting as canonical market behavior", async () => {
  const view = renderHook(() => useTerminal({ ownerId: "A" }));
  await finish(0, "canonical");
  settings.valuationMode = "leagueAdjusted";
  view.rerender();
  await act(async () => {});
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(view.result.current.team.ownerId).toBe("canonical");
  expect(pending[0].url).not.toContain("leagueAdjusted");
});

it("does not cache failed requests and permits a later subscriber to retry", async () => {
  const first = renderHook(() => useTerminal({ ownerId: "A" }));
  await act(async () => pending[0].reject(new Error("offline")));
  expect(first.result.current.loading).toBe(false);
  expect(first.result.current.error).toBe("offline");
  const retry = renderHook(() => useTerminal({ ownerId: "A" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  await finish(1, "recovered");
  expect(retry.result.current.team.ownerId).toBe("recovered");
});

it("league change has one new flight and cannot publish previous league data", async () => {
  localStorage.setItem("next_active_league_v1", "league-a");
  const a = renderHook(() => useTerminal({ ownerId: "A" }));
  const b = renderHook(() => useTerminal({ ownerId: "A" }));
  act(() => { localStorage.setItem("next_active_league_v1", "league-b"); window.dispatchEvent(new Event("league:changed")); });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(pending[1].url).toContain("leagueKey=league-b");
  await finish(1, "league-b");
  await finish(0, "league-a");
  expect(a.result.current.team.ownerId).toBe("league-b");
  expect(b.result.current.team.ownerId).toBe("league-b");
});

it("retains 503 response semantics and zero-valued aggregates", async () => {
  const view = renderHook(() => useTerminal({ ownerId: "A" }));
  await finish(0, "A", 503);
  expect(view.result.current.loading).toBe(false);
  expect(view.result.current.error).toBeNull();
  expect(view.result.current.teamAggregates.totalValue).toBe(0);
});
