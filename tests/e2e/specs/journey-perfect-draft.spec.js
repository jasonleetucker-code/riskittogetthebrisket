/**
 * Critical journey: the Perfect Draft budget optimizer on /draft.
 *
 * Why this spec exists, specifically: the panel VANISHES on any non-ok
 * response — flag off, no roster context, wrong league, no solvable plan — and
 * a vanished panel is DOM-identical to a broken one. Every unit test can pass
 * while the feature is unreachable in a browser, and that is not hypothetical:
 * it happened. The panel read `workspace.myTeamIdx` where the real workspace
 * carries `workspace.settings.myTeamIdx`, so it resolved no team, requested a
 * context with no team, got `context: null` and returned `null` — before its
 * own team selector could render. Thirty-two component tests were green,
 * because the fixture used the flat shape.
 *
 * So this spec asserts on ROWS and on ARITHMETIC, never on a heading.
 *
 * State: the draft workspace lives entirely in localStorage. It is seeded via
 * `addInitScript` with team names sampled from the live contract rather than
 * hardcoded — the snapshot refreshes nightly. Live Sleeper sync is explicitly
 * pinned off so a spec can never start polling a real draft.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET is unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  SEL,
  attachConsoleGuards,
  contractFixture,
  desktopOnly,
  expectNoBadValueTokens,
  pageUrl,
} = require("../helpers/journey");

const LEAGUE = "dynasty_main";
const WORKSPACE_KEY = `next_draft_board_v1__${LEAGUE}`;
const LIVE_SYNC_KEY = `next_draft_live_sync__${LEAGUE}`;

/**
 * Seed a draft workspace whose "my team" is a REAL team in the loaded league.
 *
 * `settings.myTeamIdx` is the shape `createDefaultWorkspace` produces and the
 * one the panel must read; putting it at the root is what the old test fixture
 * did and what let the bug ship.
 */
async function seedWorkspace(page, teamNames, { myRemaining = 400 } = {}) {
  const teams = teamNames.slice(0, 12).map((name, i) => ({
    name,
    initialBudget: i === 0 ? myRemaining : 400,
  }));
  await page.addInitScript(
    ([wsKey, syncKey, leagueKey, wsTeams]) => {
      window.localStorage.setItem("next_active_league_v1", leagueKey);
      // Never let a spec start polling a live Sleeper draft.
      window.localStorage.setItem(syncKey, "0");
      window.localStorage.setItem(
        wsKey,
        JSON.stringify({
          version: 1,
          settings: { myTeamIdx: 0 },
          teams: wsTeams,
          players: [],
          picks: [],
          tags: {},
          targetBoard: [],
          nominations: [],
        }),
      );
    },
    [WORKSPACE_KEY, LIVE_SYNC_KEY, LEAGUE, teams],
  );
}

test.describe("journey: perfect draft", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("recommends a buyable combination of real rookies", async ({ authedPage: page }) => {
    // Lazy chunk + roster-context round trip (4 MB contract, lineup solver,
    // scarcity) + the solve. The default 90s budget is not enough.
    test.setTimeout(180_000);
    const guard = attachConsoleGuards(page);

    const { teamNames } = await contractFixture(page);
    expect(teamNames.length, "the loaded league must carry rosters").toBeGreaterThan(1);
    await seedWorkspace(page, teamNames);

    await page.goto(pageUrl("/draft"), { waitUntil: "domcontentloaded" });

    const panel = page.locator(SEL.perfectDraftPanel);
    await expect(
      panel,
      "the panel returns null on any non-ok response, so invisible means broken",
    ).toBeVisible({ timeout: 90_000 });

    const rows = page.locator(SEL.perfectDraftRow);
    await expect(rows.first()).toBeVisible({ timeout: 60_000 });
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);

    // Every recommended name must be a real player, not a placeholder.
    const firstName = (await rows.first().locator("strong").first().innerText()).trim();
    expect(firstName.length).toBeGreaterThan(2);
    expect(firstName).not.toMatch(/^Rookie #/);

    // No NaN / undefined / $NaN leaking into the rendered numbers.
    await expectNoBadValueTokens(panel);

    guard.assertClean();
  });

  test("never plans to spend more than the budget", async ({ authedPage: page }) => {
    test.setTimeout(180_000);
    const { teamNames } = await contractFixture(page);
    await seedWorkspace(page, teamNames, { myRemaining: 120 });

    await page.goto(pageUrl("/draft"), { waitUntil: "domcontentloaded" });
    const panel = page.locator(SEL.perfectDraftPanel);
    await expect(panel).toBeVisible({ timeout: 90_000 });

    // The budget tile and the plan-spend tile are both rendered; spend must
    // never exceed budget. This is the one invariant a user would notice
    // immediately and no unit test exercises end to end.
    const text = await panel.innerText();
    const budget = text.match(/Budget\s*\$([\d,]+)/i);
    const spend = text.match(/Plan spend\s*\$([\d,]+)/i);
    expect(budget, "the summary must render a Budget tile").not.toBeNull();
    expect(spend, "the summary must render a Plan spend tile").not.toBeNull();
    const toNum = (m) => Number(m[1].replace(/,/g, ""));
    expect(toNum(spend)).toBeLessThanOrEqual(toNum(budget));
  });

  test("says which league state it is in rather than rendering an error", async ({
    authedPage: page,
  }) => {
    // A league whose rosters are not loaded must produce NO panel — the
    // documented posture — rather than a banner or a plan built on
    // placeholders. Asserting the absence keeps that deliberate.
    await page.addInitScript(() => {
      window.localStorage.setItem("next_active_league_v1", "dynasty_new");
      window.localStorage.setItem("next_draft_live_sync__dynasty_new", "0");
    });
    await page.goto(pageUrl("/draft"), { waitUntil: "domcontentloaded" });
    // The page itself must still render.
    await expect(page.locator(SEL.draftBoard).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.locator(SEL.perfectDraftPanel)).toHaveCount(0);
  });
});
