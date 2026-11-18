/**
 * The /trade phone sheet's focus hand-back after an add (TC-D2 / TC-E).
 *
 * Adding a result clears the query, which unmounts the row that was just
 * activated and drops focus to <body>; one frame later the sheet puts focus
 * back in its search field so typing on works.  That frame lands AFTER the
 * "Added …" status renders, so anything focused inside it — the Done button a
 * keyboard user tabbed to, a control assistive tech moved to, Playwright's
 * `press()` — used to have focus taken back to the search field, and its
 * Enter went into the input instead of closing the sheet (E2E trade-tce,
 * WebKit mobile-390, 6 of 77 attempts across 2026-10-30..2026-11-18).
 *
 * Pinned with a hand-driven frame queue, so the frame fires exactly where
 * the race put it:
 *   - focus that was dropped is still handed back to the search field;
 *   - focus that moved to another control before the frame stays there, and
 *     that control still works (Done closes the sheet).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { TradeAssetSheet } from "@/app/trade/trade-asset-sheet";

const ROW = {
  name: "Bijan Robinson",
  pos: "RB",
  position: "RB",
  assetClass: "offense",
  team: "ATL",
  rankDerivedValue: 8000,
  values: { full: 8000 },
  blendedSourceRank: 1,
  raw: {},
};

let frames;

beforeEach(() => {
  frames = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    frames.push(cb);
    return frames.length;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function flushFrame() {
  const pending = frames.splice(0);
  act(() => {
    for (const cb of pending) cb(performance.now());
  });
}

function renderSheet() {
  const onAdd = vi.fn();
  const onClose = vi.fn();
  render(
    <TradeAssetSheet
      side={{ label: "A" }}
      sideIdx={0}
      searchAssets={(q) => (q.trim() ? [ROW] : [])}
      settings={{}}
      onAdd={onAdd}
      onClose={onClose}
    />,
  );
  const sheet = screen.getByRole("dialog", { name: "Add to Side A" });
  const input = within(sheet).getByLabelText("Search to add a player to Side A");
  return { sheet, input, onAdd, onClose };
}

/** Type a query, put focus on the result row (Tab), activate it (Enter → click). */
function addByKeyboard(sheet, input) {
  fireEvent.change(input, { target: { value: "Bijan" } });
  const row = within(sheet).getByRole("button", { name: /Bijan Robinson/ });
  act(() => row.focus());
  expect(document.activeElement).toBe(row);
  fireEvent.click(row);
  return row;
}

describe("TradeAssetSheet focus hand-back", () => {
  it("hands dropped focus back to the search field on the next frame", () => {
    const { sheet, input, onAdd } = renderSheet();
    const row = addByKeyboard(sheet, input);

    expect(onAdd).toHaveBeenCalledWith(ROW, 0);
    expect(within(sheet).getByRole("status").textContent).toMatch(/Added Bijan Robinson/);
    // The activated row is gone, so focus has nowhere to be until the frame.
    expect(row.isConnected).toBe(false);
    expect(document.activeElement).not.toBe(input);

    flushFrame();
    expect(document.activeElement).toBe(input);
  });

  it("does not take focus back from a control focused before that frame", () => {
    const { sheet, input, onClose } = renderSheet();
    addByKeyboard(sheet, input);
    const done = within(sheet).getByRole("button", { name: "Done" });

    // Inside the frame window: the status is already on screen and focus
    // moves to Done (Tab, assistive tech, or Playwright's press()).
    act(() => done.focus());
    flushFrame();

    expect(document.activeElement).toBe(done);
    fireEvent.click(done);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("leaves the close button focused too", () => {
    const { sheet, input } = renderSheet();
    addByKeyboard(sheet, input);
    const close = within(sheet).getByRole("button", { name: "Close Side A search" });

    act(() => close.focus());
    flushFrame();

    expect(document.activeElement).toBe(close);
  });
});
