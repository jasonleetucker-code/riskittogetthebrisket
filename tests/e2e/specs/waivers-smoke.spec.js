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
// /waivers is served by Next.js but is NOT in server.py's explicit
// page-route list, so the backend origin 404s it — production works
// because nginx routes page traffic straight to Next.  pageUrl()
// (E2E_PAGE_ORIGIN) reproduces that topology for local/CI runs.
const { pageUrl, NAME, awaitStreamSettled } = require("../helpers/journey");

test.describe("signed-in: /waivers page", () => {
  test("renders header + sections", async ({ authedPage }) => {
    await authedPage.goto(pageUrl("/waivers"));
    // /waivers has a loading.jsx, so the App Router streams it. Let the swap
    // finish before any strict locator runs — see awaitStreamSettled (#716).
    await awaitStreamSettled(authedPage);
    // Assert the page's OWN <h1>, not body text: the R1 shell puts a
    // "Waivers" nav link in the sidebar on every page, so a body-level
    // /Waivers/i match passed even when the page itself failed to
    // render — a vacuous assertion.
    await expect(
      authedPage.getByRole("heading", { level: 1, name: /Waivers/i }),
    ).toBeVisible({ timeout: 30000 });
    await expect(authedPage.locator("body")).toContainText(
      /Best add\/drop moves|Addable|Droppable|Pick your team/i,
      { timeout: 30000 },
    );
  });

  test("rookie toggle is present and toggleable", async ({ authedPage }) => {
    await authedPage.goto(pageUrl("/waivers"));
    // /waivers has a loading.jsx, so the App Router streams it. Let the swap
    // finish before any strict locator runs — see awaitStreamSettled (#716).
    await awaitStreamSettled(authedPage);
    const toggle = authedPage.getByLabel(NAME.waiverRookieToggle, {
      exact: false,
    });
    await expect(toggle).toBeVisible({ timeout: 30000 });
    // Operable: clicking it doesn't throw.
    await toggle.click();
    await toggle.click();
  });

  test("position filter dropdown is present", async ({ authedPage }) => {
    await authedPage.goto(pageUrl("/waivers"));
    // /waivers has a loading.jsx, so the App Router streams it. Let the swap
    // finish before any strict locator runs — see awaitStreamSettled (#716).
    await awaitStreamSettled(authedPage);
    const select = authedPage.getByLabel(NAME.waiverPositionFilter);
    await expect(select).toBeVisible({ timeout: 30000 });
  });

  // ── Manual add/drop calculator (Phase B1+B8 surface) ───────────

  test("manual add/drop calculator section renders", async ({ authedPage }) => {
    await authedPage.goto(pageUrl("/waivers"));
    // /waivers has a loading.jsx, so the App Router streams it. Let the swap
    // finish before any strict locator runs — see awaitStreamSettled (#716).
    await awaitStreamSettled(authedPage);
    // The calculator's heading is unique — distinguishes from the
    // existing Best Add/Drop Moves recommendation table.
    await expect(authedPage.locator("body")).toContainText(
      /Manual add\/drop calculator/i,
      { timeout: 30000 },
    );
    // Both pickers are labelled DROP / ADD (case-sensitive, to avoid
    // matching the bestMoves table's "Add" column header) — but they
    // only render once a team is selected.  A session without a
    // selected team (the e2e test user) shows the calculator's
    // pick-a-team empty state instead; both are valid "section
    // renders" outcomes.
    //
    // This must NOT branch on a single innerText read.  The page passes
    // through three distinct bodies while it settles — signed-out
    // shell, signed-in-without-team, then the team picker — and a read
    // that lands on the middle one contains NEITHER "Select a team" nor
    // "DROP", picks the else branch, and then waits 15s for a "DROP"
    // that this session will never render.  Same hydration race as the
    // archives one, in its read-once-then-branch form: the branch is
    // decided on a frame that is not the final frame.
    //
    // Poll for whichever settled state actually arrives.
    const body = authedPage.locator("body");
    await expect
      .poll(
        async () => {
          const text = await body.innerText();
          if (/Select a team .* calculator/i.test(text)) return "pick-a-team";
          if (/DROP/.test(text) && /ADD/.test(text)) return "pickers";
          return "unsettled";
        },
        {
          message:
            "the calculator should settle on either its pick-a-team empty " +
            "state or its DROP/ADD pickers",
          timeout: 30_000,
          intervals: [250, 500, 1000, 2000],
        },
      )
      .not.toBe("unsettled");
  });

  test("FAAB recommender endpoint returns the documented shape", async ({
    authedPage,
  }) => {
    // First grab a real player name from the live contract so the
    // endpoint resolves the lookup.  Using a hardcoded name would
    // fail every offseason as players retire/get cut.
    // view=delta: the app view intentionally omits playersArray (payload
    // optimization) — delta and full both carry it.
    const dataRes = await authedPage.request.get("/api/data?view=delta");
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
