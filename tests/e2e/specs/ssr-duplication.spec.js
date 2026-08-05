/**
 * SSR streaming leaves no duplicate copy behind.
 *
 * WHY THIS SPEC EXISTS
 * --------------------
 * `dynamic()` in `components/AppShell.jsx` once put a React lazy boundary
 * around `{children}` — the whole page. Every route's content became
 * deferred streaming content: React staged it in a hidden
 * `<div id="S:1">`, moved it into place, and left the staged copy behind.
 * /waivers served THREE <main> elements.
 *
 * Six rounds of performance instrumentation — CLS, LCP, INP, long-task,
 * scroll FPS, per-route bundle size — ALL reported unchanged numbers for
 * a build that rendered every page twice. `pr-validation.yml` runs
 * pytest, vitest and lint; it never opens a browser. The single detector
 * was an INCIDENTAL Playwright strict-mode violation in
 * waivers-smoke.spec.js — a spec about a rookie toggle, which happened to
 * fail because its locator resolved to two elements.
 *
 * Depending on an accident is not a detector. This spec names the
 * invariant directly, so the next occurrence fails a test that is *about*
 * duplication instead of one that is about a checkbox.
 *
 * WHAT IT ASSERTS, AND WHY THESE THREE
 * ------------------------------------
 * All three are route-independent, which is what makes them safe to
 * assert flatly. Measured across 1,200 loads (six routes × 200) with
 * `frontend/scripts/measure-duplication.mjs`, the clean baseline is:
 *
 *   - zero surviving `div[id^="S:"]` staging containers AFTER settle
 *   - zero duplicate element ids
 *   - exactly one level-1 heading
 *
 * Deliberately NOT asserted: the `<main>` count. It is route-dependent —
 * the shell renders one and some pages render their own, so /waivers
 * baselines at 2 and /arbitrage at 1. A flat assertion there would be
 * wrong on half the routes.
 *
 * The staging-container check is specifically an AFTER-SETTLE check. A
 * `div[id^="S:"]` mid-load is React streaming working correctly — it is
 * how streamed content arrives, measured on 24-46% of loads on the
 * heavier routes. Asserting its mere presence would fail constantly on a
 * perfectly healthy app.
 *
 * SCOPE: this is a TRIPWIRE, not a rate estimator. The historical race
 * was ~1/15 loads at worst, so one navigation per route has limited power
 * to catch a low-rate recurrence. It reliably catches the deterministic
 * shape (a boundary around `{children}` duplicates EVERY load, which is
 * what the `dynamic()` regression did), and
 * `frontend/scripts/measure-duplication.mjs --loads 200` is the
 * instrument for measuring a rate. Layered on purpose.
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl } = require("../helpers/journey");

// Private routes, chosen as the heaviest streamers measured: /rankings
// (46% of loads stage mid-flight) and /waivers + /arbitrage (the two the
// race was originally measured on). If a boundary regression lands, these
// are where it shows first.
const ROUTES = ["/rankings", "/waivers", "/arbitrage"];

// Matches the settle delay used by the measurement harness, so this spec
// and that instrument agree on when "after streaming" begins.
const SETTLE_MS = 500;

const PROBE = () => {
  const seen = Object.create(null);
  const dupIds = [];
  for (const el of document.querySelectorAll("[id]")) {
    if (!el.id) continue;
    seen[el.id] = (seen[el.id] || 0) + 1;
  }
  for (const [id, n] of Object.entries(seen)) if (n > 1) dupIds.push(`${id}×${n}`);
  return {
    staged: Array.from(document.querySelectorAll('div[id^="S:"]')).map((d) => d.id),
    dupIds,
  };
};

test.describe("SSR streaming duplication", () => {
  for (const route of ROUTES) {
    test(`${route} renders exactly one copy of itself`, async ({ authedPage }) => {
      await authedPage.goto(pageUrl(route), { waitUntil: "domcontentloaded" });
      await authedPage.waitForTimeout(SETTLE_MS);

      const { staged, dupIds } = await authedPage.evaluate(PROBE);

      expect(
        staged,
        `React staging container(s) survived settle on ${route}: ${staged.join(", ")}. ` +
          `The page is in the document twice. See the header of this spec.`,
      ).toEqual([]);

      expect(
        dupIds,
        `Duplicate element ids on ${route}: ${dupIds.join(", ")}. ` +
          `Duplicate ids break getElementById, label/for, aria-labelledby and anchor links.`,
      ).toEqual([]);

      // getByRole rather than a DOM count, so this fails the same way the
      // original incidental detector did: a locator resolving to 2.
      await expect(authedPage.getByRole("heading", { level: 1 })).toHaveCount(1);
    });
  }
});
