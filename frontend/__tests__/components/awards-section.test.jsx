import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AwardsSection, { groupAwards, vorpExclusionNote } from "@/app/league/sections/awards";

const managers = new Map([
  ["owner-a", { displayName: "Jason", currentTeamName: "Brisket Club", avatar: "manager-a" }],
  ["owner-b", { displayName: "Ed", currentTeamName: "Smoke House", avatar: "manager-b" }],
]);

function playerLeader(rank, name, ownerId = "owner-a") {
  return {
    rank,
    ownerId,
    displayName: managers.get(ownerId).displayName,
    value: {
      playerId: `${name}-${rank}`,
      playerName: name,
      position: "QB",
      team: "MIN",
      vorp: 30 - rank,
      starterPoints: 40 - rank,
      gamesStarted: 2,
    },
  };
}

function race(key, label, leaders, value = {}) {
  return { key, label, description: `${label} description`, leaders, ...value };
}

const races = [
  race("manager_of_the_year", "Manager of the Year Race", [
    {
      rank: 1,
      ownerId: "owner-b",
      displayName: "Ed",
      value: { compositeScore: 0.91 },
    },
  ]),
  race("top_qb", "Top QB Race", [
    playerLeader(1, "Quarterback One"),
    playerLeader(2, "Quarterback Two", "owner-b"),
    playerLeader(3, "Quarterback Three"),
    playerLeader(4, "Quarterback Four"),
  ]),
  race("playoff_mvp", "Playoff MVP", [playerLeader(1, "Future Playoff Star")]),
  race("off_mvp", "Offensive Player of the Year Race", [playerLeader(1, "Offensive Star")]),
  race("league_mvp", "League MVP Race", [playerLeader(1, "League Star")]),
];

const awards = [
  {
    key: "manager_of_the_year",
    label: "Manager of the Year",
    description: "Best manager.",
    ownerId: "owner-b",
    displayName: "Ed",
    teamName: "Smoke House",
    value: { compositeScore: 0.91, wins: 2, losses: 0, pointsFor: 700 },
  },
  {
    key: "playoff_mvp",
    label: "Playoff MVP",
    description: "Best postseason player.",
    ownerId: "owner-a",
    displayName: "Jason",
    value: playerLeader(1, "Future Playoff Star").value,
  },
  {
    key: "league_mvp",
    label: "League MVP",
    description: "Most valuable player.",
    ownerId: "owner-a",
    displayName: "Jason",
    value: playerLeader(1, "League Star").value,
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
      awards,
      finalists: {},
    },
  ],
};

describe("AwardsSection", () => {
  it("puts current player races first and postseason races last", () => {
    const grouped = groupAwards(races);
    expect(grouped.players.map((item) => item.key)).toEqual([
      "league_mvp",
      "off_mvp",
      "top_qb",
    ]);
    expect(grouped.managers.map((item) => item.key)).toEqual([
      "manager_of_the_year",
    ]);
    expect(grouped.postseason.map((item) => item.key)).toEqual(["playoff_mvp"]);
  });

  it("renders a saveable, top-three race board with compact player rows", () => {
    const { container } = render(
      <AwardsSection managers={managers} data={data} onNavigate={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: "Save weekly snapshot" }),
    ).toBeInTheDocument();

    const raceCards = [...container.querySelectorAll("[data-award-key]")];
    expect(raceCards.map((node) => node.dataset.awardKey)).toEqual([
      "league_mvp",
      "off_mvp",
      "top_qb",
      "manager_of_the_year",
      "playoff_mvp",
    ]);

    const qbRace = container.querySelector('[data-award-key="top_qb"]');
    expect(within(qbRace).getAllByRole("listitem")).toHaveLength(3);
    expect(qbRace.textContent).not.toContain("Quarterback Four");
    expect(qbRace.textContent.match(/Quarterback One/g)).toHaveLength(1);
    expect(within(qbRace).getAllByRole("img")).toHaveLength(3);
  });

  it("orders winner cards as players, managers, then later-season honors", () => {
    const { container } = render(
      <AwardsSection managers={managers} data={data} onNavigate={vi.fn()} />,
    );
    const cards = [...container.querySelectorAll('[role="button"]')].filter(
      (node) => node.textContent.includes("Award history"),
    );
    expect(cards.map((node) => node.textContent)).toEqual([
      expect.stringContaining("League MVP"),
      expect.stringContaining("Manager of the Year"),
      expect.stringContaining("Playoff MVP"),
    ]);

    const playerWinner = cards[0];
    expect(within(playerWinner).getAllByRole("img")).toHaveLength(1);
    expect(playerWinner).toHaveTextContent("Rostered by Jason");
  });
  it("explains a position excluded from the VORP awards instead of hiding it", () => {
    const exclusion = {
      position: "DB",
      reason: "insufficient_replacement_band",
      poolSize: 1,
      required: 6,
    };
    const withExclusion = {
      ...data,
      awardRaces: races.map((r) =>
        r.key === "league_mvp" ? { ...r, vorpExclusions: [exclusion] } : r,
      ),
      bySeason: [{ ...data.bySeason[0], vorpExclusions: [exclusion] }],
    };
    const { container } = render(
      <AwardsSection managers={managers} data={withExclusion} onNavigate={vi.fn()} />,
    );
    const mvpRace = container.querySelector('[data-award-key="league_mvp"]');
    expect(mvpRace).toHaveTextContent(
      "DB excluded — not enough rostered players to set a replacement level",
    );
    // The race's leaders still render: an exclusion is a note, not an empty board.
    expect(mvpRace).toHaveTextContent("League Star");
    const offRace = container.querySelector('[data-award-key="off_mvp"]');
    expect(offRace.querySelector("[data-vorp-exclusion]")).toBeNull();
    expect(container.querySelectorAll("[data-vorp-exclusion]")).toHaveLength(2);
  });

  it("formats the exclusion note by reason and renders nothing when there is none", () => {
    expect(vorpExclusionNote(undefined)).toBeNull();
    expect(vorpExclusionNote([])).toBeNull();
    expect(vorpExclusionNote([{ position: "FB", reason: "no_bench_population" }])).toBe(
      "FB excluded — no bench scoring on record to set a replacement level",
    );
  });
});
