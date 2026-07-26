/**
 * PlayerContextSection (R2) — the playerctx surface: contracts, snap
 * share, depth-chart standing.  Must render what exists, hide what
 * doesn't, and degrade silently on 404/missing snapshot.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

// PlayerPopup's module pulls the full hook graph — stub everything the
// section itself doesn't use.
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: [], rawData: {} }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: null }),
}));
vi.mock("@/components/useTerminal", () => ({
  useTerminal: () => ({ signals: [] }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({ state: {}, toggleWatchlist: vi.fn(), serverBacked: false }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {} }),
}));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeagueKey: "dynasty_main", loading: false }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ byPlayer: new Map(), digestByPlayer: new Map() }),
}));
vi.mock("@/components/PlayerRankHistoryChart", () => ({
  default: () => <div data-testid="rank-history-stub" />,
}));
vi.mock("next/link", () => ({
  default: ({ children, href }) => <a href={href}>{children}</a>,
}));

import { PlayerContextSection, _loadPlayerContext } from "@/components/PlayerPopup";

const CTX_PAYLOAD = {
  player: {
    gsisId: "00-0033280",
    sleeperId: "4034",
    name: "Christian McCaffrey",
    team: "SF",
    position: "RB",
    contract: {
      apy: 16015853,
      total: 64063412,
      guaranteed: 36346412,
      years: 4,
      yearSigned: 2020,
      endYear: 2023,
      team: "CAR",
    },
    snaps: { season: 2025, games: 19, side: "offense", pct: 81.7, recentPct: 75.3, trend: -6.4 },
    depth: { position: "RB", rank: 1, depthPosition: "RB", team: "SF" },
  },
  generatedAt: "2026-07-26T00:00:00+00:00",
};

function row(playerId = "4034") {
  return { name: "Christian McCaffrey", pos: "RB", raw: { playerId, team: "SF" } };
}

beforeEach(() => {
  // module-level cache persists across tests — use unique player ids
  vi.restoreAllMocks();
});

describe("PlayerContextSection", () => {
  it("renders contract, snaps, and depth blocks from the endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => CTX_PAYLOAD })
    );
    render(<PlayerContextSection row={row("4034")} />);
    await waitFor(() =>
      expect(screen.getByTestId("player-context")).toBeInTheDocument()
    );
    // contract: APY + end year + guaranteed + signing-team caveat
    expect(screen.getByText(/\$16\.0M\/yr thru 2023/)).toBeInTheDocument();
    expect(screen.getByText(/\$36\.3M gtd/)).toBeInTheDocument();
    expect(screen.getByText(/signed with CAR/)).toBeInTheDocument();
    // snaps: pct + season line + trend as a Movement (down 6.4%)
    expect(screen.getByText("81.7%")).toBeInTheDocument();
    expect(screen.getByText(/2025 season · 19 gm \(offense\)/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /snap share down 6\.4/ })).toBeInTheDocument();
    // depth: RB1 + starter badge
    expect(screen.getByText("RB1")).toBeInTheDocument();
    expect(screen.getByText("starter")).toBeInTheDocument();
  });

  it("renders nothing when the endpoint has no context (silent degrade)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
    );
    const { container } = render(<PlayerContextSection row={row("0000")} />);
    // give the effect a tick to resolve
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container.querySelector("[data-testid=player-context]")).toBeNull();
  });

  it("skips the fetch entirely for rows without a Sleeper id (picks)", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<PlayerContextSection row={{ name: "2027 1st", pos: "PICK", raw: {} }} />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("_loadPlayerContext caches per player id", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => CTX_PAYLOAD });
    vi.stubGlobal("fetch", fetchSpy);
    await _loadPlayerContext("7777");
    await _loadPlayerContext("7777");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
