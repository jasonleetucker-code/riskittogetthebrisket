/**
 * V1-123 Phase 2 — Team Strength/Weakness tab
 * (`/league?tab=rosTeamStrength`), on production.
 *
 * Note: the tab KEY is `rosTeamStrength` (camelCase) — confirmed directly
 * against frontend/app/league/tabs.js::VALID_TABS. There is no
 * `TAB_ALIASES` entry for a kebab-case `ros-team-strength`; that URL
 * would silently fall back to the default tab rather than 404, which is
 * exactly the kind of test bug already caught once this session on the
 * Phase 0 public-league-matrix spec's `conduct` alias. Using the real key
 * here from the start.
 *
 * No spec anywhere renders this section and asserts its table before
 * this — public-league.spec.js only proves the endpoint requires a
 * session (401 for anonymous), not page content.
 */
const { test, expect, prodUrl, annotate } = require("./helpers");

test.describe("V1-123 Phase 2: Team Strength/Weakness tab (production)", () => {
  test("ROS roster strength renders a real per-team table or an explicit not-ready state on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/league?tab=rosTeamStrength"), { waitUntil: "domcontentloaded" });

    const current = new URL(page.url());
    expect(current.searchParams.get("tab"), "tab must not have been rewritten to a different key").toBe(
      "rosTeamStrength",
    );

    const table = page.getByRole("table");
    const notReady = page.getByText(/ROS data not ready/i);
    const unavailable = page.getByText(/ROS roster strength unavailable/i);
    const settled = table.or(notReady).or(unavailable);
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });

    const hasTable = await table.isVisible().catch(() => false);
    if (hasTable) {
      const rows = table.locator("tbody tr");
      const rowCount = await rows.count();
      expect(rowCount, "ROS team strength table rendered with no rows").toBeGreaterThan(0);

      // Row click expands an inline detail row (starting lineup / bench depth).
      await rows.first().click();
      await expect(page.getByText(/Starting lineup/i)).toBeVisible({ timeout: 15_000 });

      annotate(testInfo, "states-observed", `ros-team-strength: populated (${rowCount} teams)`);
    } else {
      const which = (await notReady.isVisible().catch(() => false)) ? "not-ready" : "unavailable";
      annotate(testInfo, "states-observed", `ros-team-strength: ${which}`);
    }
  });
});
