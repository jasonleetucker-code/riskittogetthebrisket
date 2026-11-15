/**
 * applyImportedSides — the one bulk-load rule shared by the KTC URL import
 * and the screenshot import on /trade.
 */
import { describe, expect, it } from "vitest";
import { applyImportedSides, createSide } from "@/lib/trade-logic";

const row = (name, extra = {}) => ({
  name,
  assetClass: "offense",
  values: { full: 100 },
  ...extra,
});

function twoSides() {
  const a = createSide(0);
  const b = createSide(1);
  a.assets = [row("Old A")];
  b.assets = [row("Old B")];
  return [a, b];
}

function threeSides() {
  const sides = [createSide(0), createSide(1), createSide(2)];
  sides[0].assets = [row("Old A")];
  sides[0].destinations = { "Old A": 2 };
  sides[1].assets = [row("Old B")];
  sides[1].destinations = { "Old B": 0 };
  sides[2].assets = [row("Kept C")];
  sides[2].destinations = { "Kept C": 1 };
  return sides;
}

describe("applyImportedSides — replace", () => {
  it("replaces sides A and B and keeps empty routing in a 2-team trade", () => {
    const next = applyImportedSides(
      twoSides(),
      [[row("New 1"), row("New 2")], [row("New 3")]],
      "replace",
    );
    expect(next.map((s) => s.assets.map((a) => a.name))).toEqual([
      ["New 1", "New 2"],
      ["New 3"],
    ]);
    expect(next[0].destinations).toEqual({});
    expect(next[1].destinations).toEqual({});
    expect(next[0].label).toBe("A");
  });

  it("leaves a third side untouched (same object) and seeds default routing", () => {
    const sides = threeSides();
    const next = applyImportedSides(
      sides,
      [[row("New 1")], [row("New 2")]],
      "replace",
    );
    expect(next[2]).toBe(sides[2]);
    // Stale routing for Old A / Old B is dropped; new entries go to the next side.
    expect(next[0].destinations).toEqual({ "New 1": 1 });
    expect(next[1].destinations).toEqual({ "New 2": 2 });
  });

  it("preserves repeated assets as repeated entries (never deduped)", () => {
    const pick = row("2027 Mid 1st", { assetClass: "pick" });
    const next = applyImportedSides(
      twoSides(),
      [[pick, pick, pick], [pick]],
      "replace",
    );
    expect(next[0].assets).toHaveLength(3);
    expect(next[1].assets).toHaveLength(1);
  });

  it("does not mutate its input", () => {
    const sides = twoSides();
    const snapshot = JSON.stringify(sides);
    applyImportedSides(sides, [[row("X")], [row("Y")]], "replace");
    expect(JSON.stringify(sides)).toBe(snapshot);
  });

  it("an empty import clears sides A and B", () => {
    const next = applyImportedSides(twoSides(), [[], []], "replace");
    expect(next[0].assets).toEqual([]);
    expect(next[1].assets).toEqual([]);
  });
});

describe("applyImportedSides — add", () => {
  it("appends to sides A and B, keeping what is already there", () => {
    const next = applyImportedSides(
      twoSides(),
      [[row("New 1")], [row("New 2")]],
      "add",
    );
    expect(next.map((s) => s.assets.map((a) => a.name))).toEqual([
      ["Old A", "New 1"],
      ["Old B", "New 2"],
    ]);
  });

  it("adding an asset already in the trade adds another copy", () => {
    const next = applyImportedSides(twoSides(), [[row("Old A")], []], "add");
    expect(next[0].assets.map((a) => a.name)).toEqual(["Old A", "Old A"]);
  });

  it("keeps existing routing and seeds only new lines in a 3+-team trade", () => {
    const sides = threeSides();
    const next = applyImportedSides(
      sides,
      [[row("Old A"), row("New 1")], [row("New 2")]],
      "add",
    );
    expect(next[0].destinations).toEqual({ "Old A": 2, "New 1": 1 });
    expect(next[1].destinations).toEqual({ "Old B": 0, "New 2": 2 });
    expect(next[2]).toBe(sides[2]);
  });
});
