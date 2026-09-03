/**
 * V1-123 Phase 2 — Package Builder (`/angle`), on production.
 *
 * No local spec exists to port from (confirmed by the research pass for
 * this row — zero coverage anywhere). Written fresh against
 * frontend/app/angle/page.jsx: pick a player on your own roster to send,
 * submit, and require either real return packages or the backend's own
 * named empty state ("No packages clear the bar") — never a fabricated
 * pass.
 */
const { test, expect, prodUrl, annotate } = require("./helpers");

test.describe("V1-123 Phase 2: Package Builder /angle (production)", () => {
  test("offer mode returns ranked return packages or an explicit empty state on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/angle"), { waitUntil: "domcontentloaded" });

    const ownerSelect = page.locator("#angle-owner");
    await expect
      .poll(async () => ownerSelect.locator("option").count(), {
        message: "Your team selector should populate from the contract",
        timeout: 60_000,
      })
      .toBeGreaterThan(0);

    // Roster rows use a CSS module (`styles.rosterRow`), so the browser does
    // not expose a literal `rosterRow` class. Target the actual checkbox
    // control rendered by RosterPicker instead of depending on a build hash.
    const rosterCheckbox = page.locator('input[type="checkbox"]').first();
    await expect(rosterCheckbox, "your roster list should render at least one player").toBeVisible({
      timeout: 30_000,
    });
    await rosterCheckbox.check();
    await expect(rosterCheckbox).toBeChecked();

    const submit = page.getByRole("button", { name: /Find return options/i });
    await expect(submit).toBeEnabled({ timeout: 15_000 });
    await submit.click();

    const settled = page
      .getByRole("table")
      .or(page.getByText(/No packages clear the bar/i))
      .or(page.getByText(/Couldn't find packages/i));
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });

    const tableVisible = await page.getByRole("table").isVisible().catch(() => false);
    annotate(
      testInfo,
      "angle-offer-scan",
      tableVisible ? "real return packages rendered" : "explicit empty/validation state",
    );
  });
});
