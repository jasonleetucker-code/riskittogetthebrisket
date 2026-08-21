/**
 * Manual override UX (V1-45 / C3-CALC-02): visually silent, one global
 * reset.
 *
 * `docs/C_SERIES_SCOPE_MANIFEST.md` final state for this row: "No
 * per-player badge; top-level Reset Values; removal clears the
 * override; canonical truth unchanged." Before this fix, an overridden
 * asset-value input carried an `overridden` CSS class (amber text +
 * border — a per-player badge, the exact thing the row forbids), and no
 * top-level control existed to clear every override at once — only a
 * per-player ghost "Reset <name>" button next to each overridden input.
 *
 * Pure UX: this never touches `rankDerivedValue` or any canonical
 * field. `customValue`-first resolution in `trade-logic.js` is
 * untouched by this change and is proven elsewhere
 * (`trade-logic.test.js`).
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const ROWS = [
  {
    name: "Bijan Robinson",
    pos: "RB",
    position: "RB",
    assetClass: "offense",
    rankDerivedValue: 8000,
    values: { full: 8000 },
    rank: 1,
    blendedSourceRank: 1,
  },
  {
    name: "Puka Nacua",
    pos: "WR",
    position: "WR",
    assetClass: "offense",
    rankDerivedValue: 7000,
    values: { full: 7000 },
    rank: 3,
    blendedSourceRank: 3,
  },
];

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    rows: ROWS,
    rawData: { currentDraftYear: 2026, sleeper: null },
  }),
}));

vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({
    settings: {},
    setSettings: () => {},
    valueMode: "full",
    setValueMode: () => {},
  }),
}));

let TradePage;

beforeEach(async () => {
  window.localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
  );
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function seedTwoSideWorkspace() {
  window.localStorage.setItem(
    "next_trade_workspace_v1",
    JSON.stringify({
      version: 2,
      valueMode: "full",
      activeSide: 0,
      sides: [
        { label: "Team A", assets: ["Bijan Robinson"], destinations: {} },
        { label: "Team B", assets: ["Puka Nacua"], destinations: {} },
      ],
    }),
  );
}

describe("/trade manual override UX", () => {
  it("does not badge an overridden value — the input carries no visually-distinguishing class", async () => {
    seedTwoSideWorkspace();
    render(<TradePage />);
    const input = await screen.findByLabelText(
      /Override Bijan Robinson's value for this trade/i,
    );
    await userEvent.type(input, "5000");
    await waitFor(() => expect(input).toHaveValue(5000));

    // The pre-fix defect: `className="asset-value-override-input overridden"`,
    // styled amber in globals.css — a per-player badge. Post-fix the class
    // list carries no such marker regardless of override state.
    expect(input.className).not.toMatch(/\boverridden\b/);
  });

  it("exposes one top-level Reset Values control that clears every override at once", async () => {
    seedTwoSideWorkspace();
    render(<TradePage />);

    const inputA = await screen.findByLabelText(
      /Override Bijan Robinson's value for this trade/i,
    );
    const inputB = await screen.findByLabelText(
      /Override Puka Nacua's value for this trade/i,
    );
    await userEvent.type(inputA, "5000");
    await userEvent.type(inputB, "3000");
    await waitFor(() => expect(inputA).toHaveValue(5000));
    await waitFor(() => expect(inputB).toHaveValue(3000));

    const resetButton = await screen.findByRole("button", {
      name: /reset values/i,
    });
    expect(resetButton).toBeEnabled();

    await userEvent.click(resetButton);

    await waitFor(() => expect(inputA).toHaveValue(null));
    await waitFor(() => expect(inputB).toHaveValue(null));
  });

  it("disables the top-level Reset Values control when nothing is overridden", async () => {
    seedTwoSideWorkspace();
    render(<TradePage />);
    const resetButton = await screen.findByRole("button", {
      name: /reset values/i,
    });
    expect(resetButton).toBeDisabled();
  });
});
