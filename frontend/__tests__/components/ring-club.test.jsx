/**
 * The Ring Club (owner directive 2026-11-23, "BUILD THE RING CLUB").
 *
 * A public honor roll of NFL players with two or more verified Brisket
 * Dynasty championship rings, rendered on the League Hub History tab, plus a
 * compact "Championship rings" card on the public player journey page.
 *
 * The backend owns every fact: member order, shared ranks and ties,
 * prestige, ring counts, coverage and the empty-state message.  These tests
 * pin that the UI renders those facts verbatim and never re-derives them —
 * the order is the payload's order, "T-1" comes from `tied`, the empty
 * message is the payload's message, and a missing field renders nothing
 * rather than "null".
 */
import fs from "node:fs";
import path from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/league/advisor-bootstrap", () => ({
  leagueHomeHref: vi.fn(async () => "/league"),
}));

import HistorySection from "@/app/league/sections/history";
import RingClubCard from "@/app/league/sections/_ring-club";
import ChampionshipRingsCard from "@/app/league/player/[playerId]/championship-rings";
import { coverageNotes, playerCoverageNote, rankLabel, ringsAriaLabel } from "@/lib/ring-club";
import PlayerJourneyPage from "@/app/league/player/[playerId]/page";

const managers = new Map(
  [
    ["owner-A", "Joey", "Team X"],
    ["owner-B", "Ed", "Smoke House"],
  ].map(([id, name, team]) => [id, { ownerId: id, displayName: name, currentTeamName: team, avatar: "" }]),
);

function champ(season, ownerId, teamName, displayName, rosterId = 1) {
  return { season, ownerId, rosterId, teamName, displayName };
}

const MEMBERS = [
  {
    playerId: "4046",
    playerName: "Jane Doe",
    position: "QB",
    nflTeam: "BUF",
    rings: 3,
    prestige: true,
    rank: 1,
    tied: true,
    seasons: ["2022", "2024", "2026"],
    championships: [
      champ("2022", "owner-A", "Team X", "Joey"),
      champ("2024", "owner-B", "Smoke House", "Ed", 2),
      champ("2026", "owner-A", "Team X", "Joey"),
    ],
  },
  {
    playerId: "5000",
    playerName: "Zed Alpha",
    position: "WR",
    nflTeam: "MIN",
    rings: 3,
    prestige: true,
    rank: 1,
    tied: true,
    seasons: ["2022", "2024", "2026"],
    championships: [
      champ("2022", "owner-A", "Team X", "Joey"),
      champ("2024", "owner-B", "Smoke House", "Ed", 2),
      champ("2026", "owner-A", "Team X", "Joey"),
    ],
  },
  {
    playerId: "6001",
    playerName: "Amy Bench",
    position: null,
    nflTeam: null,
    rings: 2,
    prestige: false,
    rank: 3,
    tied: false,
    seasons: ["2024", "2026"],
    championships: [
      champ("2024", "owner-B", "Smoke House", "Ed", 2),
      champ("2026", "owner-A", "Team X", "Joey"),
    ],
  },
];

const COMPLETE_COVERAGE = {
  state: "complete",
  seasons: [],
  verifiedSeasons: ["2022", "2024", "2026"],
  unverifiedSeasons: [],
  partialSeasons: [],
  historyComplete: true,
  historyState: "complete",
  decidedChampionships: 3,
  singleRingPlayers: 92,
  ringedPlayers: 95,
};

function ringClub(over = {}) {
  return {
    title: "THE RING CLUB",
    subtitle: "Players with Multiple Championships",
    description:
      "The exclusive club of NFL players who have been part of two or more Brisket Dynasty championship-winning rosters.",
    minimumRings: 2,
    prestigeRings: 3,
    members: MEMBERS,
    memberCount: MEMBERS.length,
    coverage: COMPLETE_COVERAGE,
    emptyState: null,
    ...over,
  };
}

function emptyClub(kind, message, coverage) {
  return ringClub({
    members: [],
    memberCount: 0,
    coverage,
    emptyState: { kind, title: "THE RING CLUB", message },
  });
}

