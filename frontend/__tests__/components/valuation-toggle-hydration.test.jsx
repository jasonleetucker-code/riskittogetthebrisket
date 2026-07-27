/**
 * The valuation toggle must not claim a value basis before it knows one.
 *
 * `useSettings` is a `useSyncExternalStore` over localStorage. React uses
 * `getServerSnapshot` for BOTH the SSR render and the client's hydration
 * pass, so the first client render of every consumer sees
 * SETTINGS_DEFAULTS — `valuationMode: "market"` — regardless of what this
 * device has persisted. React then re-renders with the real value.
 *
 * For most settings that gap is invisible. For this one it is a claim
 * about which board produced the numbers on screen, on pages where that
 * claim decides trade verdicts. And it cost a wasted round-trip:
 * `useDynastyData`'s fetch effect fired once on the defaults and again
 * after hydration.
 *
 * WHAT THIS FILE DOES AND DOES NOT PROVE
 * `SegmentedControl` already handled an unmatched value correctly —
 * `aria-checked` has always been `opt.value === value`, and the
 * `Math.max(0, findIndex(...))` nearby only ever drove the roving
 * tabindex. So these are NOT regression tests for a bug that existed
 * here; they pin a contract the call sites now depend on. The
 * demonstration that the flash was real lives next door, in
 * `useSettings.hydration.test.jsx`'s "the UNGATED render is the bug".
 *
 * They still earn their place: `/rankings` and `/trade` now pass `null`
 * on purpose, and the cheapest way to break that is to wire
 * `aria-checked` to `activeIndex` during some future tidy-up, which
 * would restore a confident highlight on an unknown value. Every
 * assertion is therefore about `aria-checked` on a named option — the
 * one attribute that separates "nothing selected" from "wrong thing
 * selected".
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { SegmentedControl } from "@/components/ds/SegmentedControl";

const OPTIONS = [
  { value: "market", label: "Market" },
  { value: "leagueAdjusted", label: "My league" },
];

function renderToggle(value) {
  return render(
    <SegmentedControl label="Value basis" value={value} options={OPTIONS} onChange={() => {}} />
  );
}

describe("SegmentedControl indeterminate state", () => {
  it("checks nothing when the value is null", () => {
    renderToggle(null);
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toHaveAttribute("aria-checked", "false");
    }
  });

  it("does NOT fall back to highlighting the first option", () => {
    // The failure this guards: `activeIndex` floors at 0, so wiring
    // `aria-checked` to it would confidently highlight "Market" for any
    // unmatched value — including the `null` the hydration gate passes.
    renderToggle(null);
    expect(screen.getByRole("radio", { name: "Market" })).toHaveAttribute(
      "aria-checked",
      "false"
    );
  });

  it("treats an unknown value the same as no value", () => {
    // Not only hydration: a stale or renamed setting must not silently
    // resolve to whichever option happens to be listed first.
    renderToggle("someRetiredMode");
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toHaveAttribute("aria-checked", "false");
    }
  });

  it("stays keyboard-reachable while indeterminate", () => {
    // A radiogroup with no tab stop is unreachable. The roving tabindex
    // falls to the first option even when nothing is checked — which is
    // NOT the same as checking it.
    renderToggle(null);
    const radios = screen.getAllByRole("radio");
    expect(radios.filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(radios[0]).toHaveAttribute("tabindex", "0");
    expect(radios[0]).toHaveAttribute("aria-checked", "false");
  });

  it("renders the same options either way, so nothing shifts on hydration", () => {
    const { container: indeterminate } = renderToggle(null);
    const before = indeterminate.querySelectorAll(".ds-segmented__option").length;
    const { container: settled } = renderToggle("leagueAdjusted");
    const after = settled.querySelectorAll(".ds-segmented__option").length;
    expect(before).toBe(after);
    expect(before).toBe(OPTIONS.length);
  });

  it("checks exactly the matching option once a value arrives", () => {
    renderToggle("leagueAdjusted");
    expect(screen.getByRole("radio", { name: "My league" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
    expect(screen.getByRole("radio", { name: "Market" })).toHaveAttribute(
      "aria-checked",
      "false"
    );
  });
});
