/**
 * /trade on-demand sections — kept out of the page's first-load chunk.
 *
 * The /trade page chunk sat at 92.8 KB against its 93 KB budget
 * (scripts/check-bundle-sizes.mjs) after release train #1709.  Three
 * sections that cannot be on screen at first render were split into their
 * own modules and loaded with React.lazy (2026-10-08):
 *
 *   - trade-simulation-panel.jsx — only after "Simulate impact" answers
 *   - trade-ktc-import.jsx       — only after "Import KTC" is pressed
 *   - trade-suggestions-desk.jsx — the foot of the page
 *
 * The split is undone silently by ONE static import: webpack puts a module
 * statically reachable from the page entry into the page chunk, whatever
 * else also imports it lazily.  The budget would catch it eventually, but
 * only once the page is over — these pins catch it at the line that does it.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = (rel) => fs.readFileSync(path.resolve(__dirname, "..", rel), "utf8");
const page = read("app/trade/page.jsx");
const sections = read("app/trade/trade-sections.jsx");

const ON_DEMAND = ["trade-simulation-panel", "trade-ktc-import", "trade-suggestions-desk"];

/** Static `import … from "./x"` / `export … from "./x"` of a module. */
const staticImportOf = (mod) =>
  new RegExp(`(?:import|export)\\b[^;]*?\\bfrom\\s*["']\\./${mod}["']`);

describe("/trade on-demand sections", () => {
  for (const mod of ON_DEMAND) {
    it(`page.jsx loads ./${mod} only through a dynamic import()`, () => {
      expect(page).not.toMatch(staticImportOf(mod));
      expect(page).toMatch(new RegExp(`import\\(\\s*["']\\./${mod}["']\\s*\\)`));
    });

    it(`trade-sections.jsx does not import or re-export ./${mod}`, () => {
      expect(sections).not.toMatch(staticImportOf(mod));
    });
  }

  it("the lazy sections go through `dyn` (one Suspense boundary each)", () => {
    for (const name of ["SimulationPanel", "KtcImportPanel", "SuggestionsDesk"]) {
      expect(page).toMatch(new RegExp(`const ${name} = dyn\\(`));
    }
  });

  it("each lazy section has its own reload-recovering error boundary inside `dyn`", () => {
    // A failed chunk load must not fall through to app/error.jsx (the whole
    // page); React.lazy caches the rejection, so recovery is a reload.
    const dyn = page.slice(page.indexOf("const dyn ="), page.indexOf("const TradeSourceBreakdown"));
    expect(dyn).toMatch(/<ResilientSection name=\{name\} recovery="reload">\s*<Suspense fallback=\{null\}>/);
  });

  it("SimulationPanel is gated on a result in the page, so its chunk is not requested on load", () => {
    expect(page).toMatch(/\{simResult \|\| simError \? \(\s*<SimulationPanel\b/);
  });

  it("KtcImportPanel renders only while the import row is open", () => {
    expect(page).toMatch(/\{ktcImportOpen \? \(\s*<KtcImportPanel\b/);
  });
});
