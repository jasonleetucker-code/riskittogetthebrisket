/**
 * The dashboard panel `order` pairing invariant (R5 purge guard).
 *
 * `globals.css` carries two halves of one contract:
 *
 *   .panel--signals { order: 10 }  … base, applies at EVERY width
 *   @media (min-width: 720px) { .panel--signals, … { order: 0 } }
 *
 * `order` is inert on a static block but live inside a flex or grid
 * container, and the dashboard columns are `display: flex; flex-direction:
 * column` above 768px. The reset is the only thing keeping the base scale
 * off the desktop layout.
 *
 * So deleting the reset while keeping the base orders silently re-sorts
 * every tagged panel inside its column at desktop. Nothing throws, no test
 * fails, and the page renders in the wrong order — which is precisely the
 * shape of bug an R5 sweep produces when it deletes "the dead terminal grid
 * block" and takes half the contract with it.
 *
 * This asserts the PAIRING rather than the presence, so it holds across the
 * purge instead of having to be rewritten by it:
 *
 *   before the purge — both halves present  => PASS
 *   half deleted     — the landmine         => FAIL
 *   after the purge  — both halves gone     => PASS
 *
 * See docs/redesign/R5-PANEL-CSS-PURGE.md §3.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const CSS = fs
  .readFileSync(path.resolve(__dirname, "../app/globals.css"), "utf8")
  // Comments document these rules with literal CSS; parsing them finds the
  // explanation instead of the declaration.
  .replace(/\/\*[\s\S]*?\*\//g, "");

/** Every rule whose selector mentions .panel--<name> and whose body sets order. */
function panelOrderRules() {
  const out = [];
  const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = ruleRe.exec(CSS)) !== null) {
    const [, selector, body] = m;
    if (!selector.includes(".panel--")) continue;
    const order = body.match(/(?:^|[;\s])order\s*:\s*(-?\d+)/);
    if (!order) continue;
    const names = [...selector.matchAll(/\.panel--([\w-]+)/g)].map((x) => x[1]);
    out.push({ names, order: Number(order[1]), index: m.index });
  }
  return out;
}

describe("dashboard panel order pairing (globals.css)", () => {
  const rules = panelOrderRules();
  const positioned = new Set();
  const reset = new Set();
  for (const r of rules) {
    for (const n of r.names) (r.order === 0 ? reset : positioned).add(n);
  }

  it("pairs every positioned panel with a reset", () => {
    // The whole point: these two sets move together or not at all.
    expect([...positioned].sort()).toEqual([...reset].sort());
  });

  it("declares the reset AFTER the base orders it neutralises", () => {
    // Equal specificity (0,1,0) both sides, so source order decides. A
    // reset written above the base rules loses and is decorative.
    if (positioned.size === 0) return; // purged; nothing to order
    const lastBase = Math.max(
      ...rules.filter((r) => r.order !== 0).map((r) => r.index),
    );
    const firstReset = Math.min(
      ...rules.filter((r) => r.order === 0).map((r) => r.index),
    );
    expect(firstReset).toBeGreaterThan(lastBase);
  });

  it("keeps the reset inside a min-width query, not an unconditional rule", () => {
    // An unconditional `order: 0` would neutralise the mobile scale too,
    // flattening the priority stack back to DOM order.
    if (positioned.size === 0) return;
    const firstReset = Math.min(
      ...rules.filter((r) => r.order === 0).map((r) => r.index),
    );
    const before = CSS.slice(0, firstReset);
    const lastQuery = before.lastIndexOf("@media");
    expect(lastQuery).toBeGreaterThan(-1);
    expect(CSS.slice(lastQuery, firstReset)).toMatch(/min-width/);
  });
});
