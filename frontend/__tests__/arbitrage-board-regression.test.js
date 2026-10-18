// Regression on a REAL dynasty_main board (owner directive 2026-10-18).
//
// The owner's capture of /arbitrage (owner_arbitrage_capture_2026-10-18.pdf,
// not committed) showed the default Player-level table led by deep IDP
// players with huge PERCENTAGE edges — Trevin Wallace LB #385 +128%, Will
// Johnson DB #574, Bryan Bresee DL #568, Derek Stingley DB #639, Nate Wiggins
// DB #536 — while Cedric Gray LB #90 (+2,320), CJ Allen LB #114 (+1,691) and
// Jamien Sherwood LB #130 (+1,451) appeared only incidentally.
//
// The fixture is the backend-stamped row set of the newest complete archived
// scrape of that day (built read-only by src.api.data_contract), so every
// assertion is deterministic.  They are INVARIANTS of the new defaults, not
// counts of a live board.
import { describe, expect, it } from "vitest";
import fixture from "./fixtures/arbitrage-board-dynasty-main-2026-10-18.json";
import { buildArbitrageRows } from "@/lib/market-arbitrage";
import {
  DEFAULT_TABLE_SORT,
  DEFAULT_TARGET_QUALITY,
  playerScopeGroup,
} from "@/lib/trade-discovery";

const rows = fixture.rows;
const DEEP_IDP = ["Trevin Wallace", "Will Johnson", "Bryan Bresee", "Derek Stingley", "Nate Wiggins"];
const MEANINGFUL = ["Cedric Gray", "CJ Allen", "Jamien Sherwood"];

const legacy = () =>
  buildArbitrageRows(rows, { action: "buy", assetClass: "all", minEdge: 0.05 });
const defaults = (extra = {}) =>
  buildArbitrageRows(rows, {
    action: "buy",
    minEdge: 0.05,
    targetQuality: DEFAULT_TARGET_QUALITY,
    scope: "both",
    sort: DEFAULT_TABLE_SORT,
    ...extra,
  });

describe("/arbitrage research table on the real 2026-10-18 board", () => {
  it("BEFORE: the legacy default (all players, % sort) is led by a deep IDP player", () => {
    const top = legacy().slice(0, 5).map((r) => r.row.name);
    expect(top[0]).toBe("Trevin Wallace");
    expect(top.filter((n) => DEEP_IDP.includes(n)).length).toBeGreaterThanOrEqual(3);
  });

  it("AFTER: under Top 250 + absolute opportunity no deep player appears at all", () => {
    const out = defaults();
    expect(out.length).toBeGreaterThan(0);
    for (const { row } of out) {
      expect(row.canonicalConsensusRank).not.toBeNull();
      expect(row.canonicalConsensusRank).toBeLessThanOrEqual(250);
    }
    const names = out.map((r) => r.row.name);
    for (const n of DEEP_IDP) expect(names).not.toContain(n);
  });

  it("AFTER: meaningful-rank players with large absolute surplus lead", () => {
    const out = defaults();
    const top10 = out.slice(0, 10).map((r) => r.row.name);
    const present = MEANINGFUL.filter((n) =>
      legacy().some((r) => r.row.name === n),
    );
    expect(present.length).toBeGreaterThan(0);
    for (const n of present) expect(top10).toContain(n);
    // Ordered by absolute opportunity, best first.
    const surplus = out.map((r) => Math.abs(r.edge.edgePoints));
    expect(surplus).toEqual([...surplus].sort((a, b) => b - a));
  });

  it("deep low-value arbitrage stays an explicit opt-in (All Players + % sort)", () => {
    const deep = defaults({ targetQuality: "all", sort: "percentage" });
    expect(deep[0].row.name).toBe(legacy()[0].row.name);
  });

  it("Players to target maps positions through the shared vocabulary", () => {
    const dfn = defaults({ scope: "defense", targetQuality: "all" });
    expect(dfn.length).toBeGreaterThan(0);
    expect(dfn.every((r) => playerScopeGroup(r.row.pos) === "defense")).toBe(true);
    const off = defaults({ scope: "offense", targetQuality: "all" });
    expect(off.every((r) => ["QB", "RB", "WR", "TE"].includes(r.row.pos))).toBe(true);
  });

  it("a minimum incoming value is a per-row gate on canonical value", () => {
    const out = defaults({ minValue: 3500 });
    expect(out.every((r) => r.edge.ourValue >= 3500)).toBe(true);
  });

  it("missing position or missing market never enters a narrowed or priced view", () => {
    const extra = [
      { name: "No Pos", pos: "?", assetClass: "offense", canonicalConsensusRank: 50, rankDerivedValue: 5000, canonicalSites: { ktcCrowdTradesSfTep: 1000 } },
      { name: "No Market", pos: "WR", assetClass: "offense", canonicalConsensusRank: 40, rankDerivedValue: 5500, canonicalSites: {} },
    ];
    const both = buildArbitrageRows([...rows, ...extra], { action: "buy", targetQuality: "top250", sort: "absolute" });
    expect(both.some((r) => r.row.name === "No Market")).toBe(false);
    const off = buildArbitrageRows([...rows, ...extra], { action: "buy", scope: "offense", sort: "absolute" });
    expect(off.some((r) => r.row.name === "No Pos")).toBe(false);
  });
});
