/**
 * Tests for lib/dynasty-data.js — the data normalization layer
 * that feeds the trade page, rankings, and all other surfaces.
 */
import { describe, expect, it } from "vitest";
import {
  normalizePos,
  classifyPos,
  inferValueBundle,
  buildRows,
  getSiteKeys,
} from "@/lib/dynasty-data";

// ── normalizePos ─────────────────────────────────────────────────────

describe("normalizePos", () => {
  it("maps DE/DT/EDGE/NT → DL", () => {
    expect(normalizePos("DE")).toBe("DL");
    expect(normalizePos("DT")).toBe("DL");
    expect(normalizePos("EDGE")).toBe("DL");
    expect(normalizePos("NT")).toBe("DL");
  });

  it("maps CB/S/FS/SS → DB", () => {
    expect(normalizePos("CB")).toBe("DB");
    expect(normalizePos("S")).toBe("DB");
    expect(normalizePos("FS")).toBe("DB");
    expect(normalizePos("SS")).toBe("DB");
  });

  it("maps OLB/ILB → LB", () => {
    expect(normalizePos("OLB")).toBe("LB");
    expect(normalizePos("ILB")).toBe("LB");
  });

  it("passes through standard offense positions", () => {
    expect(normalizePos("QB")).toBe("QB");
    expect(normalizePos("RB")).toBe("RB");
    expect(normalizePos("WR")).toBe("WR");
    expect(normalizePos("TE")).toBe("TE");
  });

  it("uppercases lowercase input", () => {
    expect(normalizePos("qb")).toBe("QB");
    expect(normalizePos("de")).toBe("DL");
  });

  it("handles null/undefined/empty", () => {
    expect(normalizePos(null)).toBe("");
    expect(normalizePos(undefined)).toBe("");
    expect(normalizePos("")).toBe("");
  });
});

// ── classifyPos ──────────────────────────────────────────────────────

describe("classifyPos", () => {
  it("classifies offense positions", () => {
    expect(classifyPos("QB")).toBe("offense");
    expect(classifyPos("RB")).toBe("offense");
    expect(classifyPos("WR")).toBe("offense");
    expect(classifyPos("TE")).toBe("offense");
  });

  it("classifies IDP positions", () => {
    expect(classifyPos("DL")).toBe("idp");
    expect(classifyPos("DE")).toBe("idp");
    expect(classifyPos("LB")).toBe("idp");
    expect(classifyPos("DB")).toBe("idp");
    expect(classifyPos("CB")).toBe("idp");
  });

  it("classifies PICK", () => {
    expect(classifyPos("PICK")).toBe("pick");
  });

  it("classifies unknown as other", () => {
    expect(classifyPos("K")).toBe("other");
    expect(classifyPos("P")).toBe("other");
  });
});

// ── inferValueBundle ─────────────────────────────────────────────────

describe("inferValueBundle", () => {
  it("extracts all four value tiers from a full player", () => {
    const player = {
      _rawComposite: 8500,
      _scoringAdjusted: 8700,
      _scarcityAdjusted: 8900,
      _finalAdjusted: 9100,
    };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(8500);
    expect(v.scoring).toBe(8700);
    expect(v.scarcity).toBe(8900);
    expect(v.full).toBe(9100);
  });

  it("falls back through the value chain when fields are missing", () => {
    const player = { _composite: 5000 };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(5000);
    expect(v.scoring).toBe(5000);
    expect(v.scarcity).toBe(5000);
    expect(v.full).toBe(5000);
  });

  it("rounds values to integers", () => {
    const player = { _rawComposite: 8500.7 };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(8501);
  });

  it("prefers _canonicalDisplayValue for full when available", () => {
    const player = {
      _rawComposite: 7738,
      _scoringAdjusted: 7738,
      _scarcityAdjusted: 7738,
      _finalAdjusted: 7738,
      _canonicalDisplayValue: 9920,
    };
    const v = inferValueBundle(player);
    expect(v.full).toBe(9920);
    expect(v.raw).toBe(7738);
  });

  it("falls back to _finalAdjusted when _canonicalDisplayValue is missing", () => {
    const player = {
      _rawComposite: 7738,
      _finalAdjusted: 7738,
    };
    const v = inferValueBundle(player);
    expect(v.full).toBe(7738);
  });

  it("returns zeros for empty/undefined player", () => {
    const v = inferValueBundle({});
    expect(v.raw).toBe(0);
    expect(v.full).toBe(0);
  });

  it("handles undefined argument", () => {
    const v = inferValueBundle();
    expect(v.raw).toBe(0);
  });
});

