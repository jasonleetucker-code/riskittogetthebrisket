/**
 * ScreenshotImportDialog — the review UI for "Import trade from screenshot".
 *
 * Drives the dialog with a mocked status + extraction endpoint and a mocked
 * image preparation step (lib/image-downscale is unit-tested on its own).
 * Pins the product rules: nothing imports until every item is resolved and
 * placed, ambiguous items wait for the user, sides are neutral and
 * swappable, Cancel imports nothing, and the Replace/Add choice appears only
 * when the trade already has assets.
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

import { ScreenshotImportDialog } from "@/app/trade/trade-screenshot-import";

const row = (name, extra = {}) => ({
  name,
  pos: "WR",
  team: "LAR",
  assetClass: "offense",
  values: { full: 5000 },
  rankDerivedValue: 5000,
  blendedSourceRank: 10,
  ...extra,
});
const ROWS = [
  row("Puka Nacua", { playerId: "9493" }),
  row("Ja'Marr Chase", { playerId: "7564", team: "CIN" }),
  row("Josh Allen", { playerId: "4984", pos: "QB", team: "BUF" }),
  row("Josh Allen (LB)", {
    playerId: "1111",
    pos: "LB",
    team: "JAX",
    assetClass: "idp",
  }),
  row("Bijan Robinson", { playerId: "9509", pos: "RB", team: "ATL" }),
  row("2027 Round 1", { pos: "PICK", team: null, assetClass: "pick" }),
];
const rowByName = new Map(ROWS.map((r) => [r.name, r]));
const rowByLowerName = new Map(ROWS.map((r) => [r.name.toLowerCase(), r]));

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
const resolved = (boardName, extra = {}) => ({
  ...ITEM,
  raw: boardName,
  boardName,
  ...extra,
});

function extraction(overrides = {}) {
  return {
    ok: true,
    imageIndex: 0,
    engine: { name: "tesseract", version: "5.3" },
    layout: { kind: "two_column", confidence: 0.92 },
    sides: [
      {
        label: "Team Alpha",
        labelSource: "anchor",
        items: [
          resolved("Ja'Marr Chase"),
          resolved("2027 Round 1", { kind: "pick" }),
        ],
      },
      { label: "", labelSource: "position", items: [resolved("Puka Nacua")] },
    ],
    unassigned: [],
    ignored: [{ raw: "Accept", reason: "ui_text" }],
    warnings: [],
    ...overrides,
  };
}

let extractionBody;
let statusBody;
let postCalls;

function stubFetch() {
  postCalls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, init) => {
      if (String(url).includes("/api/trade/import-screenshot/status")) {
        return { ok: true, status: 200, json: async () => statusBody };
      }
      if (String(url).includes("/api/trade/import-screenshot")) {
        postCalls.push(JSON.parse(init.body));
        const body =
          typeof extractionBody === "function"
            ? extractionBody(postCalls.length)
            : extractionBody;
        if (body.__status) {
          return {
            ok: false,
            status: body.__status,
            headers: { get: () => null },
            json: async () => body,
          };
        }
        return {
          ok: true,
          status: 200,
          headers: { get: () => null },
          json: async () => body,
        };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    }),
  );
}

const png = (name = "trade.png") =>
  new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], name, {
    type: "image/png",
  });

function renderDialog(props = {}) {
  const onImport = vi.fn();
  const onClose = vi.fn();
  const utils = render(
    <ScreenshotImportDialog
      onImport={onImport}
      onClose={onClose}
      rows={ROWS}
      rowByName={rowByName}
      rowByLowerName={rowByLowerName}
      pickAliases={{}}
      {...props}
    />,
  );
  return { onImport, onClose, ...utils };
}

async function upload(container, files = [png()]) {
  const input = container.querySelector('input[type="file"]');
  await userEvent.upload(input, files);
}

function sideSection(name) {
  return screen.getByRole("region", { name });
}

beforeEach(() => {
  statusBody = {
    available: true,
    enabled: true,
    reason: null,
    engine: "tesseract",
    version: "5.3",
  };
  extractionBody = extraction();
  stubFetch();
  window.matchMedia = undefined;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ScreenshotImportDialog", () => {
  it("explains and disables upload when the server cannot read screenshots", async () => {
    renderDialog({
      status: { available: false, enabled: true, reason: "tesseract_missing" },
    });
    expect(
      screen.getByText("Screenshot reading isn't set up yet"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Choose screenshots" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Import trade" })).toBeDisabled();
  });

  it("asks for status itself when the page has none", async () => {
    statusBody = { available: false, enabled: true, reason: null };
    renderDialog();
    expect(
      await screen.findByText("Screenshot reading isn't set up yet"),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/trade/import-screenshot/status",
      expect.anything(),
    );
  });

  it("happy path: reads one screenshot, reviews it, imports the board rows", async () => {
    const { container, onImport } = renderDialog({ status: statusBody });
    await upload(container);
    const sideA = await screen.findByRole("region", { name: "Side A" });
    expect(postCalls).toEqual([
      { image: "data:image/png;base64,AAAA", index: 0 },
    ]);
    expect(
      within(sideA).getByText("Ja'Marr Chase", { selector: "span" }),
    ).toBeInTheDocument();
    expect(
      within(sideA).getByText("Screenshot label: “Team Alpha”"),
    ).toBeInTheDocument();
    expect(
      within(sideSection("Side B")).getByText("Puka Nacua", {
        selector: "span",
      }),
    ).toBeInTheDocument();
    // Ignored text is shown, collapsed.
    expect(screen.getByText("Ignored text (1)")).toBeInTheDocument();
    expect(screen.getByText("Read — 3 assets found")).toBeInTheDocument();

    const importBtn = screen.getByRole("button", { name: "Import trade" });
    expect(importBtn).toBeEnabled();
    await userEvent.click(importBtn);
    expect(onImport).toHaveBeenCalledTimes(1);
    const [sides, mode] = onImport.mock.calls[0];
    expect(mode).toBe("replace");
    expect(sides[0]).toEqual([
      rowByName.get("Ja'Marr Chase"),
      rowByName.get("2027 Round 1"),
    ]);
    expect(sides[1]).toEqual([rowByName.get("Puka Nacua")]);
    expect(sides[0][0]).toBe(rowByName.get("Ja'Marr Chase"));
  });

  it("needs_confirmation blocks the import until the user chooses", async () => {
    extractionBody = extraction({
      sides: [
        {
          label: "",
          labelSource: "none",
          items: [
            {
              ...ITEM,
              raw: "J. Allen",
              boardName: null,
              status: "needs_confirmation",
              candidates: [
                {
                  sleeperId: "4984",
                  boardName: "Josh Allen",
                  position: "QB",
                  team: "BUF",
                },
                {
                  sleeperId: "1111",
                  boardName: "Josh Allen (LB)",
                  position: "LB",
                  team: "JAX",
                },
              ],
            },
          ],
        },
        { label: "", labelSource: "none", items: [resolved("Puka Nacua")] },
      ],
    });
    const { container, onImport } = renderDialog({ status: statusBody });
    await upload(container);
    const chooser = await screen.findByRole("combobox", {
      name: "Choose the asset for “J. Allen”",
    });
    expect(screen.getByText("Confirm")).toBeInTheDocument();
    const importBtn = screen.getByRole("button", { name: "Import trade" });
    expect(importBtn).toBeDisabled();
    expect(screen.getByText(/Before importing: confirm 1/)).toBeInTheDocument();
    await userEvent.click(importBtn);
    expect(onImport).not.toHaveBeenCalled();

    await userEvent.selectOptions(chooser, "1");
    await waitFor(() => expect(importBtn).toBeEnabled());
    await userEvent.click(importBtn);
    expect(onImport.mock.calls[0][0][0]).toEqual([
      rowByName.get("Josh Allen (LB)"),
    ]);
  });

  it("a Not found item offers suggestions and a board search", async () => {
    extractionBody = extraction({
      sides: [
        {
          label: "",
          labelSource: "none",
          items: [
            {
              ...ITEM,
              raw: "Pukka Nakua",
              boardName: null,
              status: "unresolved",
              reason: "no_match",
              suggestions: [
                {
                  sleeperId: "9493",
                  boardName: "Puka Nacua",
                  position: "WR",
                  team: "LAR",
                },
              ],
            },
            {
              ...ITEM,
              raw: "Gibberish QB",
              boardName: null,
              status: "unresolved",
              reason: "no_match",
            },
          ],
        },
        { label: "", labelSource: "none", items: [resolved("Ja'Marr Chase")] },
      ],
    });
    const { container, onImport } = renderDialog({ status: statusBody });
    await upload(container);
    await screen.findByRole("region", { name: "Side A" });
    expect(screen.getAllByText("Not found")).toHaveLength(2);
    await userEvent.click(
      screen.getByRole("button", { name: "Use Puka Nacua" }),
    );
    // Fix the second one through the search box.
    await userEvent.click(screen.getByRole("button", { name: "Find asset" }));
    await userEvent.type(
      screen.getByLabelText("Search the board for “Gibberish QB”"),
      "Bijan",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Bijan Robinson/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    expect(onImport.mock.calls[0][0][0].map((r) => r.name)).toEqual([
      "Puka Nacua",
      "Bijan Robinson",
    ]);
  });

  it("Swap sides swaps the review wholesale", async () => {
    const { container, onImport } = renderDialog({ status: statusBody });
    await upload(container);
    await screen.findByRole("region", { name: "Side A" });
    await userEvent.click(screen.getByRole("button", { name: "Swap sides" }));
    expect(
      within(sideSection("Side A")).getByText("Puka Nacua", {
        selector: "span",
      }),
    ).toBeInTheDocument();
    expect(
      within(sideSection("Side B")).getByText("Screenshot label: “Team Alpha”"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    const [sides] = onImport.mock.calls[0];
    expect(sides[0].map((r) => r.name)).toEqual(["Puka Nacua"]);
    expect(sides[1].map((r) => r.name)).toEqual([
      "Ja'Marr Chase",
      "2027 Round 1",
    ]);
  });

  it("moving an item to the tray blocks import until it is placed again", async () => {
    const { container, onImport } = renderDialog({ status: statusBody });
    await upload(container);
    await screen.findByRole("region", { name: "Side A" });
    await userEvent.click(
      screen.getByRole("button", { name: "Needs a side: Puka Nacua" }),
    );
    const tray = screen.getByRole("region", { name: "Needs a side" });
    expect(
      within(tray).getByText("Puka Nacua", { selector: "span" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import trade" })).toBeDisabled();
    await userEvent.click(
      within(tray).getByRole("button", { name: "To Side A: Puka Nacua" }),
    );
    expect(screen.queryByRole("region", { name: "Needs a side" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    expect(onImport.mock.calls[0][0][0].map((r) => r.name)).toEqual([
      "Ja'Marr Chase",
      "2027 Round 1",
      "Puka Nacua",
    ]);
  });

  it("server warnings show as banners and unassigned items need a side", async () => {
    extractionBody = extraction({
      sides: [
        { label: "", labelSource: "none", items: [resolved("Puka Nacua")] },
      ],
      unassigned: [resolved("Bijan Robinson")],
      warnings: ["missing_side", "pick_owner_not_established"],
    });
    const { container } = renderDialog({ status: statusBody });
    await upload(container);
    expect(
      await screen.findByText(/Only one side of the trade was found/),
    ).toBeInTheDocument();
    expect(screen.getByText(/pick owners aren't shown/i)).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Needs a side" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import trade" })).toBeDisabled();
  });

  it("maps an extraction error to plain words and offers Retry when it can help", async () => {
    let n = 0;
    extractionBody = () => {
      n += 1;
      return n === 1
        ? { __status: 503, error: "ocr_busy", message: "busy" }
        : extraction();
    };
    const { container } = renderDialog({ status: statusBody });
    await upload(container);
    expect(
      await screen.findByText(/The screenshot reader is busy/),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Retry screenshot 1" }),
    );
    expect(
      await screen.findByRole("region", { name: "Side A" }),
    ).toBeInTheDocument();
    expect(postCalls).toHaveLength(2);
  });

  it("Cancel closes without importing anything", async () => {
    const { container, onImport, onClose } = renderDialog({
      status: statusBody,
    });
    await upload(container);
    await screen.findByRole("region", { name: "Side A" });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onImport).not.toHaveBeenCalled();
  });

  it("offers Replace and Add only when the trade already has assets", async () => {
    const { container, onImport } = renderDialog({
      status: statusBody,
      hasExistingAssets: true,
    });
    expect(screen.queryByRole("button", { name: "Import trade" })).toBeNull();
    await upload(container);
    await screen.findByRole("region", { name: "Side A" });
    await userEvent.click(
      screen.getByRole("button", { name: "Add to current trade" }),
    );
    expect(onImport.mock.calls[0][1]).toBe("add");
    await userEvent.click(
      screen.getByRole("button", { name: "Replace current trade" }),
    );
    expect(onImport.mock.calls[1][1]).toBe("replace");
  });

  it("reads several screenshots one request at a time, in order", async () => {
    extractionBody = (call) =>
      extraction({
        imageIndex: call - 1,
        sides: [
          {
            label: "",
            labelSource: "none",
            items: [resolved(call === 1 ? "Puka Nacua" : "Bijan Robinson")],
          },
        ],
      });
    const { container, onImport } = renderDialog({ status: statusBody });
    await upload(container, [png("a.png"), png("b.png")]);
    await screen.findByRole("region", { name: "Side A" });
    expect(postCalls.map((c) => c.index)).toEqual([0, 1]);
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    expect(onImport.mock.calls[0][0][0].map((r) => r.name)).toEqual([
      "Puka Nacua",
      "Bijan Robinson",
    ]);
  });

  it("a follow-up screenshot showing only 'Team 2 gets' fills Team 2's side", async () => {
    const anchored = (label, slot, items) => ({
      label,
      labelSource: "anchor",
      anchorFamily: "team 1/team 2",
      anchorSlot: slot,
      items,
    });
    extractionBody = (call) =>
      call === 1
        ? extraction({
            imageIndex: 0,
            layout: { kind: "stacked", confidence: 0.9 },
            sides: [
              anchored("Team 1 gets", 0, [resolved("Ja'Marr Chase")]),
              anchored("Team 2 gets", 1, []),
            ],
            warnings: ["missing_side"],
          })
        : extraction({
            imageIndex: 1,
            layout: { kind: "single", confidence: 0.7 },
            sides: [anchored("Team 2 gets", 1, [resolved("Puka Nacua")])],
            warnings: ["missing_side"],
          });
    const { container, onImport } = renderDialog({ status: statusBody });
    await upload(container, [png("top.png"), png("scrolled.png")]);
    await screen.findByRole("region", { name: "Side A" });
    expect(
      await screen.findByText(
        'Screenshot 2 shows only "Team 2 gets", so its assets were added to that side.',
      ),
    ).toBeInTheDocument();
    expect(
      within(sideSection("Side B")).getByText("Puka Nacua"),
    ).toBeInTheDocument();
    // both sides are filled: no stale "only one side was found" banner
    expect(screen.queryByText(/only one side of the trade/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    const [sides] = onImport.mock.calls[0];
    expect(sides.map((side) => side.map((r) => r.name))).toEqual([
      ["Ja'Marr Chase"],
      ["Puka Nacua"],
    ]);
  });

  it("renders a Drawer on a narrow viewport", async () => {
    window.matchMedia = vi.fn(() => ({
      matches: true,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    renderDialog({ status: statusBody });
    const dialog = screen.getByRole("dialog", {
      name: "Import trade from screenshot",
    });
    expect(dialog).toHaveClass("ds-drawer");
  });

  it("renders a Modal on a wide viewport", () => {
    renderDialog({ status: statusBody });
    expect(
      screen.getByRole("dialog", { name: "Import trade from screenshot" }),
    ).toHaveClass("ds-modal__panel");
  });
});
