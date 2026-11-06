// Master-site-audit W20-F008 (CW-40 P1 re-adjudication, 2026-11-06) -- PARTIAL.
//
// August claim: /phases classified zero teams as Rebuild on the live snapshot, so the
// trade-partner block rendered nothing and the page never said why.
//
// What changed: the age axis is now the canonical continuous `valueWeightedCoreAge`
// (not integer medians of a top-25), so the six-teams-tied-at-the-median collapse that
// produced the live zero is much less likely.  What did not change: Rebuild still needs
// age STRICTLY below the league median, and a league with no rebuilder renders NO
// explanation -- the partner block is simply absent (TeamPhasePanel renders it only when
// `myPartnerships.length > 0`, with no empty state).
//
// Reproduction is synthetic (12 teams, fixed): five young high-value teams, one old
// high-value team, six low-value teams exactly AT the league median age -> zero Rebuild.
// The `it.fails` states the correct behavior (an empty partner list is explained); it flips
// when an explanation is added.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

import { analyzeLeaguePhases, PHASES } from "@/lib/team-phase";

const mockUseRosterIntelligence = vi.fn();
const mockUseUserState = vi.fn();

vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: [], rawData: null, loading: false, error: "" }),
}));
vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => {
    throw new Error("TeamPhasePanel must not read useDynastyData");
  },
}));
vi.mock("@/components/useRosterIntelligence", () => ({
  useRosterIntelligence: (...args) => mockUseRosterIntelligence(...args),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => mockUseUserState(),
}));

import TeamPhasePanel from "@/components/TeamPhasePanel";

// ownerId, strengthTotal, valueWeightedCoreAge
const LEAGUE = [
  ["o1", 20000, 24.0],
  ["o2", 19000, 24.5],
  ["o3", 18000, 25.0],
  ["o4", 17000, 25.2],
  ["o5", 16000, 25.4],
  ["o6", 15000, 28.0], // high value, older
  ["o7", 5000, 26.0],
  ["o8", 4800, 26.0],
  ["o9", 4600, 26.0],
  ["o10", 4400, 26.0],
  ["o11", 4200, 26.0],
  ["o12", 4000, 26.0],
];

function ladder() {
  return LEAGUE.map(([ownerId, strengthTotal, valueWeightedCoreAge], i) => ({
    ownerId,
    teamName: `Team ${i + 1}`,
    strengthTotal,
    valueWeightedCoreAge,
    isMe: ownerId === "o6",
  }));
}

beforeEach(() => {
  mockUseUserState.mockReturnValue({ state: {} });
});

describe("W20-F008: /phases with no rebuilder", () => {
  it("strict-below-median age leaves tied-at-median low-value teams as Mixed: zero Rebuild, no partners", () => {
    const out = analyzeLeaguePhases(ladder());
    expect(out.leagueMedians.age).toBe(26);
    const keys = out.teams.map((t) => t.phase.key);
    expect(keys.filter((k) => k === PHASES.REBUILD.key)).toHaveLength(0);
    expect(keys.filter((k) => k === PHASES.MIXED.key)).toHaveLength(6);
    expect(out.partnerships).toEqual([]);
  });

  it("explains why there are no trade partners instead of rendering nothing", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: {
        leagueContext: ladder().map((t) => ({
          ownerId: t.ownerId,
          teamName: t.teamName,
          strengthTotal: t.strengthTotal,
          valueWeightedCoreAge: t.valueWeightedCoreAge,
        })),
      },
    });
    mockUseUserState.mockReturnValue({ state: { selectedTeam: "Team 6" } });
    const { container } = render(<TeamPhasePanel />);
    expect(container.textContent).toMatch(/no rebuild|no trade partner|no natural partner/i);
  });
});
