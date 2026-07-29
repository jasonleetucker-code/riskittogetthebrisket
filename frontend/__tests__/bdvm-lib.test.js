/**
 * bdvm-lib.test.js — the /bdvm display helpers.
 *
 * Dangerous cases, in order:
 * 1. The three 503 variants MUST classify differently — rendering
 *    flag-off as a generic error (or vice versa) misleads the operator.
 * 2. Null market values must render as absence ("—"), never as 0 — the
 *    backend's §9.5 no-fabrication rule extends to the UI.
 * 3. Row building must not mutate the payload (it is cached by the
 *    hook and re-shaped per strategy switch).
 * 4. Strategy switching must re-order rows by THAT currency — the
 *    whole point of strategy currencies is that the order changes.
 */

import { describe, expect, it } from "vitest";
import {
  classifyBdvmFailure,
  buildBdvmValueRows,
  buildBdvmPickRows,
  buildBdvmRosterRows,
  buildBdvmTradeRows,
  buildBdvmIndex,
  bdvmEntryForRow,
  bdvmSignalEdgeCss,
  bdvmGroupOptions,
  bdvmSignalTone,
  bdvmDirectionTone,
  formatBdvmValue,
  formatBdvmGap,
  formatBdvmDecimal,
} from "@/lib/bdvm";

function player(name, overrides = {}) {
  return {
    playerId: `id-${name}`,
    name,
    position: "WR",
    group: "WR",
    raw: { age: 25.0 },
    tradeValue: { contender: 5000, balanced: 5000, rebuilder: 5000, risk_neutral: 5000 },
    projection: { fpg: 15.0, sourceCount: 2, anyProxy: false, sources: ["a"] },
    market: { marketValue: 4800, marketSource: "ktcSfTep", gap: 200.0 },
    signal: { signal: "BUY", reason: "gap" },
    quality: { confidenceScore: 0.7, confidenceLabel: "medium" },
    range: { floor_p20: 4000, median: 5000, ceiling_p85: 6200 },
    dynastyScore0to100: 88.2,
    ...overrides,
  };
}

describe("classifyBdvmFailure", () => {
  it("distinguishes the three 503 variants", () => {
    expect(classifyBdvmFailure(503, { error: "feature_disabled", flag: "bdvm_engine" }).kind).toBe(
      "disabled",
    );
    expect(classifyBdvmFailure(503, { error: "data_not_ready", message: "m" }).kind).toBe(
      "not_ready",
    );
    expect(classifyBdvmFailure(503, { error: "bdvm_unavailable", message: "boom" }).kind).toBe(
      "unavailable",
    );
  });

  it("maps 401 to auth and unknown statuses to error with a message", () => {
    expect(classifyBdvmFailure(401, null).kind).toBe("auth");
    const err = classifyBdvmFailure(500, null);
    expect(err.kind).toBe("error");
    expect(err.message).toBe("HTTP 500");
  });

  it("returns null on 2xx", () => {
    expect(classifyBdvmFailure(200, { status: "ok" })).toBeNull();
  });

  it("survives a non-JSON body", () => {
    expect(classifyBdvmFailure(503, null).kind).toBe("error");
  });
});

describe("buildBdvmValueRows", () => {
  it("orders by the selected strategy currency and stamps 1-based ranks", () => {
    const payload = {
      players: [
        player("Old Vet", {
          tradeValue: { contender: 9000, balanced: 6000, rebuilder: 2000, risk_neutral: 6000 },
        }),
        player("Young Stash", {
          tradeValue: { contender: 3000, balanced: 5500, rebuilder: 8000, risk_neutral: 5500 },
        }),
      ],
    };
    const byContender = buildBdvmValueRows(payload, "contender");
    expect(byContender.map((r) => r.name)).toEqual(["Old Vet", "Young Stash"]);
    expect(byContender[0].rank).toBe(1);
    const byRebuilder = buildBdvmValueRows(payload, "rebuilder");
    expect(byRebuilder.map((r) => r.name)).toEqual(["Young Stash", "Old Vet"]);
  });

  it("does not mutate the payload", () => {
    const payload = { players: [player("A"), player("B")] };
    const snapshot = JSON.stringify(payload);
    buildBdvmValueRows(payload, "balanced");
    expect(JSON.stringify(payload)).toBe(snapshot);
  });

  it("carries null market fields as null, never 0", () => {
    const payload = {
      players: [
        player("No Market", {
          market: {
            marketValue: null,
            marketSource: null,
            gap: null,
            liquidity: 0.0,
          },
          signal: { signal: "NO_MARKET", reason: "no anchor" },
        }),
      ],
    };
    const [row] = buildBdvmValueRows(payload, "balanced");
    expect(row.marketValue).toBeNull();
    expect(row.gap).toBeNull();
    expect(formatBdvmValue(row.marketValue)).toBe("—");
    expect(formatBdvmGap(row.gap)).toBe("—");
  });

  it("flags proxy projections", () => {
    const payload = {
      players: [player("Proxy Guy", { projection: { fpg: 8, anyProxy: true, sourceCount: 1 } })],
    };
    expect(buildBdvmValueRows(payload, "balanced")[0].anyProxy).toBe(true);
  });

  it("handles a missing players array", () => {
    expect(buildBdvmValueRows({}, "balanced")).toEqual([]);
    expect(buildBdvmValueRows(null, "balanced")).toEqual([]);
  });
});

