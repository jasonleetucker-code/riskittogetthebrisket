/**
 * W1-16 — the owner's Week 1 private matchup-intelligence experience is
 * deployed and production-verified for the selected team.
 *
 * Covers the `/game-day` surface (W1-14/W1-15/W1-25/W1-26 render here too —
 * one route, one owner). Authenticated, because the whole point of the row is
 * the OWNER'S experience, and everything on the page is private decision
 * intelligence under CLAUDE.md §5.
 *
 * TEAM RESOLUTION. The workflow's session is a GUEST pass (it logs in as
 * `guest`), so it carries no Sleeper user id and the league's default team map
 * does not name it — `/api/matchup/intel` would answer 400 `team_required` and
 * the page would show "No team selected". That is CORRECT behaviour and not
 * what this row is about, so the spec resolves a real team the way the other
 * prod-auth specs do — from `sleeper.teams` on the deployed authenticated
 * contract — and asks about that team explicitly. Recorded because a reader
 * would otherwise reasonably expect the session's own team to be used.
 *
 * The assertions are deliberately about TRUTHFULNESS, not pixels. This page
 * can legitimately be in one of three states on any given day — priced,
 * unpriced, or live — and the failure mode that matters is not "it looked
 * wrong", it is "it showed a number it had no right to". So each state is
 * asserted on what must and must not appear, and the run annotates which
 * state production was actually in.
 */
const {
  test,
  expect,
  prodUrl,
  getJson,
  annotate,
  desktopOnly,
  mobileOnly,
} = require("./helpers");

/**
 * A real ownerId from the deployed board. Same source `v1-27` uses
 * (`/api/data?view=app` → `sleeper.teams`), so the spec cannot drift onto a
 * team the production contract does not actually hold.
 */
async function resolveTeam(page) {
  const { status, body } = await getJson(page, "/api/data?view=app");
  expect(status, "/api/data must serve the session").toBe(200);
  const teams = (body && body.sleeper && body.sleeper.teams) || [];
  const withOwner = teams.filter((t) => t && t.ownerId);
  expect(withOwner.length, "contract carries no Sleeper team with an ownerId").toBeGreaterThan(0);
  return String(withOwner[0].ownerId);
}

