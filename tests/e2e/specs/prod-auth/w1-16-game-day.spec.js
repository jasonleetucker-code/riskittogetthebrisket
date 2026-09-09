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
 * can legitimately be in several states on any given day — pregame priced,
 * pregame unpriced, live with a numeric probability, live with the
 * LIVE_PROGRESS_UNAVAILABLE degraded state (owner decision 2026-09-09: an
 * in-progress player's remaining is time-prorated when kickoff evidence is
 * usable; this state means it genuinely is not), live with game-state/
 * scoring evidence unavailable, or final — and the failure mode that matters is not
 * "it looked wrong", it is "it showed a number it had no right to". So each
 * state is asserted on what must and must not appear, and the run annotates
 * which state production was actually in. This is the W1-27/W1-28 evidence
 * instrument: it asserts on `body.mode` / `body.probabilityState`, whatever
 * they actually are on the day it runs, rather than assuming pregame.
 *
 * `/api/matchup/intel` no longer refuses a started week with 409 — that was
 * the pre-#1271 behaviour, before `resolve_scoring_week` could resolve
 * live/final state. `WeekInProgress`/409 and the frontend's
 * `code === "week_in_progress"` branch are dead code today (confirmed by
 * reading `resolve_scoring_week`, which always nulls the matchups it hands
 * to the inner pregame-only guard once the week has begun, so that guard
 * can never fire from this call path) but are left in place as a defensive
 * fallback rather than removed, since removing them is not required to
 * make this row's evidence collection correct.
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

    // 409 is dead code today (see the file header) but kept as a defensive
    // branch: if it were ever to fire again, this must not read as a
    // silent pass — it needs its own accounted-for annotation.
    if (status === 409) {
      await page.goto(prodUrl(`/game-day${q}`), { waitUntil: "domcontentloaded" });
      await expect(page.getByText(/This week has already started/)).toBeVisible({
        timeout: 60_000,
      });
      annotate(testInfo, "w1-16-branch", "409 — unexpected on the current implementation");
      return;
    }

    expect(status).toBe(200);
    expect(body).toBeTruthy();
    annotate(testInfo, "w1-16-week", `${body.season} week ${body.week}`);
    annotate(testInfo, "w1-27-mode", String(body.mode));
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
    // Wait for positive evidence that the client-side request completed.
    // Waiting only for the *absence* of the loading copy is racy: immediately
    // after navigation React may not have mounted GameDayPanel yet, so the
    // loading string is absent for one frame and that negative predicate
    // returns true before the request even starts. Production run 39 caught
    // exactly that state on both viewports. The endpoint's own team identity
    // is a stronger terminal signal and is required by this assertion anyway.
    await page.waitForFunction(
      (teamName) => document.body.innerText.includes(teamName),
      body.team.displayName,
      { timeout: 90_000 },
    );
    const text = await page.locator("body").innerText();

    // The matchup identity is a fact and must always render, in every mode.
    expect(text).toContain(body.team.displayName);
    if (body.opponent) expect(text).toContain(body.opponent.displayName);

    if (body.mode === "pregame") {
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
      return;
    }

    // LIVE or FINAL — this is the W1-27/W1-28 evidence. `ActualSide`
    // replaces `SideHeadline` in both modes, so the score/lineup facts must
    // render regardless of whether a probability can be shown at all.
    const final = body.mode === "final";
    expect(text).toContain(final ? "Final score" : "Current score");
    expect(text).toContain(final ? "Final optimal lineup" : "Current optimal lineup");

    if (final) {
      // A final result is a fact, not a forecast distribution — the page
      // must not render a probability card for it (W1-28's own acceptance
      // text: "preserves final optimal lineup/results").
      expect(text).not.toContain("Remaining-week probabilities");
      if (body.team?.result) {
        expect(text).toContain(body.team.result);
        annotate(testInfo, "w1-28-branch", `final — result ${body.team.result}`);
      } else {
        annotate(testInfo, "w1-28-branch", "final — result not yet resolvable for this side");
      }
      if (body.recapUrl) {
        expect(text).toContain("articles and recap");
        annotate(testInfo, "w1-28-recap", body.recapUrl);
      }
      return;
    }

    // LIVE. The probability half is exactly one of three truthful states —
    // never a fabricated number when evidence is incomplete. Do not assert
    // the live score's exact value: it is genuinely racy between this API
    // read and the panel's own independent 60s-interval fetch a few
    // seconds later, in either direction, while a game is actually live.
    annotate(testInfo, "w1-27-probability-state", String(body.probabilityState));
    if (body.probabilityState === "LIVE_PROGRESS_UNAVAILABLE") {
      // Owner methodology decision (2026-09-09): in-progress remaining
      // production is time-prorated; this state means real evidence exists
      // that a game is live, but no reliable kickoff/game-progress evidence
      // exists to prorate against — a missing-evidence report, never a
      // methodology-undecided one.
      expect(text).toContain("could not be estimated");
      expect(body.progressUnavailablePlayerIds?.length).toBeGreaterThan(0);
      annotate(testInfo, "w1-27-branch", "live — LIVE_PROGRESS_UNAVAILABLE, no fabricated probability");
    } else if (body.probabilityState === "GAME_STATE_OR_SCORING_UNAVAILABLE") {
      expect(text).toContain("Live probabilities unavailable");
      annotate(testInfo, "w1-27-branch", "live — game-state/scoring evidence incomplete");
    } else if (body.probabilityState === "AVAILABLE") {
      const win = body.team?.outcome?.winMatchupPct;
      expect(win, "AVAILABLE must carry a real number").not.toBeUndefined();
      expect(win).not.toBeNull();
      expect(text).toContain("Remaining-week probabilities");
      expect(text).toContain(`${win.toFixed(1)}%`);
      annotate(testInfo, "w1-27-branch", `live — priced, win ${win.toFixed(1)}%`);
    } else {
      // UNAVAILABLE: no simulation could be produced (e.g. zero coverage).
      // No probability card, and no fabricated number either.
      expect(text).not.toContain("Remaining-week probabilities");
      annotate(testInfo, "w1-27-branch", `live — ${body.probabilityState}`);
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

    // If this league's host semantics are unverified (for example an
    // unsupported odd-sized case), the surface must still say so.
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
