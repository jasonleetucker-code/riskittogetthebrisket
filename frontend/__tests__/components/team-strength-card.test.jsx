/**
 * TeamStrengthCard — the canonical Team Strength surface on /rosters.
 *
 * This card replaced `scoreTeamTiers`, a frontend team-score formula.
 * The properties below are the ones that make the replacement real
 * rather than cosmetic: if any of them regresses, the page is either
 * computing a strength again or hiding the fact that it could not get
 * one.
 *
 *  1. The canonical `total` is rendered VERBATIM and never clamped.
 *  2. Team Strength and the full-roster portfolio never appear under
 *     the same label (`V1-35`: the named quantities stay distinct).
 *  3. `available: false` renders the backend's reason, never a zero.
 *  4. A `null` league rank renders as NOT MEASURED and does not sort to
 *     the top; the backend's own order is preserved.
 *  5. `unpricedCount` and `unfilledStarterSlots` qualify the total.
 *  6. No FLEX group is invented — the groups come from the payload.
 *  7. Every failure kind renders its own state, and NONE of them falls
 *     back to a locally computed score.
 *
 * The payload is `fixtures/roster-intelligence.json`, produced by
 * running the real backend over the tracked export archive.
 */
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";

import TeamStrengthCard from "@/components/TeamStrengthCard";
import fixture from "../fixtures/roster-intelligence.json";

const clone = (v) => JSON.parse(JSON.stringify(v));

function renderCard(props) {
  return render(
    <TeamStrengthCard loading={false} data={null} failure={null} {...props} />,
  );
}

