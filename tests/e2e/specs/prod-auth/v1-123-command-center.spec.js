/**
 * V1-123 Phase 2 — Command Center / home dashboard (`/`), on production.
 *
 * Ports the assertions from ../signed-in-smoke.spec.js's home-dashboard
 * test onto a real authenticated production session: the war-room
 * surface renders with a real team command header, and the team
 * switcher's menu lists the same teams the contract itself reports.
 */
const { test, expect, prodUrl, getJson, annotate } = require("./helpers");

test.describe("V1-123 Phase 2: Command Center (production)", () => {
  test("home dashboard renders the war-room surface with a real team list on production", async ({
    prodPage: page,
  }, testInfo) => {
    const { status, body: contract } = await getJson(page, "/api/data?view=app");
    expect(status).toBe(200);
    const teamNames = (contract?.sleeper?.teams || []).map((t) => t.name).filter(Boolean);
    expect(teamNames.length, "contract served no Sleeper teams to compare against").toBeGreaterThan(0);

    await page.goto(prodUrl("/"), { waitUntil: "domcontentloaded" });

    const commandBar = page.locator('[aria-label="Team command bar"]');
    await expect(commandBar).toBeVisible({ timeout: 60_000 });
    await expect(page.locator('[aria-label="Team aggregates"]')).toBeVisible({ timeout: 30_000 });

    // Desktop and mobile variants coexist in the responsive shell. `.first()`
    // can select the hidden desktop button on a mobile viewport, so operate on
    // the variant that is actually visible to the production user.
    const switcherToggle = page.locator("button.team-switcher-toggle:visible").first();
    await expect(switcherToggle).toBeVisible({ timeout: 15_000 });
    await switcherToggle.click();
    const menu = page.locator(".team-switcher-menu:visible").first();
    await expect(menu).toBeVisible({ timeout: 15_000 });
    const options = await menu.locator('[role="option"]').allInnerTexts();
    const trimmedOptions = options.map((o) => o.trim()).filter(Boolean);

    const missing = teamNames.filter(
      (name) => !trimmedOptions.some((opt) => opt.includes(name)),
    );
    expect(
      missing,
      `team switcher menu is missing contract teams: ${missing.join(", ")}`,
    ).toEqual([]);

    annotate(testInfo, "command-center-teams", `${trimmedOptions.length} teams in switcher, ${teamNames.length} in contract`);
  });
});
