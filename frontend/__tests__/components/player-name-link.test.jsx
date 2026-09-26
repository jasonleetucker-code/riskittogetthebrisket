/**
 * #1337 — canonical player links.
 *
 * `PlayerNameButton` is THE player-name primitive: a name that carries a
 * canonical Sleeper `playerId` is a real link to the Universal Player
 * Profile / Player File (`/players/[playerId]`); a name without one is
 * never routed by display name (quick-view button when a handler is
 * given, otherwise plain text).
 *
 * Covered here:
 *   1. the primitive — href for a known id, encoding, missing id → text,
 *      the legacy quick-view fallback, and that a name is never an id;
 *   2. keyboard — the link is reachable with Tab and activates on Enter;
 *   3. surfaces converted in this slice — Game Day (per-game players,
 *      best-ball lineup tables, slate bye list, stat corrections), the
 *      /rankings signal rails, the /edge player column inside an
 *      interactive DataTable row — each rendering the right href, a
 *      plain-text fallback for an id-less player, and no link nested in
 *      a button (or another link).
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  DataTable,
  PlayerNameButton,
  canonicalPlayerId,
  playerProfileHref,
} from "@/components/ds";
import GamePlayers from "@/components/game-day/GamePlayers";
import NflSlate from "@/components/game-day/NflSlate";
import BestBallDetailsBody from "@/components/game-day/BestBallDetailsBody";
import DataInfoBody from "@/components/game-day/DataInfoBody";
import { TopMoversRail } from "@/app/rankings/board-sections";
import { colPlayer } from "@/app/edge/edge-columns";

/** Every canonical player link on the page must be a top-level control:
 *  no <a> inside a <button>, and no <a> inside another <a>. */
function expectNoNestedPlayerLinks(container) {
  const links = container.querySelectorAll("a.ds-player-name");
  for (const a of links) {
    expect(a.parentElement.closest("button"), `${a.textContent} sits inside a button`).toBeNull();
    expect(a.parentElement.closest("a"), `${a.textContent} sits inside a link`).toBeNull();
  }
  return links.length;
}

// ── 1. The primitive ─────────────────────────────────────────────────────

