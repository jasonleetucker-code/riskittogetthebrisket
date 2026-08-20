// TradeCard's grade badge (V1-97 / C3-REPLAY-01).
//
// The public activity feed's grade is now computed AS OF the trade's
// own date, and a side whose assets have no admissible historical
// evidence carries an explicit `{available: false}` sentinel instead
// of a silently-substituted grade. TradeCard must render that as an
// honest "insufficient evidence" state -- never the letter/color
// badge, and never nothing at all (which would look identical to a
// trade with no grading enabled).
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { TradeCard } from "@/app/league/sections/activity.jsx";

function tradeWith(sides) {
  return {
    transactionId: "t1",
    season: "2025",
    week: 3,
    totalAssets: 2,
    sides,
  };
}

describe("TradeCard grade badge", () => {
  it("renders the letter/color badge for a normally-graded side", () => {
    const trade = tradeWith([
      {
        ownerId: "a",
        teamName: "Team A",
        receivedAssets: [{ kind: "player", playerName: "Player One", position: "WR" }],
        grade: { grade: "A", color: "var(--green)", label: "Fair trade" },
      },
      {
        ownerId: "b",
        teamName: "Team B",
        receivedAssets: [{ kind: "player", playerName: "Player Two", position: "RB" }],
        grade: { grade: "A", color: "var(--green)", label: "Fair trade" },
      },
    ]);
    render(<TradeCard trade={trade} managers={new Map()} onNavigate={() => {}} />);
    expect(screen.getAllByText("A").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fair trade").length).toBe(2);
  });

  it("renders an honest unavailable state instead of a letter grade", () => {
    const trade = tradeWith([
      {
        ownerId: "a",
        teamName: "Team A",
        receivedAssets: [{ kind: "player", playerName: "Player One", position: "WR" }],
        grade: {
          grade: null,
          color: null,
          label: "Insufficient historical evidence",
          available: false,
          reason: "no_historical_evidence",
          missingAssets: [{ kind: "player", name: "Player One" }],
        },
      },
      {
        ownerId: "zeta",
        teamName: "Team Z",
        receivedAssets: [{ kind: "player", playerName: "Player Two", position: "RB" }],
        grade: { grade: "A", color: "var(--green)", label: "Fair trade" },
      },
    ]);
    render(<TradeCard trade={trade} managers={new Map()} onNavigate={() => {}} />);
    // The unavailable side shows its label, never a bare "null" letter.
    expect(screen.getByText("Insufficient historical evidence")).toBeInTheDocument();
    // It must be the DEDICATED unavailable-state chip, not the
    // letter-grade badge just carrying a null/undefined color+letter --
    // that would render an empty-but-present span at the exact spot the
    // grade letter normally goes, which visually reads as a bug rather
    // than an explicit "we don't know". The title text below only
    // exists on the unavailable branch.
    expect(
      screen.getByTitle(/predates our historical value coverage/i)
    ).toBeInTheDocument();
    // The other side in the SAME trade is unaffected -- one side's
    // missing evidence does not poison its counterpart.
    expect(screen.getByText("Fair trade")).toBeInTheDocument();
    expect(screen.queryByText("null")).toBeNull();
  });

  it("renders no grade badge at all when grading was not attempted", () => {
    const trade = tradeWith([
      {
        ownerId: "a",
        teamName: "Team A",
        receivedAssets: [{ kind: "player", playerName: "Player One", position: "WR" }],
      },
    ]);
    render(<TradeCard trade={trade} managers={new Map()} onNavigate={() => {}} />);
    expect(screen.queryByText("Insufficient historical evidence")).toBeNull();
    expect(screen.queryByText("Fair trade")).toBeNull();
  });
});
