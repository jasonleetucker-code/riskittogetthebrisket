/**
 * The TE-premium default, and the one property that makes it correct.
 *
 * `tepMultiplier` decides whether the backend applies the MEASURED ADR-015
 * TE basis conversion or an operator's flat override. The backend asks
 * "did the operator choose a number?", and `tepMultiplierIsCustomized`
 * answers yes for ANY finite number — so a NUMERIC default is
 * indistinguishable from a deliberate override.
 *
 * That is what shipped: the default was 1.15, so every page load for every
 * user POSTed `tep_multiplier=1.15` and silently disabled the measured
 * curve. Measured against the live stack, the override body produced 627
 * rank / 654 tier / 135 value divergences from `GET /api/data` while the
 * response still stamped `isCustomized:false`; the empty body produces
 * 0/0/0. Audit findings W03-F001, W07-F001, W08-F001, W07-F002.
 *
 * The whole suite passed with the defective default in place, which is why
 * these assertions exist: nothing pinned the one property that matters —
 * *the default must be a value the customization predicate reads as auto*.
 */
import { describe, expect, it, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  SETTINGS_DEFAULTS,
  useSettings,
} from "@/components/useSettings";
import { tepMultiplierIsCustomized } from "@/lib/dynasty-data";
import { SETTINGS_KEY } from "@/lib/trade-logic";

function syncStore() {
  window.dispatchEvent(new StorageEvent("storage", { key: SETTINGS_KEY }));
}

function persist(obj) {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(obj));
  syncStore();
}

function stored() {
  return JSON.parse(window.localStorage.getItem(SETTINGS_KEY) || "{}");
}

describe("tepMultiplier default", () => {
  beforeEach(() => {
    window.localStorage.clear();
    syncStore();
  });

  // The load-bearing assertion. If this fails, every page load overrides
  // the measured curve again, and it fails silently — the board still
  // renders, it just renders different numbers than the API serves.
  it("is not customized, so no override is posted on a fresh install", () => {
    expect(tepMultiplierIsCustomized(SETTINGS_DEFAULTS.tepMultiplier)).toBe(false);
  });

  it("is null specifically — the only sentinel the predicate reads as auto", () => {
    expect(SETTINGS_DEFAULTS.tepMultiplier).toBeNull();
  });

  it("uses the same sentinel as its sibling knob", () => {
    // tepNativeMultiplier always used null correctly; the two knobs
    // disagreeing is what made the bug easy to miss on review.
    expect(SETTINGS_DEFAULTS.tepNativeMultiplier).toBeNull();
  });

  it("a number the operator chooses is still an override", () => {
    // The fix must not make deliberate overrides unreachable.
    expect(tepMultiplierIsCustomized(1.25)).toBe(true);
    expect(tepMultiplierIsCustomized(1.15)).toBe(true);
  });
});

describe("tepMultiplier v4 migration", () => {
  beforeEach(() => {
    window.localStorage.clear();
    syncStore();
  });

  it("returns a persisted 1.15 to auto", () => {
    // These users were put on 1.15 by the v3 migration or by the old
    // numeric default, not by choosing it.
    persist({ tepMultiplier: 1.15, tepDefaultV3Applied: true });
    renderHook(() => useSettings());
    expect(stored().tepMultiplier).toBeNull();
    expect(stored().tepDefaultV4Applied).toBe(true);
  });

  it("retires the v3 marker rather than leaving both", () => {
    persist({ tepMultiplier: 1.15, tepDefaultV3Applied: true });
    renderHook(() => useSettings());
    expect(stored()).not.toHaveProperty("tepDefaultV3Applied");
  });

  it("leaves a deliberate non-default value alone", () => {
    persist({ tepMultiplier: 1.4, tepDefaultV3Applied: true });
    renderHook(() => useSettings());
    expect(stored().tepMultiplier).toBe(1.4);
  });

  it("runs once — a later deliberate 1.15 survives", () => {
    persist({ tepMultiplier: 1.15, tepDefaultV3Applied: true });
    const { result } = renderHook(() => useSettings());
    expect(stored().tepMultiplier).toBeNull();

    act(() => result.current.update("tepMultiplier", 1.15));
    expect(stored().tepMultiplier).toBe(1.15);

    // Re-reading must not undo the operator's choice.
    renderHook(() => useSettings());
    expect(stored().tepMultiplier).toBe(1.15);
  });

  it("leaves an install that never had the key on auto", () => {
    persist({ valuationMode: "market" });
    renderHook(() => useSettings());
    expect(stored().tepMultiplier ?? null).toBeNull();
  });
});
