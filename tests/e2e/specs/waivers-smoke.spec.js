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

  // ── Manual add/drop calculator (Phase B1+B8 surface) ───────────

  test("manual add/drop calculator section renders", async ({ authedPage }) => {
    await authedPage.goto("/waivers");
    // The calculator's heading is unique — distinguishes from the
    // existing Best Add/Drop Moves recommendation table.
    await expect(authedPage.locator("body")).toContainText(
      /Manual add\/drop calculator/i,
      { timeout: 10000 },
    );
    // Both pickers are labelled DROP / ADD and live in the
    // calculator card.  Use case-sensitive "DROP" + "ADD" labels
    // to avoid matching the bestMoves table's "Add" column header.
    await expect(authedPage.locator("body")).toContainText(/DROP/);
    await expect(authedPage.locator("body")).toContainText(/ADD/);
  });

  test("FAAB recommender endpoint returns the documented shape", async ({
    authedPage,
  }) => {
    // First grab a real player name from the live contract so the
    // endpoint resolves the lookup.  Using a hardcoded name would
    // fail every offseason as players retire/get cut.
    const dataRes = await authedPage.request.get("/api/data?view=app");
    expect(dataRes.ok(), "GET /api/data must succeed for the test").toBeTruthy();
    const contract = await dataRes.json();
    const players = Array.isArray(contract?.playersArray)
      ? contract.playersArray
      : [];
    expect(players.length).toBeGreaterThan(0);
    // Pick the highest-value non-pick — guaranteed to be a real
    // player the recommender can resolve.
    const target = players.find(
      (p) =>
        p?.assetClass !== "pick" &&
        Number.isFinite(Number(p?.rankDerivedValue)) &&
        Number(p?.rankDerivedValue) > 0,
    );
    expect(target?.displayName).toBeTruthy();

    const res = await authedPage.request.post(
      "/api/waiver/faab-recommend",
      {
        data: {
          addPlayerName: target.displayName,
        },
      },
    );
    expect(res.ok(), `POST /api/waiver/faab-recommend should be 2xx, got ${res.status()}`).toBeTruthy();
    const body = await res.json();
    // Documented shape (see src/trade/faab_recommender.py).
    for (const k of [
      "conservative",
      "standard",
      "aggressive",
      "max",
      "confidence",
      "factors",
      "warnings",
      "explanation",
    ]) {
      expect(body, `recommendation must include ${k}`).toHaveProperty(k);
    }
    expect(["low", "medium", "high"]).toContain(body.confidence);
    expect(Array.isArray(body.factors)).toBeTruthy();
    expect(Array.isArray(body.warnings)).toBeTruthy();
    expect(typeof body.explanation).toBe("string");
    // Bids are non-negative integers.
    for (const k of ["conservative", "standard", "aggressive", "max"]) {
      expect(Number.isInteger(body[k])).toBeTruthy();
      expect(body[k]).toBeGreaterThanOrEqual(0);
    }
  });
});
