/**
 * THE team-direction classifier — one definition, and it matches the
 * Python one it was ported from.
 *
 * Audit W20-F006 / W20-F007 / W20-F008 / W20-F009 / W30-F016: four
 * classifiers shipped at once and agreed on 3 of 12 live teams.
 * `src/roster_intel/window.py` is the nominated definition;
 * `frontend/lib/team-phase.js` is a port of it and this file pins the
 * port against `tests/fixtures/competitive_window_cases.json` — the
 * SAME fixture `tests/roster_intel/test_window_parity.py` asserts on.
 * Neither half hardcodes expectations of its own.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import {
  analyzeLeaguePhases,
  classifyDirection,
  classifyLeagueDirections,
  percentileRank,
  stateProbabilities,
  trajectoryScore,
  COMPETITIVE_STATES,
  STATE_ANCHORS,
  DEFAULT_TEMPERATURE,
  PHASES,
} from "@/lib/team-phase";

const REPO_ROOT = path.resolve(__dirname, "../..");
const FIXTURE = JSON.parse(
  fs.readFileSync(
    path.join(REPO_ROOT, "tests", "fixtures", "competitive_window_cases.json"),
    "utf8",
  ),
);

function row({ name, value = 5000, age = 26, pos = "WR" }) {
  return { name, pos, rankDerivedValue: value, values: { full: value }, age };
}

// 21 real slots minus K — the shape /rosters and /phases actually pass.
const SLOTS = [
  "QB", "QB", "RB", "RB", "WR", "WR", "WR", "TE",
  "FLEX", "FLEX", "SUPER_FLEX",
  "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB",
];

function fakeLeague(teams, rosterPositions = SLOTS) {
  return {
    sleeper: {
      rosterPositions,
      teams: teams.map((t, i) => ({
        ownerId: t.ownerId || `own${i}`,
        rosterId: String(i + 1),
        name: t.name,
        players: t.players,
        picks: t.picks || [],
      })),
    },
  };
}

describe("model parity with src/roster_intel/window.py", () => {
  it("uses the same anchors, weights and temperature", () => {
    expect(DEFAULT_TEMPERATURE).toBe(FIXTURE.model.temperature);
    for (const [state, anchor] of Object.entries(FIXTURE.model.stateAnchors)) {
      expect(STATE_ANCHORS[state]).toEqual(anchor);
    }
    expect([...COMPETITIVE_STATES].sort()).toEqual(
      Object.keys(FIXTURE.model.stateAnchors).sort(),
    );
  });

  for (const c of FIXTURE.cases) {
    it(`${c.id} — ${c.why}`, () => {
      const probs = stateProbabilities(c.competitiveness, c.trajectory);
      for (const state of COMPETITIVE_STATES) {
        expect(probs[state]).toBeCloseTo(c.probabilities[state], 9);
      }
      expect(
        classifyDirection({
          competitiveness: c.competitiveness,
          trajectory: c.trajectory,
        }).mostLikely,
      ).toBe(c.mostLikely);
    });
  }

  for (const c of FIXTURE.trajectoryCases) {
    it(`trajectory ${c.id} — ${c.why}`, () => {
      const { score, sample } = trajectoryScore(c.entrants);
      expect(score).toBeCloseTo(c.expectedScore, 9);
      expect(sample).toBe(c.expectedSample);
    });
  }
});

describe("percentileRank — the JS twin of src/utils/percentile.py", () => {
  it("is a self-inclusive midrank", () => {
    const pop = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120];
    expect(percentileRank(120, pop)).toBeCloseTo(23 / 24, 9);
    expect(percentileRank(10, pop)).toBeCloseTo(1 / 24, 9);
  });

  it("returns null on an empty population rather than a confident 0", () => {
    expect(percentileRank(5, [])).toBeNull();
    expect(percentileRank(5, null)).toBeNull();
  });

  it("scores an all-identical population at 0.5", () => {
    expect(percentileRank(7, [7, 7, 7, 7])).toBe(0.5);
  });
});

describe("analyzeLeaguePhases", () => {
  it("reaches Rebuild on a league where every team's median age ties", () => {
    // W20-F008, exactly: the old classifier required medianAge STRICTLY
    // below the league median of team medians. Team medians land on
    // integers, so on the live snapshot six of twelve teams sat at
    // exactly 26.0 and were all forced to the "older" side — Rebuild
    // count 0 of 12 and the partner list therefore empty. Here EVERY
    // team is age 26, which the old model could not classify as Rebuild
    // under any roster value at all.
    const rows = [];
    const teams = [];
    for (let t = 0; t < 12; t += 1) {
      const players = [];
      for (let p = 0; p < 20; p += 1) {
        const name = `t${t}p${p}`;
        rows.push(row({ name, value: (12 - t) * 1000 + p, age: 26 }));
        players.push(name);
      }
      teams.push({ name: `Team ${t}`, players });
    }
    const result = analyzeLeaguePhases(fakeLeague(teams), rows);
    const byState = {};
    for (const t of result.teams) byState[t.mostLikely] = (byState[t.mostLikely] || 0) + 1;
    expect(byState.rebuild || 0).toBeGreaterThan(0);
    expect(
      (byState.championship_contender || 0) + (byState.playoff_contender || 0),
    ).toBeGreaterThan(0);
    expect(result.partnerships.length).toBeGreaterThan(0);
  });

  it("ranks competitiveness on the STARTING lineup, not the whole roster", () => {
    // A hoarder with 40 mediocre bodies must not out-compete a team
    // whose 20 starters are elite. The raw-sum ordering says otherwise,
    // which is why this axis goes through fillLineup.
    const rows = [];
    const elite = [];
    for (let i = 0; i < 20; i += 1) {
      const name = `elite${i}`;
      rows.push(row({ name, value: 9000, age: 25, pos: SLOTS[i] === "SUPER_FLEX" ? "QB" : "WR" }));
      elite.push(name);
    }
    const hoard = [];
    for (let i = 0; i < 60; i += 1) {
      const name = `scrub${i}`;
      rows.push(row({ name, value: 4000, age: 25 }));
      hoard.push(name);
    }
    const result = analyzeLeaguePhases(
      fakeLeague([
        { name: "Elite", players: elite },
        { name: "Hoard", players: hoard },
      ]),
      rows,
    );
    const eliteRow = result.teams.find((t) => t.name === "Elite");
    const hoardRow = result.teams.find((t) => t.name === "Hoard");
    expect(hoardRow.totalValue).toBeGreaterThan(eliteRow.totalValue);
    expect(eliteRow.competitiveness).toBeGreaterThan(hoardRow.competitiveness);
    expect(eliteRow.competitivenessSource).toBe("lineupScoreRank");
  });

  it("says so when the league has no lineup slots instead of pretending", () => {
    const rows = [row({ name: "a", value: 1000 }), row({ name: "b", value: 2000 })];
    const result = analyzeLeaguePhases(
      fakeLeague([{ name: "T1", players: ["a"] }, { name: "T2", players: ["b"] }], null),
      rows,
    );
    expect(result.axes.slotsAvailable).toBe(false);
    expect(result.axes.competitivenessSource).toBe("rosterValueRank");
    for (const t of result.teams) expect(t.competitivenessSource).toBe("rosterValueRank");
  });

  it("reports trajectory as unmeasured rather than neutral-looking when ages are missing", () => {
    const rows = [
      { name: "a", pos: "WR", values: { full: 1000 }, age: null },
      { name: "b", pos: "WR", values: { full: 2000 }, age: null },
    ];
    const result = analyzeLeaguePhases(
      fakeLeague([{ name: "T1", players: ["a"] }, { name: "T2", players: ["b"] }]),
      rows,
    );
    for (const t of result.teams) {
      expect(t.trajectorySample).toBe(0);
      expect(t.trajectory).toBe(0.5);
    }
  });

  it("carries the starter / depth / pick split scoreTeamTiers used to produce", () => {
    const rows = [
      row({ name: "starter", value: 9000, pos: "QB" }),
      row({ name: "benchie", value: 1200, pos: "WR" }),
      { name: "2027 Mid 1st", pos: "PICK", values: { full: 5000 } },
    ];
    const result = analyzeLeaguePhases(
      fakeLeague([
        { name: "T1", players: ["starter", "benchie"], picks: ["2027 Mid 1st"] },
        { name: "T2", players: [] },
      ]),
      rows,
    );
    const t1 = result.teams.find((t) => t.name === "T1");
    expect(t1.starterValue).toBe(10200);
    expect(t1.depthValue).toBe(0);
    expect(t1.pickValue).toBe(5000);
    expect(t1.totalValue).toBe(15200);
  });

  // Regression pins moved here from league-analysis.test.js when
  // `scoreTeamTiers` was deleted. Math audit H5(a): pick capital was
  // counted TWICE — inside `depthValue` (which was totalValue −
  // starterValue, and totalValue includes picks) at +0.2, and again in
  // its own term at −0.1 — so every pick dollar was a NET +0.1 REWARD
  // under a docstring calling it a penalty. Each roster dollar must
  // feed exactly one term.
  describe("each roster dollar is counted exactly once", () => {
    const H5_SLOTS = ["QB", "WR", "LB", "BN", "BN"];
    const h5PickNames = [
      "2026 Early 1st", "2026 Mid 1st", "2026 Late 1st",
      "2027 Early 1st", "2027 Mid 1st", "2027 Late 1st",
    ];
    const h5Rows = [
      row({ name: "Star QB", value: 5000, pos: "QB" }),
      row({ name: "Star WR", value: 4000, pos: "WR" }),
      row({ name: "Star LB", value: 3000, pos: "LB" }),
      row({ name: "Bench WR", value: 2000, pos: "WR" }),
      row({ name: "Solid QB", value: 3000, pos: "QB" }),
      row({ name: "Solid WR", value: 2000, pos: "WR" }),
      row({ name: "Depth LB", value: 1000, pos: "LB" }),
      row({ name: "Spare WR", value: 1500, pos: "WR" }),
      row({ name: "Lone WR", value: 1000, pos: "WR" }),
      ...h5PickNames.map((name) => ({ name, pos: "PICK", values: { full: 8000, raw: 8000 } })),
    ];
    const h5League = fakeLeague(
      [
        { name: "Win Now", players: ["Star QB", "Star WR", "Star LB", "Bench WR"], picks: [] },
        { name: "Balanced", players: ["Solid QB", "Solid WR", "Depth LB", "Spare WR"], picks: [] },
        { name: "Pick Hoard", players: ["Lone WR"], picks: h5PickNames },
      ],
      H5_SLOTS,
    );
    const byName = () => {
      const out = {};
      for (const t of analyzeLeaguePhases(h5League, h5Rows).teams) out[t.name] = t;
      return out;
    };

    it("picks are NOT also depth", () => {
      const hoard = byName()["Pick Hoard"];
      expect(hoard.totalValue).toBe(49000); // 1000 + 6 × 8000
      expect(hoard.pickValue).toBe(48000);
      // Lone WR fills the WR slot; QB and LB go unfilled.
      expect(hoard.starterValue).toBe(1000);
      // Everything else this team owns IS the picks. Read 48000 while
      // picks lived inside depth.
      expect(hoard.depthValue).toBe(0);
    });

    it("still counts non-starting PLAYERS as depth", () => {
      const winNow = byName()["Win Now"];
      expect(winNow.starterValue).toBe(12000);
      expect(winNow.depthValue).toBe(2000);
      expect(winNow.pickValue).toBe(0);
    });

    it("a pick hoarder does not out-compete a deeper roster", () => {
      const teams = byName();
      // With picks double-counted the hoarder scored 5500 against
      // Balanced's 4500 and took the mid tier. Competitiveness is now
      // the STARTING lineup, where 1000 loses to 6000 outright.
      expect(teams["Pick Hoard"].starterValue).toBeLessThan(teams["Balanced"].starterValue);
      expect(teams["Pick Hoard"].competitiveness).toBeLessThan(
        teams["Balanced"].competitiveness,
      );
    });
  });

  it("pick capital does NOT subtract from a team's direction", () => {
    // The deleted scoreTeamTiers ladder charged −0.1 per pick dollar,
    // which is what moved Jason from #1 (328,504 total) to #5
    // "Mid-Tier" in the block 400px below (W20-F007). Picks are not in
    // the lineup, so they cannot raise competitiveness — but they must
    // not lower it either.
    const rows = [
      row({ name: "qb", value: 9000, pos: "QB" }),
      { name: "2027 Mid 1st", pos: "PICK", values: { full: 20000 } },
    ];
    const league = (picks) =>
      analyzeLeaguePhases(
        fakeLeague([
          { name: "T1", players: ["qb"], picks },
          { name: "T2", players: [] },
        ]),
        rows,
      ).teams.find((t) => t.name === "T1");
    expect(league([]).competitiveness).toBe(league(["2027 Mid 1st"]).competitiveness);
    expect(league([]).mostLikely).toBe(league(["2027 Mid 1st"]).mostLikely);
  });

  it("returns empty when sleeper teams missing", () => {
    expect(analyzeLeaguePhases({}, []).teams).toEqual([]);
    expect(analyzeLeaguePhases({ sleeper: { teams: [] } }, []).teams).toEqual([]);
  });

  it("exposes every state through PHASES with a display label", () => {
    const keys = Object.values(PHASES).map((p) => p.key);
    expect([...keys].sort()).toEqual([...COMPETITIVE_STATES].sort());
    for (const p of Object.values(PHASES)) {
      expect(typeof p.label).toBe("string");
      expect(["up", "warn", "down"]).toContain(p.tone);
    }
  });
});

describe("classifyLeagueDirections", () => {
  it("stamps competitiveness as unavailable when there is no league to rank in", () => {
    const [only] = classifyLeagueDirections([
      { key: "solo", lineupValue: null, entrants: [], competitivenessSource: "lineupScoreRank" },
    ]);
    expect(only.competitiveness).toBe(0.5);
    expect(only.competitivenessSource).toBe("unavailable");
  });

  it("flags a roster that sits between windows rather than asserting one", () => {
    const rows = classifyLeagueDirections([
      { key: "a", lineupValue: 100, entrants: [{ age: 27, value: 100 }] },
      { key: "b", lineupValue: 200, entrants: [{ age: 27, value: 100 }] },
      { key: "c", lineupValue: 300, entrants: [{ age: 27, value: 100 }] },
    ]);
    for (const r of rows) {
      expect(r.ambiguous).toBe(r.confidence < 0.3);
      expect(Object.values(r.probabilities).reduce((s, v) => s + v, 0)).toBeCloseTo(1, 9);
    }
  });
});