// ── getSiteKeys ──────────────────────────────────────────────────────

describe("getSiteKeys", () => {
  it("extracts site keys from data", () => {
    const data = { sites: [{ key: "ktc" }, { key: "fantasyCalc" }] };
    expect(getSiteKeys(data)).toEqual(["ktc", "fantasyCalc"]);
  });

  it("returns empty array for missing sites", () => {
    expect(getSiteKeys({})).toEqual([]);
    expect(getSiteKeys(null)).toEqual([]);
  });

  it("filters out empty keys", () => {
    const data = { sites: [{ key: "" }, { key: "ktc" }, {}] };
    expect(getSiteKeys(data)).toEqual(["ktc"]);
  });
});

// ── buildRows ────────────────────────────────────────────────────────

describe("buildRows", () => {
  it("builds rows from playersArray (contract format)", () => {
    const data = {
      playersArray: [
        {
          displayName: "Josh Allen",
          position: "QB",
          assetClass: "offense",
          sourceCount: 6,
          values: {
            rawComposite: 8500,
            scoringAdjusted: 8700,
            scarcityAdjusted: null,
            finalAdjusted: 9100,
            overall: 9100,
          },
          canonicalSiteValues: { ktc: 8500 },
        },
        {
          displayName: "Micah Parsons",
          position: "LB",
          assetClass: "idp",
          sourceCount: 4,
          values: {
            rawComposite: 5000,
            finalAdjusted: 5200,
            overall: 5200,
          },
          canonicalSiteValues: {},
        },
      ],
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(2);

    const allen = rows.find((r) => r.name === "Josh Allen");
    expect(allen).toBeDefined();
    expect(allen.pos).toBe("QB");
    expect(allen.assetClass).toBe("offense");
    expect(allen.values.full).toBe(9100);
    expect(allen.values.raw).toBe(8500);
    expect(allen.siteCount).toBe(6);
  });

  it("builds rows from legacy players map", () => {
    const data = {
      players: {
        "Josh Allen": {
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 9100,
          _sites: 6,
          position: "QB",
        },
      },
      sleeper: { positions: { "Josh Allen": "QB" } },
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    expect(rows[0].values.full).toBe(9100);
    expect(rows[0].values.raw).toBe(8500);
  });

  it("prefers displayValue for full in contract format", () => {
    const data = {
      playersArray: [
        {
          displayName: "Josh Allen",
          position: "QB",
          assetClass: "offense",
          sourceCount: 6,
          values: {
            rawComposite: 7738,
            scoringAdjusted: 7738,
            scarcityAdjusted: 7738,
            finalAdjusted: 7738,
            overall: 7738,
            displayValue: 9920,
          },
          canonicalSiteValues: {},
        },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].values.full).toBe(9920);
    expect(rows[0].values.raw).toBe(7738);
  });

  it("falls back to finalAdjusted when displayValue is missing", () => {
    const data = {
      playersArray: [
        {
          displayName: "Josh Allen",
          position: "QB",
          values: { finalAdjusted: 7738, rawComposite: 7738, overall: 7738 },
        },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].values.full).toBe(7738);
  });

  it("sorts rows by full value descending", () => {
    const data = {
      playersArray: [
        { displayName: "Low", position: "RB", values: { finalAdjusted: 1000, rawComposite: 1000, overall: 1000 } },
        { displayName: "High", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 } },
        { displayName: "Mid", position: "WR", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 } },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].name).toBe("High");
    expect(rows[1].name).toBe("Mid");
    expect(rows[2].name).toBe("Low");
  });

  it("assigns ranks starting from 1", () => {
    const data = {
      playersArray: [
        { displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 } },
        { displayName: "B", position: "RB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 } },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].rank).toBe(1);
    expect(rows[1].rank).toBe(2);
  });

  it("filters out kickers", () => {
    const data = {
      playersArray: [
        { displayName: "Justin Tucker", position: "K", values: { finalAdjusted: 100, overall: 100, rawComposite: 100 } },
        { displayName: "Josh Allen", position: "QB", values: { finalAdjusted: 9000, overall: 9000, rawComposite: 9000 } },
      ],
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe("Josh Allen");
  });

  it("detects picks from legacy name pattern", () => {
    const data = {
      players: {
        "2026 Early 1st": { _composite: 7000, _finalAdjusted: 7000 },
        "2026 Pick 1.01": { _composite: 6500, _finalAdjusted: 6500 },
      },
    };
    const rows = buildRows(data);
    expect(rows.every((r) => r.pos === "PICK")).toBe(true);
    expect(rows.every((r) => r.assetClass === "pick")).toBe(true);
  });

  it("computes decimal consensus ranks from site values", () => {
    // Generate 25 players with varying site values across 2 sites
    const players = [];
    for (let i = 0; i < 25; i++) {
      players.push({
        displayName: `Player ${i}`,
        position: "QB",
        values: { finalAdjusted: 9000 - i * 100, rawComposite: 9000 - i * 100, overall: 9000 - i * 100 },
        canonicalSiteValues: {
          ktc: 9000 - i * 100,            // same order as full value
          fantasyCalc: 9000 - (24 - i) * 100,  // reversed order
        },
      });
    }
    const rows = buildRows({ playersArray: players });
    expect(rows.length).toBe(25);

    // Player 0 is rank 1 at ktc but rank 25 at fantasyCalc
    const p0 = rows.find((r) => r.name === "Player 0");
    expect(p0.computedConsensusRank).toBeDefined();
    expect(p0.computedConsensusRank).not.toBe(1); // should NOT be clean integer 1

    // Player 12 is rank 13 at both sites, so consensus should be 13
    const p12 = rows.find((r) => r.name === "Player 12");
    expect(p12.computedConsensusRank).toBeDefined();
    expect(p12.computedConsensusRank).toBe(13);

    // At least some players should have non-integer ranks
    const nonIntegers = rows.filter((r) => r.computedConsensusRank != null && r.computedConsensusRank % 1 !== 0);
    expect(nonIntegers.length).toBeGreaterThan(0);
  });

  it("computes consensus ranks even when players have different site coverage", () => {
    // 30 players across 3 sites, with some players missing from some sites
    const players = [];
    for (let i = 0; i < 30; i++) {
      const sites = { ktc: 9000 - i * 100 };
      if (i < 25) sites.fantasyCalc = 8000 - i * 80;
      if (i % 2 === 0) sites.dynastyDaddy = 7500 - i * 90;
      players.push({
        displayName: `TestPlayer ${i}`,
        position: i < 20 ? "QB" : "RB",
        values: { finalAdjusted: 9000 - i * 100, rawComposite: 9000 - i * 100, overall: 9000 - i * 100 },
        canonicalSiteValues: sites,
      });
    }
    const rows = buildRows({ playersArray: players });
    const withRank = rows.filter((r) => r.computedConsensusRank != null);
    expect(withRank.length).toBeGreaterThan(25);

    // Players with 3 sites should have more nuanced ranks than those with 1
    const p0 = rows.find((r) => r.name === "TestPlayer 0");
    const p1 = rows.find((r) => r.name === "TestPlayer 1");
    expect(p0.computedConsensusRank).toBeDefined();
    expect(p1.computedConsensusRank).toBeDefined();
    // Different rank due to different site coverage
    expect(p0.computedConsensusRank).not.toBe(p1.computedConsensusRank);
  });

  it("returns empty array for empty data", () => {
    expect(buildRows({})).toEqual([]);
    expect(buildRows({ players: {} })).toEqual([]);
  });

  it("skips players with no name", () => {
    const data = {
      playersArray: [
        { displayName: "", position: "QB", values: { overall: 5000 } },
        { displayName: "Josh Allen", position: "QB", values: { overall: 9000, finalAdjusted: 9000, rawComposite: 9000 } },
      ],
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
  });
});