describe("TeamStrengthCard — canonical numbers", () => {
  it("renders the backend total verbatim", () => {
    renderCard({ data: fixture });
    expect(screen.getByTestId("team-strength-total")).toHaveTextContent("79,994");
  });

  it("does not clamp an aggregate to the 1-9999 player scale", () => {
    const huge = clone(fixture);
    huge.team.strength.total = 250000;
    renderCard({ data: huge });
    expect(screen.getByTestId("team-strength-total")).toHaveTextContent("250,000");
  });

  it("shows the canonical rank, not a position in a locally sorted list", () => {
    renderCard({ data: fixture });
    // rank 9 of 12 on the real board — the fixture's own ladder is 12
    // long, so a card that numbered rows itself would say #1 here (this
    // team is not the strongest).
    expect(screen.getByText(/#9 of 12/)).toBeInTheDocument();
  });

  it("labels the portfolio differently from the strength total", () => {
    const withPortfolio = clone(fixture);
    withPortfolio.team.strength.fullRosterValue = 131000;
    renderCard({ data: withPortfolio });
    expect(screen.getByTestId("team-strength-total")).toHaveTextContent("79,994");
    expect(screen.getByTestId("team-strength-full-roster")).toHaveTextContent("131,000");
    // The words "Team Strength" must not be the label on the portfolio.
    const portfolioLabel = screen.getByText(/Full roster portfolio/);
    expect(portfolioLabel.textContent).not.toMatch(/Team Strength/);
  });

  it("omits the portfolio facet entirely when the backend publishes none", () => {
    // The live endpoint returns null today. A permanent em-dash under a
    // heading reads as "this team owns nothing".
    renderCard({ data: fixture });
    expect(screen.queryByTestId("team-strength-full-roster")).toBeNull();
  });
});

describe("TeamStrengthCard — missing is never zero", () => {
  it("renders the reason for an unavailable strength instead of a total", () => {
    const refused = clone(fixture);
    refused.team.strength = {
      ...refused.team.strength,
      available: false,
      unavailableReason: "no_starter_slots",
      total: 0,
      leagueRank: null,
    };
    renderCard({ data: refused });
    expect(screen.getByText(/Team Strength is unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/no_starter_slots/)).toBeInTheDocument();
    expect(screen.getByText(/not a strength of zero/)).toBeInTheDocument();
    expect(screen.queryByTestId("team-strength-total")).toBeNull();
  });

  it("renders an unranked team as not measured, in the backend's position", () => {
    const withUnranked = clone(fixture);
    withUnranked.leagueContext.push({
      ownerId: "unreadable",
      teamName: "Unreadable",
      strengthTotal: null,
      strengthRank: null,
      youngCoreIndex: null,
      valueWeightedCoreAge: null,
    });
    renderCard({ data: withUnranked });
    // The unranked row exists, says so, and shows no fabricated rank.
    const row = screen.getByText("Unreadable").closest("tr");
    expect(within(row).getByText(/Not measured/)).toBeInTheDocument();
    expect(within(row).queryByText("#0")).toBeNull();
    // And it is LAST, not first: the server ordered it there.
    const bodyRows = row.parentElement.querySelectorAll("tr");
    expect(bodyRows[bodyRows.length - 1]).toBe(row);
  });

  it("qualifies the total with the slots it could not fill", () => {
    renderCard({ data: fixture });
    // The real board: this league starts a K and the roster has none.
    expect(screen.getByText(/starting slot could not be filled \(K\)/)).toBeInTheDocument();
    expect(screen.getByText(/unmeasured rather than low/)).toBeInTheDocument();
  });

  it("surfaces unpriced players as excluded, not as zero-valued", () => {
    renderCard({ data: fixture });
    expect(screen.getByText(/12 rostered players have no canonical value/)).toBeInTheDocument();
  });
});

describe("TeamStrengthCard — position groups", () => {
  it("renders the groups the backend published, in its order", () => {
    renderCard({ data: fixture });
    const rows = screen
      .getByRole("table", { name: /by position/i })
      .querySelectorAll("tbody th");
    expect([...rows].map((th) => th.textContent)).toEqual([
      "QB",
      "RB",
      "WR",
      "TE",
      "DL",
      "LB",
      "DB",
    ]);
  });

  it("invents no FLEX group", () => {
    // A FLEX-seated RB is summed under RB by the backend's own
    // `MeaningfulCore.by_position`; FLEX is not a displayed group.
    renderCard({ data: fixture });
    const table = screen.getByRole("table", { name: /by position/i });
    expect(within(table).queryByText("FLEX")).toBeNull();
    expect(within(table).queryByText("SUPER_FLEX")).toBeNull();
  });

  it("omits a count it was not given, rather than printing (0)", () => {
    const gappy = clone(fixture);
    gappy.team.strength.positionOrder = ["QB"];
    gappy.team.strength.byPosition = [
      { position: "QB", value: 19082, starterValue: 17113, reserveValue: 1969, leagueRank: 3 },
    ];
    renderCard({ data: gappy });
    const row = screen.getByText("QB").closest("tr");
    expect(row.textContent).toContain("17,113");
    expect(row.textContent).not.toContain("(0)");
    expect(row.textContent).not.toContain("(null)");
  });

  it("renders a group the frontend has never heard of", () => {
    const exotic = clone(fixture);
    exotic.team.strength.positionOrder = ["QB", "PK"];
    exotic.team.strength.byPosition = [
      { position: "QB", value: 19082, count: 3, starterValue: 17113, starterCount: 2, reserveValue: 1969, reserveCount: 1, leagueRank: 3 },
      { position: "PK", value: 400, count: 1, starterValue: 400, starterCount: 1, reserveValue: 0, reserveCount: 0, leagueRank: null },
    ];
    renderCard({ data: exotic });
    const table = screen.getByRole("table", { name: /by position/i });
    expect(within(table).getByText("PK")).toBeInTheDocument();
  });
});

describe("TeamStrengthCard — failure states", () => {
  const cases = [
    ["auth", /Sign in to see Team Strength/],
    ["team_required", /Choose a team/],
    ["team_not_found", /That team is not in this league/],
    ["not_ready", /Team Strength is not ready yet/],
    ["league", /League unavailable/],
    ["unavailable", /Team Strength is unavailable/],
    ["error", /Team Strength could not be measured/],
  ];

  for (const [kind, pattern] of cases) {
    it(`renders a distinct state for "${kind}"`, () => {
      renderCard({ failure: { kind, message: "" } });
      expect(screen.getByText(pattern)).toBeInTheDocument();
      // The critical half: no number is invented to fill the gap.
      expect(screen.queryByTestId("team-strength-total")).toBeNull();
      expect(screen.queryByRole("table")).toBeNull();
    });
  }

  it("renders a loading state rather than an empty board", () => {
    renderCard({ loading: true });
    expect(screen.queryByTestId("team-strength-total")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says so when the server returns neither a team nor a league", () => {
    renderCard({ data: { contractVersion: "x", leagueContext: [] } });
    expect(screen.getByText(/No Team Strength for this league/)).toBeInTheDocument();
  });
});
