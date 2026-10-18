/**
 * TC-E on the real /trade page — request sequencing and keyboard paths.
 *
 * Every async answer on the page is resolved OUT OF ORDER here, by hand, so a
 * slower, older response arrives after a newer one:
 *
 *   - suggestions: a roster change while the previous roster's fetch is in
 *     flight; the old answer lands last and must not replace the new one;
 *   - KTC import: the user edits the trade (or cancels) while the import is
 *     loading; the late answer must not overwrite the newer trade;
 *   - KTC export: the trade changes before the link arrives; nothing is copied.
 *
 * Keyboard: the inline side search is a WAI-ARIA combobox (ArrowDown / Enter
 * adds, Escape clears), and the toolbar's More group returns focus to its
 * trigger on Escape.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const ROWS = [
  {
    name: "Bijan Robinson",
    playerId: "9509",
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
    playerId: "9493",
    pos: "WR",
    position: "WR",
    assetClass: "offense",
    rankDerivedValue: 7000,
    values: { full: 7000 },
    rank: 2,
    blendedSourceRank: 2,
  },
  {
    name: "Puka Two",
    playerId: "9999",
    pos: "WR",
    position: "WR",
    assetClass: "offense",
    rankDerivedValue: 3000,
    values: { full: 3000 },
    rank: 40,
    blendedSourceRank: 40,
  },
];

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    rows: ROWS,
    rawData: { currentDraftYear: 2026, sleeper: { teams: [] } },
  }),
}));

vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({
    settings: {},
    setSettings: () => {},
    update: () => {},
    hydrated: true,
  }),
}));

// Team identity answered (no team): the proactive suggestions fetch waits on it.
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: null,
    setSelectedTeam: () => {},
    idpEnabled: true,
    leagueMismatch: false,
    selectedLeagueKey: "dynasty_main",
    leagueLoading: false,
    loading: false,
  }),
}));

vi.setConfig({ testTimeout: 30000 });

/** A fetch whose answers the test releases one by one, in any order. */
function controlledFetch(matcher) {
  const pending = [];
  const fetchMock = vi.fn((url, init) => {
    const u = String(url);
    if (matcher(u)) {
      return new Promise((resolve) => {
        pending.push({
          url: u,
          body: init?.body ? JSON.parse(init.body) : null,
          resolve: (data, status = 200) =>
            resolve({ ok: status < 400, status, json: async () => data }),
        });
      });
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, pending };
}

function savedSides() {
  return JSON.parse(window.localStorage.getItem("next_trade_workspace_v1") || "{}").sides;
}

let TradePage;
beforeEach(async () => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/trade");
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function keyboardAdd(sideLetter, query) {
  const input = screen.getByLabelText(`Search to add a player to Side ${sideLetter}`);
  input.focus();
  fireEvent.change(input, { target: { value: query } });
  await screen.findByRole("listbox", { name: `Results for Side ${sideLetter}` });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  return input;
}

describe("inline side search is a keyboard combobox (TC-E)", () => {
  it("ArrowDown marks an option and Enter adds it; focus never leaves the input", async () => {
    controlledFetch(() => false);
    render(<TradePage />);
    const input = screen.getByLabelText("Search to add a player to Side A");
    expect(input.getAttribute("role")).toBe("combobox");
    input.focus();
    fireEvent.change(input, { target: { value: "Puka" } });
    const listbox = await screen.findByRole("listbox", { name: "Results for Side A" });
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(input.getAttribute("aria-controls")).toBe(listbox.id);
    expect(input.hasAttribute("aria-activedescendant")).toBe(false);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    const first = screen.getAllByRole("option")[0];
    expect(input.getAttribute("aria-activedescendant")).toBe(first.id);
    expect(first.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const second = screen.getAllByRole("option")[1];
    expect(input.getAttribute("aria-activedescendant")).toBe(second.id);
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input.getAttribute("aria-activedescendant")).toBe(first.id);

    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(savedSides()?.[0]?.assets).toEqual(["Puka Nacua"]));
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
    // The add is read back politely, like the phone sheet's.
    expect(screen.getByText("Added Puka Nacua to Side A.")).toBeTruthy();
  });

  it("Escape clears the query and closes the list", async () => {
    controlledFetch(() => false);
    render(<TradePage />);
    const input = screen.getByLabelText("Search to add a player to Side B");
    input.focus();
    fireEvent.change(input, { target: { value: "Bij" } });
    await screen.findByRole("listbox", { name: "Results for Side B" });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input.getAttribute("aria-expanded")).toBe("false");
  });
});

describe("suggestions: an older roster's answer never replaces the newer one", () => {
  it("resolves the new roster first and the old one last", async () => {
    const { pending } = controlledFetch((u) => u.includes("/api/trade/suggestions"));
    render(<TradePage />);
    const roster = await screen.findByLabelText("Roster");
    fireEvent.change(roster, { target: { value: "Bijan Robinson, Puka Nacua, Puka Two" } });
    await waitFor(() => expect(pending.length).toBe(1), { timeout: 3000 });
    fireEvent.change(roster, { target: { value: "Puka Nacua, Puka Two, Bijan Robinson, X" } });
    await waitFor(() => expect(pending.length).toBe(2), { timeout: 3000 });
    const empty = { sellHigh: [], buyLow: [], consolidation: [], positionalUpgrades: [] };

    await act(async () => {
      pending[1].resolve({ ...empty, totalSuggestions: 22 });
    });
    await screen.findByText(/22 suggestions/);
    await act(async () => {
      pending[0].resolve({ ...empty, totalSuggestions: 11 });
    });
    expect(screen.queryByText(/11 suggestions/)).toBeNull();
    expect(screen.getByText(/22 suggestions/)).toBeTruthy();
  });
});

async function openKtcImport() {
  await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
  await userEvent.click(await screen.findByRole("button", { name: "From KeepTradeCut URL" }));
  const url = await screen.findByLabelText("KeepTradeCut trade-calculator URL");
  fireEvent.change(url, {
    target: { value: "https://keeptradecut.com/trade-calculator?teamOne=1&teamTwo=2" },
  });
  return url;
}

const KTC_ANSWER = {
  ok: true,
  sideOne: [{ name: "Bijan Robinson" }],
  sideTwo: [{ name: "Puka Two" }],
  unresolved: { sideOne: [], sideTwo: [] },
};

describe("KTC import never overwrites a newer trade", () => {
  it("an import that lands after the trade was edited replaces nothing and says so", async () => {
    const { pending } = controlledFetch(
      (u) => u.includes("/api/trade/import-ktc") || u.includes("/api/trade/import-screenshot/status"),
    );
    render(<TradePage />);
    await openKtcImport();
    await userEvent.click(screen.getByRole("button", { name: "Load trade" }));
    const ktc = pending.find((p) => p.url.includes("import-ktc"));
    expect(ktc).toBeTruthy();

    // The user keeps building while the import loads.
    await keyboardAdd("A", "Puka N");
    await waitFor(() => expect(savedSides()?.[0]?.assets).toEqual(["Puka Nacua"]));

    await act(async () => {
      ktc.resolve(KTC_ANSWER);
    });
    expect(savedSides()?.[0]?.assets).toEqual(["Puka Nacua"]);
    expect(savedSides()?.[1]?.assets).toEqual([]);
    expect(await screen.findByText(/The trade changed while the import was loading/)).toBeTruthy();
  });

  it("Cancel retires an import in flight", async () => {
    const { pending } = controlledFetch(
      (u) => u.includes("/api/trade/import-ktc") || u.includes("/api/trade/import-screenshot/status"),
    );
    render(<TradePage />);
    await openKtcImport();
    await userEvent.click(screen.getByRole("button", { name: "Load trade" }));
    const ktc = pending.find((p) => p.url.includes("import-ktc"));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => {
      ktc.resolve(KTC_ANSWER);
    });
    expect(savedSides()?.[0]?.assets || []).toEqual([]);
    expect(savedSides()?.[1]?.assets || []).toEqual([]);
  });

  it("an import that lands on the trade it was asked about still loads", async () => {
    const { pending } = controlledFetch(
      (u) => u.includes("/api/trade/import-ktc") || u.includes("/api/trade/import-screenshot/status"),
    );
    render(<TradePage />);
    await openKtcImport();
    await userEvent.click(screen.getByRole("button", { name: "Load trade" }));
    const ktc = pending.find((p) => p.url.includes("import-ktc"));
    await act(async () => {
      ktc.resolve(KTC_ANSWER);
    });
    await waitFor(() => expect(savedSides()?.[0]?.assets).toEqual(["Bijan Robinson"]));
    expect(savedSides()?.[1]?.assets).toEqual(["Puka Two"]);
  });
});

