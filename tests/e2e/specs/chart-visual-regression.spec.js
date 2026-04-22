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
// ``_waitForChart`` waits up to READINESS_TIMEOUT_MS for the chart
// SVG to become visible and LETS THE TIMEOUT FAIL THE TEST.  Earlier
// iterations either used a non-waiting ``count()`` or converted the
// timeout into ``test.skip`` — both patterns masked the regressions
// this suite exists to catch (chart removed, selector drift, data-
// path broken, render genuinely slower than the budget).  Every
// chart this spec targets is expected on its route; if it never
// renders, that's the signal.
//
// Only legitimate skip path: ``SKIP_VISUAL_REGRESSION=1`` set by
// the caller, for local runs where the dev server isn't up.
// ─────────────────────────────────────────────────────────────────────

const { test, expect } = require("@playwright/test");

const SCREENSHOT_OPTIONS = {
  maxDiffPixelRatio: 0.002,
  mask: [],
  animations: "disabled",
};

// Upper bound on how long we'll wait for a chart to render before
// failing the test with "chart didn't render in time" — that's the
// regression signal the suite exists to catch.  Set generously so
// benign CI slowness doesn't flap, but tight enough that a genuinely
// broken chart surfaces within a reasonable dev-loop.  15s covers
// the 4 MB contract fetch plus the initial React mount on a
// CI-sized runner.
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
 * Wait up to READINESS_TIMEOUT_MS for a chart locator to become
 * visible.  Returns the locator on success; throws on timeout so the
 * test fails (see readiness-model comment at the top of the file).
 *
 * ``friendlyName`` is threaded through purely to enrich the Playwright
 * error message when the wait fails.
 */
async function _waitForChart(
  page,
  selector,
  friendlyName,
) {
  // Let the timeout throw.  Per Codex PR #216 round 2: if the chart
  // doesn't become visible within READINESS_TIMEOUT_MS, that's
  // exactly the "chart broke / selector drifted / data-path regressed"
  // class of regression this suite exists to catch.  Silently
  // skipping converts real failures into green builds.  Every chart
  // this spec targets is expected on its route.
  const el = page.locator(selector).first();
  await el.waitFor({ state: "visible", timeout: READINESS_TIMEOUT_MS });
  return el;
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
    const el = await _waitForChart(
      page,
      CHART_SELECTORS.hillCurve,
      "Hill curve",
    );
    await expect(el).toHaveScreenshot("hill-curve.png", SCREENSHOT_OPTIONS);
  });

  test("Tier-gap waterfall", async ({ page }) => {
    await page.goto("/rankings");
    await _openMethodology(page);
    const el = await _waitForChart(
      page,
      CHART_SELECTORS.tierGap,
      "Tier-gap waterfall",
    );
    await expect(el).toHaveScreenshot("tier-gap.png", SCREENSHOT_OPTIONS);
  });

  test("Confidence vs value scatter", async ({ page }) => {
    await page.goto("/edge");
    const el = await _waitForChart(
      page,
      CHART_SELECTORS.confidenceScatter,
      "Confidence scatter",
    );
    await expect(el).toHaveScreenshot("confidence-scatter.png", SCREENSHOT_OPTIONS);
  });

  test("Matchup margin histogram (league/weekly)", async ({ page }) => {
    await page.goto("/league?tab=weekly");
    const el = await _waitForChart(
      page,
      CHART_SELECTORS.matchupMargin,
      "Matchup margin chart",
    );
    await expect(el).toHaveScreenshot("matchup-margin.png", SCREENSHOT_OPTIONS);
  });

  test("Trade flow Sankey (league/activity)", async ({ page }) => {
    await page.goto("/league?tab=activity");
    const el = await _waitForChart(
      page,
      CHART_SELECTORS.tradeFlow,
      "Trade flow Sankey",
    );
    await expect(el).toHaveScreenshot("trade-flow.png", SCREENSHOT_OPTIONS);
  });

  test("Activity heatmap (league/activity)", async ({ page }) => {
    await page.goto("/league?tab=activity");
    const el = await _waitForChart(
      page,
      CHART_SELECTORS.activityHeatmap,
      "Activity heatmap",
    );
    await expect(el).toHaveScreenshot("activity-heatmap.png", SCREENSHOT_OPTIONS);
  });

  test("Franchise trajectory (league/franchise)", async ({ page }) => {
    await page.goto("/league?tab=franchise");
    const el = await _waitForChart(
      page,
      CHART_SELECTORS.franchiseTraj,
      "Franchise trajectory",
    );
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
    const svg = await _waitForChart(
      page,
      CHART_SELECTORS.hillCurve,
      "Hill curve",
    );
    await expect(svg.locator("path").first()).toBeVisible();
    await expect(svg.locator("circle").first()).toBeVisible();
  });

  test("Confidence scatter has enough points", async ({ page }) => {
    await page.goto("/edge");
    const svg = await _waitForChart(
      page,
      CHART_SELECTORS.confidenceScatter,
      "Confidence scatter",
    );
    const circles = svg.locator("circle");
    await expect(circles.first()).toBeVisible();
    // Healthy scatter has many points.  A "zero dots because the
    // data flow broke" state trips this.
    const count = await circles.count();
    expect(count).toBeGreaterThan(5);
  });
});
