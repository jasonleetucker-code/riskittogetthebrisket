/**
 * Tests for the live roster ingestion logic used in the trade page.
 * Validates Sleeper team data → roster textarea conversion and pick normalization.
 */
import { describe, expect, it } from "vitest";

// ── Pick normalization logic (extracted from trade page selectTeam) ──

function normalizePick(raw) {
  const m = raw.match(/^(\d{4})\s+(\d)\./);
  if (m) {
    const round = { "1": "1st", "2": "2nd", "3": "3rd", "4": "4th" }[m[2]] || `${m[2]}th`;
    return `${m[1]} ${round}`;
  }
  return raw.replace(/\s*\(.*\)/, "").trim();
}

function teamToRosterNames(team) {
  const picks = (team.picks || []).map(normalizePick);
  return [...(team.players || []), ...picks];
}

function buildOpponentRosters(teams, selectedIdx) {
  return teams
    .filter((_, i) => i !== selectedIdx)
    .map((t) => ({ team_name: t.name, players: t.players || [] }));
}

// ── Tests ─────────────────────────────────────────────────────────────

describe("normalizePick", () => {
  it("converts slot format to round format", () => {
    expect(normalizePick("2026 1.06 (from Pop Trunk)")).toBe("2026 1st");
    expect(normalizePick("2026 2.03 (from Draft Daddies)")).toBe("2026 2nd");
    expect(normalizePick("2027 3.09 (own)")).toBe("2027 3rd");
    expect(normalizePick("2026 4.01 (own)")).toBe("2026 4th");
  });

  it("strips provenance from non-slot formats", () => {
    expect(normalizePick("2026 1st (from Rival)")).toBe("2026 1st");
    expect(normalizePick("2027 2nd")).toBe("2027 2nd");
  });

  it("handles edge cases", () => {
    expect(normalizePick("2028 5.12 (own)")).toBe("2028 5th");
    expect(normalizePick("plain text")).toBe("plain text");
  });
});

describe("teamToRosterNames", () => {
  it("combines players and normalized picks", () => {
    const team = {
      name: "Test Team",
      players: ["Josh Allen", "Bijan Robinson"],
      picks: ["2026 1.06 (from Pop Trunk)", "2027 2.03 (own)"],
    };
    const names = teamToRosterNames(team);
    expect(names).toEqual([
      "Josh Allen",
      "Bijan Robinson",
      "2026 1st",
      "2027 2nd",
    ]);
  });

  it("handles team with no picks", () => {
    const team = { name: "No Picks", players: ["Player A"], picks: [] };
    expect(teamToRosterNames(team)).toEqual(["Player A"]);
  });

  it("handles team with no players", () => {
    const team = { name: "Empty", players: [], picks: ["2026 1.01 (own)"] };
    expect(teamToRosterNames(team)).toEqual(["2026 1st"]);
  });

  it("handles missing fields gracefully", () => {
    expect(teamToRosterNames({ name: "Bare" })).toEqual([]);
    expect(teamToRosterNames({})).toEqual([]);
  });
});

describe("buildOpponentRosters", () => {
  const teams = [
    { name: "Team A", players: ["Player 1"] },
    { name: "Team B", players: ["Player 2"] },
    { name: "Team C", players: ["Player 3"] },
  ];

  it("excludes the selected team", () => {
    const opponents = buildOpponentRosters(teams, 1);
    expect(opponents).toHaveLength(2);
    expect(opponents.map((o) => o.team_name)).toEqual(["Team A", "Team C"]);
  });

  it("includes all teams when none selected", () => {
    const opponents = buildOpponentRosters(teams, -1);
    expect(opponents).toHaveLength(3);
  });

  it("returns correct structure", () => {
    const opponents = buildOpponentRosters(teams, 0);
    expect(opponents[0]).toEqual({ team_name: "Team B", players: ["Player 2"] });
  });
});
