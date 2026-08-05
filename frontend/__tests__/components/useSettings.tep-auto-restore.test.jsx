/**
 * Existing installs must actually be moved back onto the measured curve.
 *
 * Changing `SETTINGS_DEFAULTS.tepMultiplier` to `null` only helps a fresh
 * install. Every browser that had ever loaded the site already had a
 * stored blob with `tepMultiplier: 1.15` and `tepDefaultV3Applied: true`,
 * written by the previous migration — which promoted the auto sentinel to
 * a flat number and set a flag so it never reverted.
 *
 * So the default change on its own would have fixed the defect for nobody
 * who was already using the site. This is the half that does.
 */

import { describe, expect, it, beforeEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { useSettings } from "@/components/useSettings";
import { SETTINGS_KEY } from "@/lib/trade-logic";

function TepProbe() {
  const { settings, hydrated } = useSettings();
  const raw = settings?.tepMultiplier;
  return (
    <span data-testid="tep">
      {!hydrated ? "pending" : raw === null || raw === undefined ? "auto" : String(raw)}
    </span>
  );
}

function seed(blob) {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(blob));
  window.dispatchEvent(new StorageEvent("storage", { key: SETTINGS_KEY }));
}

function stored() {
  return JSON.parse(window.localStorage.getItem(SETTINGS_KEY) || "{}");
}

describe("the TEP auto-restore migration", () => {
  beforeEach(() => {
    // The store memoizes in a module-level cache that only a write
    // through `update()` or a cross-tab storage event invalidates, so
    // clearing storage alone would leave the previous test's settings
    // live. Fire the store's own invalidation path, same as
    // useSettings.hydration.test.jsx does.
    window.localStorage.clear();
    window.dispatchEvent(new StorageEvent("storage", { key: SETTINGS_KEY }));
  });

  it("restores an install the old migration pinned to 1.15", async () => {
    // Exactly the state the previous migration left behind.
    seed({ tepMultiplier: 1.15, tepDefaultV3Applied: true });
    render(<TepProbe />);
    expect(await screen.findByTestId("tep")).toHaveTextContent("auto");
    expect(stored().tepMultiplier ?? null).toBeNull();
    expect(stored().tepAutoRestored).toBe(true);
  });

  it.each([1.0, 1.25])("also restores the other default-ish value %s", async (value) => {
    // 1.0 was a stray wheel-scroll on the number input; 1.25 was an
    // interim build's default. The old migration named both as
    // default-ish and promoted them; this returns them to auto instead.
    seed({ tepMultiplier: value, tepDefaultV3Applied: true });
    render(<TepProbe />);
    expect(await screen.findByTestId("tep")).toHaveTextContent("auto");
  });

  it("leaves a genuinely chosen value alone", async () => {
    // 1.30 is not a value any default or migration ever wrote, so the
    // only way it is in storage is that someone typed it. The fix must
    // not sweep up real overrides on its way past.
    seed({ tepMultiplier: 1.3, tepDefaultV3Applied: true });
    render(<TepProbe />);
    expect(await screen.findByTestId("tep")).toHaveTextContent("1.3");
    expect(stored().tepMultiplier).toBe(1.3);
  });

  it("runs once, so a later explicit 1.15 sticks", async () => {
    // The flag is what makes this a migration rather than a policy. An
    // operator who types 1.15 tomorrow is making a choice, and it must
    // survive the next page load.
    seed({ tepMultiplier: 1.15, tepAutoRestored: true });
    render(<TepProbe />);
    expect(await screen.findByTestId("tep")).toHaveTextContent("1.15");
  });

  it("leaves a fresh install on auto without writing anything odd", async () => {
    render(<TepProbe />);
    expect(await screen.findByTestId("tep")).toHaveTextContent("auto");
  });
});