describe("KTC export never copies a link for an older trade", () => {
  it("the trade changes before the link arrives: nothing is copied", async () => {
    const { pending } = controlledFetch((u) => u.includes("/api/trade/export-ktc"));
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<TradePage />);
    await keyboardAdd("A", "Bij");
    await waitFor(() => expect(savedSides()?.[0]?.assets).toEqual(["Bijan Robinson"]));
    await keyboardAdd("B", "Puka N");
    await waitFor(() => expect(savedSides()?.[1]?.assets).toEqual(["Puka Nacua"]));

    await userEvent.click(screen.getByRole("button", { name: "More" }));
    await userEvent.click(screen.getByRole("button", { name: "Copy KTC URL" }));
    await waitFor(() => expect(pending.length).toBe(1));
    await keyboardAdd("B", "Puka T");
    await waitFor(() => expect(savedSides()?.[1]?.assets).toEqual(["Puka Nacua", "Puka Two"]));

    await act(async () => {
      pending[0].resolve({ ok: true, url: "https://keeptradecut.com/x", unresolved: {} });
    });
    expect(writeText).not.toHaveBeenCalled();
    expect(await screen.findByText(/nothing was copied/)).toBeTruthy();
  });
});

describe("toolbar disclosures return focus to their trigger (TC-E)", () => {
  it("Escape closes More and focuses the More button", async () => {
    controlledFetch(() => false);
    render(<TradePage />);
    const more = screen.getByRole("button", { name: "More" });
    await userEvent.click(more);
    const csv = screen.getByRole("button", { name: "Download CSV" });
    csv.focus();
    fireEvent.keyDown(csv, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Download CSV" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(more));
  });
});

describe("immediate math vs expensive analysis (TC-E)", () => {
  it("the balancer search reads a deferred snapshot and never shows for another trade", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    expect(src).toMatch(/const deferredBalancerInput = useDeferredValue\(balancerInput\);/);
    expect(src).toMatch(/const balancersCurrent = deferredBalancerInput === balancerInput;/);
    expect(src).toMatch(/const balancers = balancersCurrent \? deferredBalancers : NO_BALANCERS;/);
    expect(src).toMatch(/const multiBalancers = balancersCurrent \? deferredMultiBalancers : null;/);
    // Both findBalancers calls read the snapshot, never the live trade.
    const calls = src.match(/findBalancers\(([^,]+),/g) || [];
    expect(calls).toHaveLength(2);
    for (const c of calls) expect(c).toMatch(/findBalancers\(b\.sidesWithOverrides,/);
  });
});

describe("Escape on the More trigger itself closes the group (its actions start disabled)", () => {
  it("closes and keeps focus on More", async () => {
    controlledFetch(() => false);
    render(<TradePage />);
    const more = screen.getByRole("button", { name: "More" });
    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeTruthy();
    fireEvent.keyDown(more, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Download CSV" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(more));
  });
});
