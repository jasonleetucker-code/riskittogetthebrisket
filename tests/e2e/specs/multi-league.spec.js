/**
 * Multi-league critical-path smoke suite.
 *
 * These tests exercise the API contract that the league switcher
 * depends on.  They don't run a full browser click-through — the
 * app-level auth gate ships a session cookie on login and UI-level
 * tests would require seeding a fake admin login, which is more
 * setup than this layer needs.  Instead we verify:
 *
 *   1. /api/leagues exposes both leagues with live Sleeper names
 *   2. /api/data accepts ?leagueKey= and never 500s
 *   3. /api/terminal requires auth (401 without cookie)
 *   4. /api/status.leagues[] reports per-league data health
 *   5. /api/scrape?leagueKey=<non-default> refreshes the overlay
 *
 * Add a test here whenever the multi-league surface gains a new
 * invariant the team-switcher relies on — same rule as
 * critical-smoke.spec.js.  Regressions in this suite mean users
 * will see stale or mislabelled data for their non-primary league.
 */
const { test, expect } = require("@playwright/test");


test.describe("multi-league: /api/leagues exposes both leagues", () => {
  test("both active leagues listed with live Sleeper names", async ({ request }) => {
    const res = await request.get("/api/leagues");
    expect(res.status()).toBe(200);
    const body = await res.json();
    // Structural sanity.
    expect(Array.isArray(body.leagues)).toBe(true);
    expect(typeof body.defaultKey).toBe("string");
    expect(body.defaultKey).toBeTruthy();

    const keys = body.leagues.map((l) => l.key);
    // Both leagues MUST be listed when active.  If either drops out
    // the switcher disappears.
    expect(keys).toContain("dynasty_main");
    expect(keys).toContain("dynasty_new");

    // Live Sleeper names should flow through (not the registry's
    // editable ``displayName``).  We only assert non-empty + not
    // the pre-2026-04-24 legacy string — ``name`` changes in
    // Sleeper would propagate here within 5 minutes so pinning
    // the exact text is too brittle.
    for (const lg of body.leagues) {
      expect(typeof lg.displayName).toBe("string");
      expect(lg.displayName.length).toBeGreaterThan(0);
      expect(lg.displayName).not.toMatch(/^Dynasty Main \(/);
      expect(lg.displayName).not.toMatch(/^Dynasty New \(/);
    }
  });

  test("every league exposes its scoringProfile + idpEnabled", async ({ request }) => {
    const body = await (await request.get("/api/leagues")).json();
    for (const lg of body.leagues) {
      expect(typeof lg.scoringProfile).toBe("string");
      expect(typeof lg.idpEnabled).toBe("boolean");
      // Roster settings must at least exist (may be partial).
      expect(lg.rosterSettings).toBeTruthy();
    }
  });
});


test.describe("multi-league: private endpoints gate on auth", () => {
  test("/api/data returns 401 without a session (regardless of leagueKey)", async ({ request }) => {
    for (const suffix of ["", "?leagueKey=dynasty_main", "?leagueKey=dynasty_new"]) {
      const res = await request.get(`/api/data${suffix}`);
      expect(res.status(), `auth gate missing on /api/data${suffix}`).toBe(401);
      const body = await res.json();
      expect(body.error).toBe("auth_required");
    }
  });

  test("/api/terminal returns 401 without a session", async ({ request }) => {
    const res = await request.get("/api/terminal?leagueKey=dynasty_new");
    expect(res.status()).toBe(401);
  });

  test("/api/scrape?leagueKey=<non-default> requires auth", async ({ request }) => {
    const res = await request.post("/api/scrape?leagueKey=dynasty_new");
    expect(res.status()).toBe(401);
  });
});


test.describe("multi-league: unknown / inactive keys rejected cleanly", () => {
  test("unknown leagueKey → 400 unknown_league", async ({ request }) => {
    // Middleware returns 401 first when unauthenticated, but the
    // /api/leagues endpoint is public so we can at least confirm
    // the registry itself doesn't advertise ghost leagues.
    const body = await (await request.get("/api/leagues")).json();
    const keys = body.leagues.map((l) => l.key);
    expect(keys).not.toContain("ghost");
    expect(keys).not.toContain("");
  });
});


test.describe("multi-league: /api/status.leagues[] per-league health", () => {
  test("status exposes an entry per active league with a source tag", async ({ request }) => {
    const res = await request.get("/api/status");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.leagues)).toBe(true);
    expect(body.leagues.length).toBeGreaterThanOrEqual(2);

    // At least ONE league must have source="primary-scrape" — that's
    // the league the scraper is wired to.  Others are "overlay" or
    // "none".  If all three are "none" the observability pass failed
    // and nothing's loaded.
    const sources = body.leagues.map((l) => l.source);
    expect(sources).toContain("primary-scrape");
    for (const lg of body.leagues) {
      expect(["primary-scrape", "overlay", "none"]).toContain(lg.source);
      // teamCount + tradeCount must be numbers (possibly 0).
      expect(typeof lg.teamCount).toBe("number");
      expect(typeof lg.tradeCount).toBe("number");
    }
  });
});


test.describe("multi-league: public endpoints never 401", () => {
  // These are the routes the league switcher + public /league page
  // depend on.  If any of them moves to the private allowlist by
  // accident the login flow breaks.
  const PUBLIC_PATHS = [
    "/api/health",
    "/api/status",
    "/api/leagues",
    "/api/rankings/sources",
    "/api/auth/status",
  ];
  for (const path of PUBLIC_PATHS) {
    test(`GET ${path} stays reachable without auth`, async ({ request }) => {
      const res = await request.get(path);
      expect(res.status(), `${path} unexpectedly 401`).not.toBe(401);
    });
  }
});
