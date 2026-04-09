/**
 * Tests for lib/dynasty-data.js — the data normalization layer
 * that feeds the trade page, rankings, and all other surfaces.
 */
import { afterEach, describe, expect, it } from "vitest";
import {
  normalizePos,
  classifyPos,
  inferValueBundle,
  rankToValue,
  resolvedRank,
  buildRows,
  getSiteKeys,
  fetchDynastyData,
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
  it("extracts value tiers from a full player", () => {
    const player = {
      _rawComposite: 8500,
      _finalAdjusted: 9100,
    };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(8500);
    expect(v.full).toBe(9100);
  });

  it("falls back through the value chain when fields are missing", () => {
    const player = { _composite: 5000 };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(5000);
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
    const data = { sites: [{ key: "ktc" }, { key: "idpTradeCalc" }] };
    expect(getSiteKeys(data)).toEqual(["ktc", "idpTradeCalc"]);
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
    // Backend display value is preserved — NOT overwritten by rankDerivedValue.
    // values.full comes from backend finalAdjusted (9100), not from rank curve.
    expect(allen.values.full).toBe(9100);
    // rankDerivedValue is still computed and available for rankings "Our Value" display.
    expect(allen.rankDerivedValue).toBe(rankToValue(1));
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

    // rankDerivedValue is computed but does NOT overwrite values.full.
    // values.full preserves backend finalAdjusted (9000); rankDerivedValue is separate.
    expect(p0.rankDerivedValue).toBe(rankToValue(1)); // 9999
    expect(p0.values.full).toBe(9000); // backend value preserved

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

// ── Backend displayValue preservation (regression) ──────────────────

describe("displayValue preservation", () => {
  it("backend displayValue is preserved as values.full (not overwritten by rankDerivedValue)", () => {
    const data = {
      playersArray: [
        {
          displayName: "Josh Allen",
          position: "QB",
          values: { rawComposite: 8500, finalAdjusted: 9100, overall: 9100, displayValue: 9500 },
          canonicalSiteValues: { ktc: 8500 },
        },
      ],
    };
    const rows = buildRows(data);
    const allen = rows[0];
    // displayValue (9500) wins over finalAdjusted (9100)
    expect(allen.values.full).toBe(9500);
    // rankDerivedValue is still computed
    expect(allen.rankDerivedValue).toBeGreaterThan(0);
    // But values.full was NOT overwritten
    expect(allen.values.full).not.toBe(allen.rankDerivedValue);
  });

  it("computedConsensusRank (row.rank) is still assigned after sort", () => {
    const data = {
      playersArray: [
        { displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } },
        { displayName: "B", position: "RB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { ktc: 5000 } },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].rank).toBe(1);
    expect(rows[1].rank).toBe(2);
  });

  it("rankDerivedValue is still computed for KTC-ranked players", () => {
    const data = {
      playersArray: [
        { displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].rankDerivedValue).toBe(rankToValue(1));
  });

  it("values.full is NOT overwritten by rankDerivedValue in legacy path", () => {
    const data = {
      players: {
        "Josh Allen": {
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 9100,
          _sites: 6,
          _canonicalSiteValues: { ktc: 8500 },
          position: "QB",
        },
      },
      sleeper: { positions: { "Josh Allen": "QB" } },
      sites: [{ key: "ktc" }],
    };
    const rows = buildRows(data);
    // values.full should be finalAdjusted (9100), not rankDerivedValue
    expect(rows[0].values.full).toBe(9100);
    expect(rows[0].rankDerivedValue).toBeGreaterThan(0);
    expect(rows[0].values.full).not.toBe(rows[0].rankDerivedValue);
  });
});

// ── Rank precedence (resolvedRank) ──────────────────────────────────

describe("resolvedRank", () => {
  it("canonicalConsensusRank wins when present", () => {
    const row = { canonicalConsensusRank: 5, computedConsensusRank: 10 };
    expect(resolvedRank(row)).toBe(5);
  });

  it("falls back to computedConsensusRank when canonicalConsensusRank is null", () => {
    const row = { canonicalConsensusRank: null, computedConsensusRank: 10 };
    expect(resolvedRank(row)).toBe(10);
  });

  it("falls back to Infinity when both are null/missing", () => {
    expect(resolvedRank({})).toBe(Infinity);
    expect(resolvedRank({ canonicalConsensusRank: null })).toBe(Infinity);
  });

  it("handles undefined row gracefully", () => {
    expect(resolvedRank(null)).toBe(Infinity);
    expect(resolvedRank(undefined)).toBe(Infinity);
  });
});

// ── computedConsensusRank field ──────────────────────────────────────

describe("computedConsensusRank", () => {
  it("is assigned as explicit field on every row from playersArray path", () => {
    const data = {
      playersArray: [
        { displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } },
        { displayName: "B", position: "RB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { ktc: 5000 } },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].computedConsensusRank).toBe(1);
    expect(rows[1].computedConsensusRank).toBe(2);
  });

  it("is assigned as explicit field on every row from legacy path", () => {
    const data = {
      players: {
        "A": { _rawComposite: 9000, _finalAdjusted: 9000, _sites: 3, _canonicalSiteValues: { ktc: 9000 }, position: "QB" },
        "B": { _rawComposite: 5000, _finalAdjusted: 5000, _sites: 2, _canonicalSiteValues: { ktc: 5000 }, position: "RB" },
      },
      sleeper: { positions: { "A": "QB", "B": "RB" } },
    };
    const rows = buildRows(data);
    expect(rows[0].computedConsensusRank).toBe(1);
    expect(rows[1].computedConsensusRank).toBe(2);
  });

  it("row.rank uses canonicalConsensusRank when present, else computedConsensusRank", () => {
    const data = {
      playersArray: [
        {
          displayName: "Canonical",
          position: "QB",
          canonicalConsensusRank: 42,
          values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 },
          canonicalSiteValues: { ktc: 9000 },
        },
        {
          displayName: "Computed",
          position: "RB",
          values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 },
          canonicalSiteValues: { ktc: 5000 },
        },
      ],
    };
    const rows = buildRows(data);
    const canonical = rows.find(r => r.name === "Canonical");
    const computed = rows.find(r => r.name === "Computed");
    // canonicalConsensusRank (42) wins over computedConsensusRank (1)
    expect(canonical.rank).toBe(42);
    expect(canonical.computedConsensusRank).toBe(1);
    // Without canonicalConsensusRank, rank equals computedConsensusRank
    expect(computed.rank).toBe(computed.computedConsensusRank);
  });

  it("IDP players get idpRank and canonicalConsensusRank after offense", () => {
    const data = {
      playersArray: [
        // Offense player with KTC value
        { displayName: "QB Star", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } },
        // IDP player with IDP sources
        { displayName: "DL Star", position: "DL", values: { finalAdjusted: 6000, rawComposite: 6000, overall: 6000 }, canonicalSiteValues: { idpTradeCalc: 5800 } },
        // Another IDP player
        { displayName: "LB Star", position: "LB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { idpTradeCalc: 4000 } },
      ],
    };
    const rows = buildRows(data);
    const qb = rows.find(r => r.name === "QB Star");
    const dl = rows.find(r => r.name === "DL Star");
    const lb = rows.find(r => r.name === "LB Star");

    // Offense player gets ktcRank
    expect(qb.ktcRank).toBe(1);
    // IDP players get idpRank
    expect(dl.idpRank).toBe(1); // higher mean IDP value
    expect(lb.idpRank).toBe(2);
    // IDP canonicalConsensusRank offsets after offense count
    expect(dl.canonicalConsensusRank).toBe(2); // 1 offense + idpRank 1
    expect(lb.canonicalConsensusRank).toBe(3); // 1 offense + idpRank 2
    // IDP players have rankDerivedValue
    expect(dl.rankDerivedValue).toBeGreaterThan(0);
    expect(lb.rankDerivedValue).toBeGreaterThan(0);
    // Sort order: offense first, then IDP
    expect(rows[0].name).toBe("QB Star");
    expect(rows[1].name).toBe("DL Star");
    expect(rows[2].name).toBe("LB Star");
  });

  it("IDP players without IDP sources remain unranked", () => {
    const data = {
      playersArray: [
        { displayName: "Mystery DL", position: "DL", values: { finalAdjusted: 100, rawComposite: 100, overall: 100 }, canonicalSiteValues: {} },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].idpRank).toBeUndefined();
    expect(rows[0].rankDerivedValue).toBeUndefined();
  });
});

// ── fetchDynastyData response normalization (production regression) ──

describe("fetchDynastyData", () => {
  afterEach(() => {
    globalThis.fetch = undefined;
  });

  it("normalizes unwrapped Python backend contract to { ok, source, data }", async () => {
    // Simulate Python backend returning raw contract (no { ok, source, data } wrapper)
    const rawContract = {
      version: 4,
      date: "2026-04-07",
      scrapeTimestamp: "2026-04-07T21:14:51",
      players: { "Josh Allen": { _composite: 8500, _sites: 6 } },
      playersArray: [{ displayName: "Josh Allen", position: "QB", values: { overall: 8500 } }],
      playerCount: 1,
      dataSource: { type: "scrape", path: "/data/latest", loadedAt: "2026-04-07T21:15:00Z" },
    };
    globalThis.fetch = async () => ({ ok: true, json: async () => rawContract });

    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    expect(result.source).toBe("backend:scrape");
    expect(result.data).toBe(rawContract);
    expect(result.data.players).toBeDefined();
    expect(result.data.playersArray).toBeDefined();
  });

  it("passes through already-wrapped Next.js route response", async () => {
    const wrapped = {
      ok: true,
      source: "backend:http://127.0.0.1:8000/api/data?view=app",
      data: {
        players: { "Josh Allen": { _composite: 8500 } },
        version: 4,
      },
    };
    globalThis.fetch = async () => ({ ok: true, json: async () => wrapped });

    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    expect(result.source).toBe("backend:http://127.0.0.1:8000/api/data?view=app");
    expect(result.data.players).toBeDefined();
  });

  it("normalizes unwrapped contract without dataSource to date-based source", async () => {
    const rawContract = {
      version: 4,
      date: "2026-04-07",
      players: { "Josh Allen": { _composite: 8500 } },
    };
    globalThis.fetch = async () => ({ ok: true, json: async () => rawContract });

    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    expect(result.source).toBe("contract:2026-04-07");
    expect(result.data).toBe(rawContract);
  });

  it("buildRows produces rows from unwrapped backend contract (production regression)", () => {
    // Simulates the exact data shape the Python backend returns via /api/dynasty-data
    // Before the fix, payload.data was undefined, causing buildRows({}) → []
    const rawContract = {
      version: 4,
      date: "2026-04-07",
      players: {
        "Josh Allen": {
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 9100,
          _sites: 6,
          _canonicalSiteValues: { ktc: 8500 },
        },
      },
      sleeper: { positions: { "Josh Allen": "QB" } },
    };

    // This is what buildRows receives after fetchDynastyData normalizes:
    const rows = buildRows(rawContract);
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe("Josh Allen");
    expect(rows[0].pos).toBe("QB");
    expect(rows[0].values.full).toBe(9100);
  });
});
