/**
 * Suppressed tier-pick aliases are re-anchored to their priced slot row.
 *
 * Once a class becomes current, the board keeps "2027 Mid 1st" only as an
 * unpriced alias of "2027 Pick 1.06" (``pickAliases``).  A trade saved,
 * shared or KTC-imported by NAME used to land on the alias and render as
 * "—" / unpriced.  ``canonicalTradeEntry`` / ``reanchorSuppressedPickEntries``
 * move such entries onto the slot row the board actually prices.
 */
import { describe, expect, it } from "vitest";
import {
  canonicalTradeEntry,
  deserializeWorkspaceMulti,
  reanchorSuppressedPickEntries,
} from "@/lib/trade-logic";

const MID = {
  name: "2027 Mid 1st",
  pos: "PICK",
  assetClass: "pick",
  rankDerivedValue: null,
  values: { full: 0 },
  pickGenericSuppressed: true,
};
const SLOT = {
  name: "2027 Pick 1.06",
  pos: "PICK",
  assetClass: "pick",
  rankDerivedValue: 4887,
  values: { full: 4887 },
};
const PLAYER = { name: "Cam Ward", pos: "QB", assetClass: "offense", rankDerivedValue: 3817 };
const ALIASES = { "2027 Mid 1st": "2027 Pick 1.06" };

const rows = [MID, SLOT, PLAYER];
const byLower = new Map(rows.map((r) => [r.name.toLowerCase(), r]));
const byName = new Map(rows.map((r) => [r.name, r]));

describe("canonicalTradeEntry", () => {
  it("follows the alias to the priced slot row", () => {
    expect(canonicalTradeEntry(MID, byLower, ALIASES)).toBe(SLOT);
  });

  it("works without the alias map (stale contract) via the slot candidates", () => {
    expect(canonicalTradeEntry(MID, byLower, null)?.name).toBe("2027 Pick 1.06");
  });

  it("leaves priced rows and players alone", () => {
    expect(canonicalTradeEntry(SLOT, byLower, ALIASES)).toBe(SLOT);
    expect(canonicalTradeEntry(PLAYER, byLower, ALIASES)).toBe(PLAYER);
  });

  it("keeps an owned pick's canonical id and label", () => {
    const owned = { ...MID, assetId: "pick:dynasty_main:2027:r1:o3", assetLabel: "2027 Mid 1st (own)" };
    const fixed = canonicalTradeEntry(owned, byLower, ALIASES);
    expect(fixed.rankDerivedValue).toBe(4887);
    expect(fixed.assetId).toBe("pick:dynasty_main:2027:r1:o3");
    expect(fixed.assetLabel).toBe("2027 Mid 1st (own)");
  });

  it("never drops an entry nothing resolves", () => {
    const orphan = { ...MID, name: "2031 Mid 1st" };
    expect(canonicalTradeEntry(orphan, new Map(), {})).toBe(orphan);
  });
});

describe("reanchorSuppressedPickEntries", () => {
  it("re-prices every copy and moves destinations with the entry", () => {
    const sides = [
      { id: 0, label: "A", assets: [MID, MID, MID, PLAYER], destinations: { "2027 Mid 1st": 2 } },
      { id: 1, label: "B", assets: [SLOT], destinations: {} },
    ];
    const next = reanchorSuppressedPickEntries(sides, byLower, ALIASES);
    expect(next).not.toBe(sides);
    expect(next[0].assets.map((a) => a.name)).toEqual([
      "2027 Pick 1.06",
      "2027 Pick 1.06",
      "2027 Pick 1.06",
      "Cam Ward",
    ]);
    expect(next[0].assets.every((a) => a.rankDerivedValue != null)).toBe(true);
    expect(next[0].destinations).toEqual({ "2027 Pick 1.06": 2 });
    expect(next[1]).toBe(sides[1]);
  });

  it("returns the same array when nothing needs re-anchoring (no effect loop)", () => {
    const sides = [{ id: 0, label: "A", assets: [SLOT, PLAYER], destinations: {} }];
    expect(reanchorSuppressedPickEntries(sides, byLower, ALIASES)).toBe(sides);
  });

  it("repairs a workspace saved before the class roll", () => {
    const saved = { version: 2, sides: [{ assets: ["2027 Mid 1st", "2027 Mid 1st", "Cam Ward"] }, { assets: [] }] };
    const restored = deserializeWorkspaceMulti(saved, byName);
    expect(restored.sides[0].assets[0].pickGenericSuppressed).toBe(true); // the bug's input
    const fixed = reanchorSuppressedPickEntries(restored.sides, byLower, ALIASES);
    expect(fixed[0].assets.map((a) => a.rankDerivedValue)).toEqual([4887, 4887, 3817]);
  });
});
