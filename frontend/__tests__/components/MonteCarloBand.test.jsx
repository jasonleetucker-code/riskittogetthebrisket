/**
 * The Monte Carlo band the UI posts, and where it says it came from.
 *
 * WHY THIS EXISTS
 * ===============
 * `_payloadFromSides` builds the ONLY band any live simulation ever
 * sees. Measured on the pinned 2026-07-30 contract, **0 of 1093** rows
 * carry a stamped `valueBand`, so every asset takes the synthesized
 * ±15% branch — and this function had no test at all. The least-tested
 * number in the simulator was also the most load-bearing one.
 *
 * Worse, both branches post under the same `valueBand` key, so the
 * backend could not tell a measured interval from a constant, while
 * labelling every result `consensus_based_win_rate` and rendering a
 * disclaimer describing "the sources' consensus distribution". Nothing
 * on either side of the wire was capable of contradicting that.
 *
 * The fix is a declared `bandSource` per asset, tallied by the backend
 * into `bandSources` and surfaced in the disclaimer. This file guards
 * the frontend half; `tests/trade/test_monte_carlo_band_integrity.py`
 * guards the backend half.
 */
import { describe, it, expect, vi } from "vitest";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));
vi.mock("@/lib/trade-logic", () => ({
  effectiveValue: (row) => row?.rankDerivedValue ?? 0,
}));

const { _payloadFromSides } = await import("@/components/ui/MonteCarloButton");

const sidesWith = (a, b = []) => [{ assets: a }, { assets: b }];

describe("_payloadFromSides — band provenance", () => {
  it("labels a synthesized band as synthesized", () => {
    const out = _payloadFromSides(
      sidesWith([{ name: "Josh Allen", rankDerivedValue: 9988 }]),
      "full",
      {},
    );
    expect(out.sideA[0].bandSource).toBe("synthetic_flat_15pct");
  });

  it("still synthesizes ±15% — the width itself is unchanged here", () => {
    // Non-vacuity for the label above: it must describe what was
    // actually built, not a string chosen independently of it.
    const out = _payloadFromSides(
      sidesWith([{ name: "Josh Allen", rankDerivedValue: 1000 }]),
      "full",
      {},
    );
    const { p10, p50, p90 } = out.sideA[0].valueBand;
    expect([p10, p50, p90]).toEqual([850, 1000, 1150]);
  });

  it("labels a row-carried band as stamped, and only then", () => {
    const out = _payloadFromSides(
      sidesWith([
        {
          name: "Someone",
          rankDerivedValue: 5000,
          valueBand: { p10: 4000, p50: 5000, p90: 6000 },
        },
      ]),
      "full",
      {},
    );
    expect(out.sideA[0].bandSource).toBe("stamped_value_band");
  });

  it("does not clamp the posted p90 at the board's 9999 ceiling", () => {
    // 9999 is where the BOARD's normalization tops out, not a bound on
    // a quantile. The backend used to clamp it and mark the top 12
    // assets down by up to 520 points; the UI must not reintroduce the
    // same truncation one hop earlier.
    const out = _payloadFromSides(
      sidesWith([{ name: "Josh Allen", rankDerivedValue: 9988 }]),
      "full",
      {},
    );
    expect(out.sideA[0].valueBand.p90).toBe(11486);
  });

  it("every asset on both sides carries a declaration", () => {
    // An undeclared band reaches the backend as `unknown` rather than
    // being assumed measured — correct, but it would silently drop the
    // disclaimer's honesty for that asset, so nothing here may omit it.
    const out = _payloadFromSides(
      sidesWith(
        [{ name: "A", rankDerivedValue: 100 }, { name: "B", rankDerivedValue: 200 }],
        [{ name: "C", rankDerivedValue: 300 }],
      ),
      "full",
      {},
    );
    const all = [...out.sideA, ...out.sideB];
    expect(all).toHaveLength(3);
    for (const asset of all) {
      expect(["synthetic_flat_15pct", "stamped_value_band"]).toContain(asset.bandSource);
    }
  });
});
