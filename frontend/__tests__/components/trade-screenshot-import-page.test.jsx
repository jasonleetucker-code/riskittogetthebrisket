/**
 * /trade "Import trade" control — wiring of the screenshot import into the
 * real page.
 *
 *   - the feature status is fetched on the FIRST open of the control, never
 *     on page load, and "From screenshot" is hidden unless it is enabled;
 *   - "From KeepTradeCut URL" still opens the KTC row;
 *   - a confirmed import is ONE sides update (Replace keeps a third side;
 *     Add appends to what is already there, repeats preserved);
 *   - Cancel leaves the trade untouched.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/image-downscale", () => ({
  prepareScreenshot: vi.fn(async () => ({
    dataUrl: "data:image/png;base64,AAAA",
    width: 10,
    height: 10,
    bytes: 3,
    mime: "image/png",
  })),
}));

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
    name: "2027 Round 1",
    pos: "PICK",
    position: "PICK",
    assetClass: "pick",
    rankDerivedValue: 4000,
    values: { full: 4000 },
    rank: 50,
    blendedSourceRank: 50,
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

vi.setConfig({ testTimeout: 30000 });

const ITEM = {
  kind: "player",
  status: "resolved",
  sleeperId: null,
  candidates: [],
  suggestions: [],
  hints: { position: null, team: null },
  reason: null,
  lineIndex: 0,
  conf: 0.9,
};
const EXTRACTION = {
  ok: true,
  imageIndex: 0,
  engine: { name: "tesseract", version: "5.3" },
  layout: { kind: "two_column", confidence: 0.9 },
  sides: [
    {
      label: "",
      labelSource: "none",
      items: [
        {
          ...ITEM,
          raw: "Puka Nacua",
          boardName: "Puka Nacua",
          sleeperId: "9493",
        },
        { ...ITEM, raw: "2027 1st", boardName: "2027 Round 1", kind: "pick" },
      ],
    },
    {
      label: "",
      labelSource: "none",
      items: [
        {
          ...ITEM,
          raw: "Bijan Robinson",
          boardName: "Bijan Robinson",
          sleeperId: "9509",
        },
      ],
    },
  ],
  unassigned: [],
  ignored: [],
  warnings: [],
};

let statusBody;
let fetchMock;
let TradePage;

beforeEach(async () => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/trade");
  statusBody = {
    available: true,
    enabled: true,
    reason: null,
    engine: "tesseract",
    version: "5.3",
  };
  fetchMock = vi.fn(async (url) => {
    const u = String(url);
    if (u.includes("/api/trade/import-screenshot/status")) {
      return { ok: true, status: 200, json: async () => statusBody };
    }
    if (u.includes("/api/trade/import-screenshot")) {
      return {
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => EXTRACTION,
      };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function savedSides() {
  return JSON.parse(
    window.localStorage.getItem("next_trade_workspace_v1") || "{}",
  ).sides;
}

const statusCalls = () =>
  fetchMock.mock.calls.filter(([u]) =>
    String(u).includes("/api/trade/import-screenshot/status"),
  );

async function openScreenshotDialog() {
  await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "From screenshot" }),
  );
  return screen.findByRole("dialog", { name: "Import trade from screenshot" });
}

async function readScreenshot(dialog) {
  const input = dialog.querySelector('input[type="file"]');
  await userEvent.upload(
    input,
    new File([new Uint8Array([0x89, 0x50])], "t.png", { type: "image/png" }),
  );
  await screen.findByRole("region", { name: "Side A" });
}

async function searchAndPick(sideLetter, query, rowName) {
  const input = screen.getByLabelText(
    `Search to add a player to Side ${sideLetter}`,
  );
  await userEvent.clear(input);
  await userEvent.type(input, query);
  const box = input.closest(".trade-side-search") || document.body;
  // TC-E: inline search rows are combobox options.
  await userEvent.click(
    await within(box).findByRole("option", { name: new RegExp(`^${rowName}`) }),
  );
}

describe("/trade Import trade control", () => {
  it("does not ask for the screenshot status on page load", async () => {
    render(<TradePage />);
    await screen.findByRole("button", { name: "Import trade" });
    expect(statusCalls()).toHaveLength(0);
  });

  it("hides From screenshot when the feature is disabled; KTC stays available", async () => {
    statusBody = { available: false, enabled: false, reason: "disabled" };
    render(<TradePage />);
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    await waitFor(() => expect(statusCalls()).toHaveLength(1));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "From screenshot" }),
      ).toBeNull(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "From KeepTradeCut URL" }),
    );
    expect(
      await screen.findByLabelText("KeepTradeCut trade-calculator URL"),
    ).toBeTruthy();
  });

  it("hides From screenshot when the status endpoint is unreachable", async () => {
    fetchMock.mockImplementation(async (url) => {
      if (String(url).includes("/status")) throw new TypeError("network");
      return { ok: false, status: 404, json: async () => ({}) };
    });
    render(<TradePage />);
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    await waitFor(() => expect(statusCalls()).toHaveLength(1));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "From screenshot" }),
      ).toBeNull(),
    );
  });

  it("imports a screenshot into an empty trade with one Import trade action", async () => {
    render(<TradePage />);
    const dialog = await openScreenshotDialog();
    await readScreenshot(dialog);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Import trade" }),
    );
    await waitFor(() =>
      expect(savedSides()?.map((s) => s.assets)).toEqual([
        ["Puka Nacua", "2027 Round 1"],
        ["Bijan Robinson"],
      ]),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      screen.getByText("Imported 3 assets from screenshot"),
    ).toBeInTheDocument();
    // the status was fetched exactly once (reused by the dialog)
    expect(statusCalls()).toHaveLength(1);
  });

  it("Add to current trade appends, repeats preserved", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Puka", "Puka Nacua");
    await waitFor(() =>
      expect(savedSides()?.[0]?.assets).toEqual(["Puka Nacua"]),
    );
    const dialog = await openScreenshotDialog();
    await readScreenshot(dialog);
    expect(
      within(dialog).queryByRole("button", { name: "Import trade" }),
    ).toBeNull();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Add to current trade" }),
    );
    await waitFor(() =>
      expect(savedSides()?.map((s) => s.assets)).toEqual([
        ["Puka Nacua", "Puka Nacua", "2027 Round 1"],
        ["Bijan Robinson"],
      ]),
    );
  });

  it("Replace current trade replaces sides A and B and keeps a third side", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    await userEvent.click(screen.getByRole("button", { name: "Add Team" }));
    await searchAndPick("C", "2027", "2027 Round 1");
    await waitFor(() =>
      expect(savedSides()?.[2]?.assets).toEqual(["2027 Round 1"]),
    );
    const dialog = await openScreenshotDialog();
    await readScreenshot(dialog);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Replace current trade" }),
    );
    await waitFor(() =>
      expect(savedSides()?.map((s) => s.assets)).toEqual([
        ["Puka Nacua", "2027 Round 1"],
        ["Bijan Robinson"],
        ["2027 Round 1"],
      ]),
    );
  });

  it("Cancel leaves the trade untouched", async () => {
    render(<TradePage />);
    await screen.findByLabelText("Search to add a player to Side A");
    await searchAndPick("A", "Bijan", "Bijan Robinson");
    await waitFor(() =>
      expect(savedSides()?.[0]?.assets).toEqual(["Bijan Robinson"]),
    );
    const before = JSON.stringify(savedSides());
    const dialog = await openScreenshotDialog();
    await readScreenshot(dialog);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(JSON.stringify(savedSides())).toBe(before);
    expect(screen.queryByText(/Imported .* from screenshot/)).toBeNull();
  });
});
