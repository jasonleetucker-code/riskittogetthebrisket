// /waivers Manual add/drop: the DROP / ADD pickers must be operable without
// a mouse (verified sweep 2026-11-16, accessibility, high).
//
// The defect: result buttons answered only mouse-down / touch-start (no
// click), the input carried no combobox semantics, and the list closed on a
// 120 ms timer after focus left the INPUT — so a keyboard or screen-reader
// user could neither move to a result nor activate one, and the two "Remove"
// buttons shared one accessible name.  The only interaction test
// (fairness-meter-one-side-and-percent.test.jsx) picks with mouseDown, which
// is why none of this was caught.  Every case below fails on that code.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ManualAddDrop from "@/components/waivers/ManualAddDrop";

const row = (name, value, pos = "WR") => ({
  name,
  pos,
  rankDerivedValue: value,
  assetClass: "offense",
  sourceCount: 6,
  confidenceBucket: "high",
  values: { full: value },
});

const ALLEN = row("Josh Allen", 5200, "QB");
const HURTS = row("Jalen Hurts", 4100, "QB");
const EGBUKA = row("Emeka Egbuka", 3100, "WR");
const TEAM = { name: "Mine", players: ["Josh Allen", "Jalen Hurts"], faabRemaining: 63 };

beforeEach(() => {
  // League analytics + the bid desk both answer 503: this file is about the
  // pickers, and a failing desk renders a stated banner, not a crash.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}), text: async () => "" })),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderManual() {
  return render(
    <ManualAddDrop
      rows={[ALLEN, HURTS, EGBUKA]}
      selectedTeam={TEAM}
      sleeperTeams={[]}
      settings={{}}
    />,
  );
}

const dropInput = () => screen.getByRole("combobox", { name: "Search drop candidates" });
const addInput = () => screen.getByRole("combobox", { name: "Search add candidates" });

describe("combobox semantics", () => {
  it("the search input is a combobox that controls a listbox of options", async () => {
    const user = userEvent.setup();
    renderManual();
    const input = dropInput();
    expect(input).toHaveAttribute("aria-expanded", "false");

    await user.click(input);
    expect(input).toHaveAttribute("aria-expanded", "true");
    const listbox = screen.getByRole("listbox", { name: "Drop candidates" });
    expect(input).toHaveAttribute("aria-controls", listbox.id);
    const options = within(listbox).getAllByRole("option");
    // The drop pool is lowest-value first.
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining("Jalen Hurts"),
      expect.stringContaining("Josh Allen"),
    ]);
    // Options are reached through aria-activedescendant, not the tab order.
    for (const o of options) expect(o).toHaveAttribute("tabindex", "-1");
  });

  it("an empty search states 'No matches.' outside the listbox", async () => {
    const user = userEvent.setup();
    renderManual();
    await user.type(dropInput(), "zzz");
    expect(screen.getByRole("status")).toHaveTextContent("No matches.");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(dropInput()).toHaveAttribute("aria-expanded", "false");
  });
});

describe("keyboard: arrows move, Enter picks", () => {
  it("ArrowDown / ArrowUp move the active option; Enter picks it", async () => {
    const user = userEvent.setup();
    renderManual();
    const input = dropInput();
    await user.click(input);
    expect(input).not.toHaveAttribute("aria-activedescendant");

    await user.keyboard("{ArrowDown}");
    let options = screen.getAllByRole("option");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveAttribute("aria-selected", "false");

    await user.keyboard("{ArrowDown}");
    options = screen.getAllByRole("option");
    expect(input).toHaveAttribute("aria-activedescendant", options[1].id);

    await user.keyboard("{ArrowUp}");
    options = screen.getAllByRole("option");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);

    await user.keyboard("{Enter}");
    // Jalen Hurts (the first, lowest-value drop) is now the drop side.
    expect(screen.queryByRole("combobox", { name: "Search drop candidates" })).toBeNull();
    const clear = screen.getByRole("button", { name: "Clear drop selection" });
    expect(clear.closest("div").parentElement.textContent).toContain("Jalen Hurts");
    // Focus is moved to that side's clear button, never dropped on <body>.
    expect(clear).toHaveFocus();
  });

  it("Escape closes the list without picking", async () => {
    const user = userEvent.setup();
    renderManual();
    const input = dropInput();
    await user.click(input);
    await user.keyboard("{ArrowDown}{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Clear drop selection" })).toBeNull();
  });

  it("the full keyboard flow fills both sides and the fairness bar reads them", async () => {
    const user = userEvent.setup();
    renderManual();
    await user.click(dropInput());
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}"); // Josh Allen
    await user.click(addInput());
    await user.keyboard("{ArrowDown}{Enter}"); // Emeka Egbuka
    // 5200 vs 3100 on a 1-for-1: the same verdict the mouse path pins.
    expect(screen.getByText("Side Drop wins by 40.3%")).toBeInTheDocument();
  });
});

