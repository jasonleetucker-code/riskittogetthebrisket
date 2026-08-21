import { describe, it, expect } from "vitest";
import { analyzeLeaguePhases, PHASES } from "@/lib/team-phase";

function ladderRow(name, ownerId, { strengthTotal = 5000, valueWeightedCoreAge = 26 } = {}) {
  return {
    ownerId,
    teamName: name,
    strengthTotal,
    valueWeightedCoreAge,
    isMe: false,
  };
}

describe("analyzeLeaguePhases", () => {
  it("classifies a young, valuable team as Win-now", () => {
    const ladder = [
      ladderRow("Young Squad", "o1", { strengthTotal: 17500, valueWeightedCoreAge: 22.5 }),
      ladderRow("Old Squad", "o2", { strengthTotal: 4000, valueWeightedCoreAge: 30 }),
    ];
    const result = analyzeLeaguePhases(ladder);
    const young = result.teams.find((t) => t.name === "Young Squad");
    expect(young.phase.key).toBe(PHASES.WIN_NOW.key);
  });

  it("classifies a low-value young team as Rebuild", () => {
    const ladder = [
      ladderRow("Rookies", "o1", { strengthTotal: 2000, valueWeightedCoreAge: 21 }),
      ladderRow("Veterans", "o2", { strengthTotal: 17500, valueWeightedCoreAge: 30.5 }),
    ];
    const result = analyzeLeaguePhases(ladder);
    const rebuilder = result.teams.find((t) => t.name === "Rookies");
    expect(rebuilder.phase.key).toBe(PHASES.REBUILD.key);
    const contender = result.teams.find((t) => t.name === "Veterans");
    expect(contender.phase.key).toBe(PHASES.CONTENDER.key);
  });

  it("returns trade partnerships pairing winners with rebuilders", () => {
    const ladder = [
      ladderRow("Win-now", "o1", { strengthTotal: 17800, valueWeightedCoreAge: 22 }),
      ladderRow("Contender", "o2", { strengthTotal: 16500, valueWeightedCoreAge: 30.5 }),
      ladderRow("Rebuilder", "o3", { strengthTotal: 2000, valueWeightedCoreAge: 21 }),
    ];
    const result = analyzeLeaguePhases(ladder);
    expect(result.partnerships.length).toBeGreaterThan(0);
    const partnerNames = new Set(
      result.partnerships.map((p) => `${p.winnerName}→${p.rebuilderName}`),
    );
    expect(partnerNames.has("Win-now→Rebuilder")).toBe(true);
  });

  it("returns empty when the ladder is empty", () => {
    expect(analyzeLeaguePhases([]).teams).toEqual([]);
    expect(analyzeLeaguePhases(null).teams).toEqual([]);
  });

  it("computes league medians from the ladder's own strengthTotal/valueWeightedCoreAge", () => {
    const ladder = [
      ladderRow("T1", "o1", { strengthTotal: 1000, valueWeightedCoreAge: 25 }),
      ladderRow("T2", "o2", { strengthTotal: 2000, valueWeightedCoreAge: 27 }),
    ];
    const result = analyzeLeaguePhases(ladder);
    expect(result.leagueMedians.value).toBe(1500);
    expect(result.leagueMedians.age).toBe(26);
  });

  it("treats an unmeasured strength/age as unmeasured, never a fabricated zero", () => {
    const ladder = [
      ladderRow("Unmeasured", "o1", { strengthTotal: null, valueWeightedCoreAge: null }),
      ladderRow("Measured", "o2", { strengthTotal: 5000, valueWeightedCoreAge: 25 }),
    ];
    const result = analyzeLeaguePhases(ladder);
    // A team with no measured strength/age defaults to Mixed (not
    // high-value, not younger) rather than crashing or reading as 0.
    const unmeasured = result.teams.find((t) => t.name === "Unmeasured");
    expect(unmeasured.phase.key).toBe(PHASES.MIXED.key);
  });
});
