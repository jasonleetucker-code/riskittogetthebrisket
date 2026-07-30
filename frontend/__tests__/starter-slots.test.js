/**
 * Tests for lib/starter-slots.js and the two consumers that used to
 * carry their own answer.
 *
 * There was NO coverage of any of this before 2026-07-30 — not of
 * `STARTER_SLOTS`, `buildTeamValueBreakdown`, `buildAllTeamSummaries`,
 * `scoreTeamTiers` or `splitStartersBench`. That is why a table saying
 * this league starts 2 DL, 2 LB and 2 DB sat in the tree while the
 * league started 3 of each, undercounting every team on /rosters and
 * reordering the leaderboard. These tests exist so the next drift is
 * caught by CI rather than by an audit.
 *
 * The lineup arrays below are the REAL ones, copied from
 * config/leagues/registry.json and corroborated against
 * `sleeper.rosterPositions` on the live contract.
 */
import { describe, expect, it } from "vitest";
import { fillLineup, lineupPosition, lineupSlots } from "@/lib/starter-slots";
import { computePortfolio } from "@/lib/portfolio-insights";
import {
  buildAllTeamSummaries,
  buildPlayerMetaMap,
  buildTeamValueBreakdown,
} from "@/lib/league-analysis";

// dynasty_main — 12-team superflex TEP IDP. 21 lineup slots + 37 bench.
const DYNASTY_MAIN_SLOTS = [
  "QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE",
  "FLEX", "FLEX", "SUPER_FLEX", "K",
  "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB",
  ...Array(37).fill("BN"),
];

// dynasty_new — 10-team, no IDP, no K, TE 1. Same scoring profile,
// completely different lineup: the reason a literal cannot be right.
const DYNASTY_NEW_SLOTS = [
  "QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX",
  ...Array(14).fill("BN"),
];

/** n players of one group, values descending from `top`. */
function squad(spec) {
  const out = [];
  for (const [group, count, top] of spec) {
    for (let i = 0; i < count; i += 1) {
      out.push({ name: `${group}${i + 1}`, group, value: top - i * 10 });
    }
  }
  return out;
}

const byGroup = (players) =>
  players.reduce((acc, p) => {
    acc[p.group] = (acc[p.group] || 0) + 1;
    return acc;
  }, {});

describe("lineupSlots", () => {
  it("drops bench, IR and taxi and keeps the 21 starting slots", () => {
    const slots = lineupSlots(DYNASTY_MAIN_SLOTS);
    expect(slots).toHaveLength(21);
    expect(slots).not.toContain("BN");
    expect(slots.filter((s) => s === "DL")).toHaveLength(3);
    expect(slots.filter((s) => s === "LB")).toHaveLength(3);
    expect(slots.filter((s) => s === "DB")).toHaveLength(3);
  });

  it("is case-insensitive and drops IR/TAXI", () => {
    expect(lineupSlots(["qb", "bn", "ir", "taxi", "rb"])).toEqual(["QB", "RB"]);
  });

  it("returns [] for a missing or empty array", () => {
    expect(lineupSlots(null)).toEqual([]);
    expect(lineupSlots([])).toEqual([]);
  });
});

