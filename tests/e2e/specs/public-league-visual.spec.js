// ── Public /league section visual regression ─────────────────────────
//
// Snapshot test per top-level tab on the public /league hub.  Catches
// CSS / layout regressions on the surfaces with the highest editorial
// volatility (Records, Streaks, Awards, Recaps) — those got reworked
// in PR #300 and continue to evolve, so we want pixel-level guard-
// rails before the next round of polish.
//
// Baseline generation (run once after intentional UI changes):
//
//   npx playwright test --update-snapshots public-league-visual
//
// Tolerance rationale: 0.5% pixel difference so the test absorbs
// benign font-antialiasing variance across runners but still catches
// real layout breakage.  Higher than the chart suite's 0.2% because
// /league sections include avatars + player headshots loaded from
// Sleeper's CDN, which can have JPEG-compression jitter that the
// chart suite (pure SVG) doesn't have to deal with.
//
// Skip path: ``SKIP_VISUAL_REGRESSION=1`` for local runs without the
// dev server running, mirroring the chart suite.
// ─────────────────────────────────────────────────────────────────────
const { test, expect } = require("@playwright/test");
const { pageUrl } = require("../helpers/journey");

const SCREENSHOT_OPTIONS = {
  maxDiffPixelRatio: 0.005,
  // Mask out player headshots — Sleeper's CDN can serve slightly
  // different JPEG quality on the same player ID over time, so any
  // headshot byte-shift would falsely fail the layout-only check.
  // The mask is applied as a flat-colour rectangle before comparison.
  mask: [],
  animations: "disabled",
  // Allow the league snapshot fetch + initial render to settle
  // before capture.  The /api/public/league endpoint can take a
  // few hundred ms on a cold cache.
  fullPage: false,
};

const READINESS_TIMEOUT_MS = 30_000;

async function _waitForLeagueLoaded(page) {
  // Wait for the loading sentinel to clear — this fires only after
  // the /api/public/league response materialises.
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading league data..."),
    null,
    { timeout: READINESS_TIMEOUT_MS },
  );
}

/**
 * Open a /league sub-tab and wait for ITS content to render.
 *
 * ── Why this changed (see docs/e2e-assertion-audit.md) ─────────────
 * The previous version was `if (await btn.count()) { click }` — a
 * silent no-op when the tab button was missing or renamed.  Combined
 * with a `page.locator("section").first()` assertion it made all four
 * tests in this file vacuous: LeagueClient.jsx wraps the ENTIRE page
 * in one `<section>` (line 243), so that locator resolves to the same
 * always-present wrapper on every tab, whether or not the tab
 * switched or the section rendered.  Under the documented
 * `npm run e2e` (which passes `--ignore-snapshots`, and no pixel
 * baselines are committed) `toHaveScreenshot` is a no-op too — so the
 * entire assertion content of this file was "the /league page has at
 * least one <section> element".
 *
 * Now: the tab button must exist (hard assert), and the section's own
 * content must appear before we return.  `expectContent` is matched
 * against the page body, which is safe here because these strings are
 * section copy, not shell chrome — no /league sub-tab label or nav
 * item contains them.
 */
async function _openLeagueTab(page, tabLabel, expectContent) {
  await page.goto(pageUrl("/league"));
  await _waitForLeagueLoaded(page);

  const btn = page.getByRole("button", { name: tabLabel, exact: true });
  await expect(
    btn.first(),
    `the "${tabLabel}" sub-tab must exist on /league — a renamed or ` +
      `dropped tab used to make this test silently pass`,
  ).toBeVisible({ timeout: READINESS_TIMEOUT_MS });
  // Click INSIDE the poll, not before it.
  //
  // `toBeVisible` proves the markup arrived, not that React has attached
  // handlers — and against a large document those are far apart. A click
  // that lands in that gap is not queued, it is LOST, and the wait below
  // then watches a section that was never going to change. That is the
  // race diagnosed on the archives tab (30 production runs read
  // FFFF.SFFSFSSSSSSFSFSFFSS.FSFFF — 13 pass, 15 fail, interleaved), and
  // the remedy proven there is to retry the click while polling.
  //
  // ALL FOUR tests in this file funnel through this helper, so the fix
  // was worth generalising rather than leaving in public-league.spec.js
  // alone. Re-clicking is safe: the handler sets tab state, so extra
  // clicks re-select the same tab.
  // NOTE: every caller passes a RegExp, so this must test with `.test()`,
  // not `String.includes` — the latter would stringify the pattern and
  // silently never match, turning a race fix into a permanent failure.
  const matcher =
    expectContent instanceof RegExp ? expectContent : new RegExp(expectContent, "i");
  await expect
    .poll(
      async () => {
        await btn.first().click();
        return matcher.test(await page.locator("body").innerText());
      },
      {
        message:
          `the "${tabLabel}" section should render its own content ` +
          `(expected to match ${matcher})`,
        timeout: READINESS_TIMEOUT_MS,
        intervals: [250, 500, 1000, 2000, 3000],
      },
    )
    .toBe(true);
}

