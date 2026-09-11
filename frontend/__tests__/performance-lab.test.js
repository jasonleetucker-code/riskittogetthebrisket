import { afterEach, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); });
async function helper(build = "1", enabled = true) {
  vi.stubEnv("NEXT_PUBLIC_PERFORMANCE_LAB", build);
  vi.stubGlobal("window", { __CHASE_PERFORMANCE_LAB: { enabled, events: [] } });
  return import("@/lib/performance-lab.js");
}
it("requires both compile-time and browser opt-in; normal JSON path stays native", async () => {
  const { performanceLabMark, performanceLabJson } = await helper("0");
  performanceLabMark("publish", "rankings");
  const response = { json: vi.fn().mockResolvedValue({ ok: true }), text: vi.fn() };
  expect(await performanceLabJson(response, "rankings")).toEqual({ ok: true });
  expect(response.json).toHaveBeenCalledOnce();
  expect(response.text).not.toHaveBeenCalled();
  expect(window.__CHASE_PERFORMANCE_LAB.events).toEqual([]);
});
it("does not collect when browser opt-in is absent", async () => {
  const { performanceLabMark } = await helper("1", false);
  performanceLabMark("publish", "rankings");
  expect(window.__CHASE_PERFORMANCE_LAB.events).toEqual([]);
});
it("only collects enumerated phases/scopes and finite numeric fields", async () => {
  const { performanceLabMark } = await helper();
  performanceLabMark("publish", "rankings", { rows: 10, actualDuration: Infinity, playerId: "private", url: "private", token: "private" });
  performanceLabMark("private", "rankings");
  performanceLabMark("publish", "private");
  expect(window.__CHASE_PERFORMANCE_LAB.events).toEqual([{ phase: "publish", scope: "rankings", timeMs: expect.any(Number), rows: 10 }]);
});
it("separates body reading from JSON parsing only in diagnostics", async () => {
  const { performanceLabJson } = await helper();
  expect(await performanceLabJson({ text: async () => '{"ok":true}' }, "trade")).toEqual({ ok: true });
  expect(window.__CHASE_PERFORMANCE_LAB.events.map((event) => event.phase)).toEqual(["body-start", "body-end", "parse-start", "parse-end"]);
});
it("records parse completion on invalid JSON and preserves rejection", async () => {
  const { performanceLabJson } = await helper();
  await expect(performanceLabJson({ text: async () => "invalid" }, "trade")).rejects.toThrow(SyntaxError);
  expect(window.__CHASE_PERFORMANCE_LAB.events.at(-1).phase).toBe("parse-end");
});
it("bounds collection and does not retain arbitrary profiler IDs", async () => {
  const { performanceLabProfile, performanceLabMark } = await helper();
  performanceLabProfile("private-id", "mount", 10, 20, 30, 40);
  expect(window.__CHASE_PERFORMANCE_LAB.events[0]).toEqual({ phase: "profile-mount", scope: "shell", timeMs: expect.any(Number), actualDuration: 10, baseDuration: 20, startTime: 30, commitTime: 40 });
  window.__CHASE_PERFORMANCE_LAB.events.length = 4000;
  performanceLabMark("publish", "rankings");
  expect(window.__CHASE_PERFORMANCE_LAB.events.length).toBe(4000);
});
