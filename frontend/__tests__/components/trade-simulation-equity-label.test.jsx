/**
 * TC-A — the Simulate-impact panel labels its equity as RAW (before Value
 * Adjustment), never as "KTC" equity or an unqualified "Equity" beside the
 * meter's adjusted gap.
 */
import { describe, it, expect, afterEach } from "vitest";
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { SimulationPanel } from "@/app/trade/trade-simulation-panel";

afterEach(cleanup);

describe("Simulate impact equity basis", () => {
  it("names raw equity and its basis", () => {
    render(
      <SimulationPanel
        simResult={{
          team: { name: "Jason" },
          delta: {},
          before: {},
          after: {},
          equity: 5817,
          teamImpact: {
            verdict: "lean decline",
            compositeScore: -9.1,
            fitScore: -20,
            equityScore: 12,
            rationale: ["Net raw equity +5817 (before Value Adjustment)"],
          },
        }}
        onReset={() => {}}
      />,
    );
    expect(screen.getByText("Raw equity")).toBeTruthy();
    expect(screen.getByText(/Raw equity \(receiving − sending, before Value Adjustment\)/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/KTC equity/);
  });
});
