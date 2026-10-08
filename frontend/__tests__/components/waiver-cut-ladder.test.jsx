/**
 * useWaiverAnalysis — the drop side of /waivers comes from the canonical
 * cut ladder (C2-DROP-01), fetched through `useRosterIntelligence` with
 * `droppability: true` (`GET /api/roster/intelligence?droppability=1`,
 * owner `src/draft/displacement.py`).
 *
 * The roster below has a lineup-protected player who is also its CHEAPEST
 * player. The served ladder leaves him out. The pre-C2-DROP-01 hook never
 * asked for the ladder and ranked the roster by raw value, so it offered
 * him as the first drop — every "never offered" assertion fails on it.
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

const row = (name, value, pos = "WR") => ({
  name,
  pos,
  position: pos,
  assetClass: "offense",
  rankDerivedValue: value,
  values: { full: value },
  sourceCount: 3,
  confidenceBucket: "medium",
});

const ROWS = [
  row("Only TE", 300, "TE"),
  row("Bench A", 800),
  row("Bench B", 600),
  row("FA One", 2000),
];
const TEAM = { name: "Mine", ownerId: "me", players: ["Only TE", "Bench A", "Bench B"] };

const LADDER_PAYLOAD = {
  droppabilityIncluded: true,
  team: {
    ownerId: "me",
    droppability: {
      cutLadder: {
        rungs: [
          { rung: 1, playerId: "", name: "Bench B", position: "WR", baseValue: 600, valueBasis: "board", effectiveCutCost: 100 },
          { rung: 2, playerId: "", name: "Bench A", position: "WR", baseValue: 800, valueBasis: "board", effectiveCutCost: 300 },
        ],
        undroppable: [{ name: "Only TE" }],
      },
    },
  },
};

function Probe() {
  const { analysis, loading } = useWaiverAnalysis({});
  if (loading) return <span data-testid="state">loading</span>;
  return (
    <div>
      <span data-testid="state">{analysis?.dropState?.state || "none"}</span>
      <span data-testid="reason">{analysis?.dropState?.reasonText || ""}</span>
      <span data-testid="droppable">{(analysis?.droppable || []).map((d) => d.row.name).join("|")}</span>
      <span data-testid="moves">{(analysis?.bestMoves || []).map((m) => m.drop.name).join("|")}</span>
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
  // The bid POST is optional enrichment; keep it inert here.
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
});

afterEach(() => {
  vi.unstubAllGlobals();
  mockUseRosterIntelligence.mockReset();
});

describe("useWaiverAnalysis — canonical cut ladder", () => {
  it("requests this team's ladder", () => {
    mockUseRosterIntelligence.mockReturnValue({ loading: false, data: LADDER_PAYLOAD, failure: null });
    render(<Probe />);
    expect(mockUseRosterIntelligence).toHaveBeenCalledWith(
      expect.objectContaining({ ownerId: "me", droppability: true, enabled: true }),
    );
  });

  it("drops only served rungs, in cut order — never the lineup-protected player", () => {
    mockUseRosterIntelligence.mockReturnValue({ loading: false, data: LADDER_PAYLOAD, failure: null });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("ok");
    expect(screen.getByTestId("droppable")).toHaveTextContent("Bench B|Bench A");
    expect(screen.getByTestId("droppable").textContent).not.toMatch(/Only TE/);
    expect(screen.getByTestId("moves")).toHaveTextContent("Bench B");
    expect(screen.getByTestId("moves").textContent).not.toMatch(/Only TE/);
  });

  it("a failed ladder is an explicit unavailable state with no drops", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      data: null,
      failure: { kind: "not_ready", message: "No data loaded yet." },
    });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("reason")).toHaveTextContent("No data loaded yet.");
    expect(screen.getByTestId("droppable")).toBeEmptyDOMElement();
    expect(screen.getByTestId("moves")).toBeEmptyDOMElement();
  });

  it("keeps the page loading while this team's ladder is in flight", () => {
    mockUseRosterIntelligence.mockReturnValue({ loading: true, data: null, failure: null });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
  });

  it("never reads another team's ladder as this team's", () => {
    const stale = JSON.parse(JSON.stringify(LADDER_PAYLOAD));
    stale.team.ownerId = "someone_else";
    mockUseRosterIntelligence.mockReturnValue({ loading: true, data: stale, failure: null });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
  });

  it("a fetch that settles with no data and no failure is unavailable, not a permanent skeleton", () => {
    mockUseRosterIntelligence.mockReturnValue({ loading: false, data: null, failure: null });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("droppable")).toBeEmptyDOMElement();
  });

  it("a settled answer for another team is unavailable, never read as this team's", () => {
    const stale = JSON.parse(JSON.stringify(LADDER_PAYLOAD));
    stale.team.ownerId = "someone_else";
    mockUseRosterIntelligence.mockReturnValue({ loading: false, data: stale, failure: null });
    render(<Probe />);
    expect(screen.getByTestId("state")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("reason")).toHaveTextContent("different team");
    expect(screen.getByTestId("droppable")).toBeEmptyDOMElement();
  });
});
