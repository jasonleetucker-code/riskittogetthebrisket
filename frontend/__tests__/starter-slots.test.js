/**
 * Tests for lib/starter-slots.js and the two consumers that used to
 * carry their own answer.
 *
 * WHAT CHANGED IN C2-U1
 *
 * This file used to prove that the client-side fill picked the right
 * starters — that it credited the 3rd DL/LB/DB, allocated FLEX and
 * SUPER_FLEX by value, and refused rather than inventing an
 * offence-only default. Those questions have MOVED, not vanished: the
 * server now solves every lineup (`src/ros/lineup.py`, exact, verified
 * against Sleeper's own awarded lineups on 10/10 real team-weeks) and
 * stamps it on `sleeper.teams[].optimalLineup`, so
 * `tests/lineup/test_canonical_lineup.py` owns "who starts" and this
 * file owns "does the client render the server's answer faithfully".
 *
 * The old client fill reproduced the host lineup on 5 of those 10 weeks
 * — 34.01 points short on eligibility it could not see and 16.13 points
 * short on the greedy itself. Keeping these tests pointed at a local
 * fill would have pinned the wrong answer in place.
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

/**
 * A server lineup stamp, written out as FIXTURE DATA.
 *
 * Deliberately hand-authored rather than computed here: recomputing it
 * would be the second implementation this unit deleted. What the client
 * must prove is that it renders whatever the server decided — including
 * decisions it would not have made itself.
 */
function stamp({ slots, starters, unpriced = [], unfilled = [], source = "sleeper_roster_positions" }) {
  const assignments = [];
  const remaining = [...starters];
  slots.forEach((slot, i) => {
    if (!remaining.length) return;
    assignments.push({ slotIndex: i, slot, player: remaining.shift() });
  });
  return {
    available: true,
    slotSource: source,
    slots,
    assignments,
    starters,
    bench: [],
    unpriced,
    unfilledSlots: unfilled,
  };
}

describe("lineupSlots", () => {
  it("drops bench, IR and taxi and keeps the 21 starting slots", () => {
    const slots = lineupSlots(DYNASTY_MAIN_SLOTS);
    expect(slots).toHaveLength(21);
    expect(slots.filter((s) => s === "DL")).toHaveLength(3);
    expect(slots.filter((s) => s === "LB")).toHaveLength(3);
    expect(slots.filter((s) => s === "DB")).toHaveLength(3);
    expect(slots).not.toContain("BN");
  });

  it("is case-insensitive and drops IR/TAXI", () => {
    expect(lineupSlots(["qb", "bn", "ir", "taxi", "rb"])).toEqual(["QB", "RB"]);
  });

  it("returns [] for a missing or empty array", () => {
    expect(lineupSlots(null)).toEqual([]);
    expect(lineupSlots([])).toEqual([]);
  });
});

