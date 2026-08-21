/**
 * V1-92 / W08-F011 — per-asset source count + normalization confidence
 * in the trade builder.
 *
 * `docs/master-site-audit/FEATURE_STATUS_MATRIX.md` W08-F011: "The trade
 * calculator shows no data freshness, no per-asset source count and no
 * normalization confidence for the assets in the trade"
 * (`frontend/app/trade/page.jsx:1757-1800`).
 *
 * Board-level freshness is already covered globally by
 * `StaleDataBanner` (mounted in `AppShellWrapper`, present on every
 * page including /trade) — that half of W08-F011 does not need
 * trade-page-specific work. The two gaps that were actually specific to
 * this page were per-asset source count and per-asset confidence, and
 * `AssetRow` (`trade-sections.jsx`) rendered neither.
 *
 * Both are backend-stamped, real per-row fields already threaded by
 * `buildRows` (`dynasty-data.js`): `sourceCount` and
 * `confidenceBucket`/`confidenceLabel`. `confidenceBucket` already
 * folds freshness in as one of its five axes
 * (`src/api/confidence.py`), so surfacing it satisfies "use backend
 * freshness truth, no Date.now()-based invented freshness" without
 * inventing a new per-row freshness computation the backend does not
 * expose.
 */

import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

import { SideCard } from "@/app/trade/trade-sections";

function row(overrides = {}) {
  return {
    name: "Bijan Robinson",
    pos: "RB",
    position: "RB",
    assetClass: "offense",
    rankDerivedValue: 8000,
    values: { full: 8000 },
    rank: 1,
    blendedSourceRank: 1,
    sourceCount: 5,
    confidenceBucket: "high",
    confidenceLabel: "High — 5 of 6 eligible families voted",
    ...overrides,
  };
}

const NOOP = () => {};

function renderSide(assets) {
  const side = { id: "a", label: "A", assets, destinations: {} };
  return render(
    <SideCard
      side={side}
      sideIdx={0}
      sides={[side, { id: "b", label: "B", assets: [], destinations: {} }]}
      total={{ raw: 8000, adjustment: 0, adjusted: 8000 }}
      isMySide={false}
      selectedTeam={null}
      sideQuery=""
      isFocused={false}
      searchResults={[]}
      settings={{}}
      valueMode="full"
      valueOverrides={{}}
      incoming={[]}
      balancers={null}
      canRemoveTeam={false}
      onSideQueryChange={NOOP}
      onSideFocus={NOOP}
      onSideBlur={NOOP}
      onAddFromSearch={NOOP}
      onOpenPlayer={NOOP}
      onSetValueOverride={NOOP}
      onClearValueOverride={NOOP}
      onRemoveAsset={NOOP}
      onSetDestination={NOOP}
      onRemoveTeam={NOOP}
      onAddBalancer={NOOP}
      registerInputRef={NOOP}
    />,
  );
}

describe("trade builder asset rows — source count + confidence (V1-92)", () => {
  it("shows the real per-asset source count", () => {
    renderSide([row({ sourceCount: 7 })]);
    expect(screen.getByText(/7 src/)).toBeTruthy();
  });

  it("stays silent (no badge) for a high-confidence asset — the expected default", () => {
    renderSide([row({ confidenceBucket: "high" })]);
    expect(screen.queryByText(/confidence/i)).toBeNull();
  });

  it("surfaces a visible badge for a medium-confidence asset, carrying the real backend label", () => {
    renderSide([
      row({
        confidenceBucket: "medium",
        confidenceLabel: "Medium — 3 of 6 eligible families voted",
      }),
    ]);
    const badge = screen.getByText("medium confidence");
    expect(badge).toBeTruthy();
    expect(badge.title).toBe("Medium — 3 of 6 eligible families voted");
  });

  it("surfaces a visible badge for a low-confidence asset", () => {
    renderSide([row({ confidenceBucket: "low", confidenceLabel: "Low — weakest axis: freshness" })]);
    expect(screen.getByText("low confidence")).toBeTruthy();
  });

  it("labels a 'none' bucket honestly as no confidence data — never fabricates a bucket", () => {
    renderSide([row({ confidenceBucket: "none", confidenceLabel: "" })]);
    expect(screen.getByText("no confidence data")).toBeTruthy();
  });

  it("never invents a client-side freshness timestamp — no Date.now-derived text rendered", () => {
    renderSide([row({ confidenceBucket: "low" })]);
    // Nothing resembling a relative/absolute freshness stamp our own
    // client computed (e.g. "Xh ago", "as of ...") should appear on the
    // asset row — freshness truth here is entirely the backend's
    // confidenceBucket/-Label, never a client Date.now() computation.
    expect(screen.queryByText(/\bago\b/i)).toBeNull();
  });
});
