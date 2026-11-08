// Division-title odds on the /league Power tab (owner decision 2026-11-08).
// The backend computes; this pins only the grouping, the honest formatting of
// simulated extremes, and that division titles stay a separate number from
// playoff odds.
import { describe, expect, it } from "vitest";

import {
  divisionOddsGroups,
  divisionRuleNote,
  fmtSimulatedShare,
} from "../lib/division-odds.js";

const section = {
  scheduleCertainty: "posted",
  divisionOdds: {
    state: "available",
    count: 2,
    names: { 1: "The Pit", 2: "Barbacoa" },
    championRule: { rule: "best_overall_record_in_division", tiebreakers: ["points_for"], affectsPlayoffs: false },
  },
  owners: [
    // A division champion that misses the playoffs, and a non-champion that
    // qualifies: two different numbers, never merged.
    { ownerId: "c", displayName: "C", division: 2, divisionChampionProbability: 0.98, playoffProbability: 0.02 },
    { ownerId: "a", displayName: "A", division: 1, divisionChampionProbability: 0.7, playoffProbability: 1 },
    { ownerId: "b", displayName: "B", division: 1, divisionChampionProbability: 0.3, playoffProbability: 0.99 },
    { ownerId: "d", displayName: "D", division: 2, divisionChampionProbability: 0.02, playoffProbability: 0 },
  ],
};

describe("divisionOddsGroups", () => {
  it("groups teams by division, named from the league, sorted by title odds", () => {
    const groups = divisionOddsGroups(section);
    expect(groups.map((g) => g.name)).toEqual(["The Pit", "Barbacoa"]);
    expect(groups[0].teams.map((t) => t.ownerId)).toEqual(["a", "b"]);
    expect(groups[1].teams.map((t) => t.ownerId)).toEqual(["c", "d"]);
    // The playoff number travels unchanged beside the title number.
    expect(groups[1].teams[0].divisionChampionProbability).toBe(0.98);
    expect(groups[1].teams[0].playoffProbability).toBe(0.02);
  });

  it("renders nothing when the section publishes no division odds", () => {
    expect(divisionOddsGroups({ ...section, divisionOdds: { state: "not_applicable", reason: "no_divisions" } })).toBeNull();
    expect(
      divisionOddsGroups({ ...section, divisionOdds: { state: "unavailable", reason: "division_champion_rule_unrecorded" } }),
    ).toBeNull();
    expect(divisionOddsGroups({ owners: section.owners })).toBeNull();
  });

  it("falls back to a numbered name when the league names no division", () => {
    const groups = divisionOddsGroups({ ...section, divisionOdds: { ...section.divisionOdds, names: {} } });
    expect(groups[0].name).toBe("Division 1");
  });
});

describe("fmtSimulatedShare", () => {
  it("never shows a simulated 0 or 1 as certainty before the season is final", () => {
    expect(fmtSimulatedShare(0)).toBe("<1%");
    expect(fmtSimulatedShare(1)).toBe(">99%");
    expect(fmtSimulatedShare(0.004)).toBe("<1%");
    expect(fmtSimulatedShare(0.4567)).toBe("46%");
  });

  it("states a decided outcome once the season is final", () => {
    expect(fmtSimulatedShare(0, { final: true })).toBe("0%");
    expect(fmtSimulatedShare(1, { final: true })).toBe("100%");
  });

  it("shows missing as a dash, never 0%", () => {
    expect(fmtSimulatedShare(null)).toBe("—");
    expect(fmtSimulatedShare(undefined)).toBe("—");
    expect(fmtSimulatedShare(Number.NaN)).toBe("—");
  });
});

describe("divisionRuleNote", () => {
  it("says division titles carry no playoff advantage when the league records that", () => {
    expect(divisionRuleNote(section)).toMatch(/no playoff berth or seeding advantage/);
  });

  it("says nothing when no rule is published", () => {
    expect(divisionRuleNote({ divisionOdds: { state: "available" } })).toBeNull();
  });
});

describe("PlayoffOddsChart labels", () => {
  it("labels a simulated certainty as an estimate mid-season and a fact once final", async () => {
    const React = (await import("react")).default;
    const { renderToStaticMarkup } = await import("react-dom/server");
    const { default: PlayoffOddsChart } = await import("../components/graphs/PlayoffOddsChart.jsx");
    const owners = [
      { ownerId: "a", displayName: "A", currentWins: 7, currentPointsFor: 900, playoffProbability: 1 },
      { ownerId: "b", displayName: "B", currentWins: 1, currentPointsFor: 700, playoffProbability: 0 },
      { ownerId: "c", displayName: "C", currentWins: 4, currentPointsFor: 800, playoffProbability: 0.5 },
    ];
    const mid = renderToStaticMarkup(
      React.createElement(PlayoffOddsChart, {
        data: { owners, scheduleCertainty: "posted", numSims: 2000, playoffSpots: 1, weeksPlayed: 8, weeksRemaining: 6 },
      }),
    );
    expect(mid).toContain("&gt;99%");
    expect(mid).toContain("&lt;1%");
    expect(mid).toContain("50%");
    const done = renderToStaticMarkup(
      React.createElement(PlayoffOddsChart, {
        data: { owners, scheduleCertainty: "final", numSims: 2000, playoffSpots: 1, weeksPlayed: 14, weeksRemaining: 0 },
      }),
    );
    expect(done).toContain("100%");
    expect(done).toMatch(/>0%</);
  });
});
