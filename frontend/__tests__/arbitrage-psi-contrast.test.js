// /arbitrage tool views wear `.psi-editorial` inside the terminal-themed page.
// The scope redefines the semantic tokens but does not repaint the element, so
// each view must paint its own editorial canvas — otherwise editorial ink
// (#1c1712) lands on the terminal Panel (#131519) at ~1:1.  axe caught exactly
// that on CI (a11y-axe.spec.js, /arbitrage, color-contrast) once Golden
// Upgrades became the default view (owner directive 2026-10-18).
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(root, p), "utf8");

function psiTokens() {
  const css = read("app/tokens.css");
  const start = css.indexOf(".psi-editorial {");
  const block = css.slice(start, css.indexOf("\n}", start));
  const out = {};
  for (const m of block.matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2];
  return out;
}

function luminance(hex) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const VIEWS = [
  ["GoldenUpgradesView.jsx", "golden-upgrades.module.css"],
  ["BestOffersView.jsx", "best-offers.module.css"],
  ["PackageBuilderView.jsx", "package-builder.module.css"],
  ["TradeDeskView.jsx", "trade-desk.module.css"],
];

describe("/arbitrage PSI tool views paint their own canvas", () => {
  it.each(VIEWS)("%s: a psi-editorial view sets an editorial background and ink", (jsx, css) => {
    expect(read(`app/arbitrage/${jsx}`)).toMatch(/styles\.view\} psi-editorial/);
    const rule = read(`app/arbitrage/${css}`).match(/\.view \{([^}]*)\}/)[1];
    expect(rule).toMatch(/background:\s*var\(--surface-1\)/);
    expect(rule).toMatch(/color:\s*var\(--text-primary\)/);
  });

  it("every editorial text token clears WCAG AA on that canvas", () => {
    const t = psiTokens();
    for (const name of ["--text-primary", "--text-secondary", "--text-tertiary", "--accent"]) {
      expect(ratio(t[name], t["--surface-1"]), name).toBeGreaterThanOrEqual(4.5);
    }
  });
});
