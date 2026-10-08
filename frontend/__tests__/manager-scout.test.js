/**
 * Manager Scout (C6-MGR-01) — the frontend formats, the backend owns.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import * as leagueAnalysis from "@/lib/league-analysis";
import {
  classifyManagerScoutFailure,
  managerScoutCoverage,
  managerScoutRows,
  stateText,
  topCounts,
} from "@/lib/manager-scout";

const measured = {
  ownerId: "U1",
  displayName: "Team One",
  currentMember: true,
  tradeTendencies: {
    state: "measured",
    sampleSize: 3,
    tradeCount: 3,
    partners: [{ ownerId: "U2", displayName: null, trades: 2 }],
    received: { picks: 2, byPosition: { WR: 3, RB: 1, UNRESOLVED: 1 } },
    sent: { picks: 0, byPosition: { QB: 1 } },
    pickShareOfReceived: { state: "measured", value: 0.2857, sampleSize: 7 },
    packageShape: { consolidating: 1 },
    valueAtToday: {
      state: "measured",
      basis: "todays_canonical_board_raw_sum_not_value_adjusted",
      receivedPerTrade: 2500,
      sentPerTrade: 4750,
      netPerTrade: -2250,
      unpricedAssets: 2,
    },
  },
  waiverTendencies: { state: "measured", sampleSize: 4, claims: 4 },
  faabTendencies: {
    state: "measured",
    resolvedBids: {
      state: "measured",
      sampleSize: 5,
      meanPctOfBudget: 3.25,
      ratioToLeagueMeanBidPct: 1.4,
    },
  },
};

const quiet = {
  ownerId: "U9",
  displayName: "Quiet",
  currentMember: true,
  tradeTendencies: {
    state: "insufficient_sample",
    sampleSize: 0,
    tradeCount: 0,
    partners: [],
    received: { picks: 0, byPosition: {} },
    sent: { picks: 0, byPosition: {} },
    pickShareOfReceived: { state: "insufficient_sample", value: null, sampleSize: 0 },
    packageShape: { consolidating: 0 },
  },
  waiverTendencies: { state: "unavailable", reason: "acquisition_store_missing", sampleSize: null },
  faabTendencies: {
    state: "insufficient_sample",
    resolvedBids: { state: "insufficient_sample", sampleSize: 0, meanPctOfBudget: null },
  },
};

describe("managerScoutRows — a materializer, never a second owner", () => {
  it("formats published values verbatim", () => {
    const [row] = managerScoutRows({ managers: [measured] });
    expect(row.manager).toBe("Team One");
    expect(row.trades).toBe(3);
    expect(row.topPartner).toBe("Former manager (2)");
    expect(row.picksIn).toBe(2);
    expect(row.picksOut).toBe(0); // a real zero over a measured sample
    expect(row.pickSharePct).toBe(29);
    expect(row.bought).toBe("WR 3 · RB 1");
    expect(row.claims).toBe(4);
    expect(row.faabMeanPct).toBe(3.25);
    expect(row.faabRatio).toBe(1.4);
    expect(row.gotPerTrade).toBe(2500);
    expect(row.gavePerTrade).toBe(4750);
    expect(row.netPerTrade).toBe(-2250);
    expect(row.unpricedAssets).toBe(2);
  });

  it("an insufficient sample is null with its state, never 0%", () => {
    const [row] = managerScoutRows({ managers: [quiet] });
    expect(row.tradeState).toBe("insufficient_sample");
    expect(row.trades).toBe(0); // the count of observed trades is real
    expect(row.pickSharePct).toBeNull();
    expect(row.picksIn).toBeNull();
    expect(row.bought).toBeNull();
    expect(row.claims).toBeNull();
    expect(row.waiverState).toBe("unavailable");
    expect(row.faabMeanPct).toBeNull();
    expect(row.faabState).toBe("insufficient_sample");
    expect(row.netPerTrade).toBeNull(); // no valueAtToday block → no number
    expect(row.valueState).toBe("unavailable");
    expect(stateText(row.tradeState)).toBe("No sample");
    expect(stateText(row.waiverState)).toBe("Unavailable");
  });

  it("an empty or malformed payload yields no rows", () => {
    expect(managerScoutRows(null)).toEqual([]);
    expect(managerScoutRows({ managers: "x" })).toEqual([]);
  });

  it("topCounts orders by the published count and labels unresolved", () => {
    expect(topCounts({ UNRESOLVED: 4, WR: 1 }, 1)).toBe("Unresolved 4");
    expect(topCounts({}, 2)).toBe("");
  });
});

describe("managerScoutCoverage", () => {
  it("reports source counts only when the source is available", () => {
    const c = managerScoutCoverage({
      sources: {
        trades: { state: "available", trades: 12, window: { seasons: ["2025", "2026"] } },
        waivers: { state: "acquisition_store_missing", claims: 0 },
        faab: { state: "available" },
        lineup: { state: "not_applicable" },
      },
    });
    expect(c.trades).toBe(12);
    expect(c.claims).toBeNull();
    expect(c.seasons).toEqual(["2025", "2026"]);
    expect(c.lineupState).toBe("not_applicable");
  });
});

describe("classifyManagerScoutFailure", () => {
  it("separates auth, league, not-ready and unavailable", () => {
    expect(classifyManagerScoutFailure(200, {})).toBeNull();
    expect(classifyManagerScoutFailure(401, {}).kind).toBe("auth");
    expect(classifyManagerScoutFailure(400, { error: "unknown_league" }).kind).toBe("league");
    expect(classifyManagerScoutFailure(503, { error: "data_not_ready" }).kind).toBe("not_ready");
    expect(classifyManagerScoutFailure(503, { error: "manager_scout_unavailable" }).kind).toBe(
      "unavailable",
    );
    expect(classifyManagerScoutFailure(500, {}).kind).toBe("error");
  });
});

describe("the client-side tendency engine is retired", () => {
  it("league-analysis no longer exports analyzeTradeTendencies", () => {
    expect(leagueAnalysis.analyzeTradeTendencies).toBeUndefined();
  });

  it("/trades consumes the Manager Scout endpoint", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "../app/trades/page.jsx"), "utf8");
    expect(src).toContain("useManagerScout");
    expect(src).not.toContain("analyzeTradeTendencies");
  });
});