const historyData = (club) => ({
  hallOfFame: [],
  seasons: [{ season: "2026", standings: [] }],
  championsBySeason: [{ season: "2026", ownerId: "owner-A", displayName: "Joey", teamName: "Team X" }],
  ...(club === undefined ? {} : { ringClub: club }),
});

// Direct members only — each member's franchise rows are a nested list.
const memberItems = () => Array.from(screen.getByRole("list", { name: "THE RING CLUB" }).children);

describe("Ring Club card on the History tab", () => {
  it("sits right after the Champion timeline, with title, subtitle and description", () => {
    render(<HistorySection managers={managers} data={historyData(ringClub())} onNavigate={() => {}} />);
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    const timeline = headings.indexOf("Champion timeline");
    expect(timeline).toBeGreaterThanOrEqual(0);
    expect(headings[timeline + 1]).toMatch(/THE RING CLUB/);
    expect(headings[timeline + 1]).toContain("🏆");
    expect(screen.getByText("Players with Multiple Championships")).toBeInTheDocument();
    expect(screen.getByText(/The exclusive club of NFL players/)).toBeInTheDocument();
  });

  it("renders members in the payload's order with name, position and team", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    const items = memberItems();
    expect(items).toHaveLength(3);
    expect(items.map((li) => within(li).getByRole("link").textContent)).toEqual([
      "Jane Doe",
      "Zed Alpha",
      "Amy Bench",
    ]);
    expect(items[0].textContent).toContain("Jane Doe — QB — BUF");
    expect(items[1].textContent).toContain("Zed Alpha — WR — MIN");
  });

  it("links each player to the PUBLIC player journey, never the private Player File", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    expect(screen.getByRole("link", { name: "Jane Doe" })).toHaveAttribute("href", "/league/player/4046");
    for (const a of screen.getAllByRole("link")) {
      expect(a.getAttribute("href")).not.toMatch(/^\/players\//);
    }
  });

  it("shows the ring count with one trophy per ring, read as a single label", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    const [first, , third] = memberItems();
    const three = within(first).getByRole("img", { name: "3 championship rings" });
    expect(three.textContent).toBe("3🏆🏆🏆");
    expect(first.textContent).toContain("Championship Rings:");
    const two = within(third).getByRole("img", { name: "2 championship rings" });
    expect(two.textContent).toBe("2🏆🏆");
    expect(ringsAriaLabel(1)).toBe("1 championship ring");
  });

  it("lists the championship seasons and each season's franchise", () => {
    const onNavigate = vi.fn();
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={onNavigate} />);
    const [first] = memberItems();
    expect(first.textContent).toContain("Championship Seasons: 2022, 2024, 2026");
    const franchises = within(first).getByRole("list", { name: "Jane Doe's championship franchises" });
    const rows = within(franchises).getAllByRole("button");
    expect(rows.map((b) => b.textContent)).toEqual([
      expect.stringMatching(/2022.*Team X.*Joey/),
      expect.stringMatching(/2024.*Smoke House.*Ed/),
      expect.stringMatching(/2026.*Team X.*Joey/),
    ]);
    fireEvent.click(rows[1]);
    expect(onNavigate).toHaveBeenCalledWith("franchise", { owner: "owner-B" });
  });

  it("marks a shared rank T-1 and a sole rank plainly", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    const [first, second, third] = memberItems();
    const rankOf = (li) => li.firstElementChild.textContent;
    expect(rankOf(first)).toBe("T-1");
    expect(rankOf(second)).toBe("T-1");
    expect(rankOf(third)).toBe("3");
    expect(rankLabel({ rank: 1, tied: false })).toBe("1");
    expect(rankLabel({ rank: 2, tied: true })).toBe("T-2");
    expect(rankLabel({})).toBeNull();
  });

  it("gives the prestige treatment only to prestige members", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    const [first, second, third] = memberItems();
    for (const li of [first, second]) {
      expect(li.className).toMatch(/memberPrestige/);
      expect(li).toHaveAttribute("data-prestige", "true");
    }
    expect(third.className).not.toMatch(/memberPrestige/);
    expect(third).not.toHaveAttribute("data-prestige");
    // One club: no separate tier heading for prestige members.
    expect(screen.getAllByRole("heading")).toHaveLength(1);
  });

  it("renders a null team and position without the word null", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    const third = memberItems()[2];
    expect(third.textContent).not.toMatch(/null|undefined/);
    expect(within(third).getByRole("link", { name: "Amy Bench" })).toBeInTheDocument();
    expect(third.querySelector("[class*='name']").textContent).toBe("Amy Bench");
  });

  it("states the verified championship rosters under a complete club", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    expect(screen.getByText("Verified championship rosters: 2022, 2024, 2026")).toBeInTheDocument();
    expect(screen.queryByText(/Coverage is incomplete/)).toBeNull();
  });

  it("lays members out as a wrapping grid that collapses to one column on phones", () => {
    render(<RingClubCard ringClub={ringClub()} managers={managers} onNavigate={() => {}} />);
    const list = screen.getByRole("list", { name: "THE RING CLUB" });
    expect(list.className).toMatch(/members/);
    const css = fs.readFileSync(path.resolve(__dirname, "../../app/league/sections/ring-club.module.css"), "utf8");
    const rule = css.match(/\.members\s*\{[^}]*\}/)[0];
    expect(rule).toMatch(/display:\s*grid/);
    expect(rule).toMatch(/repeat\(auto-fill,\s*minmax\(min\(100%,\s*[\d.]+rem\),\s*1fr\)\)/);
  });
});