describe("bdvmGroupOptions", () => {
  it("orders known groups QB-first and appends unknowns", () => {
    const rows = [{ group: "LB" }, { group: "QB" }, { group: "XX" }, { group: "QB" }];
    expect(bdvmGroupOptions(rows)).toEqual(["QB", "LB", "XX"]);
  });
});

describe("buildBdvmPickRows", () => {
  it("sorts priced picks by strategy EV and sinks unpriced ones", () => {
    const payload = {
      picks: [
        { name: "2027 Mid 1st", assetClass: "pick", distribution: null, reason: "unparseable_pick_name", market: { marketValue: 5000, marketSource: "ktcSfTep", liquidity: 0.5 } },
        { name: "2027 1.05", assetClass: "pick", overallSlot: 5, pickYear: 2027, yearsOut: 1, market: { marketValue: 6000, marketSource: "ktcSfTep", liquidity: 0.5 }, distribution: { balanced: { ev: 4200, p_hit: 0.4, p_mid: 0.3, p_miss: 0.3, ceiling: 8000, median: 3800, class_strength: 1.0, years_out: 1.0 } } },
      ],
    };
    const rows = buildBdvmPickRows(payload, "balanced");
    expect(rows[0].name).toBe("2027 1.05");
    expect(rows[0].ev).toBe(4200);
    expect(rows[1].unpriced).toBe(true);
    expect(rows[1].ev).toBeNull();
  });
});

describe("buildBdvmRosterRows", () => {
  it("flattens capitals and keeps assets for the drawer", () => {
    const payload = {
      rosters: [
        {
          name: "Team A",
          ownerId: "o1",
          rosterId: 1,
          assetCount: 20,
          unmatchedPlayerIds: 2,
          capitals: { contender: 50000.5, balanced: 48000, rebuilder: 40000, risk_neutral: 47000 },
          nowFutureRatio: 1.25,
          valueWeightedAge: 26.4,
          starterFpg: 130.2,
          positionalSurplus: { WR: 1 },
          pickCount: 4,
          assets: [{ playerId: "p", name: "X", tradeValue: { balanced: 9000 } }],
          direction: "contend",
          strategy: "contender",
        },
      ],
    };
    const [row] = buildBdvmRosterRows(payload);
    expect(row.key).toBe("o1");
    expect(row.contender).toBe(50000.5);
    expect(row.direction).toBe("contend");
    expect(row.assets).toHaveLength(1);
  });
});

describe("buildBdvmTradeRows", () => {
  it("flattens both sides with own-currency gains", () => {
    const payload = {
      trades: [
        {
          from: { ownerId: "a", name: "Team A", strategy: "contender", gives: ["X", "Y"], gain: 400.0 },
          to: { ownerId: "b", name: "Team B", strategy: "rebuilder", gives: ["Z"], gain: 250.0 },
          marketFairnessPct: 6.5,
          fairnessBasis: "single_market",
          doublePositive: true,
          minGain: 250.0,
        },
      ],
    };
    const [row] = buildBdvmTradeRows(payload);
    expect(row.aGives).toEqual(["X", "Y"]);
    expect(row.bGain).toBe(250.0);
    expect(row.minGain).toBe(250.0);
    expect(row.fairnessBasis).toBe("single_market");
  });
});

