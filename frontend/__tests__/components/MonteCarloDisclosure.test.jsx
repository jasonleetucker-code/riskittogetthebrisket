/**
 * Monte Carlo — what the result is allowed to claim (#790 audit, 2026-09-26).
 *
 * Measured on the live board: 0 of 1,126 rows carry a stamped value band,
 * so every run uses an assumed ±15% range. The UI said it sampled "our 6+
 * ranking sources' disagreement range" — false — and the symmetrized
 * endpoint dropped the backend's own "synthesized band" disclosure. An
 * unpriced asset was also simulated as a 0/0/0 band: missing as zero.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));
vi.mock("@/lib/trade-logic", () => ({
  effectiveValue: (row) => row?.rankDerivedValue ?? 0,
}));

const { default: MonteCarloButton, _payloadFromSides } = await import(
  "@/components/ui/MonteCarloButton"
);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const sides = (a, b) => [
  { label: "A", assets: a },
  { label: "B", assets: b },
];

describe("an unpriced asset is refused, never simulated as zero", () => {
  it("is named and left out of the payload", () => {
    const out = _payloadFromSides(
      sides([{ name: "Priced", rankDerivedValue: 5000 }], [{ name: "Ghost", rankDerivedValue: null }]),
      "full",
      {},
    );
    expect(out.unpriced).toEqual(["Ghost"]);
    expect(out.sideB).toEqual([]);
  });

  it("the button does not call the simulator and says why", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(
      <MonteCarloButton
        sides={sides([{ name: "Priced", rankDerivedValue: 5000 }], [{ name: "Ghost" }])}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Simulate/ }));
    await screen.findByText(/Can't simulate: Ghost has no value on the board/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("the result states what it is", () => {
  function mockResult(extra) {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        winProbA: 0.82,
        winProbB: 0.18,
        meanDelta: 900,
        deltaRange: { p10: 100, p50: 900, p90: 1700 },
        nSims: 40000,
        bandSources: { synthetic_flat_15pct: 2 },
        vaAdjustment: { side: 1, value: 0, effectiveValue: 0, applied: false },
        ...extra,
      }),
    });
  }

  async function run() {
    render(
      <MonteCarloButton
        sides={sides([{ name: "A1", rankDerivedValue: 6000 }], [{ name: "B1", rankDerivedValue: 5000 }])}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Simulate/ }));
    await waitFor(() => screen.getByTestId("mc-scope-note"));
  }

  it("names the assumed band and never claims to sample source disagreement", async () => {
    mockResult();
    await run();
    expect(screen.getByTestId("mc-scope-note").textContent).toMatch(
      /Assumed ±15% range, not measured — not the chance the trade works out/,
    );
    const body = document.body.textContent;
    expect(body).toMatch(/Illustrative sensitivity only/);
    expect(body).toMatch(/not a probability and is not calibrated/);
    // ODR-SR-MC-WINRATE: no percentage-of-simulations / winner framing.
    expect(body).not.toMatch(/\d+%\s+of/);
    expect(body).not.toMatch(/\b(won|wins|winner|favou?red|coin flip|came out ahead)\b/i);
    expect(body).not.toMatch(/82%|18%/);
    expect(body).not.toMatch(/ranking sources don't fully/);
    expect(body).not.toMatch(/disagreement range/);
  });

  it("says when the package adjustment moved the result", async () => {
    mockResult({ vaAdjustment: { side: 1, value: 1234, effectiveValue: 1234, applied: true } });
    await run();
    expect(document.body.textContent).toMatch(
      /includes our package adjustment: \+1,234 to Side A/,
    );
  });

  it("labels a package-adjusted gap as adjusted, beside the adjustment it includes", async () => {
    mockResult({ vaAdjustment: { side: 1, value: 1234, effectiveValue: 1234, applied: true } });
    await run();
    const body = document.body.textContent;
    expect(body).toMatch(/Side A's package-adjusted total was 900 points bigger\. It includes our package adjustment/);
  });

  it("calls the gap a plain total only when no adjustment was applied", async () => {
    mockResult();
    await run();
    const body = document.body.textContent;
    expect(body).toMatch(/Side A's total was 900 points bigger/);
    expect(body).not.toMatch(/package-adjusted/);
  });

  it("drops the assumed-range wording when every band is measured", async () => {
    mockResult({ bandSources: { stamped_value_band: 2 } });
    await run();
    expect(screen.getByTestId("mc-scope-note").textContent).not.toMatch(/assumed/i);
    // The measured path keeps the existing share-of-simulations framing.
    expect(document.body.textContent).toMatch(/82% of 40,000 simulations/);
  });

  it("any synthetic asset in a mixed run gates the percentage off", async () => {
    mockResult({ bandSources: { stamped_value_band: 1, synthetic_flat_15pct: 1 } });
    await run();
    expect(document.body.textContent).toMatch(/Illustrative sensitivity only/);
    expect(document.body.textContent).not.toMatch(/82%/);
  });

  it("fails closed when the response does not report band sources", async () => {
    mockResult({ bandSources: undefined });
    await run();
    expect(document.body.textContent).toMatch(/Illustrative sensitivity only/);
    expect(document.body.textContent).not.toMatch(/82%/);
  });
});

// Owner Priority 12 (2026-11-08): `valueUncertainty` says no empirically
// calibrated band exists.  The 10th/90th `deltaRange` is then ILLUSTRATIVE
// (it comes from the band named by `bandBasis`), and the win share stays a
// simulation fraction.  Absent on older payloads: rendering is unchanged.
describe("valueUncertainty unavailable — the range is illustrative", () => {
  const UNAVAILABLE = (bandBasis) => ({
    state: "unavailable",
    reason: "no_empirically_calibrated_band",
    bandBasis,
    horizonDays: null,
    calibratedIntervals: null,
    evidence: "docs/valuation/TRADE_UNCERTAINTY_STUDY_2026-11-08.md",
  });

  function mockResult(extra) {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        winProbA: 0.82,
        winProbB: 0.18,
        meanDelta: 900,
        deltaRange: { p10: -1250.4, p50: 900, p90: 1700 },
        nSims: 40000,
        bandSources: { synthetic_flat_15pct: 2 },
        labelHint: "consensus_based_win_rate",
        vaAdjustment: { side: 1, value: 0, effectiveValue: 0, applied: false },
        ...extra,
      }),
    });
  }

  async function run() {
    render(
      <MonteCarloButton
        sides={sides([{ name: "A1", rankDerivedValue: 6000 }], [{ name: "B1", rankDerivedValue: 5000 }])}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Simulate/ }));
    await waitFor(() => screen.getByTestId("mc-scope-note"));
  }

  it("labels the 10th/90th range as illustrative from the assumed band", async () => {
    mockResult({ valueUncertainty: UNAVAILABLE("assumed_flat_15pct") });
    await run();
    expect(screen.getByTestId("mc-range-illustrative").textContent).toBe(
      "Illustrative 10th–90th percentile gap (Side A minus Side B): −1,250 to +1,700 points, from an assumed ±15% band, not measured.",
    );
    expect(screen.getByTestId("mc-uncertainty-unavailable").textContent).toMatch(
      /No measured uncertainty band exists yet/,
    );
    // Still the sensitivity framing: no percentage, no winner.
    const body = document.body.textContent;
    expect(body).toMatch(/Illustrative sensitivity only/);
    expect(body).not.toMatch(/82%|18%/);
    expect(body).not.toMatch(/acceptance|chance (?:a|the) manager/i);
  });

  it("keeps the measured-band win share as a simulation fraction, and names the bands uncalibrated", async () => {
    mockResult({
      bandSources: { stamped_value_band: 2 },
      valueUncertainty: UNAVAILABLE("stamped_value_band_uncalibrated"),
    });
    await run();
    const body = document.body.textContent;
    expect(body).toMatch(/82% of 40,000 simulations/);
    expect(screen.getByTestId("mc-scope-note").textContent).toBe(
      "Share of simulations on uncalibrated ranges — not the chance the trade works out.",
    );
    expect(screen.getByTestId("mc-range-illustrative").textContent).toMatch(
      /from value bands that have not been calibrated, not measured\./,
    );
    // The qualitative range line no longer reads as measured uncertainty.
    expect(body).toMatch(/across this illustrative range/);
    expect(body).not.toMatch(/high uncertainty|result is consistent across simulations/);
    expect(body).toMatch(/They are not calibrated, so that count is a share of simulations only/);
  });

  it("names the range a package-adjusted gap when the adjustment was applied", async () => {
    mockResult({
      valueUncertainty: UNAVAILABLE("assumed_flat_15pct"),
      vaAdjustment: { side: 1, value: 1234, effectiveValue: 1234, applied: true },
    });
    await run();
    expect(screen.getByTestId("mc-range-illustrative").textContent).toMatch(
      /^Illustrative 10th–90th percentile package-adjusted gap \(Side A minus Side B\)/,
    );
    // The delta line uses the same condition.
    expect(document.body.textContent).toMatch(/package-adjusted total/);
  });

  it("calls it a plain gap when no adjustment was applied", async () => {
    mockResult({ valueUncertainty: UNAVAILABLE("assumed_flat_15pct") });
    await run();
    expect(screen.getByTestId("mc-range-illustrative").textContent).not.toMatch(/package-adjusted/);
  });

  it("an unreported band basis is said, not guessed", async () => {
    mockResult({ valueUncertainty: UNAVAILABLE("unknown") });
    await run();
    expect(screen.getByTestId("mc-range-illustrative").textContent).toMatch(
      /from a band whose basis was not reported, not measured\./,
    );
  });

  it("a missing p10/p90 shows no range numbers — never 0", async () => {
    mockResult({
      deltaRange: { p50: 900 },
      valueUncertainty: UNAVAILABLE("assumed_flat_15pct"),
    });
    await run();
    expect(screen.queryByTestId("mc-range-illustrative")).toBeNull();
    const note = screen.getByTestId("mc-uncertainty-unavailable").textContent;
    expect(note).toMatch(/No measured uncertainty band exists yet/);
    expect(note).not.toMatch(/\b0\b/);
  });

  it("absent valueUncertainty (older payload) renders exactly as before", async () => {
    mockResult({ bandSources: { stamped_value_band: 2 } });
    await run();
    expect(screen.queryByTestId("mc-uncertainty-unavailable")).toBeNull();
    expect(screen.queryByTestId("mc-range-illustrative")).toBeNull();
    expect(screen.getByTestId("mc-scope-note").textContent).toBe(
      "Value-uncertainty check — not the chance the trade works out.",
    );
    expect(document.body.textContent).toMatch(/Range of outcomes is narrow|Moderate range|Wide range/);
  });

  it("_valueUncertaintyNote is null unless the state is unavailable", async () => {
    const { _valueUncertaintyNote } = await import("@/components/ui/MonteCarloButton");
    expect(_valueUncertaintyNote({})).toBeNull();
    expect(_valueUncertaintyNote({ valueUncertainty: null })).toBeNull();
    expect(_valueUncertaintyNote({ valueUncertainty: { state: "available" } })).toBeNull();
    const n = _valueUncertaintyNote({
      valueUncertainty: UNAVAILABLE("assumed_flat_15pct"),
      deltaRange: { p10: 0, p90: 12 },
    });
    // A real (computed) zero is a value, shown as such; only MISSING is withheld.
    expect(n.rangeLine).toMatch(/: 0 to \+12 points/);
  });
});