describe("activation and focus are not mouse-only", () => {
  it("a plain click (keyboard / screen-reader activation, no mouse-down) picks", () => {
    renderManual();
    fireEvent.focus(addInput());
    // fireEvent.click dispatches ONLY a click — what Enter/Space on a
    // focused button and a screen reader's virtual cursor send.
    fireEvent.click(screen.getByRole("option", { name: /Emeka Egbuka/ }));
    expect(screen.getByRole("button", { name: "Clear add selection" })).toBeInTheDocument();
  });

  it("focus moving onto an option keeps the list open (no 120 ms timer)", async () => {
    renderManual();
    const input = addInput();
    fireEvent.focus(input);
    const option = screen.getByRole("option", { name: /Emeka Egbuka/ });
    fireEvent.blur(input, { relatedTarget: option });
    // Longer than the retired 120 ms close timer.
    await act(() => new Promise((r) => setTimeout(r, 200)));
    expect(screen.getByRole("listbox", { name: "Add candidates" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: /Emeka Egbuka/ }));
    expect(screen.getByRole("button", { name: "Clear add selection" })).toBeInTheDocument();
  });

  it("focus leaving the whole picker closes the list at once", () => {
    renderManual();
    const input = addInput();
    fireEvent.focus(input);
    expect(screen.getByRole("listbox", { name: "Add candidates" })).toBeInTheDocument();
    fireEvent.blur(input, { relatedTarget: dropInput() });
    expect(screen.queryByRole("listbox", { name: "Add candidates" })).toBeNull();
  });

  it("Tab leaves the picker (options are not tab stops) and closes its list", async () => {
    const user = userEvent.setup();
    renderManual();
    await user.click(dropInput());
    expect(screen.getByRole("listbox", { name: "Drop candidates" })).toBeInTheDocument();
    await user.tab();
    expect(screen.queryByRole("listbox", { name: "Drop candidates" })).toBeNull();
    expect(dropInput()).not.toHaveFocus();
  });

  it("the mouse path still picks on the press (regression)", () => {
    renderManual();
    fireEvent.focus(dropInput());
    fireEvent.mouseDown(screen.getByRole("option", { name: /Josh Allen/ }));
    expect(screen.getByRole("button", { name: "Clear drop selection" })).toBeInTheDocument();
  });
});

describe("the two clear buttons have distinct names", () => {
  it("names each side, and clearing returns focus to that side's search", async () => {
    const user = userEvent.setup();
    renderManual();
    await user.click(dropInput());
    await user.keyboard("{ArrowDown}{Enter}");
    await user.click(addInput());
    await user.keyboard("{ArrowDown}{Enter}");

    const clearDrop = screen.getByRole("button", { name: "Clear drop selection" });
    const clearAdd = screen.getByRole("button", { name: "Clear add selection" });
    expect(clearDrop).not.toBe(clearAdd);
    // No two buttons share the old generic name.
    expect(screen.queryAllByRole("button", { name: "Clear selection" })).toHaveLength(0);
    // The visible word is inside the accessible name (WCAG 2.5.3).
    expect(clearAdd.textContent).toBe("Clear");

    await user.click(clearAdd);
    expect(addInput()).toHaveFocus();
    // The drop side is untouched.
    expect(screen.getByRole("button", { name: "Clear drop selection" })).toBeInTheDocument();
  });
});
