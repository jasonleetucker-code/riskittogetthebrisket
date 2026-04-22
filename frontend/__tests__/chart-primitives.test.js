import { describe, it, expect } from "vitest";
import {
  CHART_COLORS,
  linearScale,
  clamp,
  ticks,
  formatNumber,
  categoricalColor,
  chartBox,
  linePath,
  histogram,
  median,
} from "../lib/chart-primitives.js";

describe("linearScale", () => {
  it("maps domain endpoints to range endpoints", () => {
    const s = linearScale(0, 100, 0, 1);
    expect(s(0)).toBe(0);
    expect(s(100)).toBe(1);
    expect(s(50)).toBe(0.5);
  });

  it("handles inverted ranges for y-axes (pixel space)", () => {
    const s = linearScale(0, 10, 200, 0);
    expect(s(0)).toBe(200);
    expect(s(10)).toBe(0);
    expect(s(5)).toBe(100);
  });

  it("returns midpoint when domain is degenerate", () => {
    const s = linearScale(5, 5, 0, 100);
    expect(s(5)).toBe(50);
    expect(s(999)).toBe(50);
  });

  it("is linear outside the domain (unclamped)", () => {
    const s = linearScale(0, 10, 0, 100);
    expect(s(-1)).toBe(-10);
    expect(s(11)).toBe(110);
  });
});

describe("clamp", () => {
  it("clamps above/below/within", () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-1, 0, 10)).toBe(0);
    expect(clamp(11, 0, 10)).toBe(10);
  });
});

describe("ticks", () => {
  it("produces ``count`` evenly spaced ticks", () => {
    expect(ticks(0, 10, 5)).toEqual([0, 2.5, 5, 7.5, 10]);
    expect(ticks(0, 100, 3)).toEqual([0, 50, 100]);
  });

  it("handles degenerate bounds", () => {
    expect(ticks(5, 5, 3)).toEqual([5, 5]);
    expect(ticks(0, 10, 1)).toEqual([0, 10]);
  });
});

describe("formatNumber", () => {
  it("rounds and inserts thousands separators", () => {
    expect(formatNumber(1234.5)).toBe("1,235");
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatNumber(42)).toBe("42");
  });

  it("respects precision", () => {
    expect(formatNumber(1234.5678, 2)).toBe("1,234.57");
    expect(formatNumber(0.333333, 3)).toBe("0.333");
  });

  it("renders dash for non-finite", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(undefined)).toBe("—");
    expect(formatNumber(NaN)).toBe("—");
    expect(formatNumber(Infinity)).toBe("—");
  });
});

describe("categoricalColor", () => {
  it("returns a palette color for each index", () => {
    const c0 = categoricalColor(0);
    expect(CHART_COLORS.categorical).toContain(c0);
  });

  it("wraps around for out-of-range indices", () => {
    const n = CHART_COLORS.categorical.length;
    expect(categoricalColor(0)).toBe(categoricalColor(n));
    expect(categoricalColor(-1)).toBe(categoricalColor(n - 1));
  });
});

describe("chartBox", () => {
  it("computes inner dimensions and plot transform", () => {
    const box = chartBox({ width: 400, height: 200 });
    expect(box.innerWidth).toBeGreaterThan(0);
    expect(box.innerHeight).toBeGreaterThan(0);
    expect(box.viewBox).toBe("0 0 400 200");
    expect(box.plotTransform).toBe(`translate(${box.margin.left}, ${box.margin.top})`);
  });

  it("applies custom margins", () => {
    const box = chartBox({ width: 400, height: 200, margin: { left: 100, right: 100, top: 10, bottom: 10 } });
    expect(box.innerWidth).toBe(200);
    expect(box.innerHeight).toBe(180);
  });

  it("clamps negative inner dimensions to zero", () => {
    const box = chartBox({ width: 40, height: 20, margin: { left: 50, right: 50, top: 50, bottom: 50 } });
    expect(box.innerWidth).toBe(0);
    expect(box.innerHeight).toBe(0);
  });
});

describe("linePath", () => {
  it("builds an M/L path from points", () => {
    const d = linePath([[0, 0], [10, 20], [20, 5]]);
    expect(d).toMatch(/^M0\.00,0\.00 L10\.00,20\.00 L20\.00,5\.00$/);
  });

  it("returns empty string for empty input", () => {
    expect(linePath([])).toBe("");
    expect(linePath(null)).toBe("");
  });

  it("breaks on null gaps so two segments render without a connecting zig-zag", () => {
    const d = linePath([[0, 0], [10, 10], null, [30, 5], [40, 1]]);
    // Two segments: M0 L10 then M30 L40.
    expect(d.match(/M/g)).toHaveLength(2);
  });

  it("ignores non-finite coordinates", () => {
    const d = linePath([[0, 0], [NaN, 10], [20, 5]]);
    // NaN forces a segment break; path has one M before NaN, one after.
    expect(d.match(/M/g)).toHaveLength(2);
  });
});

describe("histogram", () => {
  it("bucketises values across the observed range", () => {
    const h = histogram([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5);
    expect(h).toHaveLength(5);
    const totalCount = h.reduce((s, b) => s + b.count, 0);
    expect(totalCount).toBe(11);
  });

  it("collapses identical values into a single bucket", () => {
    const h = histogram([7, 7, 7], 10);
    expect(h).toHaveLength(1);
    expect(h[0].count).toBe(3);
  });

  it("handles empty input", () => {
    expect(histogram([], 10)).toEqual([]);
  });

  it("filters non-finite values", () => {
    const h = histogram([1, 2, NaN, Infinity, 3], 3);
    const totalCount = h.reduce((s, b) => s + b.count, 0);
    expect(totalCount).toBe(3);
  });
});

describe("median", () => {
  it("returns the middle of an odd-length array", () => {
    expect(median([1, 3, 5])).toBe(3);
    expect(median([5, 1, 3])).toBe(3);
  });

  it("averages the middle two of an even-length array", () => {
    expect(median([1, 3])).toBe(2);
    expect(median([1, 2, 3, 4])).toBe(2.5);
  });

  it("returns null for empty/all-non-finite input", () => {
    expect(median([])).toBeNull();
    expect(median([NaN, Infinity])).toBeNull();
  });
});
