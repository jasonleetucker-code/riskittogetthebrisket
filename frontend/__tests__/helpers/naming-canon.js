/**
 * The naming canon: route → the ONE user-facing name for that page.
 *
 * ── Why this file exists ───────────────────────────────────────────────
 * `lib/nav-model.js` states the rule in its header comment:
 *
 *   "NAMING RULE, load-bearing: a leaf's label here is the SAME string
 *    as the page's <h1>, as pageTitleFor's answer, and as any in-app
 *    link to it."
 *
 * That rule has four consumers — the nav model, `pageTitleFor`, each
 * page's `<h1>`, and the Playwright journey specs that assert on those
 * headings. Until 2026-07-30 the canon was a `const CANON` living
 * INSIDE `__tests__/nav-model.test.js`, which pinned only the first
 * two. `nav-model.test.js` claimed the third was covered:
 *
 *   "the page <h1>s are asserted against the same strings in
 *    __tests__/components/page-title-canon.test.jsx."
 *
 * That file did not exist. `grep -rn "page-title-canon" frontend/`
 * returned exactly one hit: the comment claiming it existed. So the
 * `<h1>` half was pinned by nothing while a comment said it was
 * pinned — `docs/ORCHESTRATION.md` §6.15's "guard that cannot fire",
 * and the reason PR #625 could rename /trade's heading from "Trade
 * Builder" to "Trade Calculator" with no fast test objecting. The only
 * artifact that noticed was the nightly E2E suite, which was already
 * red and therefore ignored, and which then stayed red for two nights
 * with 19 failures.
 *
 * Hoisting the canon here gives it ONE definition with every consumer
 * importing it, so a rename cannot satisfy some consumers and silently
 * skip others.
 *
 * When you rename a page: change it here, then run
 *   cd frontend && npm test
 *   python -m pytest tests/e2e/test_e2e_harness_guards.py
 * and fix everything that goes red. That is the whole point — the red
 * list IS the list of places the name is spelled.
 */

/** Route → canonical user-facing name. */
export const CANON = {
  "/rankings": "Rankings",
  "/trending": "Trending",
  "/idptc-rookies": "Rookie Board",
  "/players/compare": "Compare Players",
  "/bdvm": "Fundamental Values",
  "/news": "News",
  "/trade": "Trade Calculator",
  "/angle": "Package Builder",
  "/arbitrage": "Arbitrage",
  "/trades": "Trade History",
  "/rosters": "Team Strength",
  "/waivers": "Waivers",
  "/draft": "Draft Board",
  "/phases": "Win-now vs Rebuild",
  "/edge": "Source Disagreement",
  // /intel retired into two products. It shipped Sharp Tracker's
  // NAME on Insider Trading's COHORT; the split gives each its own
  // route, and Sharp Tracker is deliberately not league-scoped.
  "/market/sharp-tracker": "Sharp Tracker",
  "/league/insider-trading": "Insider Trading",
  "/league": "Hub",
  "/league/activity": "Activity",
  "/league-comparison": "Scoring Comparison",
};

/**
 * Routes whose `<h1>` is DATA-derived and therefore deliberately not
 * the canon string. The canon entry is still the correct NAV label and
 * `pageTitleFor` answer — only the heading differs, and only because
 * the page is named after the thing it is showing.
 *
 * Every entry needs a reason. An unexplained entry here is how the
 * `<h1>` guard gets hollowed out one route at a time.
 */
export const DATA_DERIVED_TITLE_ROUTES = {
  "/league":
    'the public league hub is titled with the league\'s own name — ' +
    "LeagueClient.jsx renders `title={league.leagueName || \"League\"}`. " +
    '"Hub" is its nav label (it is one tab in the League group), not ' +
    "its heading.",
};

/** Canon routes whose `<h1>` MUST equal the canon string. */
export function staticTitleRoutes() {
  return Object.keys(CANON).filter((r) => !(r in DATA_DERIVED_TITLE_ROUTES));
}