describe("fillLineup — dynasty_main", () => {
  // Deep enough at every position to fill every slot with room to spare.
  const roster = squad([
    ["QB", 4, 900], ["RB", 6, 800], ["WR", 8, 700], ["TE", 4, 600],
    ["DL", 6, 500], ["LB", 6, 400], ["DB", 6, 300],
  ]);
  const fill = () =>
    fillLineup({
      assets: roster,
      rosterPositions: DYNASTY_MAIN_SLOTS,
      positionOf: (p) => p.group,
    });

  it("starts THREE of each IDP position, not two", () => {
    // The whole defect, in one assertion. The old table said 2/2/2.
    const counts = byGroup(fill().starters);
    expect(counts.DL).toBe(3);
    expect(counts.LB).toBe(3);
    expect(counts.DB).toBe(3);
  });

  it("fills 20 of 21 slots — K goes unfilled because kickers are not rostered here", () => {
    // `buildPlayerMetaMap` drops pos === "K", so no asset can ever match
    // the K slot. That is intended; it must not be papered over by
    // adding K back to a slot table.
    const f = fill();
    expect(f.slotCount).toBe(21);
    expect(f.starters).toHaveLength(20);
    expect(f.unfilledSlots).toEqual(["K"]);
  });

  it("allocates FLEX and SUPER_FLEX by value rather than by a fixed guess", () => {
    const counts = byGroup(fill().starters);
    // 1 QB + 2 RB + 3 WR + 2 TE = 8 strict, then 2 FLEX (RB/WR/TE) and
    // 1 SUPER_FLEX (QB-eligible) = 11 offensive starters.
    const offense = counts.QB + counts.RB + counts.WR + counts.TE;
    expect(offense).toBe(11);
    // The 2nd QB is worth 890, above every remaining RB/WR/TE, so the
    // superflex takes it. A fixed "+1 QB" table happens to agree here;
    // the point is that this one is derived, not assumed.
    expect(counts.QB).toBe(2);
  });

  it("takes the highest-valued eligible player for each slot", () => {
    const names = fill().starters.map((p) => p.name);
    expect(names).toContain("QB1");
    expect(names).toContain("DL1");
    expect(names).not.toContain("DL4"); // 4th DL: no slot for it
  });

  it("picks the best eligible player when the input is NOT pre-sorted", () => {
    // Regression guard for two bugs caught in review, both of which
    // produced a wrong answer that looked right.
    //
    // 1. `fillLineup` sorts by `valueFor`, defaulting to `p.value`. The
    //    league-analysis callers hold player-meta entries whose value
    //    field is `.meta`, so the default read undefined for every asset,
    //    the sort became a no-op and slots filled in INSERTION order.
    // 2. That option was first named `valueOf` — which every object
    //    inherits from Object.prototype, so destructuring it out of the
    //    options bag ALWAYS found a function and the default never
    //    applied at all.
    //
    // Every other fixture in this file happens to be built in descending
    // order, so all of them passed through both bugs. Shuffled input with
    // a non-default value field is what actually catches them.
    const shuffled = [
      { name: "cheap", group: "QB", meta: 10 },
      { name: "best", group: "QB", meta: 999 },
      { name: "mid", group: "QB", meta: 500 },
    ];
    const f = fillLineup({
      assets: shuffled,
      rosterPositions: ["QB", "BN"],
      positionOf: (p) => p.group,
      valueFor: (p) => p.meta,
    });
    expect(f.starters.map((p) => p.name)).toEqual(["best"]);
  });

  it("treats a missing/NaN value as 0 rather than corrupting the sort", () => {
    const f = fillLineup({
      assets: [
        { name: "unpriced", group: "QB" },
        { name: "priced", group: "QB", value: 1 },
      ],
      rosterPositions: ["QB"],
      positionOf: (p) => p.group,
    });
    expect(f.starters.map((p) => p.name)).toEqual(["priced"]);
  });

  it("reports slots a thin roster cannot fill", () => {
    const thin = squad([["QB", 1, 900], ["DL", 1, 500]]);
    const f = fillLineup({
      assets: thin,
      rosterPositions: DYNASTY_MAIN_SLOTS,
      positionOf: (p) => p.group,
    });
    expect(f.starters).toHaveLength(2);
    expect(f.unfilledSlots.filter((s) => s === "DL")).toHaveLength(2);
    expect(f.unfilledSlots).toContain("RB");
  });
});

describe("fillLineup — dynasty_new (same scoring profile, different lineup)", () => {
  const roster = squad([
    ["QB", 3, 900], ["RB", 5, 800], ["WR", 6, 700], ["TE", 3, 600],
    ["DL", 3, 500], ["LB", 3, 400], ["DB", 3, 300],
  ]);
  const fill = fillLineup({
    assets: roster,
    rosterPositions: DYNASTY_NEW_SLOTS,
    positionOf: (p) => p.group,
  });

  it("starts ONE TE, not two", () => {
    expect(byGroup(fill.starters).TE).toBe(1);
  });

  it("starts no IDP at all", () => {
    const counts = byGroup(fill.starters);
    expect(counts.DL).toBeUndefined();
    expect(counts.LB).toBeUndefined();
    expect(counts.DB).toBeUndefined();
    expect(fill.starters).toHaveLength(10);
  });
});

