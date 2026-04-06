/**
 * Tests for lib/dynasty-data.js — the data normalization layer
 * that feeds the trade page, rankings, and all other surfaces.
 */
import { describe, expect, it } from "vitest";
import {
  normalizePos,
  classifyPos,
  inferValueBundle,
  rankToValue,
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

describe("rankToValue", () => {
  it("maps rank 1 to exactly 9999", () => {
    expect(rankToValue(1)).toBe(9999);
  });

  it("produces correct outputs for ranks 1–10", () => {
    const expected = [9999, 9849, 9684, 9515, 9347, 9180, 9016, 8855, 8698, 8544];
    expected.forEach((v, i) => expect(rankToValue(i + 1)).toBe(v));
  });

  it("produces correct checkpoint values", () => {
    expect(rankToValue(25)).toBe(6663);
    expect(rankToValue(50)).toBe(4766);
    expect(rankToValue(100)).toBe(2959);
    expect(rankToValue(200)).toBe(1632);
    expect(rankToValue(300)).toBe(1108);
    expect(rankToValue(500)).toBe(663);
  });

  it("produces monotonically decreasing values as rank increases", () => {
    const ranks = [1, 5, 10, 25, 50, 100, 200, 500];
    const values = ranks.map(rankToValue);
    for (let i = 1; i < values.length; i++) {
      expect(values[i]).toBeLessThan(values[i - 1]);
    }
  });

  it("returns 0 for invalid rank inputs", () => {
    expect(rankToValue(0)).toBe(0);
    expect(rankToValue(-1)).toBe(0);
    expect(rankToValue(null)).toBe(0);
    expect(rankToValue(undefined)).toBe(0);
  });

  it("returns values in 1–9999 range", () => {
    for (const rank of [1, 10, 100, 500, 1000]) {
      const v = rankToValue(rank);
      expect(v).toBeGreaterThanOrEqual(1);
      expect(v).toBeLessThanOrEqual(9999);
    }
  });

  it("top-50 value is meaningfully above replacement level", () => {
    // rank-50 ≈ 4766, well above 1 and below rank-1
    const v50 = rankToValue(50);
    expect(v50).toBeGreaterThan(1000);
    expect(v50).toBeLessThan(rankToValue(1));
  });
});

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
    // KTC-rank-first: values.full = rankDerivedValue from KTC rank (not raw finalAdjusted)
    expect(allen.values.full).toBe(allen.rankDerivedValue > 0 ? allen.rankDerivedValue : 9100);
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

  it("does not let name-based sleeper position override canonical offense", () => {
    const data = {
      players: {
        "Josh Allen": {
          _sleeperId: "111",
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 9100,
          _sites: 6,
          position: "QB",
        },
      },
      sleeper: {
        positions: { "Josh Allen": "LB" },
        playerIds: { "Josh Allen": "111" },
        positionsById: { "111": "LB" },
      },
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    expect(rows[0].pos).toBe("QB");
    expect(rows[0].assetClass).toBe("offense");
  });

  it("requires stable sleeper id before using legacy name-based fallback", () => {
    const data = {
      players: {
        "Alex Carter": {
          _sleeperId: "OFF-1",
          _composite: 5000,
          _rawComposite: 5000,
          _finalAdjusted: 5000,
          _sites: 3,
          position: "",
        },
      },
      sleeper: {
        positions: { "Alex Carter": "LB" },
        playerIds: { "Alex Carter": "DEF-2" },
        positionsById: { "DEF-2": "LB" },
      },
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    expect(rows[0].pos).toBe("?");
    expect(rows[0].assetClass).toBe("other");
  });

  it("backfills missing positionsById from legacy name map when sleeper ids match", () => {
    const data = {
      players: {
        "Player One": {
          _sleeperId: "1",
          _composite: 9000,
          _rawComposite: 9000,
          _finalAdjusted: 9000,
          _sites: 3,
          position: "",
        },
        "Player Two": {
          _sleeperId: "2",
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 8500,
          _sites: 3,
          position: "",
        },
      },
      sleeper: {
        positionsById: { "1": "QB" }, // partial map from backend
        positions: { "Player One": "QB", "Player Two": "WR" },
        playerIds: { "Player One": "1", "Player Two": "2" },
      },
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(2);
    const one = rows.find((r) => r.name === "Player One");
    const two = rows.find((r) => r.name === "Player Two");
    expect(one.pos).toBe("QB");
    expect(two.pos).toBe("WR");
  });

  it("recomputes assetClass from normalized position in playersArray", () => {
    const data = {
      playersArray: [
        {
          displayName: "Roquan Smith",
          position: "LB",
          assetClass: "offense",
          values: { finalAdjusted: 5300, rawComposite: 5300, overall: 5300 },
          canonicalSiteValues: { ktc: 5300 },
        },
      ],
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    expect(rows[0].assetClass).toBe("idp");
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

  it("sorts rows by KTC rank ascending (rank-first)", () => {
    // KTC rank is derived from canonicalSites.ktc value; higher ktc = lower rank number.
    const data = {
      playersArray: [
        { displayName: "Low", position: "RB", values: { finalAdjusted: 1000, rawComposite: 1000, overall: 1000 }, canonicalSiteValues: { ktc: 1000 } },
        { displayName: "High", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } },
        { displayName: "Mid", position: "WR", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { ktc: 5000 } },
      ],
    };
    const rows = buildRows(data);
    const ranked = rows.filter((r) => r.ktcRank > 0);
    expect(ranked[0].name).toBe("High");
    expect(ranked[1].name).toBe("Mid");
    expect(ranked[2].name).toBe("Low");
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

  it("computes integer KTC ranks from canonicalSites.ktc values", () => {
    // Generate 25 players with varying KTC values
    const players = [];
    for (let i = 0; i < 25; i++) {
      players.push({
        displayName: `Player ${i}`,
        position: "QB",
        values: { finalAdjusted: 9000 - i * 100, rawComposite: 9000 - i * 100, overall: 9000 - i * 100 },
        canonicalSiteValues: { ktc: 9000 - i * 100 },
      });
    }
    const rows = buildRows({ playersArray: players });
    expect(rows.length).toBe(25);

    // Player 0 has highest KTC value → should be rank 1
    const p0 = rows.find((r) => r.name === "Player 0");
    expect(p0.ktcRank).toBe(1);
    expect(Number.isInteger(p0.ktcRank)).toBe(true); // always integer, never decimal

    // Player 24 has lowest KTC value → should be rank 25
    const p24 = rows.find((r) => r.name === "Player 24");
    expect(p24.ktcRank).toBe(25);

    // Rank-first: values.full should equal rankDerivedValue
    expect(p0.rankDerivedValue).toBe(rankToValue(1)); // 9999
    expect(p0.values.full).toBe(p0.rankDerivedValue);

    // Rows should be sorted by ktcRank ascending
    const rankedRows = rows.filter((r) => r.ktcRank > 0);
    for (let i = 1; i < rankedRows.length; i++) {
      expect(rankedRows[i].ktcRank).toBeGreaterThan(rankedRows[i - 1].ktcRank);
    }
  });

  it("assigns KTC ranks even when players have different site coverage", () => {
    // 30 players — KTC rank is driven solely by canonicalSites.ktc, regardless
    // of whether other sites have data.
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
    const withRank = rows.filter((r) => r.ktcRank != null);
    expect(withRank.length).toBe(30); // all 30 have ktc data

    // Player 0 has highest KTC value → rank 1
    const p0 = rows.find((r) => r.name === "TestPlayer 0");
    expect(p0.ktcRank).toBe(1);

    // Player 1 has next highest KTC value → rank 2
    const p1 = rows.find((r) => r.name === "TestPlayer 1");
    expect(p1.ktcRank).toBe(2);

    // All ranks are unique integers
    const rankSet = new Set(withRank.map((r) => r.ktcRank));
    expect(rankSet.size).toBe(30);
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
