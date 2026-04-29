/**
 * Waiver Add/Drop page smoke suite.
 *
 * Mirrors the signed-in-smoke pattern: uses the auth fixture so the
 * page hydrates with a real /api/data + /api/leagues + roster
 * payload.  Skips cleanly if E2E_TEST_SECRET is unset.
 *
 * Coverage:
 *   - /waivers route renders the page header + at least one section.
 *   - The "Include rookies" toggle is present and operable.
 *   - The position filter is present and operable.
 */
const { test, expect } = require("../helpers/auth-fixture");

test.describe("signed-in: /waivers page", () => {
  test("renders header + sections", async ({ authedPage }) => {
    await authedPage.goto("/waivers");
    // Page header content + one of the four sections must be visible.
    await expect(authedPage.locator("body")).toContainText(
      /Waiver Add\/Drop/i,
      { timeout: 10000 },
    );
    await expect(authedPage.locator("body")).toContainText(
      /Best Add\/Drop Moves|Addable Players|Droppable Players|Pick your team/i,
      { timeout: 10000 },
    );
  });

  test("rookie toggle is present and toggleable", async ({ authedPage }) => {
    await authedPage.goto("/waivers");
    const toggle = authedPage.getByLabel(/Include rookies/i, { exact: false });
    await expect(toggle).toBeVisible({ timeout: 10000 });
    // Operable: clicking it doesn't throw.
    await toggle.click();
    await toggle.click();
  });

  test("position filter dropdown is present", async ({ authedPage }) => {
    await authedPage.goto("/waivers");
    const select = authedPage.getByLabel(/Position filter/i);
    await expect(select).toBeVisible({ timeout: 10000 });
  });
});
