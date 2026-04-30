// @vitest-environment node
import { describe, it, expect } from "vitest";

import {
  normName,
  rosterRowsForTeam,
} from "@/components/waivers/ManualAddDrop";

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

describe("normName", () => {
  it("lowercases and strips non-alphanumerics", () => {
    expect(normName("Ja'Marr Chase")).toBe("jamarrchase");
    expect(normName("D.J. Moore")).toBe("djmoore");
    expect(normName("  Foo Bar 1st  ")).toBe("foobar1st");
  });

  it("returns empty string for falsy input", () => {
    expect(normName(null)).toBe("");
    expect(normName(undefined)).toBe("");
    expect(normName("")).toBe("");
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

