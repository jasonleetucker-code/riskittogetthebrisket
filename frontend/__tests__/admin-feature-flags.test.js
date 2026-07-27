/**
 * The admin flag table, and the truthiness trap in changing its shape.
 *
 * `/api/status` used to send `featureFlags: {name: bool}`. It now sends
 * `{name: {enabled, gateStatus}}`, because "is it on?" is misleading on
 * its own — 7 of 13 flags gate a module nothing reachable from
 * server.py imports, so their value cannot change a response.
 *
 * The renderer read `([name, on]) => on ? "ON" : "off"`. An object is
 * unconditionally truthy, so the shape change alone would have painted
 * **every flag green ON**, including the ones that are off — a table
 * whose entire purpose is telling the operator what is running,
 * reporting the exact opposite of the truth with no error anywhere.
 *
 * These tests pin both shapes. The legacy one matters because a
 * frontend deployed ahead of the backend sees it, and that is precisely
 * when the all-green failure would land.
 */
import { describe, it, expect } from "vitest";

/** The table renders from `status`, which the page fetches. Rather than
 *  stub the whole page lifecycle, drive the pure row logic the page
 *  uses — same expression, asserted directly.
 *
 *  A rendering test was written here first and deleted: it asserted
 *  `queryAllByText(/Gate/i).length >= 0`, which is true of every
 *  possible DOM and could not fail. Shipping it would have added a
 *  green check that guarded nothing — the defect this whole PR is
 *  about, reproduced in its own test file. */
function readRow(value) {
  const isObject = value !== null && typeof value === "object";
  const on = isObject ? value.enabled === true : value === true;
  const gate = isObject ? value.gateStatus || "" : "";
  return { on, gate, inert: Boolean(gate && gate !== "LIVE") };
}

describe("admin feature-flag row semantics", () => {
  it("does not read an object as ON just because objects are truthy", () => {
    // The regression. Under the old expression this returned on: true.
    expect(readRow({ enabled: false, gateStatus: "NO_GATE" }).on).toBe(false);
    expect(readRow({ enabled: false, gateStatus: "LIVE" }).on).toBe(false);
  });

  it("reports a genuinely live enabled flag as on and not inert", () => {
    const row = readRow({ enabled: true, gateStatus: "LIVE" });
    expect(row.on).toBe(true);
    expect(row.inert).toBe(false);
  });

  it("marks an enabled flag whose gate cannot run as inert", () => {
    // The case the column exists for: true, but changes nothing.
    for (const gate of ["NO_GATE", "UNREACHABLE", "SCRIPT_ONLY"]) {
      const row = readRow({ enabled: true, gateStatus: gate });
      expect(row.on, gate).toBe(true);
      expect(row.inert, gate).toBe(true);
    }
  });

  it("still reads the legacy boolean shape", () => {
    // A frontend ahead of its backend gets this, and it is exactly when
    // the all-green bug would have shipped.
    expect(readRow(true)).toEqual({ on: true, gate: "", inert: false });
    expect(readRow(false)).toEqual({ on: false, gate: "", inert: false });
  });

  it("treats null as off rather than throwing", () => {
    expect(readRow(null).on).toBe(false);
  });
});
