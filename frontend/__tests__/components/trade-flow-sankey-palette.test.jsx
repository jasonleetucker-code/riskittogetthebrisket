// Owner Decision 14 approved a SIX-slot categorical palette.  The trade-flow
// Sankey draws one node per team, so a 13-team league must render exactly
// the colours it rendered before (no grey fold, no token repaint) until a
// >6-category fold design is approved; a league of at most six teams takes
// the --chart-1..6 slots in fixed order.
import React from "react";
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import TradeFlowSankey from "@/components/graphs/TradeFlowSankey";

const PRE_D14_PALETTE = [
  "#38bdf8", "#f472b6", "#a3e635", "#fb923c", "#c084fc",
  "#14b8a6", "#fbbf24", "#f87171", "#60a5fa", "#4ade80",
  "#e879f9", "#fb7185",
];

function ringOfTrades(n) {
  const ids = Array.from({ length: n }, (_, i) => `o${String(i).padStart(2, "0")}`);
  return ids.map((id, i) => ({
    sides: [
      { ownerId: id, displayName: `Team ${i}`, receivedAssets: [{ kind: "player", playerName: `P${i}` }] },
      { ownerId: ids[(i + 1) % n], displayName: `Team ${(i + 1) % n}`, receivedAssets: [{ kind: "player", playerName: `Q${i}` }] },
    ],
  }));
}

function nodeFills(container) {
  return [...container.querySelectorAll('rect[width="10"]')].map((r) => r.getAttribute("fill"));
}

describe("TradeFlowSankey node colours", () => {
  it("13 teams: identical to the pre-D14 palette, cycled as before", () => {
    const { container } = render(<TradeFlowSankey trades={ringOfTrades(13)} />);
    const fills = nodeFills(container);
    expect(fills).toHaveLength(26); // a source and a target node per team
    const expected = Array.from({ length: 13 }, (_, i) => PRE_D14_PALETTE[i % 12]);
    expect(fills.slice(0, 13)).toEqual(expected);
    expect(fills.slice(13)).toEqual(expected);
    expect(fills.some((f) => f.includes("--text-tertiary"))).toBe(false);
  });

  it("6 teams: the --chart-1..6 slots in fixed order", () => {
    const { container } = render(<TradeFlowSankey trades={ringOfTrades(6)} />);
    const expected = [1, 2, 3, 4, 5, 6].map((i) => `var(--chart-${i})`);
    expect(nodeFills(container).slice(0, 6)).toEqual(expected);
  });
});
