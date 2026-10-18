// /trade: unavailable draft-capital budgets turn the stack note off and SAY
// so — never stacks built from $0 budgets (MISSING IS NEVER ZERO, #1785).
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { PickTeamSelectors } from "@/app/trade/trade-sections.jsx";

const props = {
  sides: [
    { id: "a", label: "A", assets: [] },
    { id: "b", label: "B", assets: [] },
  ],
  sleeperTeams: [{ name: "Alpha" }, { name: "Beta" }],
  sideTeamNames: ["Alpha", "Beta"],
  onSetTeam: () => {},
  stackGateUnmet: false,
};

describe("PickTeamSelectors — unavailable budgets", () => {
  it("states that budgets are unavailable and the note is off", () => {
    render(<PickTeamSelectors {...props} stackBudgetsUnavailable="upcoming_class_unpriced" />);
    expect(
      screen.getByText(/Auction budgets unavailable: the upcoming draft class has no priced picks/),
    ).toBeInTheDocument();
    expect(screen.getByText(/stack note is off for this league/)).toBeInTheDocument();
  });

  it("says nothing extra when the budgets are available", () => {
    render(<PickTeamSelectors {...props} />);
    expect(screen.queryByText(/Auction budgets unavailable/)).toBeNull();
  });
});
