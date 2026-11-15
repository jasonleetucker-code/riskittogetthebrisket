// ODR-SR-ARBITRAGE (owner decision 2026-11-06): user-facing copy for the
// board-vs-market finder says "disagreement", not "arbitrage", until a
// convergence test proves an edge.  URL, API routes, field names, CSS module
// names and test ids stay stable.
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { pageTitleFor } from "@/lib/nav-model";
import { CANON } from "./helpers/naming-canon";

const page = fs.readFileSync(
  path.join(__dirname, "..", "app", "arbitrage", "page.jsx"),
  "utf8",
);
const nextActions = fs.readFileSync(
  path.join(__dirname, "..", "components", "trade", "TradeNextActions.jsx"),
  "utf8",
);

describe("/arbitrage user-facing naming", () => {
  it("keeps the route but names it Market Disagreement everywhere", () => {
    expect(CANON["/arbitrage"]).toBe("Market Disagreement");
    expect(pageTitleFor("/arbitrage")).toBe("Market Disagreement");
    expect(page).toContain('title="Market Disagreement"');
  });

  it("card chip, empty state and signal options say disagreement", () => {
    expect(page).toMatch(/disagreement \{Number\(trade\.arbitrageScore/);
    expect(page).toContain("No package disagreement found");
    expect(page).toContain("Buy disagreement</option>");
    expect(page).toContain("Sell disagreement</option>");
  });

  it("no visible JSX string still says arbitrage (identifiers are exempt)", () => {
    const visible = page
      .split("\n")
      .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
      .filter((l) => /(>[^<{]*[Aa]rbitrage|title="[^"]*[Aa]rbitrage|"[A-Z][^"]*[Aa]rbitrage)/.test(l))
      .filter((l) => !/arbitrage-trade-card|surface:|__arbitrage|buildArbitrageRows/.test(l));
    expect(visible).toEqual([]);
  });

  // Owner directive 2026-11-07 Part 5: a board-vs-market gap is disagreement,
  // not proof the market is wrong — no copy may assert mispricing or a
  // "hidden surplus" without validated convergence evidence.
  it("never asserts the market is wrong or that the gap is surplus", () => {
    for (const src of [page, nextActions]) {
      expect(src).not.toMatch(/markets? undervalue/);
      expect(src).not.toMatch(/Hidden surplus/);
    }
    expect(page).toContain('"Board − market"');
    expect(page).toContain("A disagreement is not proof the market is wrong.");
    expect(nextActions).toContain("Same-position upgrades your league's markets price below our board.");
  });
});
