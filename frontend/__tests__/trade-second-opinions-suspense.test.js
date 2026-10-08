/**
 * /trade "Second opinions" lazy panels — one Suspense boundary PER panel.
 *
 * They moved from next/dynamic to React.lazy for the /trade bundle budget
 * (#1698). next/dynamic gave every panel its own loading boundary; a single
 * shared <Suspense> around the block would blank ALL of them whenever one
 * suspends — e.g. MultiTradeFlow mounting for the first time when a third
 * side is added. Pin the per-panel shape.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const src = fs.readFileSync(path.resolve(__dirname, "../app/trade/page.jsx"), "utf8");

describe("/trade Second opinions lazy panels", () => {
  it("do not use next/dynamic (its loadable runtime breaks the /trade budget)", () => {
    expect(src).not.toMatch(/from "next\/dynamic"/);
  });

  it("wrap each lazy panel in its own Suspense boundary inside `dyn`", () => {
    const dyn = src.slice(src.indexOf("const dyn ="), src.indexOf("const TradeSourceBreakdown"));
    expect(dyn).toMatch(/lazy\(loader\)/);
    expect(dyn).toMatch(/<Suspense fallback=\{null\}>/);
  });

  it("do not share one boundary across the whole Second opinions block", () => {
    const start = src.indexOf('title="Second opinions"');
    const block = src.slice(start, src.indexOf("</CollapsiblePanel>", start));
    expect(start).toBeGreaterThan(0);
    expect(block).not.toMatch(/<Suspense\b/);
  });
});
