import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import PortfolioSummary from "@/components/dfs/PortfolioSummary";

afterEach(cleanup);

describe("PortfolioSummary", () => {
  it("renders the server's counts and says what they are not", () => {
    render(
      <PortfolioSummary
        portfolio={{
          lineups: 3,
          distinctPlayers: 14,
          teams: [{ key: "AAA", lineups: 3, share: 1 }],
          games: [{ key: "AAA@BBB", lineups: 2, share: 0.6667 }],
          lineupsWithUnknownGame: 1,
          stackShapes: [{ key: "4-2-1-1-1", lineups: 2, share: 0.6667 }],
          salary: { min: 49100, max: 50000 },
          note: "Counts of what was built. Not an ownership, duplication or payout estimate.",
        }}
      />,
    );
    expect(screen.getByText(/3 lineups use 14 different players/)).toBeTruthy();
    expect(screen.getByText(/1 lineup\(s\) include a player with an unknown game/)).toBeTruthy();
    expect(screen.getByText("4-2-1-1-1")).toBeTruthy();
    expect(screen.getAllByText("67%").length).toBe(2);
    expect(screen.getByText(/Not an ownership, duplication or payout estimate/)).toBeTruthy();
  });

  it("renders nothing for a single-lineup build", () => {
    const { container } = render(<PortfolioSummary portfolio={null} />);
    expect(container.innerHTML).toBe("");
  });
});
