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
      /Value-uncertainty check \(assumed ±15% range\) — not the chance the trade works out/,
    );
    const body = document.body.textContent;
    expect(body).toMatch(/assumption, not a measurement/);
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

  it("drops the assumed-range wording when every band is measured", async () => {
    mockResult({ bandSources: { stamped_value_band: 2 } });
    await run();
    expect(screen.getByTestId("mc-scope-note").textContent).not.toMatch(/assumed/);
  });
});
