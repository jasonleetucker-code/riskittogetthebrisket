/**
 * `.card` renders on design tokens, not a hardcoded gradient (R5 step 1).
 *
 * `.card` still has ~48 consumers after R2-R4, 86 of them in /league and
 * /league-comparison. It can't be deleted — only migrated, page by page —
 * so until that finishes it has to at least render in the same palette as
 * everything around it. Its old rule was a pre-redesign navy gradient,
 * which made those pages the only ones still in the old blue, one nav
 * click from redesigned surfaces.
 *
 * This pins the de-seam so it can't silently revert while the structural
 * migration is still in progress, and so `.card` and `.ds-panel` can't
 * drift apart into two different-looking box treatments.
 *
 * See docs/redesign/R5-PANEL-CSS-PURGE.md §7.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (p) =>
  fs
    .readFileSync(path.resolve(__dirname, p), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");

const GLOBALS = read("../app/globals.css");
const DS = read("../app/ds.css");

/** Body of the first top-level rule whose selector is exactly `sel`. */
function ruleBody(css, sel) {
  const re = new RegExp(
    `(^|[}\\s])${sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`,
    "m",
  );
  const m = css.match(re);
  return m ? m[2] : null;
}

const card = ruleBody(GLOBALS, ".card");
const panel = ruleBody(DS, ".ds-panel");

describe(".card surface", () => {
  it("exists as a top-level rule", () => {
    expect(card, ".card rule not found in globals.css").toBeTruthy();
    expect(panel, ".ds-panel rule not found in ds.css").toBeTruthy();
  });

  it("uses no gradient", () => {
    // The specific thing that made /league look like a different product.
    expect(card).not.toMatch(/gradient/i);
  });

  it("uses no raw colour literal", () => {
    // Catches a hex or rgb() creeping back in, which is how the old rule
    // was off-palette in the first place.
    expect(card).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(card).not.toMatch(/\brgba?\s*\(/i);
  });

  it("takes its background from the same token as .ds-panel", () => {
    const bg = (s) => (s.match(/(?:^|[;{\s])background\s*:\s*([^;]+)/) || [])[1];
    expect(bg(card)).toBeTruthy();
    expect(bg(card).trim()).toBe(bg(panel).trim());
  });

  it("takes its border colour from the same token as .ds-panel", () => {
    const token = (s) =>
      (s.match(/border\s*:\s*[^;]*?(var\(--[\w-]+\))/) || [])[1];
    expect(token(card)).toBeTruthy();
    expect(token(card)).toBe(token(panel));
  });
});

/**
 * The wider invariant `.card` was one instance of: no surface in
 * globals.css is painted with a hardcoded coloured gradient.
 *
 * The pre-redesign palette left five of these — `.card`, `.picker-sheet`,
 * `.sheet`, `.login-panel`, `.screenshot-fab` — all navy or purple, all
 * off-token. They were the last of the old look.
 *
 * The rule is deliberately not "no gradients": several legitimate ones
 * remain and should. A gradient is fine when it is either
 *   - built from design tokens (meter and progress fills), or
 *   - achromatic (skeleton shimmer, the diagonal texture fill),
 * because neither can drift away from the palette. What is banned is a
 * gradient carrying a hardcoded *colour* — a hex, or an rgb() whose
 * channels are not equal — since that is by definition outside the
 * token system.
 */
describe("globals.css gradients carry no hardcoded colour", () => {
  const gradients = [...GLOBALS.matchAll(/(?:repeating-)?linear-gradient\(([^;]*?)\)\s*(?:;|,\s*\n)/gs)]
    .map((m) => m[1]);

  it("finds the gradients (guards against a broken matcher)", () => {
    expect(gradients.length).toBeGreaterThanOrEqual(4);
  });

  it.each([
    ["hex literal", /#[0-9a-f]{3,8}\b/i],
  ])("uses no %s", (_label, pattern) => {
    const bad = gradients.filter((g) => pattern.test(g));
    expect(bad).toEqual([]);
  });

  it("uses no chromatic rgb()/rgba() literal", () => {
    // Achromatic (r === g === b) is allowed: shimmer and texture fills
    // are neutral by construction and cannot go off-palette.
    const bad = [];
    for (const g of gradients) {
      for (const m of g.matchAll(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/g)) {
        const [r, gr, b] = [m[1], m[2], m[3]].map(Number);
        if (!(r === gr && gr === b)) bad.push(m[0]);
      }
    }
    expect(bad).toEqual([]);
  });
});
