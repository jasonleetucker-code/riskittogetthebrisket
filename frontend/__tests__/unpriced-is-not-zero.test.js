/**
 * An asset the board declined to price is not an asset worth zero.
 *
 * WHAT WAS WRONG
 * ==============
 * `inferValueBundle` coerces a missing board value to `0`, and both
 * materializers stamp `values.full = Math.round(backendValue || 0)`. On
 * the live 2026-08-14 contract **282 of 1,094 rows** carry
 * `rankDerivedValue: null` — the backend says so explicitly, and even
 * publishes the count as `rowsUnpricedByBoard: 282`.
 *
 * The zero is defensible in exactly one place: inside `sideTotal`, where
 * it is an arithmetic neutral and dropping the row instead would shrink
 * the piece count that Value Adjustment is computed from. Everywhere it
 * reached a LABEL or a SORT it made a claim nobody made — "we priced
 * this and it is worth nothing" — and put unpriced assets alongside
 * genuinely worthless ones.
 *
 * `isUnpricedBoardRow` was added for this (audit finding W08-F006) and
 * its own docstring says unpriced rows "are labelled instead, at the
 * chip". **It had no production consumer at all** — only this test
 * directory imported it. The predicate shipped; the label did not.
 *
 * WHAT HOLDS NOW
 * ==============
 * The missingness is preserved separately from the arithmetic, which is
 * the shape the governance rule allows: `effectiveValue` still returns 0
 * for the bounded sum, while `displayValue` returns `null`,
 * `formatBoardValue` renders "—", and `unpricedAssetsOnSide` lets the
 * side total say it is incomplete instead of pretending otherwise.
 */
import { describe, it, expect } from "vitest";

import {
  displayValue,
  effectiveValue,
  formatBoardValue,
  isUnpricedBoardRow,
  sideTotal,
  unpricedAssetsOnSide,
} from "@/lib/trade-logic";

const priced = (name, value) => ({
  name,
  assetClass: "offense",
  rankDerivedValue: value,
  values: { full: value, raw: value },
});

/** Exactly the shape the materializer produces for an unpriced row. */
const unpriced = (name) => ({
  name,
  assetClass: "offense",
  rankDerivedValue: null,
  values: { full: 0, raw: 0 },
});

describe("displayValue distinguishes unpriced from worthless", () => {
  it("returns null for a row the board declined to price", () => {
    expect(displayValue(unpriced("2028 Mid 6th"))).toBeNull();
  });

  it("returns the number for a priced row", () => {
    expect(displayValue(priced("Bijan Robinson", 9100))).toBe(9100);
  });

  it("returns null rather than 0 for a missing row", () => {
    expect(displayValue(null)).toBeNull();
    expect(displayValue(undefined)).toBeNull();
  });

  it("renders an em dash, never a zero", () => {
    expect(formatBoardValue(unpriced("2028 Mid 6th"))).toBe("—");
    expect(formatBoardValue(priced("Bijan Robinson", 9100))).toBe("9,100");
  });
});

describe("an unpriced asset never sorts as the cheapest real asset", () => {
  it("sinks below every priced row instead of tying the worst one", () => {
    const rows = [
      priced("Deep bench WR", 12),
      unpriced("2028 Mid 6th"),
      priced("Star", 9100),
    ];
    const sorted = [...rows].sort((a, b) => {
      const av = displayValue(a);
      const bv = displayValue(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return bv - av;
    });

    expect(sorted.map((r) => r.name)).toEqual([
      "Star",
      "Deep bench WR",
      "2028 Mid 6th",
    ]);
    // The point: it is last because it is UNKNOWN, not because it lost a
    // comparison to 12. A `0` would have produced the same order here by
    // accident, and the wrong order the moment a negative or zero-valued
    // priced row existed.
    expect(displayValue(rows[1])).toBeNull();
    expect(displayValue(rows[1])).not.toBe(0);
  });
});

describe("the sum keeps its neutral element, and admits to it", () => {
  it("effectiveValue still returns 0 so the piece count is unchanged", () => {
    // Deliberate: Value Adjustment is a function of how many pieces a
    // side has, so dropping the row would change the verdict in a
    // different and worse way.
    expect(effectiveValue(unpriced("2028 Mid 6th"), "full")).toBe(0);
  });

  it("sideTotal counts it as zero", () => {
    const side = [priced("Star", 9100), unpriced("2028 Mid 6th")];
    expect(sideTotal(side, "full")).toBe(9100);
  });

  it("but the side reports which pieces were never priced", () => {
    const side = [priced("Star", 9100), unpriced("2028 Mid 6th")];
    expect(unpricedAssetsOnSide(side).map((r) => r.name)).toEqual([
      "2028 Mid 6th",
    ]);
  });

  it("a fully priced side reports nothing, so the note cannot cry wolf", () => {
    expect(unpricedAssetsOnSide([priced("Star", 9100)])).toEqual([]);
  });

  it("a user's manual override makes the asset priced again", () => {
    // The board has no number; the user supplied one. That is a real
    // value for this trade, and reporting it as missing would be wrong.
    const overridden = { ...unpriced("2028 Mid 6th"), customValue: 400 };
    expect(unpricedAssetsOnSide([overridden])).toEqual([]);
    expect(effectiveValue(overridden, "full")).toBe(400);
  });
});

describe("the predicate and the display agree", () => {
  it("every row the predicate calls unpriced has no display value", () => {
    const rows = [
      unpriced("2028 Mid 6th"),
      priced("Star", 9100),
      priced("Deep bench WR", 12),
    ];
    for (const row of rows) {
      expect(isUnpricedBoardRow(row)).toBe(displayValue(row) == null);
    }
  });
});
