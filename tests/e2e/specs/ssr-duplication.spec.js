/**
 * SSR streaming leaves no duplicate copy behind.
 *
 * WHY THIS SPEC EXISTS
 * --------------------
 * Two different things produce "the page is in the DOM twice", and only
 * one is a bug. #747 established the distinction; this spec exists to
 * detect the half that is still real.
 *
 * TRANSIENT (not a bug): React 19.2 defers the Suspense reveal. `$RC`
 * marks the boundary and schedules `$RV`, which is the only thing that
 * removes `<div hidden id="S:n">` — so a full copy of the boundary is
 * SUPPOSED to sit in the DOM for that window. Specs that asserted
 * mid-stream saw it and failed. Fixed suite-side by `awaitStreamSettled()`
 * in helpers/journey.js, which this spec uses before asserting anything.
 *
 * PERSISTENT (a real bug): `dynamic()` in `components/AppShell.jsx` once
 * put a React lazy boundary around `{children}` — the whole page. The
 * staged copy was never reclaimed; /waivers served THREE <main> elements.
 * Six rounds of performance instrumentation — CLS, LCP, INP, long-task,
 * scroll FPS, per-route bundle size — ALL reported unchanged numbers for
 * a build that rendered every page twice, and `pr-validation.yml` never
 * opens a browser.
 *
 * That second class is what this spec is for. The repo's existing
 * detector for it is INCIDENTAL — a strict-mode violation in
 * waivers-smoke.spec.js, a spec about a rookie toggle, which fails only
 * because its locator happens to resolve to two elements. Depending on an
 * accident is not a detector, and it names the wrong subject when it
 * fires. This asserts the invariant directly, after the stream settles,
 * so a permanent duplicate fails a test that is *about* duplication.
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
 * how streamed content arrives, measured on 12-46% of loads on the
 * heavier routes across two 1,200-load runs. Asserting its mere presence
 * would fail constantly on a perfectly healthy app.
 *
 * SCOPE: this is a TRIPWIRE, not a rate estimator — and for the bug it
 * targets, a tripwire is the right shape. A permanent duplicate is
 * DETERMINISTIC: a boundary around `{children}` duplicates every load,
 * which is what the `dynamic()` regression did, so one navigation per
 * route catches it. Rates are the transient reveal's problem, and that is
 * no longer a defect. When a rate IS wanted,
 * `frontend/scripts/measure-duplication.mjs --loads 200` is the
 * instrument for measuring a rate. Layered on purpose.
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");

// Private routes, chosen as the heaviest streamers measured: /rankings
// (46% of loads stage mid-flight) and /waivers + /arbitrage (the two the
// race was originally measured on). If a boundary regression lands, these
// are where it shows first.
const ROUTES = ["/rankings", "/waivers", "/arbitrage"];

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
      // The repo's shared settle helper (#747), not a fixed delay. React
      // 19.2 throttles the reveal to `$RT + 300 - now` — up to 2300ms in
      // one window — so no constant timeout is both fast and safe. This
      // waits for the machinery itself.
      await awaitStreamSettled(authedPage);

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
