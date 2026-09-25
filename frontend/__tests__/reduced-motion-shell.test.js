/**
 * Reduced-motion contract for decorative shell animation.
 *
 * Found by tests/e2e/specs/psi-rankings-player-a11y.spec.js on the populated
 * /rankings board under `prefers-reduced-motion: reduce`: the team picker's
 * "needs selection" pulse (`team-switcher-pulse`, 2s, infinite) kept running
 * in the shell of every private route. Motion tokens already collapse to 0ms
 * under reduced motion (tokens.css), but this keyframe animation never read
 * them. The browser spec measures it on real pages; this pins the CSS in the
 * fast suite so the override cannot be deleted without a red test.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const GLOBALS_CSS = fs.readFileSync(path.resolve(__dirname, "..", "app/globals.css"), "utf8");

/** Bodies of every `@media (prefers-reduced-motion: reduce) { … }` block. */
function reducedMotionBlocks(css) {
  const blocks = [];
  const re = /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{/g;
  let m;
  while ((m = re.exec(css))) {
    let depth = 1;
    let i = re.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth += 1;
      else if (css[i] === "}") depth -= 1;
      i += 1;
    }
    blocks.push(css.slice(re.lastIndex, i - 1));
  }
  return blocks;
}

describe("shell animation respects prefers-reduced-motion", () => {
  it("the team-switcher pulse is an infinite animation (the premise of this test)", () => {
    expect(GLOBALS_CSS).toMatch(/animation:\s*team-switcher-pulse[^;]*infinite/);
  });

  it("stops the team-switcher pulse under reduced motion", () => {
    const override = reducedMotionBlocks(GLOBALS_CSS).find((body) =>
      /\.team-switcher--needs\s+\.team-switcher-toggle\s*\{[^}]*animation:\s*none/.test(body),
    );
    expect(override, "a reduced-motion block must set animation: none on the pulsing toggle").toBeTruthy();
  });
});
