import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Owner decision 2026-09-29: the draft-capital stack effect is shown as a
// labelled, not-calibrated note and is NOT part of side totals, the
// verdict, side flows or balancer suggestions -- until it is rebuilt as an
// adjustment scoped to the moved picks' own value (#1527 audit: it
// dominated whole packages through data seams, not through the trade).
const page = readFileSync(resolve(__dirname, "../app/trade/page.jsx"), "utf8");

function callArgs(src, fn) {
  const out = [];
  let i = src.indexOf(`${fn}(`);
  while (i !== -1) {
    let depth = 0;
    let j = i + fn.length;
    for (; j < src.length; j++) {
      if (src[j] === "(") depth++;
      else if (src[j] === ")" && --depth === 0) break;
    }
    out.push(src.slice(i, j + 1));
    i = src.indexOf(`${fn}(`, j);
  }
  return out;
}

describe("/trade: the stack effect is withdrawn from the verdict", () => {
  for (const fn of [
    "adjustedSideTotals",
    "multiAdjustedSideTotals",
    "computeSideFlows",
    "findBalancers",
    "tradeImbalance",
    "tradeGapAdjusted",
  ]) {
    it(`${fn} never receives the stack context`, () => {
      for (const call of callArgs(page, fn)) {
        expect(call).not.toMatch(/stackContext/);
      }
    });
  }

  it("the stack effect is still computed for the labelled note", () => {
    expect(page).toMatch(/computeStackAdjustments\(sidesWithOverrides\.length, stackContext\)/);
    expect(page).toMatch(/not calibrated — not included in the totals or/);
  });
});
