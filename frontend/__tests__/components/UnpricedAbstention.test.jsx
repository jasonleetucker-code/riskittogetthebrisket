/**
 * Unpriced rows must abstain, not fabricate — W07-F003 / W07-F004.
 *
 * On the live 1,092-row contract, 239 non-pick rows carry
 * ``canonicalConsensusRank: null`` AND ``rankDerivedValue: null`` AND
 * ``canonicalTierId: null`` AND ``confidenceBucket: "none"``.  The board
 * could not price them.  222 of them still rendered:
 *
 *   #865 · Tier 10 · RB 115 · Low · "0" · EDGE "SELL"
 *
 * — every one of those five cells invented client-side from an array
 * index.  ``buildRows`` assigned ``r.rank = computedConsensusRank``,
 * ``tierLabel`` fell through to ``rankBasedTierLabel(row.rank)``, the
 * page re-derived RB115 from the same ordinal, ``confBadgeLabel("none")``
 * returned "Low", and ``marketAction`` recomputed a BUY/SELL verdict off
 * per-source ranks without ever consulting the board's own refusal.
 *
 * This file runs the REAL materializer over a contract-shaped payload
 * and renders the REAL page, so it covers the whole chain rather than
 * any one helper.  Every assertion below is on a row the backend
 * declined to price.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";

import { buildRows } from "@/lib/dynasty-data";

// ── A contract-shaped payload: 3 priced rows + 1 the board refused ──
function pricedRow(name, pos, rank, value) {
  return {
    displayName: name,
    canonicalName: name,
    playerId: `id-${name}`,
    position: pos,
    team: "MIN",
    assetClass: pos === "RB" || pos === "WR" || pos === "QB" ? "offense" : "idp",
    canonicalConsensusRank: rank,
    rankDerivedValue: value,
    canonicalTierId: 1,
    confidenceBucket: "high",
    confidenceLabel: "High",
    sourceCount: 4,
    blendedSourceRank: rank + 0.4,
    values: { overall: value, finalAdjusted: value, displayValue: value, rawComposite: value },
    canonicalSiteValues: { ktcSfTep: value, dlf: value },
    sourceRanks: { ktcSfTep: rank, dlf: rank },
    effectiveSourceRanks: { ktcSfTep: rank, dlf: rank },
  };
}

// Shaped exactly like Austin Ekeler on the 2026-08-04 contract: every
// backend stamp absent, but per-source ranks present and far apart —
// which is what used to manufacture a directional verb.
const UNPRICED = {
  displayName: "Austin Ekeler",
  canonicalName: "Austin Ekeler",
  playerId: "id-Austin Ekeler",
  position: "RB",
  team: "WAS",
  assetClass: "offense",
  canonicalConsensusRank: null,
  rankDerivedValue: null,
  canonicalTierId: null,
  positionRank: null,
  confidenceBucket: "none",
  confidenceLabel: "None - unranked",
  marketGapDirection: "none",
  edgeSignal: null,
  sourceCount: 2,
  values: { overall: null, finalAdjusted: null, displayValue: null, rawComposite: 0 },
  canonicalSiteValues: {},
  // ktcSfTep is retail; dlf is expert.  A 300-rank gap → "BUY" pre-fix.
  sourceRanks: { ktcSfTep: 400, dlf: 100 },
  effectiveSourceRanks: { ktcSfTep: 400, dlf: 100 },
};

const PAYLOAD = {
  playersArray: [
    pricedRow("Justin Jefferson", "WR", 1, 9541),
    pricedRow("Bijan Robinson", "RB", 2, 9155),
    pricedRow("Saquon Barkley", "RB", 3, 8900),
    UNPRICED,
  ],
};

const ROWS = buildRows(PAYLOAD);

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    source: "test",
    rows: ROWS,
    rawData: { dataFreshness: { generatedAt: "2026-08-04T00:00:00Z" } },
  }),
}));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ openPlayerPopup: vi.fn(), rows: ROWS, rawData: {} }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({
    settings: { showSiteCols: false, hiddenSiteCols: {}, siteWeights: {} },
    update: vi.fn(),
    updateSiteWeight: vi.fn(),
    resetSiteWeights: vi.fn(),
  }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ idpEnabled: true, selectedLeagueKey: "dynasty_main" }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({
    state: { watchlist: [] },
    toggleWatchlist: vi.fn(),
    serverBacked: false,
  }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ byPlayer: new Map(), digestByPlayer: new Map() }),
}));
vi.mock("@/components/graphs/HillCurveExplorer", () => ({ default: () => null }));
vi.mock("@/components/graphs/TierGapWaterfall", () => ({ default: () => null }));
vi.mock("@/components/graphs/RankChangeGlyph", () => ({ default: () => null }));
vi.mock("@/components/graphs/SourceContributionBars", () => ({ default: () => null }));
vi.mock("@/components/graphs/SourceAgreementRadar", () => ({ default: () => null }));

import RankingsPage from "@/app/rankings/page";

function rowFor(name) {
  const tr = screen
    .getAllByRole("row")
    .find((r) => within(r).queryByTitle(new RegExp(`Open ${name}`)));
  expect(tr, `no rendered row for ${name}`).toBeTruthy();
  return tr;
}

describe("buildRows — an unpriced row carries no rank (W07-F003)", () => {
  it("assigns rank null when the backend declined to price the row", () => {
    const ekeler = ROWS.find((r) => r.name === "Austin Ekeler");
    expect(ekeler.rankDerivedValue).toBeNull();
    expect(ekeler.rank).toBeNull();
    // The internal sort ordinal survives — it is a sort key, not a rank.
    expect(ekeler.computedConsensusRank).toBe(4);
  });

  it("still stamps backend ranks verbatim on priced rows", () => {
    expect(ROWS.find((r) => r.name === "Justin Jefferson").rank).toBe(1);
    expect(ROWS.find((r) => r.name === "Saquon Barkley").rank).toBe(3);
  });
});

describe("/rankings — no fabricated cells on an unpriced row (W07-F004)", () => {
  it("renders no rank, no tier, no positional rank, no confidence grade, no verdict, no value", () => {
    render(<RankingsPage />);
    const tr = rowFor("Austin Ekeler");
    const cells = within(tr).getAllByRole("cell");

    // # column
    expect(cells[0].textContent.trim()).toBe("—");
    // Tier column — never a "Tier N" derived from an array index
    expect(cells[1].textContent.trim()).toBe("Unranked");
    // Pos column — "RB", with no positional ordinal appended
    expect(cells[3].textContent.trim()).toBe("RB");
    // Value column — an unpriced row shows no number at all
    expect(within(tr).queryByText("0")).toBeNull();
    // Confidence + Edge: an explicit abstention, not "Low" / "BUY"
    expect(within(tr).queryByText("Low")).toBeNull();
    expect(within(tr).queryByText("BUY")).toBeNull();
    expect(within(tr).queryByText("SELL")).toBeNull();
    expect(within(tr).queryByText("HOLD")).toBeNull();
  });

  it("leaves the priced rows fully rendered", () => {
    render(<RankingsPage />);
    const tr = rowFor("Justin Jefferson");
    const cells = within(tr).getAllByRole("cell");
    expect(cells[0].textContent.trim()).toBe("1");
    expect(cells[1].textContent.trim()).toBe("Tier 1");
    expect(cells[3].textContent.trim()).toBe("WR1");
    expect(tr).toHaveTextContent("9,541");
    expect(within(tr).getByText("High")).toBeInTheDocument();
  });
});