describe("buildBdvmIndex + bdvmEntryForRow (rankings gap join)", () => {
  const payload = {
    players: [
      player("Elite Backer", { playerId: "sid1" }),
      player("No Id Guy", { playerId: null }),
    ],
  };

  it("joins playerId-first, then canonical name key", () => {
    const index = buildBdvmIndex(payload);
    // rankings rows carry playerId at top level or under raw
    expect(bdvmEntryForRow(index, { raw: { playerId: "sid1" }, name: "X" }).gap).toBe(200.0);
    expect(bdvmEntryForRow(index, { playerId: "sid1", name: "X" }).gap).toBe(200.0);
    expect(bdvmEntryForRow(index, { name: "NO ID GUY" }).gap).toBe(200.0);
    expect(bdvmEntryForRow(index, { name: "Unknown Player" })).toBeNull();
  });

  // The BDVM projection snapshot and the scrape contract are two
  // separate name vocabularies, so the fallback has to survive
  // punctuation / suffix / accent variance.  A bare toLowerCase key
  // (the pre-fix behaviour) missed every case below and the Fund gap
  // column silently went blank for those players.
  it("name fallback tolerates punctuation, suffix and accent variants", () => {
    const index = buildBdvmIndex({
      players: [
        player("DJ Moore", { playerId: null, market: { gap: 111, marketValue: 1 } }),
        player("Ken Walker III", { playerId: null, market: { gap: 222, marketValue: 2 } }),
        player("Amon-Ra St. Brown", { playerId: null, market: { gap: 333, marketValue: 3 } }),
        player("JaMarr Chase", { playerId: null, market: { gap: 444, marketValue: 4 } }),
      ],
    });
    expect(bdvmEntryForRow(index, { name: "D.J. Moore" }).gap).toBe(111);
    expect(bdvmEntryForRow(index, { name: "Kenneth Walker" })).toBeNull(); // different first name, still no guess
    expect(bdvmEntryForRow(index, { name: "Ken Walker" }).gap).toBe(222);
    expect(bdvmEntryForRow(index, { name: "Amon-Rá St.Brown" }).gap).toBe(333);
    expect(bdvmEntryForRow(index, { name: "Ja'Marr Chase" }).gap).toBe(444);
  });

  it("playerId still wins over a name that resolves elsewhere", () => {
    const index = buildBdvmIndex({
      players: [
        player("Alpha One", { playerId: "sid-a", market: { gap: 10, marketValue: 1 } }),
        player("Bravo Two", { playerId: "sid-b", market: { gap: 20, marketValue: 2 } }),
      ],
    });
    // Row names "Bravo Two" but carries Alpha's id — the id decides.
    expect(bdvmEntryForRow(index, { playerId: "sid-a", name: "Bravo Two" }).gap).toBe(10);
    expect(bdvmEntryForRow(index, { raw: { playerId: "sid-b" }, name: "Alpha One" }).gap).toBe(20);
  });

  it("returns null for an empty or non-ok payload shape", () => {
    expect(buildBdvmIndex({ players: [] })).toBeNull();
    expect(buildBdvmIndex(null)).toBeNull();
  });

  it("null index resolves nothing (column vanishes)", () => {
    expect(bdvmEntryForRow(null, { name: "Elite Backer" })).toBeNull();
  });

  it("entries carry the tooltip fields", () => {
    const index = buildBdvmIndex(payload);
    const entry = bdvmEntryForRow(index, { name: "elite backer" });
    expect(entry.fundamental).toBe(5000);
    expect(entry.marketValue).toBe(4800);
    expect(entry.signal).toBe("BUY");
  });

  it("maps signals onto the Edge column's pill classes", () => {
    expect(bdvmSignalEdgeCss("BUY")).toBe("edge-buy");
    expect(bdvmSignalEdgeCss("STRONG_SELL")).toBe("edge-sell");
    expect(bdvmSignalEdgeCss("HOLD")).toBe("edge-hold");
    expect(bdvmSignalEdgeCss("NO_MARKET")).toBe("");
  });
});

describe("tones and formatting", () => {
  it("maps signals to meaningful tones", () => {
    expect(bdvmSignalTone("BUY")).toBe("positive");
    expect(bdvmSignalTone("STRONG_SELL")).toBe("negative");
    expect(bdvmSignalTone("SELL")).toBe("warning");
    expect(bdvmSignalTone("NO_MARKET")).toBe("outline");
    expect(bdvmSignalTone("HOLD")).toBe("neutral");
  });

  it("never renders rebuild as negative — it is a strategy, not a failure", () => {
    expect(bdvmDirectionTone("rebuild")).toBe("info");
    expect(bdvmDirectionTone("contend")).toBe("positive");
    expect(bdvmDirectionTone("retool")).toBe("neutral");
  });

  it("formats gaps signed and absences as em dash", () => {
    expect(formatBdvmGap(412.4)).toBe("+412");
    expect(formatBdvmGap(-93)).toBe("−93");
    expect(formatBdvmGap(0.2)).toBe("0");
    expect(formatBdvmGap(null)).toBe("—");
    expect(formatBdvmDecimal(null)).toBe("—");
    expect(formatBdvmDecimal(25.04)).toBe("25.0");
    expect(formatBdvmValue(9999.6)).toBe((10000).toLocaleString());
  });
});
