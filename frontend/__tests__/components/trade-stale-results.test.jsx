/**
 * TC-A / UX audit P0-2 — expensive trade results never outlive the trade
 * they were computed for, and an older response never overwrites a newer
 * one.
 *
 * Before: Simulate impact and Monte Carlo kept their results across every
 * trade edit and Clear Trade, with no request sequencing.  Measured on
 * /trade: after adding Breece Hall to Side B the meter read "LOPSIDED, Side B
 * 46% more" while MC still said "Side A's package is probably worth more" (copy since relabelled)
 * and the simulation still said "CHANGE −353".
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));

const { useTradeSimulator } = await import("@/components/useTradeSimulator");
const { default: MonteCarloButton } = await import("@/components/ui/MonteCarloButton");
const { tradeSignature } = await import("@/lib/trade-logic");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function deferredFetch() {
  const pending = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(
    () =>
      new Promise((resolve) => {
        pending.push((data) => resolve({ ok: true, status: 200, json: async () => data }));
      }),
  );
  return pending;
}

describe("useTradeSimulator request sequencing", () => {
  it("an older response arriving last never overwrites the newer trade's result", async () => {
    const pending = deferredFetch();
    const { result } = renderHook(() => useTradeSimulator());
    let p1;
    let p2;
    act(() => {
      p1 = result.current.simulate({ playersIn: ["Old"] }, { signature: "old" });
      p2 = result.current.simulate({ playersIn: ["New"] }, { signature: "new" });
    });
    await act(async () => {
      pending[1]({ answer: "new" });
      await p2;
    });
    await act(async () => {
      pending[0]({ answer: "old" });
      await p1;
    });
    expect(result.current.result).toEqual({ answer: "new" });
    expect(result.current.signature).toBe("new");
  });

  it("reset() (Clear Trade, any edit) drops a response still in flight", async () => {
    const pending = deferredFetch();
    const { result } = renderHook(() => useTradeSimulator());
    let p;
    act(() => {
      p = result.current.simulate({ playersIn: ["X"] }, { signature: "x" });
    });
    act(() => result.current.reset());
    await act(async () => {
      pending[0]({ answer: "late" });
      await p;
    });
    expect(result.current.result).toBeNull();
  });
});

describe("tradeSignature", () => {
  const side = (assets, destinations = {}) => ({ assets, destinations });
  it("changes on every edit that changes the trade", () => {
    const base = [side([{ name: "A" }]), side([{ name: "B" }])];
    const sig = tradeSignature(base);
    expect(tradeSignature([side([{ name: "A" }]), side([{ name: "B" }])])).toBe(sig);
    expect(tradeSignature([side([{ name: "A" }]), side([{ name: "B" }, { name: "C" }])])).not.toBe(sig);
    expect(tradeSignature([side([]), side([])])).not.toBe(sig);
    expect(tradeSignature([side([{ name: "A", customValue: 9000 }]), side([{ name: "B" }])])).not.toBe(sig);
    expect(tradeSignature([side([{ name: "A", assetId: "pick:x" }]), side([{ name: "B" }])])).not.toBe(sig);
  });
});

describe("Monte Carlo result is keyed to its trade", () => {
  const row = (name, v) => ({ name, rankDerivedValue: v, values: { full: v }, pos: "WR" });
  const sides = (a, b) => [
    { label: "A", assets: a },
    { label: "B", assets: b },
  ];

  it("hides a result once the trade changes and says to re-run", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ winProbA: 0.64, nSims: 40000, meanDelta: 400, deltaRange: {} }),
    });
    const before = sides([row("Pickens", 6052)], [row("Kyren", 5699)]);
    const { rerender } = render(<MonteCarloButton sides={before} sidesSend />);
    fireEvent.click(screen.getByRole("button", { name: /Simulate/ }));
    await screen.findByText(/package came out bigger/);

    rerender(
      <MonteCarloButton
        sides={sides([row("Pickens", 6052)], [row("Kyren", 5699), row("Breece", 4912)])}
        sidesSend
      />,
    );
    expect(screen.queryByText(/package came out bigger/)).toBeNull();
    expect(screen.getByTestId("mc-stale").textContent).toMatch(/run it again/);

    // Back to the exact trade it answered: the result is valid again.
    rerender(<MonteCarloButton sides={before} sidesSend />);
    expect(screen.getByText(/package came out bigger/)).toBeTruthy();
  });
});

describe("/trade wiring", () => {
  it("renders Simulate impact only for the trade it answered, and resets on any change", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    expect(src).toMatch(/simResultSignature === simSignature/);
    expect(src).toMatch(/useEffect\(\(\) => \{\s*resetSim\(\);\s*\}, \[simSignature, resetSim\]\)/);
    expect(src).toMatch(/\{ signature: simSignature \}/);
  });
});
