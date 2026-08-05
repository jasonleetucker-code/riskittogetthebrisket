/**
 * The Signals panel must say the history is missing — W12-F011, W20-F014.
 *
 * With ``data/rank_history.jsonl`` absent, every context has trend7,
 * trend30 and volatility null, no rule can fire, and all 665 rostered
 * players fell to HOLD with the rationale "Stable — no movement,
 * volatility, or news triggers." The same payload's delta panel was
 * honest about it ("Insufficient rank history for a reliable number"),
 * so one panel asserted stability while another said unmeasured, from
 * one payload.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

const ROWS = [
  { name: "Josh Allen", pos: "QB", rankDerivedValue: 9988, canonicalConsensusRank: 1 },
  { name: "Ja'Marr Chase", pos: "WR", rankDerivedValue: 9800, canonicalConsensusRank: 2 },
];
const TEAM = { ownerId: "own1", name: "Team", players: ["Josh Allen", "Ja'Marr Chase"] };

let historyValue = {};

vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: ROWS, rawData: { players: {} }, openPlayerPopup: vi.fn() }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: TEAM, selectedLeagueKey: "dynasty_main", loading: false }),
}));
vi.mock("@/components/useRankHistory", () => ({
  useRankHistory: () => ({ history: historyValue, loading: false }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ loading: false, items: [], scored: [], byPlayer: new Map() }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({ state: {}, dismissSignal: vi.fn(), restoreSignal: vi.fn(), serverBacked: false }),
}));
vi.mock("@/components/useTerminal", () => ({
  useTerminal: () => ({ signals: [] }),
}));

import BuySellHold from "@/components/terminal/BuySellHold";

describe("Signals panel with no rank history", () => {
  it("names the evidence gap instead of blaming the filters", () => {
    historyValue = {}; // exactly what GET /api/data/rank-history returns today
    render(<BuySellHold />);
    expect(screen.getByText(/no rank history yet/i)).toBeTruthy();
    expect(screen.queryByText(/no signals match the active filters/i)).toBeNull();
  });

  it("counts the players under a 'No data' bucket, not under 'Hold'", () => {
    historyValue = {};
    const { container } = render(<BuySellHold />);
    const labels = [...container.querySelectorAll(".signal-filter")].map((n) => n.textContent);
    const noData = labels.find((t) => t.startsWith("No data"));
    const hold = labels.find((t) => t.startsWith("Hold"));
    expect(noData).toBe(`No data${ROWS.length}`);
    expect(hold).toBe("Hold0");
  });
});
