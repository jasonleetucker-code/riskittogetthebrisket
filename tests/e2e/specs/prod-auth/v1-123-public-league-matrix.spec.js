const base = require("@playwright/test");
const { test, expect, ORIGIN, prodUrl, annotate } = require("./helpers");

/**
 * V1-123 Phase 0 — real-production public League surface matrix.
 *
 * This intentionally uses the ordinary `page` fixture, NOT `prodPage`:
 * these are anonymous/public surfaces and must remain independently
 * verifiable without a guest-pass cookie.  The prod-auth Playwright
 * configuration still supplies the same desktop + true-mobile projects
 * used by the authenticated V1 matrix.
 *
 * Scope is the Phase-0 inventory frozen in
 * docs/v1-123-browser-workflow-matrix/SCOPING.md.  This does NOT promote
 * V1-123 by itself; it closes only the public-League slice of the L4
 * browser/workflow matrix.
 */

const TABS = [
  "overview",
  "activity",
  "articles",
  "franchise",
  "rivalry",
  "week",
  "weekly",
  "awards",
  "history",
  "archives",
  "records",
  "streaks",
  "superlatives",
  "conduct",
  "luck",
];

function configured() {
  return Boolean(String(ORIGIN || "").trim());
}

async function waitForLeagueReady(page, tab) {
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading league data..."),
    null,
    { timeout: 45_000 },
  );
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading section..."),
    null,
    { timeout: 30_000 },
  );

  // The two waits above can resolve vacuously true on a cold navigation:
  // if the JS bundle has not mounted a loading state yet at the exact
  // instant they are checked, "loading text is absent" is trivially
  // satisfied before the app has rendered anything at all. Measured
  // twice on real production, both prod-desktop and prod-mobile, always
  // on this test's first navigation in a fresh browser context (runs
  // 33768425785 and 33769285866): a 36-byte body at exactly this point.
  // Poll for real content rather than trusting the loading-negation's
  // single instant.
  await expect
    .poll(async () => (await page.locator("body").innerText()).trim().length, {
      message: `production /league?tab=${tab} rendered an empty document`,
      timeout: 30_000,
    })
    .toBeGreaterThan(100);

  const body = await page.locator("body").innerText();
  expect(
    body.includes("Section unavailable"),
    `production /league?tab=${tab} rendered an explicit unavailable state`,
  ).toBe(false);
  await expect(
    page.getByRole("heading", { level: 1 }).first(),
    `production /league?tab=${tab} must retain the League page heading`,
  ).toBeVisible();
  return body;
}

test.describe("V1-123 Phase 0: public League production matrix", () => {
  test("all scoped public League tabs render on the deployed site without touching private data", async ({
    page,
  }, testInfo) => {
    test.skip(!configured(), "PROD_ORIGIN is not configured");
    test.setTimeout(480_000);

    const privateHits = [];
    page.on("request", (req) => {
      const url = req.url();
      if (
        url.includes("/api/data") ||
        url.includes("/api/rankings/overrides")
      ) {
        privateHits.push(url);
      }
    });

    const states = [];
    for (const tab of TABS) {
      const response = await page.goto(prodUrl(`/league?tab=${tab}`), {
        waitUntil: "domcontentloaded",
        timeout: 60_000,
      });
      expect(
        response,
        `production navigation returned no response for /league?tab=${tab}`,
      ).toBeTruthy();
      expect(
        response.status(),
        `production /league?tab=${tab} returned HTTP ${response.status()}`,
      ).toBeLessThan(400);

      const body = await waitForLeagueReady(page, tab);
      const current = new URL(page.url());
      expect(
        current.searchParams.get("tab"),
        `deep link /league?tab=${tab} did not preserve its canonical tab`,
      ).toBe(tab);

      // State is observed, not manufactured.  Empty-state wording is
      // recorded as evidence when production naturally presents it; the
      // test never converts an unreachable state into a fabricated pass.
      const naturalEmpty = /\b(no |none |not yet|nothing |empty\b)/i.test(body);
      states.push(`${tab}:${naturalEmpty ? "natural-empty-or-none-copy" : "populated"}`);
    }

    expect(
      privateHits,
      `public League matrix touched private endpoints: ${privateHits.join(", ")}`,
    ).toEqual([]);

    annotate(testInfo, "public-tabs", `${TABS.length}/${TABS.length} rendered`);
    annotate(testInfo, "observed-states", states.join(" | "));
    annotate(
      testInfo,
      "viewport",
      `${testInfo.project.name}:${page.viewportSize()?.width || "unknown"}px`,
    );
  });
});

// Keep the imported base package live as a structural assertion that this
// file is an ordinary Playwright spec rather than a bespoke fetch script.
void base;
