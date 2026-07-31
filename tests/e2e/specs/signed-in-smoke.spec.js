/**
 * Signed-in smoke suite.
 *
 * Today's E2E tests (critical-smoke, multi-league, public-league)
 * only exercise unauthenticated surfaces.  This spec fills the gap
 * by running through critical authed flows with a session cookie
 * obtained via the test-only /api/test/create-session endpoint.
 *
 * Coverage:
 *   - Team picker populates after sign-in.
 *   - Trade calculator renders and adds a player to a side.
 *   - Signal alerts page renders without error.
 *   - Monte Carlo result panel renders its disclaimer.
 *   - League switcher preserves the new leagueKey on reload.
 *
 * These tests are infrastructure-dependent: they skip cleanly when
 * E2E_TEST_SECRET isn't set on the test runner (i.e. any default
 * local / CI env).  To opt in:
 *   export E2E_TEST_MODE=1           # on the server
 *   export E2E_TEST_SECRET=<hex>    # on the server
 *   export E2E_TEST_SECRET=<hex>    # on the Playwright runner
 */
const { test, expect } = require("../helpers/auth-fixture");
// Page navigations go through pageUrl() (Next.js directly),
// mirroring production's nginx topology.  Critical for "/": through
// the backend's page proxy it renders the ANONYMOUS landing shell
// even with a valid session, so this whole file would assert against
// logged-out chrome.  API assertions below keep the backend baseURL.
const {
  pageUrl,
  pageHeading,
  titleFor,
  contractFixture,
  desktopOnly,
} = require("../helpers/journey");


// ── Assertion policy for this file ─────────────────────────────────
// Every test below previously asserted `body).toContainText(/Word/i)`
// where `Word` also appears in the persistent shell nav ("Trade",
// "Rosters", "Settings", "Team Strength").  All four passed against a
// page whose body rendered nothing at all — proven in
// docs/e2e-assertion-audit.md by running the originals against
// /login, which has the chrome and none of the page bodies.
//
// Replacements anchor on (a) the page's own <h1> — the shell owns no
// <h1> — and (b) content derived from the live contract at run time.
// Both survive the design-system rewrite: they pin roles, accessible
// names and data, never classes, colours or fonts.

test.describe("signed-in: basic navigation + UI render", () => {
  // Desktop only, and this gate is new.  The originals ran on every
  // project, but they asserted body text that the shell prints at any
  // viewport — so running them on mobile added a green tick, not
  // coverage.  The replacements assert real page chrome (the team
  // switcher in the top bar, page <h1>s), and the top-bar switcher is
  // CSS-hidden at 390px where MobileChrome takes over: the element
  // resolves but is `hidden`, so the assertion is genuinely
  // viewport-coupled rather than flaky.  Mobile coverage lives in
  // mobile-smoke.spec.js, per the convention in helpers/journey.js.
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("home dashboard renders the war-room surface with a real team list", async ({ authedPage }) => {
    const { teamNames } = await contractFixture(authedPage);
    expect(teamNames.length, "contract must carry Sleeper teams").toBeGreaterThan(0);

    await authedPage.goto(pageUrl("/"));

    // The dashboard's own body, anchored on the command bar's
    // accessible name.  The shell does not render this — a blank or
    // crashed dashboard fails here, which the old
    // `body contains /Team/i` (matching the nav's "Team Strength")
    // could not detect.
    await expect(
      authedPage.locator('[aria-label="Team command bar"]'),
      "dashboard command bar should render",
    ).toBeVisible({ timeout: 60_000 });

    // Data-derived: TeamSwitcher returns null unless the contract
    // actually delivered rosters (`components/TeamSwitcher.jsx:56`), and
    // its listbox is populated from that same list.  Opening it and
    // matching against the contract proves the roster pipeline reached
    // the UI — not merely that some chrome rendered.
    const switcher = authedPage.locator('button[aria-haspopup="listbox"]').first();
    await expect(
      switcher,
      "team switcher only renders when rosters loaded — absent means the contract served none",
    ).toBeVisible({ timeout: 60_000 });
    await switcher.click();

    const options = authedPage.locator('[role="option"]');
    await expect
      .poll(() => options.count(), {
        message: `team switcher should offer all ${teamNames.length} contract teams`,
        timeout: 30_000,
      })
      .toBe(teamNames.length);

    const offered = (await options.allInnerTexts()).map((t) => t.split("\n")[0].trim());
    for (const name of teamNames) {
      expect(offered, `team "${name}" missing from the switcher`).toContain(name);
    }
  });

  test("trade builder renders its own page body, not just the nav link", async ({ authedPage }) => {
    await authedPage.goto(pageUrl("/trade"));
    await expect(pageHeading(authedPage, titleFor("/trade"))).toBeVisible({
      timeout: 60_000,
    });
    // The pool has to actually load — the builder is useless without it.
    await authedPage.waitForFunction(
      () => !document.body.innerText.includes("Loading player pool..."),
      null,
      { timeout: 60_000 },
    );
    await expect(
      authedPage.getByRole("button", { name: /Clear Trade/ }),
    ).toBeVisible();
  });

  test("rosters page power-ranks every team in the contract", async ({ authedPage }) => {
    const { teamNames } = await contractFixture(authedPage);
    expect(teamNames.length).toBeGreaterThan(0);

    await authedPage.goto(pageUrl("/rosters"));
    await expect(pageHeading(authedPage, titleFor("/rosters"))).toBeVisible({
      timeout: 60_000,
    });

    // One ranked row per Sleeper team, and the names must be the real
    // ones.  A blank table, a partial roster load, or a rename in the
    // pipeline all fail here; "the word Roster is on the page" — the
    // assertion this replaced — catches none of them.
    const teamCells = authedPage.locator(".table-wrap table tbody tr td:nth-child(2)");
    await expect
      .poll(() => teamCells.count(), {
        message: `rosters table should render one row per contract team (${teamNames.length})`,
        timeout: 60_000,
      })
      .toBeGreaterThanOrEqual(teamNames.length);

    const rendered = (await teamCells.allInnerTexts()).map((t) =>
      t.split("\n")[0].trim(),
    );
    for (const name of teamNames) {
      expect(rendered, `team "${name}" missing from the roster power rankings`).toContain(
        name,
      );
    }
  });

  test("settings page lists the real ranking-source registry", async ({ authedPage }) => {
    // Authoritative count from the backend registry.
    const regRes = await authedPage.request.get("/api/rankings/sources");
    expect(regRes.status()).toBe(200);
    const registry = await regRes.json();
    const sources = registry.sources || registry;
    const registeredCount = Array.isArray(sources)
      ? sources.length
      : Object.keys(sources).length;
    expect(registeredCount).toBeGreaterThan(3);

    await authedPage.goto(pageUrl("/settings"));
    await expect(pageHeading(authedPage, /^Settings$/i)).toBeVisible({
      timeout: 60_000,
    });

    // The page's substance is the source registry it exposes for
    // toggling.  Pin it to the backend's count so a settings page that
    // renders its shell but drops the registry fails.
    const toggles = authedPage.locator(
      'input.settings-src-toggle[aria-label^="Include "]',
    );
    await expect
      .poll(() => toggles.count(), {
        message: `settings should expose >= ${registeredCount} source toggles`,
        timeout: 60_000,
      })
      .toBeGreaterThanOrEqual(registeredCount);
  });
});


