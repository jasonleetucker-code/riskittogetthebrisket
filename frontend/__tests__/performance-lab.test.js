import { afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";

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
  expect(window.__CHASE_PERFORMANCE_LAB.droppedEvents).toBeUndefined();
  expect(window.__CHASE_PERFORMANCE_LAB.invalidEvents).toBeUndefined();
});
it("does not collect when browser opt-in is absent", async () => {
  const { performanceLabMark } = await helper("1", false);
  performanceLabMark("publish", "rankings");
  performanceLabMark("private", "private", { token: "secret" }, "private");
  expect(window.__CHASE_PERFORMANCE_LAB.events).toEqual([]);
  expect(window.__CHASE_PERFORMANCE_LAB.invalidEvents).toBeUndefined();
});
it("only collects enumerated phases/scopes and finite numeric fields", async () => {
  const { performanceLabMark } = await helper();
  performanceLabMark("publish", "rankings", { rows: 10, actualDuration: Infinity, playerId: "private", url: "private", token: "private" });
  performanceLabMark("private", "rankings");
  performanceLabMark("publish", "private");
  expect(window.__CHASE_PERFORMANCE_LAB.events).toEqual([{ phase: "publish", scope: "rankings", timeMs: expect.any(Number), rows: 10 }]);
  expect(window.__CHASE_PERFORMANCE_LAB.invalidEvents).toBe(2);
  expect(window.__CHASE_PERFORMANCE_LAB.invalidFields).toBe(4);
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
  expect(window.__CHASE_PERFORMANCE_LAB.droppedEvents).toBe(1);
});

it("counts real capacity loss without changing retained events", async () => {
  const { performanceLabMark } = await helper();
  for (let i = 0; i < 4003; i++) performanceLabMark("publish", "rankings", { rows: i });
  expect(window.__CHASE_PERFORMANCE_LAB.events).toHaveLength(4000);
  expect(window.__CHASE_PERFORMANCE_LAB.events.at(-1).rows).toBe(3999);
  expect(window.__CHASE_PERFORMANCE_LAB.droppedEvents).toBe(3);
});

it("allows fixed consumer marks and refuses private consumer identities", async () => {
  const { performanceLabMark } = await helper();
  performanceLabMark("module", "rankings", {}, "rankings-page");
  performanceLabMark("publish", "trade", { rows: 0 }, "trade-page");
  performanceLabMark("commit", "trade", {}, "private-player-42");
  expect(window.__CHASE_PERFORMANCE_LAB.events.map((event) => event.consumer)).toEqual(["rankings-page", "trade-page"]);
  expect(window.__CHASE_PERFORMANCE_LAB.invalidEvents).toBe(1);
  expect(JSON.stringify(window.__CHASE_PERFORMANCE_LAB)).not.toContain("private-player");
});

it("counts malformed fields and event containers without retaining invalid data", async () => {
  const { performanceLabMark } = await helper();
  performanceLabMark("publish", "trade", { rows: -1, actualDuration: NaN, url: "private" });
  expect(window.__CHASE_PERFORMANCE_LAB.invalidFields).toBe(3);
  expect(window.__CHASE_PERFORMANCE_LAB.events[0]).toEqual({ phase: "publish", scope: "trade", timeMs: expect.any(Number) });
  performanceLabMark("publish", "trade", null);
  window.__CHASE_PERFORMANCE_LAB.events = null;
  performanceLabMark("publish", "trade");
  expect(window.__CHASE_PERFORMANCE_LAB.invalidEvents).toBe(2);
});

it("keeps loss counters finite when saturated and repairs malformed counters", async () => {
  const { performanceLabMark } = await helper();
  window.__CHASE_PERFORMANCE_LAB.events.length = 4000;
  window.__CHASE_PERFORMANCE_LAB.droppedEvents = Number.MAX_SAFE_INTEGER;
  performanceLabMark("publish", "trade");
  expect(window.__CHASE_PERFORMANCE_LAB.droppedEvents).toBe(Number.MAX_SAFE_INTEGER);
  window.__CHASE_PERFORMANCE_LAB.invalidEvents = Infinity;
  performanceLabMark("private", "trade");
  expect(window.__CHASE_PERFORMANCE_LAB.invalidEvents).toBe(1);
});

it.each(["rankings", "trade"])("wires exactly one %s module observation and its fixed consumer", (route) => {
  const source = readFileSync(new URL(`../app/${route}/page.jsx`, import.meta.url), "utf8");
  const marks = [...source.matchAll(/performanceLabMark\("module",\s*"([^"]+)",\s*\{\},\s*"([^"]+)"\)/g)];
  expect(marks).toHaveLength(1);
  expect(marks[0].slice(1)).toEqual([route, `${route}-page`]);
  const imports = [...source.matchAll(/^import\s/gm)];
  expect(marks[0].index).toBeGreaterThan(imports.at(-1).index);
  expect(source).toContain(`useDynastyData({ readModel: "${route}", consumer: "${route}-page" })`);
});