describe("Ring Club empty states", () => {
  const NO_MULTI = "No player has won more than one Brisket Dynasty championship yet.";
  const INCOMPLETE = "Championship rosters for every season could not be verified yet, so the club may be missing members.";
  const NONE_YET = "No Brisket Dynasty championship has been decided yet.";

  it("no_multi_champions shows its message and the verified rosters", () => {
    const club = emptyClub("no_multi_champions", NO_MULTI, {
      ...COMPLETE_COVERAGE,
      verifiedSeasons: ["2024", "2025"],
    });
    render(<RingClubCard ringClub={club} managers={managers} onNavigate={() => {}} />);
    expect(screen.getByText(NO_MULTI)).toHaveAttribute("data-empty-kind", "no_multi_champions");
    expect(screen.getByText("Verified championship rosters: 2024, 2025")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "THE RING CLUB" })).toBeNull();
  });

  it("coverage_incomplete shows its own message, never the no-multi-champions wording, and names the seasons", () => {
    const club = emptyClub("coverage_incomplete", INCOMPLETE, {
      ...COMPLETE_COVERAGE,
      state: "incomplete",
      verifiedSeasons: ["2024", "2025"],
      unverifiedSeasons: ["2023"],
      partialSeasons: ["2022"],
    });
    render(<RingClubCard ringClub={club} managers={managers} onNavigate={() => {}} />);
    expect(screen.getByText(INCOMPLETE)).toHaveAttribute("data-empty-kind", "coverage_incomplete");
    expect(screen.queryByText(NO_MULTI)).toBeNull();
    expect(screen.queryByText(/more than one/)).toBeNull();
    const note = screen.getByText(/Coverage is incomplete/);
    expect(note.textContent).toContain("Not verified: 2023.");
    expect(note.textContent).toContain("Partially verified: 2022.");
    expect(note.textContent).not.toContain("Earlier league seasons");
    expect(screen.getByText("Verified championship rosters: 2024, 2025")).toBeInTheDocument();
  });

  it("incomplete history with no season listed says earlier seasons could not all be read", () => {
    const club = emptyClub("coverage_incomplete", INCOMPLETE, {
      ...COMPLETE_COVERAGE,
      state: "incomplete",
      verifiedSeasons: ["2024", "2025"],
      unverifiedSeasons: [],
      partialSeasons: [],
      historyComplete: false,
      historyState: "truncated",
    });
    render(<RingClubCard ringClub={club} managers={managers} onNavigate={() => {}} />);
    expect(screen.getByText(INCOMPLETE)).toBeInTheDocument();
    const note = screen.getByText(/Coverage is incomplete/);
    expect(note.textContent).toBe("Coverage is incomplete. Earlier league seasons could not all be read.");
    expect(note.textContent).not.toMatch(/Not verified:|Partially verified:/);
  });

  it("an incomplete history beside listed seasons names both", () => {
    const { incompleteLine } = coverageNotes({
      state: "incomplete",
      verifiedSeasons: ["2025"],
      unverifiedSeasons: ["2024"],
      partialSeasons: [],
      historyComplete: false,
      historyState: "unverified",
    });
    expect(incompleteLine).toBe(
      "Coverage is incomplete. Not verified: 2024. Earlier league seasons could not all be read.",
    );
    // An incomplete state with neither field (an older payload) still says why.
    expect(coverageNotes({ state: "incomplete" }).incompleteLine).toBe(
      "Coverage is incomplete. Earlier league seasons could not all be read.",
    );
  });

  it("no_championships_yet shows its message and no coverage line", () => {
    const club = emptyClub("no_championships_yet", NONE_YET, {
      state: "none",
      seasons: [{ season: "2026", status: "undecided" }],
      verifiedSeasons: [],
      unverifiedSeasons: [],
      partialSeasons: [],
      decidedChampionships: 0,
      singleRingPlayers: 0,
      ringedPlayers: 0,
    });
    render(<RingClubCard ringClub={club} managers={managers} onNavigate={() => {}} />);
    expect(screen.getByText(NONE_YET)).toHaveAttribute("data-empty-kind", "no_championships_yet");
    expect(screen.queryByText(/Verified championship rosters/)).toBeNull();
    expect(screen.queryByText(/Coverage is incomplete/)).toBeNull();
  });
});