describe("PlayerNameButton — canonical Player File link", () => {
  it("renders a link to /players/[playerId] for a known canonical id", () => {
    render(<PlayerNameButton name="Josh Allen" playerId="4984" />);
    const link = screen.getByRole("link", { name: "Josh Allen" });
    expect(link).toHaveAttribute("href", "/players/4984");
    expect(link).toHaveClass("ds-player-name");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("percent-encodes the id rather than trusting it in a path", () => {
    render(<PlayerNameButton name="Odd Id" playerId="a/b c" />);
    expect(screen.getByRole("link", { name: "Odd Id" })).toHaveAttribute(
      "href",
      "/players/a%2Fb%20c",
    );
  });

  it("renders plain text — never a link — when no canonical id is available", () => {
    const { container } = render(<PlayerNameButton name="Mystery Man" playerId={null} />);
    expect(screen.getByText("Mystery Man").tagName).toBe("SPAN");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("treats a blank id as missing", () => {
    render(<PlayerNameButton name="Blank" playerId="   " />);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("keeps the quick-view button for an id-less row when a handler is given", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const row = { name: "2027 Early 1st", assetClass: "pick" };
    render(<PlayerNameButton name={row.name} row={row} onOpen={onOpen} />);
    expect(screen.queryByRole("link")).toBeNull();
    await user.click(screen.getByRole("button", { name: "2027 Early 1st" }));
    expect(onOpen).toHaveBeenCalledWith(row);
  });

  it("prefers the link over the quick-view when both an id and a handler exist", () => {
    const onOpen = vi.fn();
    render(<PlayerNameButton name="Bijan Robinson" playerId="9509" onOpen={onOpen} />);
    expect(screen.getByRole("link", { name: "Bijan Robinson" })).toHaveAttribute(
      "href",
      "/players/9509",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("canonicalPlayerId reads id fields only — a name is never an id", () => {
    expect(canonicalPlayerId({ name: "Josh Allen" })).toBeNull();
    expect(canonicalPlayerId({ name: "Josh Allen", raw: { playerId: "4984" } })).toBe("4984");
    expect(canonicalPlayerId({ name: "Josh Allen", playerId: 4984 })).toBe("4984");
    expect(canonicalPlayerId({ raw: { playerId: "" }, playerId: "" })).toBeNull();
    expect(canonicalPlayerId(null)).toBeNull();
    expect(playerProfileHref(null)).toBeNull();
    expect(playerProfileHref("4984")).toBe("/players/4984");
  });
});

// ── 2. Keyboard ──────────────────────────────────────────────────────────

describe("PlayerNameButton — keyboard", () => {
  it("is reachable with Tab and activates on Enter", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn((e) => e.preventDefault()); // keep jsdom from navigating
    render(
      <>
        <button type="button">before</button>
        <PlayerNameButton name="Justin Jefferson" playerId="6794" onClick={onClick} />
      </>,
    );
    await user.tab();
    await user.tab();
    const link = screen.getByRole("link", { name: "Justin Jefferson" });
    expect(link).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

// ── 3. Converted surfaces ────────────────────────────────────────────────

const GAME = {
  gameId: "2026_3_ATL_GB",
  awayTeam: "ATL",
  homeTeam: "GB",
  players: [
    {
      playerId: "7564",
      name: "Drake London",
      side: "team",
      state: "in_progress",
      pointsScored: 8.4,
      projectedRemaining: 6.1,
    },
    {
      playerId: null,
      name: "Unresolved Guy",
      side: "opponent",
      state: "not_started",
      projectedRemaining: 4.0,
    },
  ],
};

describe("Game Day — player names", () => {
  it("per-game players: canonical link for a known id, plain text without one", () => {
    const { container } = render(
      <GamePlayers game={GAME} index={new Map()} teamName="Mine" opponentName="Theirs" />,
    );
    expect(screen.getByRole("link", { name: "Drake London" })).toHaveAttribute(
      "href",
      "/players/7564",
    );
    expect(screen.queryByRole("link", { name: "Unresolved Guy" })).toBeNull();
    expect(screen.getByText("Unresolved Guy")).toBeInTheDocument();
    expect(expectNoNestedPlayerLinks(container)).toBe(1);
  });

  it("slate bye list: each named player links by id", () => {
    const payload = {
      team: { displayName: "Mine" },
      opponent: { displayName: "Theirs" },
      nflSlate: {
        scheduleState: "available",
        games: [],
        byeWeek: [
          { playerId: "4046", name: "Patrick Mahomes", side: "team" },
          { playerId: "6813", name: "Jonathan Taylor", side: "opponent" },
        ],
        unattributed: [{ playerId: null, name: "Free Agent Fred", side: "team" }],
      },
    };
    const { container } = render(<NflSlate payload={payload} />);
    expect(screen.getByRole("link", { name: "Patrick Mahomes" })).toHaveAttribute(
      "href",
      "/players/4046",
    );
    expect(screen.getByRole("link", { name: "Jonathan Taylor" })).toHaveAttribute(
      "href",
      "/players/6813",
    );
    expect(screen.queryByRole("link", { name: "Free Agent Fred" })).toBeNull();
    expect(screen.getByText(/On bye:/).textContent).toBe(
      "On bye: Patrick Mahomes, Jonathan Taylor.",
    );
    expect(expectNoNestedPlayerLinks(container)).toBe(2);
  });

  it("best-ball lineup tables and the unknown-state note link by id", () => {
    const side = {
      displayName: "Mine",
      players: [
        { playerId: "4984", name: "Josh Allen", finalLineupPct: 97 },
        { playerId: "8130", name: "Trey McBride", finalLineupPct: 40 },
      ],
      actualLineup: {
        lineupState: "live",
        total: 30.2,
        slots: [{ slotIndex: 0, slot: "QB", playerId: "4984", name: "Josh Allen", points: 30.2 }],
        unknownStatePlayerIds: ["8130"],
      },
    };
    const payload = { mode: "live", team: side, opponent: null };
    const { container } = render(<BestBallDetailsBody payload={payload} />);
    const allen = screen.getAllByRole("link", { name: "Josh Allen" });
    expect(allen.length).toBeGreaterThan(0);
    for (const a of allen) expect(a).toHaveAttribute("href", "/players/4984");
    const mcbride = screen.getAllByRole("link", { name: "Trey McBride" });
    expect(mcbride.length).toBeGreaterThan(0);
    for (const a of mcbride) expect(a).toHaveAttribute("href", "/players/8130");
    expect(screen.getByText(/Game status unknown for/)).toContainElement(mcbride[0]);
    expect(expectNoNestedPlayerLinks(container)).toBeGreaterThan(1);
  });

  it("stat corrections name the player as a canonical link", () => {
    const payload = {
      team: { displayName: "Mine", players: [{ playerId: "4984", name: "Josh Allen" }] },
      opponent: { displayName: "Theirs", players: [] },
      freshness: {
        state: "current",
        statCorrections: {
          pendingHost: [
            { playerId: "4984", gameId: "g1", scoredDeltaUnderLeagueCard: 1.5, hostPointsNow: 20 },
          ],
          reflectedInHostCount: 0,
          notScoredByLeagueCount: 0,
        },
      },
    };
    render(<DataInfoBody payload={payload} />);
    expect(screen.getByRole("link", { name: "Josh Allen" })).toHaveAttribute(
      "href",
      "/players/4984",
    );
  });
});

describe("/rankings signal rails", () => {
  it("links players by id; an id-less pick keeps the quick-view button", async () => {
    const user = userEvent.setup();
    const onPlayerClick = vi.fn();
    const player = { name: "Puka Nacua", pos: "WR", rank: 12, rankChange: 5, raw: { playerId: "9493" } };
    const pick = { name: "2027 Early 1st", pos: "PICK", rank: 30, rankChange: -4, raw: {} };
    const { container } = render(
      <TopMoversRail risers={[player]} fallers={[pick]} onPlayerClick={onPlayerClick} />,
    );
    const link = screen.getByRole("link", { name: /Puka Nacua/ });
    expect(link).toHaveAttribute("href", "/players/9493");
    await user.click(screen.getByRole("button", { name: /2027 Early 1st/ }));
    expect(onPlayerClick).toHaveBeenCalledWith(pick);
    expect(expectNoNestedPlayerLinks(container)).toBe(1);
  });
});

describe("/edge player column inside an interactive DataTable row", () => {
  const rows = [
    { name: "CeeDee Lamb", team: "DAL", pos: "WR", rank: 5, raw: { playerId: "6786" } },
    { name: "No Id Rookie", team: "FA", pos: "RB", rank: 90, raw: {} },
  ];

  it("the name link navigates without also activating the row; the row keeps the quick-view", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    const onPlayerClick = vi.fn();
    const { container } = render(
      <DataTable
        caption="edge"
        columns={[colPlayer(onPlayerClick), { key: "pos", header: "Pos", render: (r) => r.pos }]}
        rows={rows}
        rowKey={(r) => r.name}
        onRowClick={onRowClick}
      />,
    );
    const link = screen.getByRole("link", { name: /CeeDee Lamb/ });
    expect(link).toHaveAttribute("href", "/players/6786");
    // A click on the link must not bubble into row activation.
    link.addEventListener("click", (e) => e.preventDefault());
    await user.click(link);
    expect(onRowClick).not.toHaveBeenCalled();
    // The row itself still opens the quick-view.
    const row = link.closest("tr");
    await user.click(within(row).getByText("WR"));
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
    // id-less row: legacy quick-view button, never a name route.
    expect(screen.queryByRole("link", { name: /No Id Rookie/ })).toBeNull();
    expect(screen.getByRole("button", { name: /No Id Rookie/ })).toBeInTheDocument();
    expect(expectNoNestedPlayerLinks(container)).toBe(1);
  });
});
