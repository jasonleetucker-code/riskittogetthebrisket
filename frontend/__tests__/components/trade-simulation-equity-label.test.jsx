/**
 * TC-A — the Simulate-impact panel labels its equity as RAW (before Value
 * Adjustment), never as "KTC" equity or an unqualified "Equity" beside the
 * meter's adjusted gap.  Owner decision 5 (2026-10-18): the panel renders NO
 * accept / decline verdict and no composite / equity score -- roster
 * information only, presented neutrally.
 */
import { describe, it, expect, afterEach } from "vitest";
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { SimulationPanel } from "@/app/trade/trade-simulation-panel";

afterEach(cleanup);

const SIM = {
  team: { name: "Jason" },
  delta: {},
  before: {},
  after: {},
  equity: 5817,
  teamImpact: {
    fitScore: -20,
    starterValueDelta: { TE: -1200 },
    starterDelta: { TE: -1 },
    rationale: ["Net raw equity +5817 (before Value Adjustment)"],
  },
};

describe("Simulate impact equity basis", () => {
  it("names raw equity and its basis", () => {
    render(<SimulationPanel simResult={SIM} onReset={() => {}} />);
    expect(screen.getByText(/Raw equity \(receiving − sending, before Value Adjustment\)/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/KTC equity/);
  });
});

describe("Simulate impact renders no competing verdict (owner decision 5)", () => {
  it("shows roster information, never accept / decline", () => {
    // A stale backend that still sends the retired fields must not resurrect them.
    render(
      <SimulationPanel
        simResult={{
          ...SIM,
          teamImpact: { ...SIM.teamImpact, verdict: "lean decline", compositeScore: -9.1, equityScore: 12 },
        }}
        onReset={() => {}}
      />,
    );
    const text = document.body.textContent;
    expect(text).not.toMatch(/lean decline|lean accept|\baccept\b|\bdecline\b/i);
    expect(text).not.toMatch(/-9\.1/);
    expect(screen.getByText("Roster fit")).toBeTruthy();
    expect(screen.getByTestId("simulation-roster-info-note").textContent).toMatch(
      /not a recommendation/,
    );
    expect(screen.getByText("Roster shape")).toBeTruthy();
    expect(screen.getByText("TE starter")).toBeTruthy();
  });

  it("no frontend module reads teamImpact.verdict or compositeScore", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const root = path.resolve(__dirname, "../..");
    const hits = [];
    const walk = (dir) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (["node_modules", ".next", "__tests__"].includes(e.name)) continue;
        const p = path.join(dir, e.name);
        if (e.isDirectory()) walk(p);
        else if (/\.(jsx?|tsx?)$/.test(e.name)) {
          const src = fs.readFileSync(p, "utf8");
          if (/\bti\.verdict\b|teamImpact\??\.verdict\b|ti\.compositeScore|ti\.equityScore/.test(src)) hits.push(p);
        }
      }
    };
    for (const d of ["app", "components", "lib"]) walk(path.join(root, d));
    expect(hits).toEqual([]);
  });
});
