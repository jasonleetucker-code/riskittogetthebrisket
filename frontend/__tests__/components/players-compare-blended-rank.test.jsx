/**
 * V1-98 — /players/compare "Blended rank" stat.
 *
 * `docs/OWNER_FEATURE_INVENTORY.md` 6.7 records this stat as "renders
 * empty on the compare page". Tracing the live path shows the backend
 * computation (`data_contract.py`: mean of `effectiveSourceRanks`, the
 * post-Hampel-filtered per-source ranks) and the frontend materializer
 * (`dynasty-data.js`: `blendedSourceRank: player.blendedSourceRank ?? null`)
 * are both correct — a real number for a covered player, honest `null`
 * for one outside the ranked pool — and `page.jsx` already renders
 * `blended != null ? blended.toFixed(1) : "—"`. The gap this file closes
 * is that nothing pinned any of it: the page had zero test coverage, so
 * a future regression at any of those three points (backend stops
 * stamping the field, the materializer starts fabricating a client-side
 * rank instead of threading the backend stamp, or the page falls back to
 * printing a raw `undefined`/`NaN`) could ship silently.
 *
 * Three states pinned:
 * - a row WITH source coverage renders the real blended rank, formatted
 *   to one decimal — never the raw unformatted number, never blank.
 * - a row with NO source coverage (backend correctly stamped `null`)
 *   renders the honest "—" fallback — never blank, never "undefined",
 *   never "NaN".
 * - the number rendered is NEVER invented by the frontend: it comes
 *   straight from `row.blendedSourceRank`, so a row whose materializer
 *   forgot to thread the field (`undefined`, not the backend's explicit
 *   `null`) falls to the same honest "—" as a genuinely uncovered
 *   player, rather than the page computing its own average from
 *   `sourceOriginalRanks`.
 */

import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/players/compare",
  useSearchParams: () => new URLSearchParams("p1=Covered+Player&p2=Uncovered+Player"),
}));

let mockRows = [];
vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: mockRows,
    rawData: { sleeper: { teams: [] } },
  }),
}));

import ComparePlayersPage from "@/app/players/compare/page";

function row(overrides = {}) {
  return {
    name: "Covered Player",
    displayName: "Covered Player",
    pos: "WR",
    position: "WR",
    assetClass: "offense",
    canonicalConsensusRank: 12,
    rankDerivedValue: 8000,
    values: { full: 8000 },
    sourceCount: 5,
    quarantined: false,
    confidenceBucket: "high",
    sourceOriginalRanks: { ktcSfTep: 10, idpTradeCalc: 14 },
    blendedSourceRank: null,
    ...overrides,
  };
}

function blendedRankValues() {
  // Each "Blended rank" label is followed by its value in a sibling div
  // (the Stat component: label div, then value div, both children of
  // one stat-box div).
  return screen.getAllByText("Blended rank").map((label) => {
    const statBox = label.parentElement;
    const valueDiv = statBox.children[1];
    return valueDiv.textContent;
  });
}

describe("/players/compare — Blended rank stat (V1-98)", () => {
  it("renders the real backend-stamped value, formatted to one decimal, for a covered player", () => {
    mockRows = [
      row({ name: "Covered Player", displayName: "Covered Player", blendedSourceRank: 12.34 }),
      row({
        name: "Uncovered Player",
        displayName: "Uncovered Player",
        canonicalConsensusRank: null,
        sourceOriginalRanks: {},
        blendedSourceRank: null,
      }),
    ];
    render(<ComparePlayersPage />);
    const values = blendedRankValues();
    expect(values).toContain("12.3");
    // Never the raw unrounded number, never a stray decimal count.
    expect(screen.queryByText("12.34")).toBeNull();
  });

  it("renders the honest '—' fallback for a player with no source coverage — never blank, 'undefined' or 'NaN'", () => {
    mockRows = [
      row({ name: "Covered Player", displayName: "Covered Player", blendedSourceRank: 12.34 }),
      row({
        name: "Uncovered Player",
        displayName: "Uncovered Player",
        canonicalConsensusRank: null,
        sourceOriginalRanks: {},
        blendedSourceRank: null,
      }),
    ];
    render(<ComparePlayersPage />);
    const values = blendedRankValues();
    expect(values).toContain("—");
    expect(screen.queryByText("undefined")).toBeNull();
    expect(screen.queryByText("NaN")).toBeNull();
  });

  it("never fabricates a rank from sourceOriginalRanks when the backend stamp is missing", () => {
    // A row whose materializer forgot to thread the field entirely
    // (undefined, not the backend's explicit null) still has real
    // per-source ranks available — a frontend-side average is exactly
    // the "invent a client rank" failure mode V1-98 forbids.
    const noStamp = row({
      name: "Covered Player",
      displayName: "Covered Player",
      sourceOriginalRanks: { ktcSfTep: 3, idpTradeCalc: 5 },
    });
    delete noStamp.blendedSourceRank; // simulate a materializer regression
    mockRows = [
      noStamp,
      row({
        name: "Uncovered Player",
        displayName: "Uncovered Player",
        canonicalConsensusRank: null,
        sourceOriginalRanks: {},
        blendedSourceRank: null,
      }),
    ];
    render(<ComparePlayersPage />);
    const values = blendedRankValues();
    // Must fall back to "—", never render a computed 4.0 (mean of 3, 5).
    expect(values.every((v) => v !== "4.0")).toBe(true);
    expect(values).toContain("—");
  });
});
