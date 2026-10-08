/**
 * #1337 — the 2026-10-07 adoption pass, rendered.
 *
 * player-name-destination-guard.test.js pins WHICH surfaces route through
 * `PlayerNameButton`; this proves the routing does the right thing on the
 * converted surfaces: a player carrying a canonical Sleeper id is a link to
 * `/players/[playerId]`, an asset without one (a pick) is never a guessed
 * link, and no player link is nested inside another control.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SideCard } from "@/app/trade/trade-sections";
import SharpRosterPercentagePage from "@/app/market/sharp-roster-percentage/page";
import { sharpAssetPlayerId } from "@/lib/sharp-roster-percentage";

function expectTopLevel(link) {
  expect(link.parentElement.closest("button"), "link nested in a button").toBeNull();
  expect(link.parentElement.closest("a"), "link nested in a link").toBeNull();
}

// ── /trade asset rows ────────────────────────────────────────────────────

const PLAYER = {
  name: "Bijan Robinson",
  pos: "RB",
  position: "RB",
  assetClass: "offense",
  rankDerivedValue: 8000,
  values: { full: 8000 },
  rank: 1,
  blendedSourceRank: 1,
  sourceCount: 9,
  confidenceBucket: "high",
  raw: { playerId: "9509" },
};

const PICK = {
  name: "2027 Mid 1st",
  pos: "PICK",
  position: "PICK",
  assetClass: "pick",
  rankDerivedValue: 5606,
  values: { full: 5606 },
  rank: 48,
  blendedSourceRank: 48,
  sourceCount: 2,
  confidenceBucket: "high",
};

function renderSide({ sides, sideIdx = 0, incoming, onOpenPlayer = vi.fn() }) {
  render(
    <SideCard
      side={sides[sideIdx]}
      sideIdx={sideIdx}
      sides={sides}
      total={{ raw: 0, adjusted: 0 }}
      isMySide={false}
      selectedTeam={null}
      sideQuery=""
      isFocused={false}
      searchResults={[]}
      settings={{}}
      valueMode="full"
      valueOverrides={{}}
      incoming={incoming}
      balancers={null}
      onSideQueryChange={vi.fn()}
      onSideFocus={vi.fn()}
      onSideBlur={vi.fn()}
      onAddFromSearch={vi.fn()}
      onOpenPlayer={onOpenPlayer}
      onSetValueOverride={vi.fn()}
      onClearValueOverride={vi.fn()}
      onRemoveAsset={vi.fn()}
      onAddCopy={vi.fn()}
      onSetDestination={vi.fn()}
      onRemoveTeam={vi.fn()}
      onAddBalancer={vi.fn()}
      registerInputRef={vi.fn()}
      canRemoveTeam={false}
    />,
  );
  return { onOpenPlayer };
}

describe("/trade asset rows", () => {
  it("a player opens his Player File; a pick keeps the quick-view popup", async () => {
    const sides = [
      { label: "A", assets: [PLAYER, PICK], destinations: {} },
      { label: "B", assets: [], destinations: {} },
    ];
    const { onOpenPlayer } = renderSide({ sides });

    const link = screen.getByRole("link", { name: "Bijan Robinson" });
    expect(link).toHaveAttribute("href", "/players/9509");
    expectTopLevel(link);

    // The pick has no canonical id: never a link, still the popup button.
    expect(screen.queryByRole("link", { name: "2027 Mid 1st" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "2027 Mid 1st" }));
    expect(onOpenPlayer).toHaveBeenCalledWith(PICK);
  });

  it("an incoming player (3+ teams) links to the same Player File", () => {
    const sides = [
      { label: "A", assets: [], destinations: {} },
      { label: "B", assets: [PLAYER], destinations: {} },
      { label: "C", assets: [], destinations: {} },
    ];
    renderSide({ sides, incoming: [{ asset: PLAYER, fromSideIdx: 1 }] });
    const link = screen.getByRole("link", { name: "Bijan Robinson" });
    expect(link).toHaveAttribute("href", "/players/9509");
    expectTopLevel(link);
  });
});

// ── sharp boards ─────────────────────────────────────────────────────────

describe("sharpAssetPlayerId", () => {
  it("is the Sleeper id for a player row and null for a pick or a blank", () => {
    expect(sharpAssetPlayerId({ assetId: "4046", assetType: "player" })).toBe("4046");
    expect(sharpAssetPlayerId({ assetId: "4046" })).toBe("4046");
    expect(sharpAssetPlayerId({ assetId: "pick:2027:1", assetType: "player" })).toBeNull();
    expect(sharpAssetPlayerId({ assetId: "4046", assetType: "pick" })).toBeNull();
    expect(sharpAssetPlayerId({ assetId: "  " })).toBeNull();
    expect(sharpAssetPlayerId(null)).toBeNull();
    // A display name is never an id.
    expect(sharpAssetPlayerId({ displayName: "Justin Jefferson" })).toBeNull();
  });
});

describe("/market/sharp-roster-percentage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("a player row links to his Player File, a pick row stays text", async () => {
    const base = {
      rank: 1,
      sharpRosters: 4,
      eligibleRosters: 8,
      sharpRosterPct: 0.5,
      marketRosterPct: null,
      sharpRosterAdvantage: null,
      slots: {},
      buySell: null,
      sampleWarning: null,
      trend: {},
    };
    const board = {
      status: "ok",
      generatedAt: 1,
      lastUpdated: 1,
      players: [
        { ...base, assetId: "4046", assetType: "player", displayName: "Justin Jefferson", position: "WR" },
        { ...base, rank: 2, assetId: "pick:2027:1", assetType: "pick", displayName: "2027 Round 1 Pick", position: "PICK" },
      ],
      totalQualifyingPlayers: 2,
      transparency: {},
      cohort: {},
      sample: { eligibleRosters: 8, rankable: true, warning: null },
      marketComparison: { available: false },
      exclusions: { byReason: {}, excludedRosters: 0 },
      dataQuality: {},
    };
    global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => board }));
    render(<SharpRosterPercentagePage />);

    const link = await screen.findByRole("link", { name: "Justin Jefferson" });
    expect(link).toHaveAttribute("href", "/players/4046");
    expectTopLevel(link);
    const pickCell = screen.getByText("2027 Round 1 Pick");
    expect(pickCell.closest("a")).toBeNull();
    expect(within(pickCell.closest("tr")).queryByRole("link")).toBeNull();
  });
});