test.describe("W1-16: the owner's Game Day experience (production)", () => {
  test("the page renders for the owner's own team and names its state", async ({
    prodPage: page,
  }, testInfo) => {
    const team = await resolveTeam(page);
    annotate(testInfo, "w1-16-team", team);
    await page.goto(prodUrl(`/game-day?team=${encodeURIComponent(team)}`), {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByRole("heading", { name: "Game Day" })).toBeVisible({ timeout: 60_000 });

    // Exactly one state badge, and it must be one of the real ones — a
    // surface that renders no state at all is the implicit default this
    // row exists to remove.
    //
    // The badge is NOT part of the initial page shell — GameDayPanel fetches
    // /api/matchup/intel client-side after mount, and (see the next test's
    // comment) a cold call against a real league can genuinely take tens of
    // seconds. `.count()` does not wait; checking it immediately after the
    // static heading appears raced the fetch and failed at 0+0 even when the
    // page was working correctly (measured in production, 2026-09-06). Wait
    // for the badge itself, on the same 90s budget as the direct API calls.
    const scheduled = page.getByText(/Scheduled · pregame/);
    const live = page.getByText(/^Live$/);
    await expect(scheduled.or(live)).toBeVisible({ timeout: 90_000 });
    const scheduledCount = await scheduled.count();
    const liveCount = await live.count();
    expect(scheduledCount + liveCount).toBeGreaterThan(0);
    annotate(testInfo, "w1-16-state", scheduledCount ? "SCHEDULED/pregame" : "LIVE");
  });

  test("the page's numbers are the endpoint's numbers", async ({ prodPage: page }, testInfo) => {
    // Same posture as the other prod-auth specs: read the API the page
    // reads, then require the page to show THAT. A screenshot-shaped
    // assertion would pass against a stale client bundle.
    const team = await resolveTeam(page);
    const q = `?team=${encodeURIComponent(team)}`;
    // 90s, matching this suite's existing convention for slow-loading
    // scenarios (v1-109/v1-111/v1-123-*): a cold call here runs the full
    // league-week Monte Carlo (measured production floor here, before
    // caching: 45-51s; the eligibility hoist + cache fix reduces this on
    // a WARM hit to ~1ms, but the very first caller for a league-week
    // still pays a real, if reduced, cost). 45s was proven too tight by
    // this exact call timing out at exactly that mark in production.
    const { status, body } = await getJson(page, `/api/matchup/intel${q}`, {
      timeoutMs: 90_000,
    });
    annotate(testInfo, "w1-16-endpoint-status", String(status));

    if (status === 409) {
      // Live week. The page must say so and show no probability at all.
      await page.goto(prodUrl(`/game-day${q}`), { waitUntil: "domcontentloaded" });
      await expect(page.getByText(/This week has already started/)).toBeVisible({
        timeout: 60_000,
      });
      annotate(testInfo, "w1-16-branch", "live — no pregame number shown");
      return;
    }

    expect(status).toBe(200);
    expect(body).toBeTruthy();
    annotate(testInfo, "w1-16-week", `${body.season} week ${body.week}`);
    annotate(
      testInfo,
      "w1-16-coverage",
      `${body.lineage?.estimateCoverage?.priced}/${body.lineage?.estimateCoverage?.active} priced`,
    );

    await page.goto(prodUrl(`/game-day${q}`), { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Game Day" })).toBeVisible({ timeout: 60_000 });
    // The "Game Day" heading is static SSR content and resolves near-instantly
    // — GameDayPanel's OWN client-side fetch to /api/matchup/intel is a
    // separate round trip that has not necessarily finished yet, even though
    // the direct getJson call above already warmed the cache. Measured in
    // production (run 35, 2026-09-06): reading body text right after the
    // heading raced this and caught the panel still showing its loading
    // state on both viewports (3.0s/5.4s total — fast, but not zero). Wait
    // for the loading state to clear, same pattern this suite already uses
    // for other client-fetched panels (v1-123-public-league-matrix.spec.js).
    await page.waitForFunction(
      () => !document.body.innerText.includes("Loading this week's matchup"),
      null,
      { timeout: 90_000 },
    );
    const text = await page.locator("body").innerText();

    // The matchup identity is a fact and must always render.
    expect(text).toContain(body.team.displayName);
    if (body.opponent) expect(text).toContain(body.opponent.displayName);

    const win = body.team?.outcome?.winMatchupPct;
    if (win === null || win === undefined) {
      // UNPRICED. The row is satisfied by an honest degraded state, not by
      // a number — and a fabricated 50% is the specific thing forbidden.
      expect(text).toContain("No projection");
      expect(text).not.toMatch(/\b50\.0%/);
      annotate(testInfo, "w1-16-branch", "unpriced — degraded state, no fabricated probability");
    } else {
      // PRICED. The page must show the endpoint's own figure.
      expect(text).toContain(`${win.toFixed(1)}%`);
      annotate(testInfo, "w1-16-branch", `priced — win ${win.toFixed(1)}%`);
    }
  });

  test("provenance travels with the numbers", async ({ prodPage: page }, testInfo) => {
    // W1-15's actual ask. A win probability with no stated projection
    // source, coverage or threshold-semantics flag is a number, not
    // intelligence.
    const team = await resolveTeam(page);
    const q = `?team=${encodeURIComponent(team)}`;
    // 90s — see the previous test's comment for why 45s is too tight here.
    const { status, body } = await getJson(page, `/api/matchup/intel${q}`, {
      timeoutMs: 90_000,
    });
    if (status === 409) {
      test.skip(true, "week in progress — the pregame lineage panel is not the question today");
      return;
    }
    expect(status).toBe(200);

    await page.goto(prodUrl(`/game-day${q}`), { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Where these numbers come from")).toBeVisible({ timeout: 60_000 });
    const text = await page.locator("body").innerText();

    const cov = body.lineage?.estimateCoverage || {};
    expect(text).toContain(`${cov.priced} of ${cov.active} active players priced`);

    // W1-23 is BLOCKED on host evidence; the surface must not present the
    // median leg as settled just because it rendered.
    if (body.lineage?.simulation && body.lineage.simulation.thresholdSemanticsVerified === false) {
      expect(text).toMatch(/is NOT verified/);
      annotate(testInfo, "w1-16-threshold", "unverified median semantics surfaced");
    }
  });

  test("it is private — anonymous callers get nothing", async ({ page }, testInfo) => {
    // No prodPage fixture here on purpose: this test wants the ANONYMOUS
    // behaviour of the same route.
    const res = await page.request.get(prodUrl("/api/matchup/intel"), { timeout: 45_000 });
    expect(res.status()).toBe(401);
    annotate(testInfo, "w1-16-anon-api", `HTTP ${res.status()}`);
  });

  test("W1-25: the shell offers Game Day in the My Team group", async ({
    prodPage: page,
  }, testInfo) => {
    // W1-25's navigation-shell clause. Asserted on the DEPLOYED shell
    // rather than by reading nav-model.js, because the row is about the
    // integrated shell and a source read cannot tell whether the built
    // bundle carries it.
    desktopOnly(test, testInfo);
    await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });
    // Shell readiness: the same "authenticated UI is hydrated" signal
    // v1-131-nav-gating uses.
    await expect(page.locator(".shell-search-btn")).toBeVisible({ timeout: 60_000 });

    await page.getByRole("button", { name: "My Team menu" }).click();
    const menu = page.locator('[role="menu"][aria-label="My Team"]');
    await expect(menu).toBeVisible();

    const item = menu.getByRole("menuitem", { name: /Game Day/ });
    await expect(item, "the My Team menu does not offer Game Day").toBeVisible();
    const href = await item.getAttribute("href");
    expect(href, "Game Day nav item points somewhere else").toContain("/game-day");
    annotate(testInfo, "w1-25-nav", `My Team → Game Day → ${href}`);
  });

  test("usable at a phone viewport without horizontal scroll", async ({
    prodPage: page,
  }, testInfo) => {
    mobileOnly(test, testInfo);
    const team = await resolveTeam(page);
    await page.goto(prodUrl(`/game-day?team=${encodeURIComponent(team)}`), {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByRole("heading", { name: "Game Day" })).toBeVisible({ timeout: 60_000 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    annotate(testInfo, "w1-16-mobile-overflow-px", String(overflow));
  });
});
