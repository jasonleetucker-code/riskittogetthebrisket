/**
 * Rookie-source coverage (DYN10 item 8): the one-line pool summary and the
 * per-row low-coverage marker on the existing rookie board, plus the pure
 * helpers that phrase them.  Display only — values and order are untouched.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/app/AppShellWrapper", () => ({
  useAuthContext: () => ({ authenticated: true, logout: vi.fn() }),
}));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeagueKey: "dynasty_main", loading: false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/draft",
  useSearchParams: () => new URLSearchParams(),
}));

import { RookieBoard } from "@/app/draft/page";
import {
  buildRookieCoverageIndex,
  coverageForName,
  coverageLine,
  coverageMarker,
} from "@/lib/rookie-source-coverage";

function player(id, name, rank) {
  return {
    id,
    name,
    rank,
    tier: "A",
    pos: "WR",
    team: "MIN",
    drafted: false,
    mine: false,
    userTag: null,
    preDraft: 40,
    marketValue: 38,
    inflatedFair: 42,
    enforceUpTo: 44,
    myWinningBid: 50 - rank,
    myMaxBid: 55,
    theoreticalMaxBid: 59,
    final: null,
    draftedTo: null,
  };
}

const PLAYERS = [
  player("p1", "Alpha Back", 1),
  player("p2", "Bravo Wide", 2),
  player("p3", "Charlie End", 3),
  player("p4", "Delta Tight", 4),
];

const CAPITAL = {
  rookieSourceCoverage: {
    state: "available",
    votingCount: 4,
    relevantCount: 6,
    lowCoverageBelow: 3,
    lowCoverageRows: 1,
    sources: [
      { key: "ktc", displayName: "KTC", state: "voting" },
      {
        key: "dlfRookieSf",
        displayName: "DLF Rookie SF",
        state: "missing",
      },
      {
        key: "dlfRookieIdp",
        displayName: "DLF Rookie IDP",
        state: "held",
      },
    ],
  },
  picks: [
    {
      rookieName: "Alpha Back",
      rookieSourceCoverage: { state: "ok", votingSourceCount: 5 },
    },
    {
      rookieName: "Bravo Wide",
      rookieSourceCoverage: { state: "low", votingSourceCount: 1 },
    },
    {
      rookieName: "Charlie End",
      rookieSourceCoverage: {
        state: "unknown",
        votingSourceCount: null,
        reason: "source_meta_unavailable",
      },
    },
  ],
};

function renderBoard(rookieCoverage) {
  const noop = () => {};
  return render(
    <RookieBoard
      rookieCoverage={rookieCoverage}
      stats={{
        enrichedPlayers: PLAYERS,
        tierStats: {},
        inflation: 1,
        remainingBudget: 200,
      }}
      workspace={{ teams: [{ name: "Me" }, { name: "Rival" }] }}
      marketDollars={{}}
      onDraft={noop}
      onEditPreDraft={noop}
      onRemovePlayer={noop}
      onCycleTag={noop}
      searchInputRef={{ current: null }}
      selectedPlayerId={null}
      onSelectRow={noop}
      quickRecordingId={null}
      onQuickOpen={noop}
      onQuickSubmit={noop}
      onQuickCancel={noop}
      needSet={new Set()}
      showDrafted={false}
      onShowDraftedChange={noop}
      query=""
      onQueryChange={noop}
      tagFilter="all"
      onTagFilterChange={noop}
      onAdd={noop}
    />,
  );
}

describe("rookie source coverage helpers", () => {
  it("phrases the pool line with the non-voting sources and low rows", () => {
    const line = coverageLine(CAPITAL.rookieSourceCoverage);
    expect(line).toContain("4 of 6 rookie sources voting");
    expect(line).toContain("DLF Rookie SF: vendor-empty / no usable rows");
    expect(line).toContain("DLF Rookie IDP: held");
    expect(line).not.toContain("KTC:");
    expect(line).toContain("1 rookie on fewer than 3 sources");
  });

  it("an unavailable pool says so instead of inventing a count", () => {
    expect(coverageLine({ state: "unavailable", votingCount: null })).toBe(
      "Rookie source coverage unavailable.",
    );
    expect(coverageLine(null)).toBeNull();
  });

  it("marks only low and unknown rows; unknown is never rendered as 0", () => {
    expect(coverageMarker({ state: "ok", votingSourceCount: 5 })).toBeNull();
    expect(coverageMarker({ state: "low", votingSourceCount: 1 }).text).toBe(
      "1 source",
    );
    const unknown = coverageMarker({
      state: "unknown",
      votingSourceCount: null,
    });
    expect(unknown.kind).toBe("unknown");
    expect(unknown.text).not.toMatch(/^0/);
    expect(coverageMarker(null)).toBeNull();
  });

  it("indexes per-rookie stamps by case-insensitive name", () => {
    const idx = buildRookieCoverageIndex(CAPITAL);
    expect(coverageForName(idx, "  bravo wide ").votingSourceCount).toBe(1);
    expect(coverageForName(idx, "Nobody")).toBeNull();
    expect(buildRookieCoverageIndex({ picks: [] })).toBeNull();
  });
});

describe("RookieBoard coverage line and marker", () => {
  it("renders the line and markers on the existing board", () => {
    renderBoard(buildRookieCoverageIndex(CAPITAL));
    expect(
      screen.getByTestId("rookie-source-coverage-line").textContent,
    ).toContain("4 of 6 rookie sources voting");
    const markers = screen.getAllByTestId("rookie-low-coverage");
    expect(markers.map((m) => m.getAttribute("data-kind"))).toEqual([
      "low",
      "unknown",
    ]);
    // Alpha (5 sources) and Delta (no stamp) get none.
    expect(markers).toHaveLength(2);
  });

  it("renders nothing extra when no coverage is supplied", () => {
    renderBoard(null);
    expect(screen.queryByTestId("rookie-source-coverage-line")).toBeNull();
    expect(screen.queryByTestId("rookie-low-coverage")).toBeNull();
    expect(screen.getByText("Alpha Back")).toBeInTheDocument();
  });
});