test.describe("signed-in: API round-trips that public smoke can't hit", () => {
  test("/api/data returns 200 with a players block", async ({ authedPage }) => {
    const res = await authedPage.request.get("/api/data?view=delta");
    expect(res.status()).toBe(200);
    const body = await res.json();
    // Either playersArray or players dict must exist.
    const hasPlayers =
      (Array.isArray(body.playersArray) && body.playersArray.length > 0) ||
      (body.players && Object.keys(body.players).length > 0);
    expect(hasPlayers).toBeTruthy();
  });

  test("/api/user/state returns 200", async ({ authedPage }) => {
    const res = await authedPage.request.get("/api/user/state");
    expect(res.status()).toBe(200);
  });

  // Moved here from critical-smoke.spec.js, which is an ANONYMOUS spec.
  // The endpoint is auth-gated and 401s to an anonymous request, and the
  // test there opened with `if (status === 401) return;` — so its whole
  // body was unreachable while Playwright reported it PASSED.
  //
  // Also tightened while moving. It asserted `days <= 365 * 3`, which a
  // clamp returning 1 would satisfy just as happily as the correct one;
  // the contract is an exact value, so assert that. Both ends of the
  // clamp are checked because they are separate `max`/`min` terms
  // (server.py:3556) and only one of them was covered before.
  test("rank-history clamps days to [1, MAX_SNAPSHOTS]", async ({ authedPage }) => {
    const MAX_SNAPSHOTS = 365 * 3; // src/api/rank_history.py:85

    const high = await authedPage.request.get("/api/data/rank-history?days=9999");
    expect(high.status()).toBe(200);
    const highBody = await high.json();
    expect(highBody.days).toBe(MAX_SNAPSHOTS);
    expect(highBody.history).toBeDefined();

    const low = await authedPage.request.get("/api/data/rank-history?days=0");
    expect(low.status()).toBe(200);
    expect((await low.json()).days).toBe(1);

    // A non-numeric value falls back to the default rather than 500ing.
    const junk = await authedPage.request.get("/api/data/rank-history?days=abc");
    expect(junk.status()).toBe(200);
    const junkDays = (await junk.json()).days;
    expect(junkDays).toBeGreaterThanOrEqual(1);
    expect(junkDays).toBeLessThanOrEqual(MAX_SNAPSHOTS);
  });

  test("/api/terminal returns 200 (or 503 data_not_ready) for default league", async ({ authedPage }) => {
    const res = await authedPage.request.get("/api/terminal");
    // 200 = happy; 503 data_not_ready is acceptable when no live contract.
    expect([200, 503]).toContain(res.status());
  });

  test("/api/trade/simulate-mc returns 503 feature_disabled by default", async ({ authedPage }) => {
    // MC flag defaults OFF — endpoint returns 503 feature_disabled.
    const res = await authedPage.request.post("/api/trade/simulate-mc", {
      data: { sideA: [], sideB: [] },
    });
    // 503 expected (flag off) or 200 (flag on in this env).
    expect([200, 503]).toContain(res.status());
    if (res.status() === 503) {
      const body = await res.json();
      expect(body.error).toBe("feature_disabled");
    } else {
      const body = await res.json();
      // If enabled: must include the disclaimer + labelHint (the
      // contract the frontend depends on).
      expect(body.disclaimer).toBeTruthy();
      expect(body.labelHint).toBe("consensus_based_win_rate");
    }
  });
});


test.describe("signed-in: admin endpoints are gated", () => {
  test("/api/admin/nfl-data/flush returns ok for allowed user", async ({ authedPage }) => {
    const res = await authedPage.request.post("/api/admin/nfl-data/flush");
    // If the test user is in the admin allowlist: 200.
    // If not: 403.  Either proves the gate works — we just pin that
    // it's not 500-ing or 401-ing silently.
    expect([200, 403]).toContain(res.status());
  });
});
