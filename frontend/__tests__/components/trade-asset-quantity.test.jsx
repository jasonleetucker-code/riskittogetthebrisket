/**
 * /trade add / remove flow for repeated and owned assets.
 *
 * Owner decision 2026-10-03 (supersedes T-NEW-02 / #1415's uniqueness rule
 * for the calculator): every asset — players and owned picks included — may
 * be added any number of times, to either or both sides.
 *
 * Drives the real page: the per-side search, the − N + quantity control on
 * every line, grouped market/owned search results, persistence, KTC import
 * and share-link hydration.  The pure rules are pinned in
 * ``__tests__/trade-asset-quantity.test.js``; this proves the page actually
 * routes through them (mobile and desktop share the same ``sides`` state and
 * ``addToSide`` path, so one flow covers both).
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

// Filler players (no search here matches them) so a saved workspace can
// carry more distinct lines than a share link may (33 > 32).
const FILLERS = Array.from({ length: 33 }, (_, i) => ({
  name: `Filler Player ${i + 1}`,
  pos: "WR",
  position: "WR",
  assetClass: "offense",
  rankDerivedValue: 1000 + i,
  values: { full: 1000 + i },
  rank: 100 + i,
  blendedSourceRank: 100 + i,
}));
ROWS.push(...FILLERS);

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

// The page is heavy and these flows click many times; under the full
// parallel suite the 5 s default timed out flows that pass in ~2 s alone.
vi.setConfig({ testTimeout: 30000 });

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

  it("a player repeats: search again, + to 10, and the same player on the other side", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    // [5] the search result is still offered after the first add
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    await waitFor(() => expect(screen.getByText("×2")).toBeTruthy());

    // [6] + has no maximum
    const plus = () => screen.getByLabelText("Add another Bijan Robinson to Side A");
    for (let i = 0; i < 8; i += 1) fireEvent.click(plus());
    await waitFor(() => expect(savedSides()[0].assets).toEqual(Array(10).fill("Bijan Robinson")));
    expect(screen.getByText("×10")).toBeTruthy();
    // [9] the raw side total multiplies exactly
    const totals = document.querySelector("[data-side-raw]");
    expect(Number(totals.getAttribute("data-side-raw"))).toBe(10 * 8000);

    // [4] the same player on Side B too
    await searchAndPick("B", "Bijan", "Bijan Robinson");
    await waitFor(() => expect(savedSides()[1].assets).toEqual(["Bijan Robinson"]));
    expect(savedSides()[0].assets).toHaveLength(10);
  });

  it("[8] at quantity 1, − removes the line", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    await waitFor(() => expect(savedSides()[0].assets).toEqual(["Bijan Robinson"]));
    await userEvent.click(screen.getByLabelText("Remove Bijan Robinson from Side A"));
    await waitFor(() => expect(savedSides()[0].assets).toEqual([]));
  });
});

describe("/trade owned picks", () => {
  it("offers both same-label owned picks and keeps offering them after they are added", async () => {
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

    // Ownership is displayed, never a limit: both owned picks stay offered
    // after they are in the trade, grouped AFTER the market reference.
    const input = screen.getByLabelText("Search to add a player to Side A");
    await userEvent.clear(input);
    await userEvent.type(input, "2027");
    const box = await waitFor(() => {
      const el = document.querySelector(".trade-side-search-results");
      if (!el) throw new Error("no results yet");
      return el;
    });
    expect(within(box).getByText("2027 Mid 1st (own)")).toBeTruthy();
    expect(within(box).getByText("2027 Mid 1st (from Team Bravo)")).toBeTruthy();
    expect(within(box).getByText("2027 Mid 1st")).toBeTruthy();
    const groups = within(box).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["Market picks", "Owned picks"]);
    expect(within(groups[0]).getByText("2027 Mid 1st")).toBeTruthy();
  });

  it("[3] an owned pick can be added x10 with +, keeping its identity", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    await searchAndPick("A", "2027", "2027 Mid 1st (own)");
    const plus = () => screen.getByLabelText("Add another 2027 Mid 1st (own) to Side A");
    for (let i = 0; i < 9; i += 1) fireEvent.click(plus());
    const own = { name: "2027 Mid 1st", assetId: OWN_ID, label: "2027 Mid 1st (own)" };
    await waitFor(() =>
      expect(savedSides()[0].assets).toEqual(["Bijan Robinson", ...Array(10).fill(own)]),
    );
    await userEvent.click(screen.getByLabelText("Remove one 2027 Mid 1st (own) from Side A"));
    await waitFor(() => expect(savedSides()[0].assets).toHaveLength(10));
  });
});

describe("/trade KTC import", () => {
  it("[14] does not dedupe: repeated players and picks all load, on both sides", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        if (String(url).includes("/api/trade/import-ktc")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              ok: true,
              sideOne: [
                { name: "Bijan Robinson" },
                { name: "Bijan Robinson" },
                { name: "2027 Mid 1st" },
                { name: "2027 Mid 1st" },
                { name: "2027 Mid 1st" },
              ],
              sideTwo: [{ name: "Bijan Robinson" }],
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Import KTC" }));
    await userEvent.type(
      screen.getByLabelText("KeepTradeCut trade-calculator URL"),
      "https://keeptradecut.com/trade-calculator?teamOne=1&teamTwo=2",
    );
    await userEvent.click(screen.getByRole("button", { name: "Load trade" }));
    await waitFor(() =>
      expect(savedSides()?.map((s) => s.assets)).toEqual([
        ["Bijan Robinson", "Bijan Robinson", "2027 Mid 1st", "2027 Mid 1st", "2027 Mid 1st"],
        ["Bijan Robinson"],
      ]),
    );
  });
});

describe("/trade share-link hydration", () => {
  it("[11] restores a player repeated on both sides from a link", async () => {
    const { encodeTrade } = await import("@/lib/trade-share");
    const encoded = encodeTrade({
      sides: [
        { name: "Side A", players: Array(4).fill("Bijan Robinson"), assetIds: Array(4).fill(null) },
        { name: "Side B", players: ["Bijan Robinson"], assetIds: [null] },
      ],
    });
    window.history.replaceState({}, "", `/trade?share=${encoded}`);
    render(<TradePage />);
    await waitFor(() =>
      expect(savedSides()?.map((s) => s.assets)).toEqual([
        Array(4).fill("Bijan Robinson"),
        ["Bijan Robinson"],
      ]),
    );
  });

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
    expect(screen.getByText("Loaded shared trade from link.")).toBeTruthy();
  });

  it("a link past the untrusted-input bounds loads partially and warns instead of claiming success", async () => {
    const json = JSON.stringify({
      v: 1,
      s: [
        { n: "Side A", p: ["Bijan Robinson", ...Array.from({ length: 40 }, (_, i) => `Nobody ${i}`)] },
        { n: "Side B", p: ["2027 Mid 1st"], q: [20000] },
      ],
    });
    const enc = btoa(json).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    window.history.replaceState({}, "", `/trade?share=${enc}`);
    render(<TradePage />);
    const alert = await screen.findByText(/Loaded only part of the shared trade/);
    expect(alert.closest('[role="alert"]')).toBeTruthy();
    expect(alert.textContent).toMatch(/more than 32 different assets on a side/);
    expect(alert.textContent).toMatch(/more than 10,000 copies in total/);
    expect(screen.queryByText("Loaded shared trade from link.")).toBeNull();
    // Side A keeps its first 32 lines (1 copy each, whether or not the board
    // knows the name), so Side B gets exactly the remaining 10,000 - 32.
    await waitFor(() => expect(savedSides()[1].assets).toHaveLength(10000 - 32));
    expect(savedSides()[0].assets).toEqual(["Bijan Robinson"]);
  });
});

describe("/trade copy share link", () => {
  it("warns instead of 'copied' when the link cannot carry every distinct asset", async () => {
    window.localStorage.setItem(
      "next_trade_workspace_v1",
      JSON.stringify({
        version: 2,
        valueMode: "full",
        activeSide: 0,
        sides: [
          { label: "A", assets: FILLERS.map((r) => r.name), destinations: {} },
          { label: "B", assets: ["Bijan Robinson"], destinations: {} },
        ],
      }),
    );
    const prompt = vi.fn();
    vi.stubGlobal("prompt", prompt);
    render(<TradePage />);
    await waitFor(() => expect(savedSides()?.[0]?.assets).toHaveLength(33));
    await userEvent.click(screen.getByRole("button", { name: /Copy share link/ }));
    const alert = await screen.findByText(/will NOT reproduce this trade exactly/);
    expect(alert.closest('[role="alert"]')).toBeTruthy();
    expect(alert.textContent).toMatch(/more than 32 different assets on a side/);
    expect(prompt).toHaveBeenCalled();
  });

  it("reports a clean copy when the link carries the whole trade", async () => {
    const prompt = vi.fn();
    vi.stubGlobal("prompt", prompt);
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    fireEvent.click(screen.getByLabelText("Add another Bijan Robinson to Side A"));
    await userEvent.click(screen.getByRole("button", { name: /Copy share link/ }));
    const ok = await screen.findByText("Share link ready.");
    expect(ok.closest('[role="status"]')).toBeTruthy();
    expect(screen.queryByText(/will NOT reproduce/)).toBeNull();
  });
});
