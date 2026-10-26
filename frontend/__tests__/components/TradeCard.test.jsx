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

import ActivitySection, { TradeCard } from "@/app/league/sections/activity.jsx";
import { historyGradeBasisText } from "@/lib/trade-history-grade-policy";

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
        grade: { grade: "A", color: "var(--green)", label: "Evenly valued" },
      },
      {
        ownerId: "b",
        teamName: "Team B",
        receivedAssets: [{ kind: "player", playerName: "Player Two", position: "RB" }],
        grade: { grade: "A", color: "var(--green)", label: "Evenly valued" },
      },
    ]);
    render(<TradeCard trade={trade} managers={new Map()} onNavigate={() => {}} />);
    expect(screen.getAllByText("A").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Evenly valued").length).toBe(2);
    // OD-F6 option A: every graded band states what it measures on hover.
    for (const el of screen.getAllByTestId("activity-grade-at-trade")) {
      expect(el.getAttribute("title")).toBe(historyGradeBasisText());
    }
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
        grade: { grade: "A", color: "var(--green)", label: "Evenly valued" },
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
    expect(screen.getByText("Evenly valued")).toBeInTheDocument();
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
    expect(screen.queryByText("Evenly valued")).toBeNull();
  });
});

describe("TradeCard current-grade band (owner 2026-10-17)", () => {
  it("shows the at-the-time grade and today's grade side by side", () => {
    const trade = tradeWith([
      {
        ownerId: "a",
        teamName: "Team A",
        receivedAssets: [{ kind: "player", playerName: "Player One", position: "WR" }],
        grade: { grade: "B", color: "var(--green)", label: "Won the trade" },
        currentGrade: { grade: "D", color: "var(--red)", label: "Lost the trade" },
      },
      {
        ownerId: "zeta",
        teamName: "Team Z",
        receivedAssets: [{ kind: "player", playerName: "Player Two", position: "RB" }],
        grade: { grade: "A", color: "var(--green)", label: "Evenly valued" },
        currentGrade: {
          grade: null,
          color: null,
          label: "Current value unavailable",
          available: false,
          reason: "unpriced_today",
        },
      },
    ]);
    render(<TradeCard trade={trade} managers={new Map()} onNavigate={() => {}} />);
    const atTrade = screen.getAllByTestId("activity-grade-at-trade");
    const today = screen.getAllByTestId("activity-grade-today");
    expect(atTrade).toHaveLength(2);
    expect(today).toHaveLength(2);
    expect(atTrade[0]).toHaveTextContent("When traded");
    expect(atTrade[0]).toHaveTextContent("B");
    expect(today[0]).toHaveTextContent("Today");
    expect(today[0]).toHaveTextContent("D");
    expect(today[1]).toHaveTextContent("Current value unavailable");
    expect(screen.getByTitle(/no value on today's board/i)).toBeInTheDocument();
  });
});

describe("ActivitySection grade basis (OD-F6 option A)", () => {
  function feedWith(grade) {
    return {
      totalCount: 1,
      feed: [
        {
          transactionId: "t1",
          season: "2026",
          week: 2,
          totalAssets: 2,
          createdAt: 1790000000000,
          sides: [
            { ownerId: "a", rosterId: 1, displayName: "A", receivedAssets: [], ...(grade ? { currentGrade: grade } : {}) },
            { ownerId: "b", rosterId: 2, displayName: "B", receivedAssets: [], ...(grade ? { currentGrade: grade } : {}) },
          ],
        },
      ],
    };
  }

  it("states the basis when the feed carries grades", () => {
    render(
      <ActivitySection
        managers={new Map()}
        data={feedWith({ grade: "A", color: "var(--green)", label: "Evenly valued" })}
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByTestId("activity-grade-basis").textContent).toBe(historyGradeBasisText());
  });

  it("omits the basis when no trade carries a grade", () => {
    render(<ActivitySection managers={new Map()} data={feedWith(null)} onNavigate={() => {}} />);
    expect(screen.queryByTestId("activity-grade-basis")).toBeNull();
  });
});