describe("fillLineup — no lineup supplied", () => {
  const roster = squad([["QB", 2, 900], ["RB", 2, 800]]);

  it("refuses rather than inventing a lineup", () => {
    const f = fillLineup({
      assets: roster,
      rosterPositions: null,
      positionOf: (p) => p.group,
    });
    expect(f.available).toBe(false);
    expect(f.starters).toEqual([]);
    expect(f.bench).toHaveLength(4);
  });

  it("uses an explicit fallback only when the caller asks for one", () => {
    const f = fillLineup({
      assets: roster,
      rosterPositions: null,
      positionOf: (p) => p.group,
      fallbackSlots: ["QB", "RB"],
    });
    expect(f.available).toBe(true);
    expect(f.starters).toHaveLength(2);
  });
});

describe("lineupPosition", () => {
  it("keeps DL, LB and DB DISTINCT — the league starts 3 at each", () => {
    expect(lineupPosition("DL")).toBe("DL");
    expect(lineupPosition("LB")).toBe("LB");
    expect(lineupPosition("DB")).toBe("DB");
  });

  it("resolves the family aliases onto those three", () => {
    for (const p of ["DE", "DT", "EDGE", "NT"]) expect(lineupPosition(p)).toBe("DL");
    for (const p of ["OLB", "ILB"]) expect(lineupPosition(p)).toBe("LB");
    for (const p of ["CB", "S", "FS", "SS"]) expect(lineupPosition(p)).toBe("DB");
  });

  it("passes offense, K and DEF through so their slots still match", () => {
    for (const p of ["QB", "RB", "WR", "TE", "DEF"]) expect(lineupPosition(p)).toBe(p);
    expect(lineupPosition("PK")).toBe("K");
  });

  it("never returns the collapsed 'IDP' token", () => {
    for (const p of ["DL", "DE", "DT", "EDGE", "NT", "LB", "OLB", "ILB", "DB", "CB", "S"]) {
      expect(lineupPosition(p)).not.toBe("IDP");
    }
  });
});

describe("an IDP-stacked roster starts 3 at EACH position, not 9 defenders", () => {
  // The defect this pins, in the shape that exposes it: 9 linebackers,
  // all worth more than any lineman or back. Every defensive slot in
  // FLEX_POOLS also accepts the generic "IDP" token, so filling on a
  // collapsed vocabulary lets all 9 LBs claim the DL and DB slots too.
  // The league has 3 LB slots. It starts 3 linebackers.
  const stacked = [
    ...Array.from({ length: 9 }, (_, i) => ({
      name: `LB${i + 1}`,
      real: "LB",
      value: 900 - i,
    })),
    ...Array.from({ length: 3 }, (_, i) => ({
      name: `DL${i + 1}`,
      real: "DE",
      value: 100 - i,
    })),
    ...Array.from({ length: 3 }, (_, i) => ({
      name: `DB${i + 1}`,
      real: "CB",
      value: 50 - i,
    })),
  ];
  const idpSlots = ["DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB", "BN"];

  it("credits exactly 3 LB when filled on the resolved position", () => {
    const f = fillLineup({
      assets: stacked,
      rosterPositions: idpSlots,
      positionOf: (p) => lineupPosition(p.real),
    });
    const counts = byGroup(f.starters.map((p) => ({ group: lineupPosition(p.real) })));
    expect(counts.LB).toBe(3);
    expect(counts.DL).toBe(3);
    expect(counts.DB).toBe(3);
    expect(f.starters).toHaveLength(9);
  });

  it("credits 9 LB when filled on the collapsed vocabulary — the bug", () => {
    // Kept as an executable statement of WHY `lineupPos` exists. If this
    // ever stops reproducing, the collapsed path is gone and this test
    // and the two-field split in portfolio-insights can go with it.
    const f = fillLineup({
      assets: stacked,
      rosterPositions: idpSlots,
      positionOf: () => "IDP",
    });
    const lbStarters = f.starters.filter((p) => p.real === "LB");
    expect(lbStarters).toHaveLength(9);
    expect(f.starters.filter((p) => p.real === "DE")).toHaveLength(0);
  });
});

