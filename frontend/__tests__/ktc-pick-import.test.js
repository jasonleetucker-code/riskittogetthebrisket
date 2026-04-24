import { describe, it, expect } from "vitest";
import { buildRows } from "../lib/dynasty-data.js";

describe("KTC pick import scenario — picks must land in rowByName", () => {
  it("legacy dict payload with players + picks — pick materializes", () => {
    const data = {
      players: {
        // A few ranked players so the backend-stamp fail-fast doesn't zero rows.
        "Jeremiyah Love": {
          _composite: 8500, _finalAdjusted: 8500,
          _canonicalConsensusRank: 50, rankDerivedValue: 8500,
        },
        "Jahmyr Gibbs": {
          _composite: 9200, _finalAdjusted: 9200,
          _canonicalConsensusRank: 12, rankDerivedValue: 9200,
        },
        // The picks the KTC URL includes.  Note NO _canonicalConsensusRank.
        "2027 Mid 4th": {
          _composite: 1400, _finalAdjusted: 1400,
          rankDerivedValue: 1400,
        },
      },
    };
    const rows = buildRows(data);
    const names = rows.map((r) => r.name);
    expect(names).toContain("Jeremiyah Love");
    expect(names).toContain("Jahmyr Gibbs");
    expect(names).toContain("2027 Mid 4th");  // this is the important one
  });

  it("playersArray payload — pick must materialize with displayName match", () => {
    const data = {
      playersArray: [
        {
          playerId: "11400", displayName: "Jeremiyah Love", canonicalName: "Jeremiyah Love",
          position: "RB", assetClass: "offense",
          canonicalConsensusRank: 50, rankDerivedValue: 8500,
          values: { displayValue: 8500, finalAdjusted: 8500, rawComposite: 8500 },
        },
        {
          playerId: "9479", displayName: "Jahmyr Gibbs", canonicalName: "Jahmyr Gibbs",
          position: "RB", assetClass: "offense",
          canonicalConsensusRank: 12, rankDerivedValue: 9200,
          values: { displayValue: 9200, finalAdjusted: 9200, rawComposite: 9200 },
        },
        {
          playerId: null, displayName: "2027 Mid 4th", canonicalName: "2027 Mid 4th",
          position: "PICK", assetClass: "pick",
          canonicalConsensusRank: null, rankDerivedValue: 1400,
          values: { displayValue: 1400, finalAdjusted: 1400, rawComposite: 0 },
        },
      ],
    };
    const rows = buildRows(data);
    const names = rows.map((r) => r.name);
    expect(names).toContain("Jeremiyah Love");
    expect(names).toContain("2027 Mid 4th");
    const pick = rows.find((r) => r.name === "2027 Mid 4th");
    expect(pick.pos).toBe("PICK");
    expect(pick.assetClass).toBe("pick");
  });
});
