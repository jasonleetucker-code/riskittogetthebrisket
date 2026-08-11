/**
 * /trade must survive going multi-team.
 *
 * LIVE CRASH. `frontend/app/trade/page.jsx` calls `defaultDestination`
 * at ten sites — the pick-routing fallback, asset add, side removal,
 * workspace hydration, suggestion apply, and `addTeam` — while never
 * importing it from `@/lib/trade-logic`, where it is exported. Because
 * it is an un-imported free variable rather than a bad named import,
 * the module loads cleanly and throws only when a call site executes:
 *
 *     ReferenceError: Can't find variable: defaultDestination
 *
 * The narrowest reproduction is `addTeam` (page.jsx:979). Going from two
 * sides to three seeds an explicit destination for every asset already
 * staged, so ANY asset on the board is enough — no draft pick and no
 * fallback routing required. That makes the whole 3+-team feature
 * unreachable, not merely the pick path.
 *
 * This test drives the real button on the real page so it fails on the
 * actual ReferenceError. A grep for the import would pass the moment
 * someone re-added the symbol under a different name; this does not.
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
    name: "2027 Mid 1st",
    pos: "PICK",
    position: "PICK",
    assetClass: "pick",
    rankDerivedValue: 5606,
    values: { full: 5606 },
    rank: 48,
    blendedSourceRank: 48,
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

/** A saved 3-side workspace with assets staged — the state the page
 *  hydrates on load, and the one that reaches the destination-seeding
 *  branch at page.jsx:526 without needing any interaction. */
function seedThreeSideWorkspace() {
  window.localStorage.setItem(
    "next_trade_workspace_v1",
    JSON.stringify({
      version: 2,
      valueMode: "full",
      activeSide: 0,
      sides: [
        { label: "Team A", assets: ["Bijan Robinson"], destinations: {} },
        { label: "Team B", assets: ["2027 Mid 1st"], destinations: {} },
        { label: "Team C", assets: [], destinations: {} },
      ],
    }),
  );
}

/** Collect anything that escapes as an uncaught error or a React
 *  error-boundary console report. The crash is a free variable, so it
 *  throws during render/commit rather than returning a bad value. */
function captureErrors() {
  const seen = [];
  const onError = (event) => {
    seen.push(
      event.error?.message || String(event.message || event.reason || ""),
    );
  };
  window.addEventListener("error", onError);
  const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
    seen.push(args.map((a) => (a?.message ? a.message : String(a))).join(" "));
  });
  return {
    seen,
    stop() {
      window.removeEventListener("error", onError);
      spy.mockRestore();
    },
  };
}

describe("/trade multi-team destination seeding", () => {
  it("hydrates a saved 3-side workspace without a ReferenceError", async () => {
    seedThreeSideWorkspace();
    const cap = captureErrors();
    try {
      render(<TradePage />);
      await waitFor(() =>
        expect(screen.getAllByRole("button").length).toBeGreaterThan(0),
      );
      const hits = cap.seen.filter((m) => /defaultDestination/.test(m));
      expect(
        hits,
        `hydrating a 3-side workspace threw: ${hits[0] || "(none)"}`,
      ).toHaveLength(0);
    } finally {
      cap.stop();
    }
  });

  it("adds a third team with an asset staged without a ReferenceError", async () => {
    // `addTeam` seeds a destination per already-staged asset, so an
    // empty board never reaches the call. One asset is enough.
    window.localStorage.setItem(
      "next_trade_workspace_v1",
      JSON.stringify({
        version: 2,
        valueMode: "full",
        activeSide: 0,
        sides: [
          { label: "Team A", assets: ["Bijan Robinson"], destinations: {} },
          { label: "Team B", assets: [], destinations: {} },
        ],
      }),
    );
    const cap = captureErrors();
    try {
      render(<TradePage />);
      const button = await screen.findByRole("button", { name: /add team/i });
      await userEvent.click(button);
      const hits = cap.seen.filter((m) => /defaultDestination/.test(m));
      expect(
        hits,
        `adding a third team threw: ${hits[0] || "(none)"}`,
      ).toHaveLength(0);
    } finally {
      cap.stop();
    }
  });

  it("exposes the helper the page depends on", () => {
    // Guards the other direction: if `defaultDestination` were renamed
    // or dropped from trade-logic, the page's import would break and
    // the tests above would go red for a reason worth naming here.
    return import("@/lib/trade-logic").then((mod) => {
      expect(typeof mod.defaultDestination).toBe("function");
      // Circular next-side routing: side 0 of 3 sends to side 1.
      expect(mod.defaultDestination(0, 3)).toBe(1);
      expect(mod.defaultDestination(2, 3)).toBe(0);
    });
  });
});
