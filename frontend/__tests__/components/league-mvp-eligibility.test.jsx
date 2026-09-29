/**
 * League MVP team-success gate — the race explains itself (owner decision
 * 2026-09-26). League MVP lists only players on a team in playoff position
 * with a .500-or-better record, says so, and names the best performers it keeps
 * out. OPOY / DPOY carry no eligibility block and show none of this copy.
 */
import { render, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AwardsSection, { mvpEligibilityNote, mvpOutsideNote } from "@/app/league/sections/awards";

const managers = new Map([["owner-D", { displayName: "D", currentTeamName: "D FC", avatar: "" }]]);

function leader(pid, name, ownerId = "owner-D") {
  return {
    rank: 1,
    ownerId,
    displayName: "D",
    value: { playerId: pid, playerName: name, position: "RB", team: "KC", vorp: 84, starterPoints: 90, gamesStarted: 3 },
  };
}

const eligibility = {
  rule: "playoff_field_and_record_500_or_better",
  verified: true,
  basis: "current_standings",
  playoffTeams: 7,
  outsideTheRace: [
    { playerId: "rb1", playerName: "Star Back", position: "RB", vorp: 114, reason: "team_outside_playoff_field" },
    { playerId: "rb2", playerName: "Low Back", position: "RB", vorp: 108, reason: "team_record_below_500" },
  ],
};

const data = {
  currentSeason: "2026",
  featuredSeason: "2026",
  awardRaces: [
    { key: "league_mvp", label: "League MVP Race", leaders: [leader("rb4", "Eligible Back")], eligibility },
    { key: "off_mvp", label: "Offensive Player of the Year Race", leaders: [leader("rb1", "Star Back", "owner-A")] },
    {
      key: "def_mvp",
      label: "Defensive Player of the Year Race",
      leaders: [{ ...leader("dl6", "Edge", "owner-F"), value: { ...leader("dl6", "Edge").value, position: "DL" } }],
    },
  ],
  bySeason: [{ season: "2026", isComplete: false, hasPlayerScoring: true, awards: [], finalists: {} }],
};

function card(container, key) {
  return container.querySelector(`[data-award-key="${key}"]`);
}

describe("League MVP eligibility copy", () => {
  it("states the rule and names who is outside the race, with why", () => {
    const { container } = render(<AwardsSection managers={managers} data={data} onNavigate={vi.fn()} />);
    const mvp = card(container, "league_mvp");
    expect(within(mvp).getByText(/Eligible: players on a team in playoff position with a .500-or-better record/)).toBeInTheDocument();
    expect(mvp.querySelector("[data-mvp-outside]").textContent).toBe(
      "Outside the race: Star Back (team outside the playoff field), Low Back (team below .500)",
    );
    expect(mvp.textContent).toContain("Eligible Back");
  });

  it("OPOY and DPOY show no eligibility copy — their leaders stand on performance", () => {
    const { container } = render(<AwardsSection managers={managers} data={data} onNavigate={vi.fn()} />);
    for (const key of ["off_mvp", "def_mvp"]) {
      const c = card(container, key);
      expect(c.querySelector("[data-mvp-eligibility]")).toBeNull();
      expect(c.querySelector("[data-mvp-outside]")).toBeNull();
    }
    expect(card(container, "off_mvp").textContent).toContain("Star Back");
    expect(card(container, "off_mvp").textContent).toContain("Offensive Player of the Year Race");
    expect(card(container, "def_mvp").textContent).toContain("Defensive Player of the Year Race");
  });

  it("the finalized basis says 'made the playoffs'; unverified says nothing it cannot back", () => {
    expect(mvpEligibilityNote({ ...eligibility, basis: "final_bracket" })).toBe(
      "Eligible: players on a team that made the playoffs with a .500-or-better record.",
    );
    expect(mvpEligibilityNote({ verified: false })).toBeNull();
    // A payload built under the retired strict rule is captioned truthfully.
    expect(mvpEligibilityNote({ ...eligibility, rule: "playoff_field_and_winning_record" })).toBe(
      "Eligible: players on a team in playoff position with a winning record.",
    );
    expect(
      mvpOutsideNote({
        outsideTheRace: [
          { playerId: "x", playerName: "New Back", reason: "team_record_unavailable" },
        ],
      }),
    ).toBe("Outside the race: New Back (no decided games yet)");
    expect(mvpOutsideNote({ outsideTheRace: [] })).toBeNull();
  });

  it("an empty gated race explains itself instead of vanishing", () => {
    const awaiting = {
      ...data,
      awardRaces: [
        {
          key: "league_mvp",
          label: "League MVP Race",
          leaders: [],
          awaitingEvidence: true,
          awaitingReason: "no_eligible_mvp_candidate",
          eligibility: { ...eligibility, outsideTheRace: [] },
        },
      ],
    };
    const { container } = render(<AwardsSection managers={managers} data={awaiting} onNavigate={vi.fn()} />);
    expect(card(container, "league_mvp").textContent).toContain(
      "No team is in playoff position with a .500-or-better record yet",
    );
  });
});
