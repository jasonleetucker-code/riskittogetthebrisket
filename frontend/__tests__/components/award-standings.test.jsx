/**
 * Expand standings — the ranking behind each award (owner directive 2026-09-26).
 *
 * The collapsed race stays concise (top three); Expand reveals the backend's
 * `standings` (≤ 12) in the backend's order; Collapse restores the concise
 * card. The component computes nothing: player rows use the canonical
 * player-name primitive, manager rows the canonical franchise navigation,
 * NFL teams and events their own identity. Fewer than twelve means fewer
 * rows. A 2026 Waiver King row can be measured AND ineligible to win.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AwardsSection from "@/app/league/sections/awards";

const managers = new Map(
  [
    ["o1", "Jason"],
    ["o2", "Brent"],
    ["joel", "Joel"],
    ["blaine", "Blaine"],
    ["kich", "Kich"],
  ].map(([id, name]) => [id, { displayName: name, currentTeamName: `${name} FC`, avatar: "" }]),
);

function playerRow(rank, n, extra = {}) {
  return {
    rank,
    awardRank: rank,
    eligible: true,
    ownerId: "o1",
    displayName: "Jason",
    value: {
      playerId: `p${n}`,
      playerName: `Quarterback ${n}`,
      position: "QB",
      team: "BUF",
      starterPoints: 200 - n,
      gamesStarted: 3,
    },
    ...extra,
  };
}

const qbStandings = Array.from({ length: 12 }, (_, i) => playerRow(i + 1, i + 1));

const waiverStandings = [
  {
    rank: 1,
    awardRank: null,
    eligible: false,
    ineligibleReason: "owner_season_eligibility_override",
    ineligibleLabel: "Ineligible for 2026 award",
    ownerId: "blaine",
    displayName: "Blaine",
    teamName: "Ugh BUGHB",
    value: { pointsGained: 101.97, adds: 9 },
  },
  {
    rank: 2,
    awardRank: null,
    eligible: false,
    ineligibleReason: "owner_season_eligibility_override",
    ineligibleLabel: "Ineligible for 2026 award",
    ownerId: "joel",
    displayName: "Joel",
    teamName: "The Rossini Panini Dynasty Collective of Greater Brisketville",
    value: { pointsGained: 59.42, adds: 5 },
  },
  {
    rank: 3,
    awardRank: 1,
    eligible: true,
    ownerId: "kich",
    displayName: "Kich",
    teamName: "Kich FC",
    value: { pointsGained: 56.02, adds: 3 },
  },
];

const races = [
  {
    key: "top_qb",
    label: "Top QB Race",
    leaders: qbStandings.slice(0, 5),
    standings: qbStandings,
    standingsEntity: "player",
    standingsTotal: 31,
  },
  {
    key: "waiver_king",
    label: "Waiver King",
    leaders: [{ rank: 1, ownerId: "kich", displayName: "Kich", value: { pointsGained: 56.02, adds: 3 } }],
    standings: waiverStandings,
    standingsEntity: "manager",
    standingsTotal: 3,
  },
  {
    key: "top_offense",
    label: "Top Offense Race",
    leaders: [
      { rank: 1, ownerId: "o1", displayName: "Jason", value: { offensePoints: 900 } },
      { rank: 2, ownerId: "o2", displayName: "Brent", value: { offensePoints: 900 } },
    ],
    standings: [
      { rank: 1, awardRank: 1, eligible: true, ownerId: "o1", displayName: "Jason", teamName: "Jason FC", value: { offensePoints: 900 } },
      { rank: 1, tied: true, awardRank: 2, eligible: true, ownerId: "o2", displayName: "Brent", teamName: "Brent FC", value: { offensePoints: 900 } },
    ],
    standingsEntity: "team",
    standingsTotal: 2,
  },
  {
    key: "top_nfl_team",
    label: "Top Fantasy NFL Team Race",
    leaders: [{ rank: 1, ownerId: "", displayName: "BUF", value: { team: "BUF", points: 300 } }],
    standings: [
      { rank: 1, awardRank: 1, eligible: true, ownerId: "", displayName: "BUF", value: { team: "BUF", points: 300 } },
      { rank: 2, awardRank: 2, eligible: true, ownerId: "", displayName: "KC", value: { team: "KC", points: 250 } },
    ],
    standingsEntity: "nfl_team",
    standingsTotal: 2,
  },
  {
    key: "def_roy",
    label: "Defensive Rookie of the Year Race",
    awaitingEvidence: true,
    awaitingReason: "no_qualifying_evidence",
    leaders: [],
  },
];

const data = {
  currentSeason: "2026",
  featuredSeason: "2026",
  awardRaces: races,
  bySeason: [
    {
      season: "2026",
      isComplete: false,
      hasPlayerScoring: true,
      finalists: {},
      awards: [
        {
          key: "highest_single_week",
          label: "Highest Single Week",
          ownerId: "o1",
          displayName: "Jason",
          value: { points: 212.4, week: 2 },
          standings: [
            { rank: 1, awardRank: 1, eligible: true, ownerId: "o1", displayName: "Jason", detail: "Week 2", value: { points: 212.4, week: 2 } },
            { rank: 2, awardRank: 2, eligible: true, ownerId: "o1", displayName: "Jason", detail: "Week 1", value: { points: 201.1, week: 1 } },
          ],
          standingsEntity: "event",
          standingsTotal: 2,
        },
      ],
    },
  ],
};

function show() {
  const onNavigate = vi.fn();
  const utils = render(<AwardsSection managers={managers} data={data} onNavigate={onNavigate} />);
  const card = (key) => utils.container.querySelector(`[data-award-key="${key}"]`);
  return { ...utils, onNavigate, card };
}

const toggle = (root) => within(root).getByRole("button", { name: /standings/i });
const standingsList = (root) => root.querySelector("[data-award-standings] ol");

describe("collapsed → expanded → collapsed", () => {
  it("the race stays concise until expanded, then shows the backend's twelve in order", async () => {
    const { card } = show();
    const qb = card("top_qb");
    const btn = toggle(qb);
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(standingsList(qb)).not.toBeVisible();
    // Collapsed: the concise top three only.
    expect(within(qb.querySelector("ol")).getAllByRole("listitem")).toHaveLength(3);

    await userEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(btn.getAttribute("aria-controls")).toBe(standingsList(qb).id);
    const rows = within(standingsList(qb)).getAllByRole("listitem");
    expect(rows).toHaveLength(12);
    expect(rows.map((r) => r.textContent.match(/Quarterback \d+/)[0])).toEqual(
      qbStandings.map((r) => r.value.playerName),
    );
    expect(btn).toHaveTextContent("Top 12 of 31 players");

    await userEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(standingsList(qb)).not.toBeVisible();
  });

  it("works from the keyboard", async () => {
    const { card } = show();
    const btn = toggle(card("top_offense"));
    btn.focus();
    await userEvent.keyboard("{Enter}");
    expect(btn).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard(" ");
    expect(btn).toHaveAttribute("aria-expanded", "false");
  });
});

describe("entities", () => {
  it("player rows use the canonical player-name primitive and name the rostering manager", async () => {
    const { card } = show();
    await userEvent.click(toggle(card("top_qb")));
    const first = within(standingsList(card("top_qb"))).getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("Quarterback 1");
    expect(first).toHaveTextContent("QB · BUF · rostered by Jason");
  });

  it("manager/team rows navigate to the canonical franchise view", async () => {
    const { card, onNavigate } = show();
    await userEvent.click(toggle(card("top_offense")));
    const list = standingsList(card("top_offense"));
    await userEvent.click(within(list).getByRole("button", { name: "Brent" }));
    expect(onNavigate).toHaveBeenCalledWith("franchise", { owner: "o2" });
  });

  it("NFL-team rows are franchises, not fantasy managers", async () => {
    const { card } = show();
    await userEvent.click(toggle(card("top_nfl_team")));
    const list = standingsList(card("top_nfl_team"));
    expect(within(list).queryAllByRole("button")).toHaveLength(0);
    expect(list).toHaveTextContent("BUF");
    expect(toggle(card("top_nfl_team"))).toHaveTextContent("2 qualifying NFL teams");
  });

  it("an event award without a race expands beside its history card, not inside it", async () => {
    const { container } = show();
    const wrap = container.querySelector('[data-award-standings="highest_single_week"]');
    expect(wrap.closest('[role="button"]')).toBeNull();
    const btn = within(wrap).getByRole("button", { name: /Expand standings/ });
    expect(btn).toHaveTextContent("2 qualifying results");
    await userEvent.click(btn);
    expect(within(wrap.querySelector("ol")).getAllByRole("listitem")[0]).toHaveTextContent("Week 2");
  });
});

describe("honesty", () => {
  it("fewer than twelve qualifying rows show only those rows", async () => {
    const { card } = show();
    await userEvent.click(toggle(card("waiver_king")));
    expect(within(standingsList(card("waiver_king"))).getAllByRole("listitem")).toHaveLength(3);
    expect(toggle(card("waiver_king"))).toHaveTextContent("3 qualifying managers");
  });

  it("a tie is shown as a tie, in the backend's order", async () => {
    const { card } = show();
    await userEvent.click(toggle(card("top_offense")));
    const ranks = within(standingsList(card("top_offense")))
      .getAllByRole("listitem")
      .map((li) => li.firstChild.textContent);
    expect(ranks).toEqual(["1", "T1"]);
  });

  it("an award without deciding evidence offers no standings and says why", () => {
    const { card } = show();
    const roy = card("def_roy");
    expect(within(roy).queryByRole("button", { name: /standings/i })).toBeNull();
    expect(roy.textContent).not.toMatch(/\b0\.0\b/);
  });
});

describe("2026 Waiver King eligibility", () => {
  it("ineligible managers keep their real metric and are labelled, and the award leader is the next eligible", async () => {
    const { card } = show();
    const wk = card("waiver_king");
    // The concise race is the AWARD race: the eligible leader.
    expect(within(wk.querySelector("ol")).getAllByRole("listitem")[0]).toHaveTextContent("Kich");
    await userEvent.click(toggle(wk));
    const rows = within(standingsList(wk)).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Blaine");
    expect(rows[0]).toHaveTextContent("+102.0 pts");
    expect(rows[0]).toHaveTextContent("Ineligible for 2026 award");
    expect(rows[0]).toHaveAttribute("data-eligible", "false");
    expect(rows[1]).toHaveTextContent("Joel");
    expect(rows[1]).toHaveTextContent("Ineligible for 2026 award");
    expect(rows[2]).toHaveTextContent("Kich");
    expect(rows[2]).toHaveTextContent("Award rank 1");
    expect(rows[2]).not.toHaveTextContent("Ineligible");
  });

  it("long names wrap inside the row instead of overflowing it", async () => {
    const { card } = show();
    await userEvent.click(toggle(card("waiver_king")));
    const meta = within(standingsList(card("waiver_king"))).getByText(/Rossini Panini/);
    expect(meta.className).toMatch(/standingsMeta/);
  });
});

describe("toggle does not leak into other cards", () => {
  it("expanding one race leaves the others collapsed", () => {
    const { card } = show();
    fireEvent.click(toggle(card("top_qb")));
    expect(toggle(card("waiver_king"))).toHaveAttribute("aria-expanded", "false");
  });
});
