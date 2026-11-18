// 2026-11-16 verified sweep: /trending listed players who dropped off the
// board as movers, with Value "0" and a stale rank delta.  An off-board player
// has no rank now, so he is not a mover; a missing value is never shown as 0.
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

const app = vi.hoisted(() => ({ rows: [] }));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: app.rows, loading: false, error: null, openPlayerPopup: () => {} }),
}));

import TrendingPage from "@/app/trending/page.jsx";

describe("/trending — off-board players and missing values", () => {
  it("lists only players on the board, and never shows a missing value as 0", () => {
    const today = new Date().toISOString().slice(0, 10);
    const daysAgo = (n) => new Date(Date.now() - n * 86400_000).toISOString().slice(0, 10);
    app.rows = [
      {
        name: "Board Climber",
        pos: "WR",
        canonicalConsensusRank: 40,
        rankDerivedValue: 6123,
        rankHistory: [{ date: daysAgo(5), rank: 52 }, { date: today, rank: 40 }],
      },
      {
        name: "Value Missing",
        pos: "RB",
        canonicalConsensusRank: 90,
        rankDerivedValue: null,
        rankHistory: [{ date: daysAgo(4), rank: 95 }, { date: today, rank: 90 }],
      },
      {
        name: "Fell Off",
        pos: "TE",
        canonicalConsensusRank: null,
        rankDerivedValue: null,
        rankHistory: [{ date: daysAgo(12), rank: 600 }, { date: daysAgo(10), rank: 500 }],
      },
    ];
    render(<TrendingPage />);

    expect(screen.getByText("Board Climber")).toBeInTheDocument();
    expect(screen.queryByText("Fell Off")).not.toBeInTheDocument();
    expect(screen.getByText(/players no longer on the board are not listed/i)).toBeInTheDocument();

    const missingRow = screen.getByText("Value Missing").closest("tr");
    const cells = within(missingRow).getAllByRole("cell").map((td) => td.textContent.trim());
    expect(cells[cells.length - 1]).toBe("—");
    expect(cells).not.toContain("0");

    const climberRow = screen.getByText("Board Climber").closest("tr");
    const climberCells = within(climberRow).getAllByRole("cell").map((td) => td.textContent.trim());
    expect(climberCells[climberCells.length - 1]).toBe((6123).toLocaleString());
  });
});
