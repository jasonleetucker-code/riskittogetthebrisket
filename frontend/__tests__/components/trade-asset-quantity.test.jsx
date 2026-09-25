/**
 * /trade add / remove flow for repeated and owned assets (T-NEW-02 / #1415).
 *
 * Drives the real page: the per-side search, the − N + quantity control,
 * owned-pick search results, persistence, and share-link hydration.  The
 * pure rules are pinned in ``__tests__/trade-asset-quantity.test.js``; this
 * proves the page actually routes through them (mobile and desktop share
 * the same ``sides`` state and ``addToSide`` path, so one flow covers both).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const OWN_ID = "pick:dynasty_main:2027:r1:o1";
const FROM_ID = "pick:dynasty_main:2027:r1:o2";

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

const TEAMS = [
  {
    name: "Team Alpha",
    ownerId: "o1",
    roster_id: 1,
    players: ["Bijan Robinson"],
    picks: ["2027 Mid 1st (own)", "2027 Mid 1st (from Team Bravo)"],
    pickDetails: [
      { season: 2027, round: 1, label: "2027 Mid 1st (own)", assetId: OWN_ID },
      { season: 2027, round: 1, label: "2027 Mid 1st (from Team Bravo)", assetId: FROM_ID },
    ],
  },
  {
    name: "Team Bravo",
    ownerId: "o2",
    roster_id: 2,
    players: [],
    picks: [],
    pickDetails: [],
  },
];

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    rows: ROWS,
    rawData: { currentDraftYear: 2026, sleeper: { teams: TEAMS } },
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
  window.history.replaceState({}, "", "/trade");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
  );
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function searchAndPick(sideLabel, query, resultText) {
  const input = screen.getByLabelText(`Search to add a player to Side ${sideLabel}`);
  await userEvent.clear(input);
  await userEvent.type(input, query);
  const results = await waitFor(() => {
    const box = document.querySelector(".trade-side-search-results");
    if (!box) throw new Error("no results yet");
    return box;
  });
  const hit = within(results)
    .getAllByText(resultText, { exact: true })
    .map((el) => el.closest("button"))[0];
  fireEvent.mouseDown(hit);
}

function savedSides() {
  return JSON.parse(window.localStorage.getItem("next_trade_workspace_v1") || "{}").sides;
}

describe("/trade repeated generic picks", () => {
  it("adds a generic pick twice, shows ×2, and removing one leaves one", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");

    await searchAndPick("A", "2027 Mid", "2027 Mid 1st");
    await searchAndPick("A", "2027 Mid", "2027 Mid 1st");

    await waitFor(() => expect(screen.getByText("×2")).toBeTruthy());
    await waitFor(() => expect(savedSides()[0].assets).toEqual(["2027 Mid 1st", "2027 Mid 1st"]));

    await userEvent.click(screen.getByLabelText("Add another 2027 Mid 1st to Side A"));
    await waitFor(() => expect(savedSides()[0].assets).toHaveLength(3));

    await userEvent.click(screen.getByLabelText("Remove one 2027 Mid 1st from Side A"));
    await userEvent.click(screen.getByLabelText("Remove one 2027 Mid 1st from Side A"));
    await waitFor(() => expect(savedSides()[0].assets).toEqual(["2027 Mid 1st"]));
    expect(screen.queryByText("×2")).toBeNull();
  });

  it("refuses a second copy of a player", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    await waitFor(() => expect(savedSides()[0].assets).toEqual(["Bijan Robinson"]));

    const input = screen.getByLabelText("Search to add a player to Side B");
    await userEvent.type(input, "Bijan");
    await waitFor(() => expect(screen.getByText("No matches.")).toBeTruthy());
  });
});

describe("/trade owned picks", () => {
  it("offers both same-label owned picks, each once", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    // A Team Alpha player lets the page infer Side A's team.
    await searchAndPick("A", "Bijan", "Bijan Robinson");

    await searchAndPick("A", "2027", "2027 Mid 1st (own)");
    await searchAndPick("A", "2027", "2027 Mid 1st (from Team Bravo)");

    await waitFor(() =>
      expect(savedSides()[0].assets).toEqual([
        "Bijan Robinson",
        { name: "2027 Mid 1st", assetId: OWN_ID, label: "2027 Mid 1st (own)" },
        { name: "2027 Mid 1st", assetId: FROM_ID, label: "2027 Mid 1st (from Team Bravo)" },
      ]),
    );
    expect(screen.getAllByText("Owned pick").length).toBeGreaterThanOrEqual(2);

    // Neither owned pick is offered again once it is in the trade.
    const input = screen.getByLabelText("Search to add a player to Side A");
    await userEvent.clear(input);
    await userEvent.type(input, "2027");
    const box = await waitFor(() => {
      const el = document.querySelector(".trade-side-search-results");
      if (!el) throw new Error("no results yet");
      return el;
    });
    expect(within(box).queryByText("2027 Mid 1st (own)")).toBeNull();
    expect(within(box).queryByText("2027 Mid 1st (from Team Bravo)")).toBeNull();
    // The generic market reference is still available.
    expect(within(box).getByText("2027 Mid 1st")).toBeTruthy();
  });
});

describe("/trade share-link hydration", () => {
  it("restores repeated copies and owned identities from a link", async () => {
    const { encodeTrade } = await import("@/lib/trade-share");
    const encoded = encodeTrade({
      sides: [
        {
          name: "Side A",
          players: ["2027 Mid 1st", "2027 Mid 1st", "2027 Mid 1st"],
          assetIds: [null, null, FROM_ID],
        },
        { name: "Side B", players: ["Bijan Robinson"], assetIds: [null] },
      ],
    });
    window.history.replaceState({}, "", `/trade?share=${encoded}`);
    render(<TradePage />);
    await waitFor(() => expect(screen.getByText("×2")).toBeTruthy());
    await waitFor(() =>
      expect(savedSides()[0].assets).toEqual([
        "2027 Mid 1st",
        "2027 Mid 1st",
        {
          name: "2027 Mid 1st",
          assetId: FROM_ID,
          // Label re-derived from today's ownership, not trusted from the link.
          label: "2027 Mid 1st (from Team Bravo)",
        },
      ]),
    );
  });

  it("a legacy link (names only) still loads", async () => {
    const { encodeTrade } = await import("@/lib/trade-share");
    const encoded = encodeTrade({
      sides: [
        { name: "Side A", players: ["Bijan Robinson"] },
        { name: "Side B", players: ["2027 Mid 1st"] },
      ],
    });
    window.history.replaceState({}, "", `/trade?share=${encoded}`);
    render(<TradePage />);
    await waitFor(() =>
      expect(savedSides()?.map((s) => s.assets)).toEqual([["Bijan Robinson"], ["2027 Mid 1st"]]),
    );
  });
});
