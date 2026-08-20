/**
 * Automated accessibility scan — the instrument this repo did not have.
 *
 * WHAT WAS MISSING
 * ────────────────
 * There is no ESLint config anywhere in the tree, no `jsx-a11y`, no
 * axe-core, and no Playwright a11y scan. The ONLY a11y test was
 * `frontend/__tests__/a11y-tab-roles.test.js` — a structural guard on one
 * rule (`role="tab"` must have a real `tabpanel`), shipping a baseline of
 * seven known violations. `docs/C_SERIES_SCOPE_MANIFEST.md` records
 * `C8-A11Y-01` as PARTIAL for exactly this reason: "structural ratchet
 * exists, no axe-core".
 *
 * Everything else was unmeasured, which is not the same as clean. The
 * first run of this spec found, and this branch fixed:
 *
 *   /settings  label × 4              every numeric valuation control on
 *                                     the page was an unnamed input
 *   /settings  select-name × 3        three unnamed comboboxes
 *   /settings  aria-prohibited-attr   21 status dots carrying `aria-label`
 *              × 21                   on a bare <span>, which has no role
 *                                     to name
 *   /rosters   color-contrast × 57    white on saturated chips, down to
 *                                     2.85:1 against a 4.5:1 floor
 *   /rosters   scrollable-region-     a sideways-scrolling table with no
 *              focusable × 1          keyboard way in
 *
 * A RATCHET, NOT A GATE
 * ─────────────────────
 * `BASELINE` records what is known and not yet fixed, per route per
 * viewport. The suite fails on anything NEW, and equally on a baseline
 * entry that has become stale — because an allowance nobody re-checks is
 * how a backlog quietly grows back. That is the same posture
 * `a11y-tab-roles.test.js` and the decision-path coercion gate already
 * take; this is not a new convention.
 *
 * SCOPE
 * ─────
 * WCAG 2.0/2.1 A and AA only. Best-practice rules are deliberately out:
 * they are opinions, and mixing them in would make the ratchet argue
 * about taste instead of about conformance.
 */
const { test, expect } = require("../helpers/auth-fixture");
const AxeBuilder = require("@axe-core/playwright").default;
const { pageUrl, isMobileProject } = require("../helpers/journey");

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/** Routes worth scanning: the high-use private surfaces plus the two public ones. */
const ROUTES = [
  "/",
  "/rankings",
  "/trade",
  "/waivers",
  "/rosters",
  "/trades",
  "/settings",
  "/admin",
  "/login",
  "/league",
];

/**
 * Known, unfixed violations: `"route|viewport"` -> { ruleId: nodeCount }.
 *
 * EMPTY, and that is a measurement rather than an aspiration — every
 * violation the first scan found on these ten routes is fixed on this
 * branch. An entry added here must carry a reason and an owner.
 */
const BASELINE = {};

function keyFor(route, testInfo) {
  return `${route}|${isMobileProject(testInfo) ? "mobile" : "desktop"}`;
}

for (const route of ROUTES) {
  test(`a11y: ${route} has no new WCAG A/AA violations`, async ({
    authedPage: page,
  }, testInfo) => {
    await page.goto(pageUrl(route), { waitUntil: "domcontentloaded" });
    // The board and its panels arrive after the contract does; scanning
    // the skeleton would pass by measuring nothing.
    await page.waitForTimeout(4000);

    const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
    const found = {};
    for (const v of results.violations) found[v.id] = v.nodes.length;

    const allowed = BASELINE[keyFor(route, testInfo)] || {};

    // 1. Nothing new, and nothing worse than its allowance.
    const regressions = {};
    for (const [rule, count] of Object.entries(found)) {
      const budget = allowed[rule];
      if (budget == null || count > budget) regressions[rule] = { found: count, allowed: budget ?? 0 };
    }
    expect(
      regressions,
      `new or worsened accessibility violations on ${route}:\n` +
        results.violations
          .filter((v) => regressions[v.id])
          .map(
            (v) =>
              `  [${v.impact}] ${v.id}: ${v.help}\n` +
              v.nodes
                .slice(0, 3)
                .map((n) => `      ${JSON.stringify(n.target)}\n      ${(n.html || "").slice(0, 120)}`)
                .join("\n"),
          )
          .join("\n"),
    ).toEqual({});

    // 2. A baseline entry that is no longer needed is a stale allowance.
    //    Left alone it hides the next regression of the same rule.
    const stale = Object.keys(allowed).filter((rule) => !(rule in found));
    expect(
      stale,
      `${route}: these baseline allowances are fixed — delete them, or they ` +
        "will absorb the next regression of the same rule",
    ).toEqual([]);
  });
}