describe("Ring Club absent or partial payloads", () => {
  it("an absent ringClub renders nothing and the History tab still renders", () => {
    render(<HistorySection managers={managers} data={historyData(undefined)} onNavigate={() => {}} />);
    expect(screen.getByRole("heading", { name: "Champion timeline" })).toBeInTheDocument();
    expect(screen.queryByText(/THE RING CLUB/)).toBeNull();
    const { container } = render(<RingClubCard ringClub={undefined} managers={managers} onNavigate={() => {}} />);
    expect(container.innerHTML).toBe("");
  });

  it("a club with neither members nor an empty state renders nothing", () => {
    const { container } = render(
      <RingClubCard ringClub={{ title: "THE RING CLUB", members: [] }} managers={managers} onNavigate={() => {}} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("missing optional fields fall back without crashing", () => {
    render(
      <RingClubCard
        ringClub={{ members: [{ playerName: "No Id Guy", rings: 2, rank: 1 }] }}
        managers={managers}
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByRole("heading", { level: 2 }).textContent).toMatch(/THE RING CLUB/);
    expect(screen.getByText("Players with Multiple Championships")).toBeInTheDocument();
    // No playerId → plain text, never a guessed link.
    expect(screen.getByText("No Id Guy").closest("a")).toBeNull();
    expect(screen.getByRole("img", { name: "2 championship rings" })).toBeInTheDocument();
  });
});

describe("Championship rings card on the player journey", () => {
  const rings = (over = {}) => ({
    rings: 1,
    ringClubMember: false,
    championships: [champ("2025", "owner-B", "Still Jerry’s Team", "Ed", 2)],
    coverageState: "complete",
    unverifiedSeasons: [],
    ...over,
  });

  it("renders nothing for zero rings or an absent block", () => {
    const zero = render(<ChampionshipRingsCard championshipRings={rings({ rings: 0, championships: [] })} managers={managers} />);
    expect(zero.container.innerHTML).toBe("");
    const absent = render(<ChampionshipRingsCard championshipRings={undefined} managers={managers} />);
    expect(absent.container.innerHTML).toBe("");
  });

  it("one ring: the count, the season's franchise link, no Ring Club badge", () => {
    render(<ChampionshipRingsCard championshipRings={rings()} managers={managers} />);
    expect(screen.getByRole("heading", { name: "Championship rings" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "1 championship ring" }).textContent).toBe("1🏆");
    const link = screen.getByRole("link", { name: /2025.*Still Jerry’s Team.*Ed/ });
    expect(link).toHaveAttribute("href", "/league/franchise/owner-B");
    expect(screen.queryByText("Ring Club member")).toBeNull();
  });

  it("two rings: both seasons linked and the Ring Club member badge", () => {
    render(
      <ChampionshipRingsCard
        championshipRings={rings({
          rings: 2,
          ringClubMember: true,
          championships: [
            champ("2024", "owner-A", "Team X", "Joey"),
            champ("2025", "owner-B", "Still Jerry’s Team", "Ed", 2),
          ],
        })}
        managers={managers}
      />,
    );
    expect(screen.getByRole("img", { name: "2 championship rings" }).textContent).toBe("2🏆🏆");
    const links = within(screen.getByRole("list", { name: "Championship seasons" })).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/league/franchise/owner-A",
      "/league/franchise/owner-B",
    ]);
    expect(screen.getByText("Ring Club member")).toHaveClass("ds-badge--accent");
  });

  it("incomplete coverage says the count covers verified rosters only", () => {
    render(
      <ChampionshipRingsCard
        championshipRings={rings({ coverageState: "incomplete", unverifiedSeasons: ["2023"] })}
        managers={managers}
      />,
    );
    expect(screen.getByText("Counts verified championship rosters only. Not verified: 2023.")).toBeInTheDocument();
    // Incomplete history with no season listed still says why.
    expect(playerCoverageNote({ coverageState: "incomplete", unverifiedSeasons: [] })).toBe(
      "Counts verified championship rosters only. Earlier league seasons could not all be read.",
    );
    expect(playerCoverageNote({ coverageState: "complete" })).toBeNull();
  });

  it("ships no CSS module and no client component (server-rendered route stays JS-free)", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../../app/league/player/[playerId]/championship-rings.jsx"),
      "utf8",
    );
    expect(src).not.toMatch(/\.module\.css/);
    expect(src).not.toMatch(/^"use client"/m);
    expect(src).not.toMatch(/from "@\/components\/ds/);
  });
});

