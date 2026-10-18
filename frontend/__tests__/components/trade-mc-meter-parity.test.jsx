/**
 * TC-A / UX audit P0-1 — the Monte Carlo panel and the meter it sits inside
 * must simulate the SAME per-asset values.
 *
 * The meter's totals are built from `sidesWithOverrides` (a user override
 * replaces the board value for that line).  The Monte Carlo panel received
 * the page's raw `sides`, so with an override in play the meter graded one
 * trade and the simulation another.  The backend half (the per-asset 9999
 * clamp that absorbed most of a package adjustment) is pinned by
 * `tests/trade/test_monte_carlo_meter_parity.py`.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi } from "vitest";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));

const { _payloadFromSides } = await import("@/components/ui/MonteCarloButton");
const { adjustedSideTotals } = await import("@/lib/trade-logic");

const row = (name, full, extra = {}) => ({
  name,
  pos: "WR",
  team: "XXX",
  values: { full },
  rankDerivedValue: full,
  ...extra,
});

describe("Monte Carlo simulates the meter's values", () => {
  it("centres every asset on the value the meter sums, overrides included", () => {
    const sideA = [row("Elite", 9961, { customValue: 9500 }), row("Second", 4730)];
    const sideB = [row("One", 5814), row("Two", 4912), row("Three", 3410)];
    const { sideA: mcA, sideB: mcB, unpriced } = _payloadFromSides(
      [{ assets: sideA }, { assets: sideB }],
      "full",
      {},
    );
    expect(unpriced).toEqual([]);
    const [a, b] = adjustedSideTotals(sideA, sideB, "full", {});
    expect(mcA.reduce((s, x) => s + x.valueBand.p50, 0)).toBe(a.raw);
    expect(mcB.reduce((s, x) => s + x.valueBand.p50, 0)).toBe(b.raw);
    expect(mcA[0].valueBand.p50).toBe(9500);
  });

  it("the /trade page hands the meter (and so the MC panel) the overridden sides", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../../app/trade/page.jsx"),
      "utf8",
    );
    const meter = src.slice(src.indexOf("<TradeMeter"), src.indexOf("/>", src.indexOf("<TradeMeter")));
    expect(meter).toMatch(/sides=\{sidesWithOverrides\}/);
  });
});
