import { describe, expect, it } from "vitest";
import {
  buildKtcNameIndex,
  normalizeKtcName,
  resolveKtcEntries,
} from "@/lib/ktc-import";

const rows = [
  { name: "Jahmyr Gibbs", pos: "RB" },
  { name: "Wan'Dale Robinson", pos: "WR" },
  { name: "Marvin Harrison Jr.", pos: "WR" },
  // Same name, two people: an offensive player and a defender.
  { name: "Josh Allen", pos: "QB" },
  { name: "Josh Allen", pos: "DL" },
  { name: "2027 Mid 4th", pos: "PICK" },
];

const index = buildKtcNameIndex(rows);

describe("resolveKtcEntries", () => {
  it("matches exact, case-insensitive and normalized names", () => {
    const out = resolveKtcEntries(
      [
        { name: "Jahmyr Gibbs", position: "RB" },
        { name: "wan'dale robinson", position: "WR" },
        { name: "Marvin Harrison", position: "WR" },
      ],
      index,
    );
    expect(out.found.map((r) => r.name)).toEqual([
      "Jahmyr Gibbs",
      "Wan'Dale Robinson",
      "Marvin Harrison Jr.",
    ]);
    expect(out.missing).toEqual([]);
    expect(out.ambiguous).toEqual([]);
  });

  it("splits same-name rows by KTC's stated position", () => {
    const out = resolveKtcEntries([{ name: "Josh Allen", position: "QB" }], index);
    expect(out.found).toEqual([{ name: "Josh Allen", pos: "QB" }]);
    expect(out.ambiguous).toEqual([]);
  });

  it("reports a same-name choice it could not settle instead of hiding it", () => {
    const out = resolveKtcEntries([{ name: "Josh Allen", position: "" }], index);
    expect(out.found).toHaveLength(1);
    expect(out.ambiguous).toEqual(["Josh Allen"]);
  });

  it("falls back to the caller's pick resolver only when no name matches", () => {
    const seen = [];
    const resolvePick = (name) => {
      seen.push(name);
      return name === "2026 1.09" ? { name: "2026 Pick 1.09", pos: "PICK" } : null;
    };
    const out = resolveKtcEntries(
      [
        { name: "2027 Mid 4th", position: "RDP" },
        { name: "2026 1.09", position: "RDP" },
      ],
      index,
      { resolvePick },
    );
    expect(out.found.map((r) => r.name)).toEqual(["2027 Mid 4th", "2026 Pick 1.09"]);
    expect(seen).toEqual(["2026 1.09"]);
  });

  it("keeps duplicates as copies and reports misses", () => {
    const out = resolveKtcEntries(
      [
        { name: "Jahmyr Gibbs", position: "RB" },
        { name: "Jahmyr Gibbs", position: "RB" },
        { name: "Nobody Real", position: "WR" },
      ],
      index,
    );
    expect(out.found.map((r) => r.name)).toEqual(["Jahmyr Gibbs", "Jahmyr Gibbs"]);
    expect(out.missing).toEqual(["Nobody Real"]);
  });
});

describe("normalizeKtcName", () => {
  it("drops punctuation and generational suffixes", () => {
    expect(normalizeKtcName("Marvin Harrison Jr.")).toBe("marvin harrison");
    expect(normalizeKtcName("  J.J.   McCarthy ")).toBe("jj mccarthy");
  });
});