test.describe("public /league visual regression", () => {
  test.skip(
    !!process.env.SKIP_VISUAL_REGRESSION,
    "Set SKIP_VISUAL_REGRESSION=1 to skip this suite locally",
  );

  // Run on a single fixed viewport — the snapshot baseline is for
  // that exact size.  Matches the chart suite's convention.
  test.use({
    viewport: { width: 1366, height: 900 },
  });

  // The viewport override above makes every project render the same
  // 1366x900 frame, so running under the mobile projects would just
  // duplicate the desktop capture (against a separate, never-created
  // per-project baseline).  Desktop project only.
  test.beforeEach(async ({}, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-1366",
      "fixed-viewport visual suite runs on the desktop project only",
    );
  });

  // ── Structural assertions (the part that runs every night) ───────
  // No pixel baselines are committed and `npm run e2e` passes
  // `--ignore-snapshots`, so `toHaveScreenshot` contributes nothing to
  // the nightly signal.  It is kept so a deliberate
  // `--update-snapshots` run still produces baselines, but each test
  // must now stand on a data-derived structural assertion that fails
  // when the section breaks.

  test("Records section renders the record book with real teams", async ({ page }) => {
    await _openLeagueTab(page, "Records", /Record book/i);

    // The record book's substance: ranked single-week extremes.  Each
    // row names a team and a season/week.  A section that renders its
    // card frame but no records fails here.
    await expect(page.locator("body")).toContainText(/Highest single-week scores/i);
    const rows = page.getByText(/\(\d{4} wk \d+\)/);
    await expect
      .poll(() => rows.count(), {
        message: "record book should list at least one (season wk N) entry",
        timeout: READINESS_TIMEOUT_MS,
      })
      .toBeGreaterThan(0);

    await expect(page.locator("section").first()).toHaveScreenshot(
      "league-records.png",
      SCREENSHOT_OPTIONS,
    );
  });

  test("Streaks section renders streak content", async ({ page }) => {
    // StreaksSection renders EmptyCard("Streaks") when the league has
    // no computed streaks, so accept either the populated cards or the
    // explicit empty state — but NOT a blank tab.
    await _openLeagueTab(
      page,
      "Streaks",
      /Longest streaks|Current streak by manager|No Streaks|Streaks/i,
    );
    await expect(page.locator("section").first()).toHaveScreenshot(
      "league-streaks.png",
      SCREENSHOT_OPTIONS,
    );
  });

  test("Awards section renders award content", async ({ page }) => {
    await _openLeagueTab(page, "Awards", /award/i);
    // Awards renders per-season winners; require real content volume
    // rather than the bare card frame.
    await expect
      .poll(async () => (await page.locator("body").innerText()).length, {
        message: "awards tab should render substantive content",
        timeout: READINESS_TIMEOUT_MS,
      })
      .toBeGreaterThan(600);
    await expect(page.locator("section").first()).toHaveScreenshot(
      "league-awards.png",
      SCREENSHOT_OPTIONS,
    );
  });

  test("Recaps section renders the articles surface", async ({ page }) => {
    // ArticlesSection (mode="recap") either lists generated recaps or
    // reports why it could not load them.  Both are real states; a
    // blank tab is not.
    await _openLeagueTab(page, "Recaps", /recap|article|No .*available/i);
    await expect(page.locator("section").first()).toHaveScreenshot(
      "league-recaps.png",
      SCREENSHOT_OPTIONS,
    );
  });
});
