// @vitest-environment node
import { describe, it, expect } from "vitest";

import { rosterRowsForTeam } from "@/components/waivers/ManualAddDrop";
import { normalizeName, normalizeNameCompact } from "@/lib/waiver-logic";

// Pure-helper coverage for the manual add/drop selector.  The
// React component itself is exercised manually + via the next
// build pipeline; the helpers below are pure data-shape ops and
// deserve unit pins so a regression in normalization or filtering
// surfaces here, not as a confusing UI bug on /waivers.

function row(name, value, opts = {}) {
  return {
    name,
    pos: opts.pos || "WR",
    team: opts.team || "",
    blendedSourceRank: opts.rank ?? null,
    raw: opts.raw || {},
    assetClass: opts.assetClass || "offense",
    rookie: Boolean(opts.rookie),
    values: { full: value },
  };
}

// The component no longer defines its own normalizer — it imports the
// shared one.  These pins moved with it.
describe("normalizeNameCompact", () => {
  it("lowercases and strips non-alphanumerics", () => {
    expect(normalizeNameCompact("Ja'Marr Chase")).toBe("jamarrchase");
    expect(normalizeNameCompact("D.J. Moore")).toBe("djmoore");
    expect(normalizeNameCompact("  Foo Bar 1st  ")).toBe("foobar1st");
  });

  it("returns empty string for falsy input", () => {
    expect(normalizeNameCompact(null)).toBe("");
    expect(normalizeNameCompact(undefined)).toBe("");
    expect(normalizeNameCompact("")).toBe("");
  });

  it("is a strictly different key from the backend-parity normalizer", () => {
    // Both exist on purpose; this pin is here so nobody swaps one for
    // the other assuming they are interchangeable.
    expect(normalizeName("D.J. Moore")).toBe("d.j. moore");
    expect(normalizeNameCompact("D.J. Moore")).toBe("djmoore");
  });
});

describe("rosterRowsForTeam", () => {
  const allRows = [
    row("Ja'Marr Chase", 9908, { pos: "WR" }),
    row("Travis Etienne", 4200, { pos: "RB" }),
    row("Bo Nix", 3000, { pos: "QB" }),
    row("UnknownPlayer", 0, { pos: "WR" }),       // no value — skipped
    row("Phantom Pick", 1500, { pos: "PICK", assetClass: "pick" }), // pick — skipped
  ];

  it("returns rows for roster names that match by normalized lookup", () => {
    const out = rosterRowsForTeam(allRows, [
      "ja'marr chase",
      "Travis Etienne",
      "Bo Nix",
    ]);
    expect(out.map((r) => r.name)).toEqual([
      "Bo Nix",
      "Travis Etienne",
      "Ja'Marr Chase",
    ]); // ascending value: Nix (3000) < Etienne (4200) < Chase (9908)
  });

  it("skips picks and zero-value rows", () => {
    const out = rosterRowsForTeam(allRows, [
      "UnknownPlayer",
      "Phantom Pick",
      "Bo Nix",
    ]);
    expect(out.map((r) => r.name)).toEqual(["Bo Nix"]);
  });

  it("dedups same-normalized names", () => {
    const out = rosterRowsForTeam(allRows, [
      "Bo Nix",
      "bo  nix",
      "BoNix",
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].name).toBe("Bo Nix");
  });

  // The map is built from contract row names and probed with Sleeper
  // roster strings — two vocabularies that disagree on punctuation.
  // Both sides must use the SAME key or the roster player silently
  // disappears from the drop pool.
  it("resolves names that differ only by punctuation on both sides of the join", () => {
    const punctuated = [
      row("DJ Moore", 6100, { pos: "WR" }),
      row("Amon-Ra St. Brown", 8200, { pos: "WR" }),
    ];
    const out = rosterRowsForTeam(punctuated, [
      "D.J. Moore",          // roster string punctuated, row is not
      "Amon-Ra St.Brown",    // roster string missing a space
    ]);
    expect(out.map((r) => r.name)).toEqual(["DJ Moore", "Amon-Ra St. Brown"]);
  });

  it("returns empty arrays for non-arrays / unknown rosters", () => {
    expect(rosterRowsForTeam(null, ["Bo Nix"])).toEqual([]);
    expect(rosterRowsForTeam(allRows, null)).toEqual([]);
    expect(rosterRowsForTeam(allRows, ["NotInPool"])).toEqual([]);
  });

  it("ignores names that don't appear in the rows pool", () => {
    const out = rosterRowsForTeam(allRows, [
      "Ja'Marr Chase",
      "GhostName",
    ]);
    expect(out.map((r) => r.name)).toEqual(["Ja'Marr Chase"]);
  });
});

