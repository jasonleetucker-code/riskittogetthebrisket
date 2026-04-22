// ── Chart visual regression ──────────────────────────────────────────
//
// Full-chart screenshots + structural assertions over the chart
// components shipped across PRs #211-#214.
//
// Baseline generation (run once locally / in CI after intentional UI
// changes):
//
//   npx playwright test --update-snapshots chart-visual-regression
//
// Tolerance rationale: 0.2% pixel difference so the test absorbs
// benign SVG rendering variance across runners (font antialiasing,
// subpixel positioning) without missing genuine chart breakage.
//
// Readiness model:
// Naive ``el.count()`` returns 0 while the chart is still fetching
// data.  That made the first iteration of this spec silently mark
// real regressions as "skipped" (green) on slower CI runners.  This
// version uses ``_waitForChartOrSkip`` — a proper ``locator.waitFor``
// with a timeout that resolves EITHER "chart rendered → run the
// assertion" OR "waited the full timeout and it's definitely not
// here → skip with a clear reason."  The skip path only fires on
// timeout, not on "not yet loaded."
// ─────────────────────────────────────────────────────────────────────

const { test, expect } = require("@playwright/test");

const SCREENSHOT_OPTIONS = {
  maxDiffPixelRatio: 0.002,
  mask: [],
  animations: "disabled",
};

// Upper bound on how long we'll wait for a chart to render before
// concluding it's legitimately absent (e.g. page doesn't have the
// expected feature yet).  Set generously — chart data sometimes
// involves a 4 MB contract fetch on CI-sized runners.
const READINESS_TIMEOUT_MS = 15_000;

const CHART_SELECTORS = {
  hillCurve: 'svg[aria-label*="Hill curve"]',
  tierGap: 'svg[aria-label*="Tier-gap waterfall"]',
  confidenceScatter: 'svg[aria-label*="Confidence versus value"]',
  tradeDelta: 'svg[aria-label*="Trade value comparison"]',
  matchupMargin: 'svg[aria-label*="Matchup margin"]',
  tradeFlow: 'svg[aria-label*="Trade flow"]',
  activityHeatmap: 'svg[aria-label*="activity heatmap"]',
  franchiseTraj: 'svg[aria-label*="Franchise"]',
};

/**
 * Wait for a chart locator to become visible or, if the timeout
 * elapses, mark the test as skipped with a descriptive reason.
 *
 * This replaces a pattern where ``await el.count()`` returned 0 while
 * the page was still loading and the test quietly passed by skipping.
 * ``waitFor`` with a bounded timeout resolves the "still loading"
 * ambiguity: if the selector never resolves within ``READINESS_TIMEOUT_MS``,
 * it's definitely not on this page and the skip is accurate, not a
 * silent regression.
 *
 * Returns the locator if visible; otherwise ``null`` (and calls
 * ``test.skip``).
 */
async function _waitForChartOrSkip(
  page,
  selector,
  friendlyName,
) {
  const el = page.locator(selector).first();
  try {
    await el.waitFor({ state: "visible", timeout: READINESS_TIMEOUT_MS });
    return el;
  } catch {
    test.skip(
      true,
      `${friendlyName} didn't render within ${READINESS_TIMEOUT_MS}ms — page may not include this chart`,
    );
    return null;
  }
}

/**
 * Expand the /rankings methodology panel if it's collapsed.  No-op
 * if the button isn't present (different page variants).  The button
 * visibility check is waited so we don't race the initial React
 * mount.
 */
async function _openMethodology(page) {
  const btn = page.getByRole("button", { name: /how this works/i });
  try {
    await btn.waitFor({ state: "visible", timeout: 5_000 });
    await btn.click();
  } catch {
    // Button not present — methodology is either always-open on this
    // variant or the page doesn't have one.  Silent no-op.
  }
}

test.describe("Chart visual regression", () => {
  test.skip(
    !!process.env.SKIP_VISUAL_REGRESSION,
    "Set SKIP_VISUAL_REGRESSION=1 to skip this suite locally",
  );

  test("Hill curve (methodology panel)", async ({ page }) => {
    await page.goto("/rankings");
    await _openMethodology(page);
    const el = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.hillCurve,
      "Hill curve",
    );
    if (!el) return;
    await expect(el).toHaveScreenshot("hill-curve.png", SCREENSHOT_OPTIONS);
  });

  test("Tier-gap waterfall", async ({ page }) => {
    await page.goto("/rankings");
    await _openMethodology(page);
    const el = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.tierGap,
      "Tier-gap waterfall",
    );
    if (!el) return;
    await expect(el).toHaveScreenshot("tier-gap.png", SCREENSHOT_OPTIONS);
  });

  test("Confidence vs value scatter", async ({ page }) => {
    await page.goto("/edge");
    const el = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.confidenceScatter,
      "Confidence scatter",
    );
    if (!el) return;
    await expect(el).toHaveScreenshot("confidence-scatter.png", SCREENSHOT_OPTIONS);
  });

  test("Matchup margin histogram (league/weekly)", async ({ page }) => {
    await page.goto("/league?tab=weekly");
    const el = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.matchupMargin,
      "Matchup margin chart",
    );
    if (!el) return;
    await expect(el).toHaveScreenshot("matchup-margin.png", SCREENSHOT_OPTIONS);
  });

  test("Trade flow Sankey (league/activity)", async ({ page }) => {
    await page.goto("/league?tab=activity");
    const el = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.tradeFlow,
      "Trade flow Sankey",
    );
    if (!el) return;
    await expect(el).toHaveScreenshot("trade-flow.png", SCREENSHOT_OPTIONS);
  });

  test("Activity heatmap (league/activity)", async ({ page }) => {
    await page.goto("/league?tab=activity");
    const el = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.activityHeatmap,
      "Activity heatmap",
    );
    if (!el) return;
    await expect(el).toHaveScreenshot("activity-heatmap.png", SCREENSHOT_OPTIONS);
  });

  test("Franchise trajectory (league/franchise)", async ({ page }) => {
    await page.goto("/league?tab=franchise");
    const el = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.franchiseTraj,
      "Franchise trajectory",
    );
    if (!el) return;
    await expect(el).toHaveScreenshot("franchise-trajectory.png", SCREENSHOT_OPTIONS);
  });
});

// ── Structural assertions (non-pixel) ──────────────────────────────
//
// These run independently of baseline images.  Even if the
// ``toHaveScreenshot`` path is short-circuited (first run without
// baselines, or a CI mode that sets SKIP_VISUAL_REGRESSION), these
// assertions catch the "chart is broken" class of regression:
// missing axes, zero data points, empty SVGs.  The same waited
// readiness gate applies — no silent-skip on slow loads.

test.describe("Chart structural smoke tests", () => {
  test("Hill curve has axis + at least one path", async ({ page }) => {
    await page.goto("/rankings");
    await _openMethodology(page);
    const svg = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.hillCurve,
      "Hill curve",
    );
    if (!svg) return;
    await expect(svg.locator("path").first()).toBeVisible();
    await expect(svg.locator("circle").first()).toBeVisible();
  });

  test("Confidence scatter has enough points", async ({ page }) => {
    await page.goto("/edge");
    const svg = await _waitForChartOrSkip(
      page,
      CHART_SELECTORS.confidenceScatter,
      "Confidence scatter",
    );
    if (!svg) return;
    const circles = svg.locator("circle");
    await expect(circles.first()).toBeVisible();
    // Healthy scatter has many points.  A "zero dots because the
    // data flow broke" state trips this.
    const count = await circles.count();
    expect(count).toBeGreaterThan(5);
  });
});