describe("player journey page wires the rings card", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubPlayer(player) {
    const payload = {
      league: { managers: [...managers.values()] },
      player: {
        identity: { playerId: "4046", playerName: "Jane Doe", position: "QB", nflTeam: "BUF", yearsExp: 5 },
        totalsByOwner: [],
        events: [],
        ownershipArc: [],
        ...player,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) =>
        String(url).includes("/api/public/league/player/")
          ? { ok: true, json: async () => payload }
          : { ok: true, json: async () => ({ items: [] }) },
      ),
    );
  }

  async function renderPage() {
    const el = await PlayerJourneyPage({ params: Promise.resolve({ playerId: "4046" }) });
    return render(el);
  }

  it("shows the card for a ringed player", async () => {
    stubPlayer({
      championshipRings: {
        rings: 2,
        ringClubMember: true,
        championships: [champ("2024", "owner-A", "Team X", "Joey"), champ("2025", "owner-B", "Smoke House", "Ed", 2)],
        coverageState: "complete",
        unverifiedSeasons: [],
      },
    });
    await renderPage();
    expect(screen.getByRole("heading", { name: "Championship rings" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "2 championship rings" })).toBeInTheDocument();
    expect(screen.getByText("Ring Club member")).toBeInTheDocument();
  });

  it("an older payload without the block renders the page without the card", async () => {
    stubPlayer({});
    await renderPage();
    expect(screen.getByRole("heading", { name: "Impact by manager" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Championship rings" })).toBeNull();
  });
});