describe("computePortfolio (/terminal) fills on the resolved position", () => {
  it("starts 3 LB, 3 DL and 3 DB from an LB-heavy roster", () => {
    const players = [
      ...Array.from({ length: 9 }, (_, i) => ({ name: `LB${i + 1}`, pos: "LB", v: 900 - i })),
      ...Array.from({ length: 3 }, (_, i) => ({ name: `DL${i + 1}`, pos: "DE", v: 100 - i })),
      ...Array.from({ length: 3 }, (_, i) => ({ name: `DB${i + 1}`, pos: "CB", v: 50 - i })),
    ];
    const rows = players.map((p) => ({
      name: p.name,
      pos: p.pos,
      rankDerivedValue: p.v,
      values: { full: p.v },
      raw: {},
    }));
    const portfolio = computePortfolio({
      rows,
      selectedTeam: { players: players.map((p) => p.name), picks: [] },
      rawData: { sleeper: { rosterPositions: ["DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB", "BN"] } },
      history: {},
    });

    const starterNames = portfolio.starters.map((p) => p.name);
    const lbStarters = starterNames.filter((n) => n.startsWith("LB"));
    expect(lbStarters).toHaveLength(3);
    expect(starterNames.filter((n) => n.startsWith("DL"))).toHaveLength(3);
    expect(starterNames.filter((n) => n.startsWith("DB"))).toHaveLength(3);
  });

  it("still buckets defenders under the collapsed IDP allocation group", () => {
    // `pos` stays collapsed on purpose — byPosition reports allocation
    // against QB/RB/WR/TE/K/DEF/IDP/PICK, not per defensive position.
    const rows = [
      { name: "LB1", pos: "LB", rankDerivedValue: 900, values: { full: 900 }, raw: {} },
      { name: "CB1", pos: "CB", rankDerivedValue: 800, values: { full: 800 }, raw: {} },
    ];
    const portfolio = computePortfolio({
      rows,
      selectedTeam: { players: ["LB1", "CB1"], picks: [] },
      rawData: { sleeper: { rosterPositions: ["LB", "DB", "BN"] } },
      history: {},
    });
    expect(portfolio.byPosition.IDP.count).toBe(2);
    expect(portfolio.byPosition.IDP.value).toBe(1700);
  });
});

describe("/rosters starters scope", () => {
  const rows = [
    ...squad([
      ["QB", 3, 900], ["RB", 4, 800], ["WR", 5, 700], ["TE", 3, 600],
      ["DL", 4, 500], ["LB", 4, 400], ["DB", 4, 300],
    ]),
  ].map((p) => ({
    name: p.name,
    pos: p.group,
    values: { full: p.value },
    raw: {},
    team: "",
  }));
  const meta = buildPlayerMetaMap(rows);
  const team = { name: "T", roster_id: 1, players: rows.map((r) => r.name), picks: [] };

  it("counts the 3rd DL, LB and DB that the old table dropped", () => {
    const withSlots = buildTeamValueBreakdown(
      team, meta, rows, "starters", null, DYNASTY_MAIN_SLOTS,
    );
    // Old behaviour was top-2 per IDP group: 500+490, 400+390, 300+290.
    const old = 500 + 490 + 400 + 390 + 300 + 290;
    const now = withSlots.byGroup.DL + withSlots.byGroup.LB + withSlots.byGroup.DB;
    expect(now).toBe(old + 480 + 380 + 280);
  });

  it("reports starterSlotsUnavailable instead of guessing", () => {
    const b = buildTeamValueBreakdown(team, meta, rows, "starters", null, null);
    expect(b.starterSlotsUnavailable).toBe(true);
    expect(b.total).toBe(0);
  });

  it("does not set the flag on the non-starter scopes", () => {
    for (const scope of ["full", "players"]) {
      const b = buildTeamValueBreakdown(team, meta, rows, scope, null, null);
      expect(b.starterSlotsUnavailable).toBe(false);
      expect(b.total).toBeGreaterThan(0);
    }
  });

  it("threads the lineup through buildAllTeamSummaries", () => {
    const [summary] = buildAllTeamSummaries(
      [team], meta, rows, "starters", null, DYNASTY_MAIN_SLOTS,
    );
    expect(summary.starterSlotsUnavailable).toBe(false);
    expect(summary.total).toBeGreaterThan(0);
  });
});