describe("fillLineup — renders the server's answer, computes none of its own", () => {
  const roster = squad([
    ["QB", 2, 900], ["RB", 4, 800], ["WR", 5, 700], ["TE", 3, 600],
    ["DL", 4, 500], ["LB", 4, 400], ["DB", 4, 300],
  ]);
  const keyOf = (p) => p.name;

  it("returns exactly the starters the server named", () => {
    const server = ["QB1", "RB1", "RB2", "WR1", "DL1", "LB1", "DB1"];
    const f = fillLineup({
      assets: roster,
      keyOf,
      optimalLineup: stamp({ slots: ["QB", "RB", "RB", "WR", "DL", "LB", "DB"], starters: server }),
    });
    expect(f.starters.map(keyOf).sort()).toEqual([...server].sort());
    expect(f.available).toBe(true);
  });

  it("does NOT second-guess the server, even when a local sort would disagree", () => {
    // WR5 is the LOWEST-valued receiver. A client-side fill would never
    // pick it; a materializer must, because the server had information
    // (multi-position eligibility) this page does not.
    const f = fillLineup({
      assets: roster,
      keyOf,
      optimalLineup: stamp({ slots: ["WR"], starters: ["WR5"] }),
    });
    expect(f.starters.map(keyOf)).toEqual(["WR5"]);
  });

  it("orders `assignments` by SLOT, so a display cap cannot eat the defense", () => {
    const slots = ["QB", "RB", "DL", "LB", "DB"];
    const starters = ["QB1", "RB1", "DL1", "LB1", "DB1"];
    const f = fillLineup({ assets: roster, keyOf, optimalLineup: stamp({ slots, starters }) });
    expect(f.assignments.map((a) => a.slot)).toEqual(slots);
    // Same players as `starters`, only ordered differently.
    expect(f.assignments.map((a) => keyOf(a.asset)).sort()).toEqual(
      f.starters.map(keyOf).sort(),
    );
  });

  it("keeps UNPRICED players out of BOTH starters and bench", () => {
    // A third state. Folding "the board has no value for this player"
    // into the bench credits the roster with depth nobody measured.
    const f = fillLineup({
      assets: roster,
      keyOf,
      optimalLineup: stamp({
        slots: ["QB", "RB"],
        starters: ["QB1", "RB1"],
        unpriced: ["DB4", "LB4"],
      }),
    });
    const names = (xs) => xs.map(keyOf);
    expect(names(f.unpriced).sort()).toEqual(["DB4", "LB4"]);
    expect(names(f.bench)).not.toContain("DB4");
    expect(names(f.starters)).not.toContain("DB4");
  });

  it("passes the server's unfilled slots through verbatim", () => {
    const f = fillLineup({
      assets: roster,
      keyOf,
      optimalLineup: stamp({ slots: ["QB", "K"], starters: ["QB1"], unfilled: ["K"] }),
    });
    expect(f.unfilledSlots).toEqual(["K"]);
  });

  it("reports which rung of the server's truth ladder produced the lineup", () => {
    const f = fillLineup({
      assets: roster,
      keyOf,
      optimalLineup: stamp({ slots: ["QB"], starters: ["QB1"], source: "registry_starters" }),
    });
    expect(f.slotSource).toBe("registry_starters");
  });
});

describe("fillLineup — no server lineup", () => {
  const roster = squad([["QB", 1, 900], ["RB", 1, 800]]);
  const keyOf = (p) => p.name;

  it("refuses rather than inventing one — and never recomputes locally", () => {
    const f = fillLineup({ assets: roster, keyOf, optimalLineup: null });
    expect(f.available).toBe(false);
    expect(f.starters).toEqual([]);
    expect(f.bench).toHaveLength(2);
    expect(f.assignments).toEqual([]);
  });

  it("carries the server's reason when it gave one", () => {
    const f = fillLineup({
      assets: roster,
      keyOf,
      optimalLineup: { available: false, reason: "no_starter_slots", slotSource: null },
    });
    expect(f.available).toBe(false);
    expect(f.reason).toBe("no_starter_slots");
  });

  it("there is no fallbackSlots escape hatch any more", () => {
    // The old signature accepted `fallbackSlots` and would fill from it.
    // Passing it must not resurrect a client-side fill.
    const f = fillLineup({
      assets: roster,
      keyOf,
      optimalLineup: null,
      fallbackSlots: ["QB", "RB"],
    });
    expect(f.available).toBe(false);
    expect(f.starters).toEqual([]);
  });
});

describe("lineupPosition", () => {
  // MIRROR of src/ros/lineup.py::lineup_position. The Python side holds
  // this in lockstep — tests/lineup/test_single_owner.py parses this
  // module and diffs the families, the same arrangement the source
  // registry already uses.
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
    for (const p of ["DL", "DE", "DT", "LB", "OLB", "DB", "CB", "S"]) {
      expect(lineupPosition(p)).not.toBe("IDP");
    }
  });
});

