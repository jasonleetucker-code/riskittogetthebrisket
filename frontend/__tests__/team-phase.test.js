import { describe, it, expect } from "vitest";
import { analyzeLeaguePhases, PHASES } from "@/lib/team-phase";

function row({ name, value = 5000, age = 26 }) {
  return { name, rankDerivedValue: value, age };
}

function fakeLeague(teams) {
  return {
    sleeper: {
      teams: teams.map((t, i) => ({
        ownerId: `own${i}`,
        rosterId: String(i + 1),
        name: t.name,
        players: t.players,
      })),
    },
  };
}

describe("analyzeLeaguePhases", () => {
  it("classifies a young, valuable team as Win-now", () => {
    const rows = [
      row({ name: "young star A", value: 9000, age: 22 }),
      row({ name: "young star B", value: 8500, age: 23 }),
      row({ name: "veteran", value: 4000, age: 30 }),
    ];
    const teams = [
      { name: "Young Squad", players: ["young star A", "young star B"] },
      { name: "Old Squad", players: ["veteran"] },
    ];
    const result = analyzeLeaguePhases(fakeLeague(teams), rows);
    const young = result.teams.find((t) => t.name === "Young Squad");
    expect(young.phase.key).toBe(PHASES.WIN_NOW.key);
  });

  it("classifies a low-value young team as Rebuild", () => {
    const rows = [
      row({ name: "young rookie", value: 2000, age: 21 }),
      row({ name: "veteran star A", value: 9000, age: 30 }),
      row({ name: "veteran star B", value: 8500, age: 31 }),
    ];
    const teams = [
      { name: "Rookies", players: ["young rookie"] },
      { name: "Veterans", players: ["veteran star A", "veteran star B"] },
    ];
    const result = analyzeLeaguePhases(fakeLeague(teams), rows);
    const rebuilder = result.teams.find((t) => t.name === "Rookies");
    expect(rebuilder.phase.key).toBe(PHASES.REBUILD.key);
    const contender = result.teams.find((t) => t.name === "Veterans");
    expect(contender.phase.key).toBe(PHASES.CONTENDER.key);
  });

  it("returns trade partnerships pairing winners with rebuilders", () => {
    const rows = [
      row({ name: "young rookie", value: 2000, age: 21 }),
      row({ name: "young star", value: 9000, age: 22 }),
      row({ name: "young star B", value: 8800, age: 22 }),
      row({ name: "vet", value: 8500, age: 30 }),
      row({ name: "vet2", value: 8000, age: 31 }),
    ];
    const teams = [
      { name: "Win-now", players: ["young star", "young star B"] },
      { name: "Contender", players: ["vet", "vet2"] },
      { name: "Rebuilder", players: ["young rookie"] },
    ];
    const result = analyzeLeaguePhases(fakeLeague(teams), rows);
    expect(result.partnerships.length).toBeGreaterThan(0);
    // Winners → Rebuilders pairing.  Both Win-now and Contender pair
    // with Rebuilder.
    const partnerNames = new Set(
      result.partnerships.map((p) => `${p.winnerName}→${p.rebuilderName}`),
    );
    expect(partnerNames.has("Win-now→Rebuilder")).toBe(true);
  });

  it("returns empty when sleeper teams missing", () => {
    expect(analyzeLeaguePhases({}, []).teams).toEqual([]);
    expect(analyzeLeaguePhases({ sleeper: { teams: [] } }, []).teams).toEqual([]);
  });

  it("computes league medians from per-team snapshots", () => {
    const rows = [
      row({ name: "a", value: 1000, age: 25 }),
      row({ name: "b", value: 2000, age: 27 }),
    ];
    const teams = [
      { name: "T1", players: ["a"] },
      { name: "T2", players: ["b"] },
    ];
    const result = analyzeLeaguePhases(fakeLeague(teams), rows);
    expect(result.leagueMedians.value).toBe(1500);
    expect(result.leagueMedians.age).toBe(26);
  });
});
