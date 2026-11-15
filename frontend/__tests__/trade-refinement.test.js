import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  MAX_REFINEMENT_ASSETS,
  emptyRefinement,
  hasRefinement,
  loadRefinement,
  refinementKey,
  refinementState,
  saveRefinement,
  toRequest,
  toggleExclude,
  toggleLock,
  toggleSkip,
} from "@/lib/trade-refinement";

// The logic project runs in Node; give the module the one browser API it
// touches, as a plain in-memory store.
function memoryStorage() {
  const data = new Map();
  return {
    get length() {
      return data.size;
    },
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    clear: () => data.clear(),
  };
}

describe("trade refinement (C3-CON-03)", () => {
  beforeEach(() => {
    globalThis.window = { localStorage: memoryStorage() };
  });
  afterEach(() => {
    delete globalThis.window;
  });

  it("LOCK and EXCLUDE are mutually exclusive per player", () => {
    let r = toggleLock(emptyRefinement(), "Bob");
    expect(refinementState(r, "bob")).toBe("lock");
    r = toggleExclude(r, "Bob");
    expect(r.lock).toEqual([]);
    expect(r.exclude).toEqual(["Bob"]);
    r = toggleLock(r, "BOB ");
    expect(r.exclude).toEqual([]);
    expect(r.lock).toEqual(["BOB"]);
  });

  it("toggling the same control twice clears it", () => {
    const r = toggleExclude(toggleExclude(emptyRefinement(), "Al"), "al");
    expect(r.exclude).toEqual([]);
    expect(hasRefinement(r)).toBe(false);
  });

  it("several refinements may be active at once", () => {
    let r = emptyRefinement();
    r = toggleLock(r, "A");
    r = toggleLock(r, "B");
    r = toggleExclude(r, "C");
    r = toggleSkip(r, "Target");
    expect(r).toEqual({ lock: ["A", "B"], exclude: ["C"], skip: ["Target"] });
  });

  it("the wire shape never carries Skip (an incoming filter, not a constraint)", () => {
    const r = toggleSkip(toggleLock(emptyRefinement(), "Zed"), "Target");
    expect(toRequest(r)).toEqual({ lock: ["Zed"], exclude: [] });
  });

  it("persists LOCK / EXCLUDE until cleared, but never Skip", () => {
    const key = refinementKey({ owner: "o1", leagueKey: "lg", surface: "s", context: "c" });
    expect(key).toBe("rit.refinement.v1:o1:lg:s:c");
    let r = toggleSkip(toggleExclude(toggleLock(emptyRefinement(), "A"), "B"), "T");
    saveRefinement(key, r);
    expect(loadRefinement(key)).toEqual({ lock: ["A"], exclude: ["B"], skip: [] });
    saveRefinement(key, emptyRefinement());
    expect(window.localStorage.getItem(key)).toBeNull();
  });

  it("refinements are scoped: another league or context starts empty", () => {
    const a = refinementKey({ owner: "o1", leagueKey: "lg1", surface: "s", context: "c" });
    const b = refinementKey({ owner: "o1", leagueKey: "lg2", surface: "s", context: "c" });
    saveRefinement(a, toggleLock(emptyRefinement(), "A"));
    expect(loadRefinement(b)).toEqual(emptyRefinement());
  });

  it("a corrupted or contradictory stored value is repaired, never trusted", () => {
    const key = "rit.refinement.v1:x:y:z:w";
    window.localStorage.setItem(key, "{not json");
    expect(loadRefinement(key)).toEqual(emptyRefinement());
    window.localStorage.setItem(key, JSON.stringify({ lock: ["A"], exclude: ["a", 7, "B"] }));
    expect(loadRefinement(key)).toEqual({ lock: ["A"], exclude: ["B"], skip: [] });
  });

  it("caps each list at the server's limit", () => {
    let r = emptyRefinement();
    for (let i = 0; i < MAX_REFINEMENT_ASSETS + 5; i += 1) r = toggleLock(r, `P${i}`);
    expect(r.lock).toHaveLength(MAX_REFINEMENT_ASSETS);
  });
});
