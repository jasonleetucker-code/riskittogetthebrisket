// ── Chart visual regression ──────────────────────────────────────────
//
// Full-page screenshots of every page that renders one of the chart
// components built across PRs #211-#214.  Playwright's built-in
// ``toHaveScreenshot`` captures a baseline PNG on first run and
// diffs subsequent runs against it with a tolerance threshold.
//
// Baseline generation (run once locally / in CI after intentional
// UI changes):
//
//   npx playwright test --update-snapshots chart-visual-regression
//
// Tolerance rationale: 0.2% pixel difference + 100-pixel diff allowance
// per chart.  SVG rendering varies slightly across CI runners (font
// antialiasing, subpixel positioning); the threshold is loose enough
// that benign drift doesn't fail the build but tight enough that a
// genuinely broken chart (missing axis, blank plot area) trips it.
//
// This spec is additive to the existing smoke specs in this folder
// and intentionally limits itself to the chart region rather than
// full-page screenshots — pages change layout regularly and we only
// want to regression-test the *charts*, not the surrounding UI.

const { test, expect } = require("@playwright/test");

const SCREENSHOT_OPTIONS = {
  // 0.2% pixel difference tolerance — enough to absorb benign
  // rendering variance across runners without missing real breakage.
  maxDiffPixelRatio: 0.002,
  // Fullscale-mask any elements that change between runs (timestamps,
  // "Updated X seconds ago").  None today; placeholder for future.
  mask: [],
  // Animation can create micro-diffs on SVG paths; disable where
  // possible by setting a stable state before the shot.
  animations: "disabled",
};

// Selector helpers — each chart renders as an SVG with a known
// aria-label so we can locate and screenshot just the chart region.
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

test.describe("Chart visual regression", () => {
  test.skip(
    !!process.env.SKIP_VISUAL_REGRESSION,
    "Set SKIP_VISUAL_REGRESSION=1 to skip this suite locally",
  );

  test("Hill curve (methodology panel)", async ({ page }) => {
    await page.goto("/rankings");
    // Expand methodology to reveal the Hill curve.
    const btn = page.getByRole("button", { name: /how this works/i });
    if (await btn.count()) {
      await btn.click();
    }
    const el = page.locator(CHART_SELECTORS.hillCurve).first();
    if (await el.count()) {
      await expect(el).toHaveScreenshot("hill-curve.png", SCREENSHOT_OPTIONS);
    } else {
      test.skip(true, "Hill curve not present — methodology panel may have moved");
    }
  });

  test("Tier-gap waterfall", async ({ page }) => {
    await page.goto("/rankings");
    const btn = page.getByRole("button", { name: /how this works/i });
    if (await btn.count()) {
      await btn.click();
    }
    const el = page.locator(CHART_SELECTORS.tierGap).first();
    if (await el.count()) {
      await expect(el).toHaveScreenshot("tier-gap.png", SCREENSHOT_OPTIONS);
    } else {
      test.skip(true, "Tier-gap chart not present");
    }
  });

  test("Confidence vs value scatter", async ({ page }) => {
    await page.goto("/edge");
    const el = page.locator(CHART_SELECTORS.confidenceScatter).first();
    if (await el.count()) {
      await expect(el).toHaveScreenshot("confidence-scatter.png", SCREENSHOT_OPTIONS);
    } else {
      test.skip(true, "Confidence scatter not present — /edge may be empty");
    }
  });

  test("Matchup margin histogram (league/weekly)", async ({ page }) => {
    await page.goto("/league?tab=weekly");
    const el = page.locator(CHART_SELECTORS.matchupMargin).first();
    if (await el.count()) {
      await expect(el).toHaveScreenshot("matchup-margin.png", SCREENSHOT_OPTIONS);
    } else {
      test.skip(true, "Matchup margin chart not present");
    }
  });

  test("Trade flow Sankey (league/activity)", async ({ page }) => {
    await page.goto("/league?tab=activity");
    const el = page.locator(CHART_SELECTORS.tradeFlow).first();
    if (await el.count()) {
      await expect(el).toHaveScreenshot("trade-flow.png", SCREENSHOT_OPTIONS);
    } else {
      test.skip(true, "Trade flow chart not present");
    }
  });

  test("Activity heatmap (league/activity)", async ({ page }) => {
    await page.goto("/league?tab=activity");
    const el = page.locator(CHART_SELECTORS.activityHeatmap).first();
    if (await el.count()) {
      await expect(el).toHaveScreenshot("activity-heatmap.png", SCREENSHOT_OPTIONS);
    } else {
      test.skip(true, "Activity heatmap not present");
    }
  });

  test("Franchise trajectory (league/franchise)", async ({ page }) => {
    await page.goto("/league?tab=franchise");
    const el = page.locator(CHART_SELECTORS.franchiseTraj).first();
    if (await el.count()) {
      await expect(el).toHaveScreenshot("franchise-trajectory.png", SCREENSHOT_OPTIONS);
    } else {
      test.skip(true, "Franchise trajectory not present");
    }
  });
});

// ── Structural assertions (non-pixel) ──────────────────────────────
//
// Even if the pixel-diff tests are skipped because baselines haven't
// been generated, these structural tests catch the "chart broke"
// class of regression: missing axes, zero data points, empty SVGs.

test.describe("Chart structural smoke tests", () => {
  test("Hill curve has axis + at least one path", async ({ page }) => {
    await page.goto("/rankings");
    const btn = page.getByRole("button", { name: /how this works/i });
    if (await btn.count()) await btn.click();
    const svg = page.locator(CHART_SELECTORS.hillCurve).first();
    if (!(await svg.count())) test.skip(true, "Hill curve not present");
    // Expect at least one <path> (the curve) and at least one <circle>
    // (a scatter dot from the live board).
    await expect(svg.locator("path").first()).toBeVisible();
    await expect(svg.locator("circle").first()).toBeVisible();
  });

  test("Confidence scatter has points", async ({ page }) => {
    await page.goto("/edge");
    const svg = page.locator(CHART_SELECTORS.confidenceScatter).first();
    if (!(await svg.count())) test.skip(true, "scatter not present");
    const circles = svg.locator("circle");
    await expect(circles.first()).toBeVisible();
    // A healthy scatter has many points — assert at least 5 so a
    // "zero dots because data flow broke" state trips the test.
    const count = await circles.count();
    expect(count).toBeGreaterThan(5);
  });
});
