/**
 * TC-A / UX audit P0-4 — no control on /trade changes trade math away from
 * the canonical value.
 *
 * The "Value mode: Raw" select rewired the meter, tray, balancers and CSV
 * onto `values.raw`, the legacy scraper composite (0.27x-2.08x canonical),
 * while the side cards' "Raw" meant canonical-before-VA and every other
 * surface stayed canonical.  Captured on J2: totals 5,914 vs 5,808 beside
 * side-card "Raw 6,052" / "Raw 5,699".
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { TRADE_VALUE_MODE, VALUE_MODES, adjustedSideTotals } from "../lib/trade-logic.js";

describe("the trade value mode is canonical", () => {
  it("offers no legacy-composite mode", () => {
    expect(VALUE_MODES.map((m) => m.key)).toEqual(["full"]);
    expect(TRADE_VALUE_MODE).toBe("full");
  });

  it("the page's totals read canonical values, never values.raw", () => {
    const a = [{ name: "P", values: { full: 6052, raw: 5914 } }];
    const b = [{ name: "K", values: { full: 5699, raw: 5808 } }];
    const [ta, tb] = adjustedSideTotals(a, b, TRADE_VALUE_MODE, {});
    expect([ta.raw, tb.raw]).toEqual([6052, 5699]);
  });

  it("/trade renders no value-mode select and computes on TRADE_VALUE_MODE", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "../app/trade/page.jsx"), "utf8");
    expect(src).not.toMatch(/aria-label="Value mode"/);
    expect(src).not.toMatch(/setValueMode/);
    expect(src).toMatch(/const valueMode = TRADE_VALUE_MODE;/);
  });
});
