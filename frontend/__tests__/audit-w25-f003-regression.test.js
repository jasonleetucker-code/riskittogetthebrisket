/**
 * Master-site-audit W25-F003, display half (CW-40 P1 re-adjudication, 2026-11-06) -- REPAIRED (unpriced rows are no longer numbered).
 *
 * The finding's main claim is a CLAUDE.md accuracy error (pinned in
 * tests/api/test_audit_w25_f003_regression.py).  Its "observed" paragraph also records the
 * consequence in `buildRows`: a non-pick row the backend left rank-less because the board
 * could NOT price it (rankDerivedValue null) still receives a client display ordinal in the
 * `#` column, indistinguishable from a real board rank.
 *
 * Repaired: `buildRows` no longer numbers unpriced rows, so the former `it.fails` pin is a
 * plain test asserting the correct behaviour (an unpriced row shows no `#`).  Priced off-cap
 * rows (#1101) are deliberately left numbered here -- that is the documented display ordinal
 * and is not what this pins.
 */
import { describe, expect, it } from "vitest";

import { buildRows, resolvedRank } from "@/lib/dynasty-data";

function player(name, extra) {
  return {
    displayName: name,
    canonicalName: name,
    position: "WR",
    team: "XXX",
    assetClass: "offense",
    ...extra,
  };
}

const CONTRACT = {
  playersArray: [
    player("Ranked One", { canonicalConsensusRank: 1, rankDerivedValue: 9000 }),
    player("Ranked Two", { canonicalConsensusRank: 2, rankDerivedValue: 8000 }),
    player("Off Cap Priced", {
      canonicalConsensusRank: null,
      rankDerivedValue: 500,
      offCapPlayerValue: true,
    }),
    player("Unpriced", { canonicalConsensusRank: null, rankDerivedValue: null }),
  ],
};

describe("W25-F003: rank-less rows in buildRows", () => {
  it("backend-stamped ranks always win and rank-less priced rows sort by value", () => {
    const rows = buildRows(CONTRACT);
    const byName = Object.fromEntries(rows.map((r) => [r.name, r]));
    expect(byName["Ranked One"].rank).toBe(1);
    expect(byName["Ranked Two"].rank).toBe(2);
    expect(byName["Off Cap Priced"].computedConsensusRank).toBe(3);
  });

  it("an unpriced row gets no `#` ordinal", () => {
    const rows = buildRows(CONTRACT);
    const unpriced = rows.find((r) => r.name === "Unpriced");
    expect(unpriced).toBeTruthy();
    expect(unpriced.rank).toBeNull();
  });

  it("an unpriced row reads as unranked everywhere: no ordinal, Infinity resolved rank, sorts last", () => {
    const rows = buildRows(CONTRACT);
    const unpriced = rows.find((r) => r.name === "Unpriced");
    expect(unpriced.computedConsensusRank).toBeNull();
    expect(resolvedRank(unpriced)).toBe(Infinity);
    expect(rows[rows.length - 1].name).toBe("Unpriced");
  });
});
