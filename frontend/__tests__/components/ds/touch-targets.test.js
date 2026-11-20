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

  it("the info slop does not overlap a preceding sort button", () => {
    expect(block).toMatch(
      /\.ds-table__sort\s*\+\s*\.ds-infotip\s*\{[^}]*margin-left:\s*10px/,
    );
  });

  it("a one-column sort header is 44px wide too (measured 19px on '#')", () => {
    expect(rule(".ds-table__sort")).toMatch(/min-width:\s*44px/);
  });

  it("player names grow their HIT box without moving layout (X-MOBILE-TOUCH)", () => {
    // The padding and the negative margin must cancel exactly, or every row
    // holding a name changes height on a phone.
    const m = block.match(/a\.ds-player-name,[^{]*\{([^}]*)\}/);
    expect(m, "player-name rule missing from the coarse block").toBeTruthy();
    const pad = /padding-block:\s*(\d+)px/.exec(m[1]);
    const margin = /margin-block:\s*-(\d+)px/.exec(m[1]);
    expect(pad && margin).toBeTruthy();
    expect(Number(pad[1])).toBe(Number(margin[1]));
    // Tag-qualified: page modules reset `.x { padding: 0 }` after ds.css.
    expect(m[0]).toMatch(/button\.ds-player-name/);
  });

  it("legacy sub-24px controls are lifted to the AA floor, in their own stylesheets", () => {
    // ds.css holds .ds-* classes only (tokens-contract.test.js); page-local
    // controls are lifted in the page's stylesheet under the same condition.
    const coarse = (file) => {
      const text = fs.readFileSync(path.resolve(__dirname, "../../../app", file), "utf8");
      const at = text.lastIndexOf("@media (pointer: coarse), (max-width: 480px)");
      expect(at, `${file} has no coarse-pointer block`).toBeGreaterThan(-1);
      return text.slice(at);
    };
    const draft = coarse("draft/draft.css");
    for (const sel of [".draft-tag-tab", ".draft-tag-chip", ".draft-check", ".draft-radio"]) {
      expect(draft, sel).toContain(sel);
    }
    expect(draft).toMatch(/\.draft-radio\s*\{[^}]*min-height:\s*24px/);
    const nbt = draft.match(/button\.draft-nbt-name\s*\{([^}]*)\}/);
    expect(nbt, "nominate-name hit-box lift missing").toBeTruthy();
    const pad = /padding-block:\s*(\d+)px/.exec(nbt[1]);
    const margin = /margin-block:\s*-(\d+)px/.exec(nbt[1]);
    expect(Number(pad[1])).toBe(Number(margin[1]));
    expect(coarse("globals.css")).toMatch(/a\.rankings-chip\s*\{[^}]*min-height:\s*24px/);
  });

  it("never touches desktop: no unconditional 44px override outside the block", () => {
    const before = css.slice(0, marker);
    expect(before).not.toMatch(/\.ds-btn\s*\{[^}]*min-height:\s*44px/);
  });
});
