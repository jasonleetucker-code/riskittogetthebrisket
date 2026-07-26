/**
 * Dashboard mobile stacking order (R3 review, P2-1).
 *
 * Below 768px the three-column grid collapses to one column.  The
 * panels must NOT stack in DOM order: Portfolio and Scouting live in
 * the first column but are the two least urgent surfaces, so raw DOM
 * order puts them first and pushes Movers/Signals two panel-heights
 * down — the opposite of the reading order the page is built around
 * ("what changed, and what should I do about it").
 *
 * main achieved this with `.terminal-col { display: contents }` plus
 * per-panel `order` rules; the CSS-module migration dropped both.
 * jsdom does not evaluate media queries or resolve `order`, so this
 * asserts the CSS CONTRACT directly — that the rules exist, target
 * the right panels, and carry the right relative priority — which is
 * what actually regressed.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

/**
 * Comments are stripped before anything is parsed: the rules below are
 * documented with literal CSS in prose (`.terminal-col { display:
 * contents }`), and leaving that in makes the matchers find the
 * explanation instead of the declaration — a test that passes on its
 * own documentation.
 */
const CSS = fs
  .readFileSync(
    path.resolve(__dirname, "../components/terminal/terminal.module.css"),
    "utf8",
  )
  .replace(/\/\*[\s\S]*?\*\//g, "");

/** The `@media (width < 768px)` block that owns the single-column stack. */
function mobileBlock() {
  const start = CSS.indexOf("@media (width < 768px)");
  expect(start, "terminal.module.css must have a <768px block").toBeGreaterThan(-1);
  // walk braces to the end of the at-rule
  let depth = 0;
  let i = CSS.indexOf("{", start);
  const from = i;
  for (; i < CSS.length; i++) {
    if (CSS[i] === "{") depth++;
    else if (CSS[i] === "}") {
      depth--;
      if (depth === 0) break;
    }
  }
  return CSS.slice(from, i);
}

describe("dashboard mobile stacking order", () => {
  const block = mobileBlock();

  it("dissolves the column wrappers so panels can reorder across them", () => {
    // Without display:contents the `order` rules below are inert —
    // each column is its own flex context and panels can only sort
    // within their own column.
    expect(block).toMatch(/\.col[^{]*\{[^}]*display:\s*contents/);
  });

  it("dissolves .colRight too, which the tablet rule turns into a grid", () => {
    // `.colRight` gets `display: grid` at <1320px.  That rule is still
    // in force below 768px, so the mobile block has to name it
    // explicitly — `.col` alone leaves the right column an intact box
    // and its three panels can't leave it.
    const contents = block.match(/([^{}]*)\{[^}]*display:\s*contents[^}]*\}/);
    expect(contents, "a display:contents rule must exist").toBeTruthy();
    expect(contents[1]).toContain(".colRight");
  });

  it("declares the base .col box BEFORE the mobile block", () => {
    // The bug this pins: a media query adds no specificity, so bare
    // `.col { display: flex }` and `.col { display: contents }` inside
    // `@media` are both (0,1,0) and source order alone decides.  With
    // the base rule written after the media block, `flex` wins at every
    // width and the entire reorder is silently inert — it renders
    // exactly like the regression it was meant to fix.
    const baseCol = CSS.search(/^\.col\s*\{/m);
    const mobileAt = CSS.indexOf("@media (width < 768px)");
    expect(baseCol, "a base .col rule must exist").toBeGreaterThan(-1);
    expect(baseCol).toBeLessThan(mobileAt);
  });

  it("orders the six prioritised panels", () => {
    for (const panel of [
      "signals",
      "movement",
      "news",
      "portfolio",
      "scouting",
      "actions",
    ]) {
      expect(block, `panel--${panel} needs a mobile order rule`).toContain(
        `panel--${panel}`,
      );
    }
  });

  it("keeps the priority main established: signals/movement above portfolio/scouting", () => {
    const orderOf = (panel) => {
      const m = block.match(
        new RegExp(`panel--${panel}\\)?\\s*\\{[^}]*order:\\s*(\\d+)`),
      );
      expect(m, `panel--${panel} must declare an order`).toBeTruthy();
      return Number(m[1]);
    };
    const signals = orderOf("signals");
    const movement = orderOf("movement");
    const news = orderOf("news");
    const portfolio = orderOf("portfolio");
    const scouting = orderOf("scouting");
    const actions = orderOf("actions");

    // The regression put portfolio/scouting FIRST; these are the
    // assertions that would have caught it.
    expect(signals).toBeLessThan(portfolio);
    expect(signals).toBeLessThan(scouting);
    expect(movement).toBeLessThan(portfolio);
    expect(movement).toBeLessThan(scouting);
    // full intended sequence
    expect(signals).toBeLessThan(movement);
    expect(movement).toBeLessThan(news);
    expect(news).toBeLessThan(portfolio);
    expect(portfolio).toBeLessThan(scouting);
    expect(scouting).toBeLessThan(actions);
  });

  it("leaves Movers/Watchlist unordered so they lead the stack at order 0", () => {
    // "What changed" is the first question the page answers, and an
    // unset `order` defaults to 0 — ahead of every rule above.
    expect(block).not.toContain("panel--movers");
    expect(block).not.toContain("panel--watchlist");
  });
});
