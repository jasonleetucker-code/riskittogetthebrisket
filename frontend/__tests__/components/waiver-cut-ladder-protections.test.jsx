/**
 * /waivers greedy lists honour the user's trade protections (DYN10 B1), and
 * the hook surfaces the server's roster-freshness stamp (B3).
 *
 * The cut ladder is rebuilt server-side without the requester's protected
 * players (`droppability.protections`, owner `src/trade/constraints.py`).
 * This file pins the client half: protections that could not be read make
 * the drop side UNAVAILABLE (never an unconstrained list), and a rung the
 * same payload names as protected is never offered as a drop in "Best
 * Add/Drop Moves", "Best Unique Upgrade Set" or the droppable list.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

const mockUseApp = vi.fn();
const mockUseLeague = vi.fn();
const mockUseTeam = vi.fn();
const mockUseRosterIntelligence = vi.fn();

vi.mock("@/components/AppShell", () => ({ useApp: () => mockUseApp() }));
vi.mock("@/components/useLeague", () => ({ useLeague: () => mockUseLeague() }));
vi.mock("@/components/useTeam", () => ({ useTeam: () => mockUseTeam() }));
vi.mock("@/components/useRosterIntelligence", () => ({
  useRosterIntelligence: (args) => mockUseRosterIntelligence(args),
}));

import { useWaiverAnalysis } from "@/components/useWaiverAnalysis";
import { teamCutLadder } from "@/lib/roster-intelligence";

const row = (name, value, pos = "WR", playerId = "") => ({
  name,
  pos,
  position: pos,
  playerId,
  assetClass: "offense",
  rankDerivedValue: value,
  values: { full: value },
  sourceCount: 3,
  confidenceBucket: "medium",
});

const ROWS = [
  row("Kept Vet", 500, "WR", "p-kept"),
  row("Bench A", 800, "WR", "p-a"),
  row("Bench B", 600, "WR", "p-b"),
  row("FA One", 2000, "WR", "p-fa1"),
  row("FA Two", 1800, "WR", "p-fa2"),
];
const TEAM = { name: "Mine", ownerId: "me", players: ["Kept Vet", "Bench A", "Bench B"] };

const rung = (n, name, playerId, value) => ({
  rung: n,
  playerId,
  name,
  position: "WR",
  baseValue: value,
  valueBasis: "board",
  effectiveCutCost: value,
});

function payload({ rungs, protections, freshness } = {}) {
  return {
    droppabilityIncluded: true,
    ...(freshness ? { rosterFreshness: freshness } : {}),
    team: {
      ownerId: "me",
      droppability: {
        cutLadder: { rungs, undroppable: [] },
        ...(protections ? { protections } : {}),
      },
    },
  };
}

const PROTECTED = {
  state: "applied",
  source: "src/trade/constraints.py",
  protectedOnRoster: [
    { playerId: "p-kept", name: "Kept Vet", position: "WR", reason: "protected_individual" },
  ],
};

function Probe() {
  const { analysis, loading, rosterFreshness } = useWaiverAnalysis({});
  if (loading) return <span data-testid="state">loading</span>;
  return (
    <div>
      <span data-testid="state">{analysis?.dropState?.state || "none"}</span>
      <span data-testid="reason">{analysis?.dropState?.reasonText || ""}</span>
      <span data-testid="droppable">{(analysis?.droppable || []).map((d) => d.row.name).join("|")}</span>
      <span data-testid="moves">{(analysis?.bestMoves || []).map((m) => m.drop.name).join("|")}</span>
      <span data-testid="unique">
        {(analysis?.bestUniqueUpgradeSet || []).map((m) => m.drop.name).join("|")}
      </span>
      <span data-testid="freshness">{rosterFreshness?.state || "none"}</span>
    </div>
  );
}

beforeEach(() => {
  mockUseApp.mockReturnValue({
    rows: ROWS,
    rawData: { sleeper: { teams: [{ name: "Mine", players: TEAM.players }] } },
    loading: false,
    error: null,
  });
  mockUseLeague.mockReturnValue({
    selectedLeague: { key: "dynasty_main", displayName: "Main", idpEnabled: true },
  });
  mockUseTeam.mockReturnValue({ selectedTeam: TEAM, leagueMismatch: false, availableTeams: [TEAM] });
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
});

afterEach(() => {
  vi.unstubAllGlobals();
  mockUseRosterIntelligence.mockReset();
});

describe("useWaiverAnalysis — trade protections", () => {
  it("baseline: an unprotected cheapest player IS the first drop", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: payload({
        rungs: [rung(1, "Kept Vet", "p-kept", 500), rung(2, "Bench B", "p-b", 600)],
      }),
    });
    render(<Probe />);
    expect(screen.getByTestId("moves").textContent.split("|")[0]).toBe("Kept Vet");
  });

  it("the protection-aware ladder the server serves keeps him off every greedy list", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: payload({
        rungs: [rung(1, "Bench B", "p-b", 600), rung(2, "Bench A", "p-a", 800)],
        protections: PROTECTED,
      }),
    });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("ok");
    for (const id of ["droppable", "moves", "unique"]) {
      expect(screen.getByTestId(id).textContent).not.toMatch(/Kept Vet/);
    }
    expect(screen.getByTestId("moves").textContent.split("|")[0]).toBe("Bench B");
    expect(screen.getByTestId("unique")).toHaveTextContent("Bench B|Bench A");
  });

  it("a rung the same payload names as protected is never offered as a drop", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: payload({
        rungs: [rung(1, "Kept Vet", "p-kept", 500), rung(2, "Bench B", "p-b", 600)],
        protections: PROTECTED,
      }),
    });
    render(<Probe />);
    for (const id of ["droppable", "moves", "unique"]) {
      expect(screen.getByTestId(id).textContent).not.toMatch(/Kept Vet/);
    }
    expect(screen.getByTestId("droppable")).toHaveTextContent("Bench B");
  });

  it("protections that could not be read are an unavailable drop side, not an unconstrained list", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: payload({
        rungs: [],
        protections: { state: "unresolved", protectedOnRoster: [], source: "src/trade/constraints.py" },
      }),
    });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("reason")).toHaveTextContent(/trade protections could not be read/);
    expect(screen.getByTestId("moves")).toHaveTextContent("");
  });

  it("protections not applied (another user's team) leave the served ladder as served", () => {
    const ladder = teamCutLadder(
      payload({
        rungs: [rung(1, "Kept Vet", "p-kept", 500)],
        protections: { state: "not_applied", reason: "not_requesters_team" },
      }),
      { ownerId: "me" },
    );
    expect(ladder.state).toBe("ok");
    expect(ladder.rungs.map((r) => r.name)).toEqual(["Kept Vet"]);
    expect(ladder.protectedPlayers).toEqual([]);
  });
});

describe("useWaiverAnalysis — roster freshness", () => {
  it("surfaces this team's ladder payload stamp", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: payload({
        rungs: [rung(1, "Bench B", "p-b", 600)],
        freshness: { state: "stale", source: "last_good", ageHours: 9, delivery: "contract" },
      }),
    });
    render(<Probe />);
    expect(screen.getByTestId("freshness")).toHaveTextContent("stale");
  });

  it("never reads another team's stamp", () => {
    const other = payload({
      rungs: [],
      freshness: { state: "stale", source: "last_good", delivery: "contract" },
    });
    other.team.ownerId = "someone-else";
    mockUseRosterIntelligence.mockReturnValue({ loading: false, failure: null, data: other });
    render(<Probe />);
    expect(screen.getByTestId("freshness")).toHaveTextContent("none");
  });
});