describe("computePortfolio (/terminal) renders the stamped lineup", () => {
  const rows = [
    { name: "Star QB", pos: "QB", rankDerivedValue: 9000 },
    { name: "Star LB", pos: "LB", rankDerivedValue: 4000 },
    { name: "Deep LB", pos: "LB", rankDerivedValue: 100 },
    { name: "Star DL", pos: "DL", rankDerivedValue: 3000 },
  ];
  const team = {
    players: ["Star QB", "Star LB", "Deep LB", "Star DL"],
    picks: [],
    optimalLineup: stamp({
      slots: ["QB", "LB", "DL"],
      starters: ["Star QB", "Star LB", "Star DL"],
    }),
  };

  it("starts exactly whom the server started", () => {
    const p = computePortfolio({ rows, selectedTeam: team, rawData: {}, history: {} });
    expect(p.starters.map((x) => x.name).sort()).toEqual(["Star DL", "Star LB", "Star QB"]);
    expect(p.bench.map((x) => x.name)).toEqual(["Deep LB"]);
    expect(p.lineupKnown).toBe(true);
    expect(p.lineupFromLeague).toBe(true);
  });

  it("refuses outright when the server stamped no lineup", () => {
    const p = computePortfolio({
      rows,
      selectedTeam: { ...team, optimalLineup: undefined },
      rawData: {},
      history: {},
    });
    expect(p.lineupKnown).toBe(false);
    expect(p.starters).toEqual([]);
    expect(p.starterCount).toBe(0);
  });

  it("still buckets defenders under the collapsed IDP allocation group", () => {
    // `pos` (collapsed) and `lineupPos` (distinct) answer different
    // questions and both survive — neither selects a starter now.
    const p = computePortfolio({ rows, selectedTeam: team, rawData: {}, history: {} });
    expect(p.byPosition.IDP.count).toBe(3);
  });
});

describe("/rosters starters scope", () => {
  const rows = [
    { name: "QB1", pos: "QB", rankDerivedValue: 5000, values: { full: 5000 } },
    { name: "DL1", pos: "DL", rankDerivedValue: 500, values: { full: 500 } },
    { name: "DL2", pos: "DL", rankDerivedValue: 490, values: { full: 490 } },
    { name: "DL3", pos: "DL", rankDerivedValue: 480, values: { full: 480 } },
  ];
  const meta = buildPlayerMetaMap(rows);

  it("counts every DL slot the server filled, including the third", () => {
    const team = {
      name: "T",
      players: ["QB1", "DL1", "DL2", "DL3"],
      picks: [],
      optimalLineup: stamp({
        slots: ["QB", "DL", "DL", "DL"],
        starters: ["QB1", "DL1", "DL2", "DL3"],
      }),
    };
    const b = buildTeamValueBreakdown(team, meta, rows, "starters");
    expect(b.starterSlotsUnavailable).toBe(false);
    expect(b.byGroup.DL).toBe(500 + 490 + 480);
  });

  it("reports starterSlotsUnavailable instead of guessing", () => {
    const team = { name: "T", players: ["QB1", "DL1"], picks: [] };
    const b = buildTeamValueBreakdown(team, meta, rows, "starters");
    expect(b.starterSlotsUnavailable).toBe(true);
    expect(b.total).toBe(0);
  });

  it("does not set the flag on the non-starter scopes", () => {
    const team = { name: "T", players: ["QB1", "DL1"], picks: [] };
    expect(buildTeamValueBreakdown(team, meta, rows, "full").starterSlotsUnavailable).toBe(false);
    expect(buildTeamValueBreakdown(team, meta, rows, "players").starterSlotsUnavailable).toBe(
      false,
    );
  });

  it("threads the stamp through buildAllTeamSummaries", () => {
    const team = {
      name: "T",
      players: ["QB1", "DL1"],
      picks: [],
      optimalLineup: stamp({ slots: ["QB", "DL"], starters: ["QB1", "DL1"] }),
    };
    const [summary] = buildAllTeamSummaries([team], meta, rows, "starters");
    expect(summary.starterSlotsUnavailable).toBe(false);
    expect(summary.total).toBeGreaterThan(0);
  });
});
