/**
 * Task 10 — static guard for the coarse-pointer touch-target block at the end
 * of app/ds.css. jsdom cannot lay out CSS, so the geometry itself is asserted
 * in tests/e2e/specs/mobile-target-size.spec.js; this pins the contract that
 * block must keep: 44px on every primary control, in a coarse-pointer
 * condition that leaves fine-pointer (desktop) layout alone.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = fs.readFileSync(path.resolve(__dirname, "../../../app/ds.css"), "utf8");
const marker = css.indexOf("@media (pointer: coarse)");
const block = marker >= 0 ? css.slice(marker) : "";

function rule(selector) {
  const re = new RegExp(`${selector.replace(/[.\\[\\]]/g, "\\$&")}\\s*\\{([^}]*)\\}`);
  const m = block.match(re);
  return m ? m[1] : "";
}

describe("ds.css coarse-pointer touch targets", () => {
  it("exists, keyed on the PRIMARY pointer (not any-pointer)", () => {
    expect(marker).toBeGreaterThan(-1);
    expect(block.split("{")[0]).toContain("(pointer: coarse)");
    expect(block.split("{")[0]).not.toContain("any-pointer");
  });

  it.each([
    ".ds-input",
    ".ds-tab",
    ".ds-segmented__option",
    ".ds-table__sort",
    ".ds-panel__disclosure",
    ".ds-dialog__close",
  ])("%s reaches 44px", (selector) => {
    expect(block).toContain(selector);
    expect(rule(selector) || block).toMatch(/min-height:\s*44px/);
  });

  it("buttons are 44px in both dimensions", () => {
    const body = block.slice(block.indexOf(".ds-btn"));
    expect(body).toMatch(/min-height:\s*44px/);
    expect(body).toMatch(/min-width:\s*44px/);
  });

  it("the info trigger widens its hit area without changing layout", () => {
    expect(block).toMatch(/\.ds-infotip__trigger::after\s*\{[^}]*inset:\s*-10px/);
  });

  it("never touches desktop: no unconditional 44px override outside the block", () => {
    const before = css.slice(0, marker);
    expect(before).not.toMatch(/\.ds-btn\s*\{[^}]*min-height:\s*44px/);
  });
});
