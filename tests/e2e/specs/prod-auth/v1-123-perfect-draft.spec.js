/**
 * V1-123 Phase 1 — Perfect Draft budget optimizer on /draft, production.
 *
 * Ports ../journey-perfect-draft.spec.js onto a real authenticated
 * production session. That spec's own docstring explains why it exists:
 * the panel VANISHES on any non-ok response (flag off, no roster context,
 * wrong league, no solvable plan), and a vanished panel is DOM-identical
 * to a broken one — every unit test can pass while the feature is
 * unreachable in a browser, and that has actually happened here before.
 * So this spec asserts on ROWS and ARITHMETIC, never on a heading alone.
 *
 * State: the draft workspace lives entirely in the browser's localStorage
 * (never sent to the server as a mutation) and is seeded via
 * `addInitScript` with real team names read from the authenticated
 * production contract. Live Sleeper sync is explicitly pinned off so this
 * spec can never start polling a real draft.
 *
 * Desktop only (matches the local source spec's `desktopOnly` gate) — the
 * panel is a wide data-table surface not designed for the 390px viewport.
 */
const { test, expect, prodUrl, getJson, desktopOnly, annotate } = require("./helpers");

const LEAGUE = "dynasty_main";
const WORKSPACE_KEY = `next_draft_board_v1__${LEAGUE}`;
const LIVE_SYNC_KEY = `next_draft_live_sync__${LEAGUE}`;

const SEL = {
  draftBoard: ".draft-board-panel",
  perfectDraftPanel: ".perfect-draft-panel",
  perfectDraftRow: ".perfect-draft-panel .ds-table-wrap table tbody tr",
};

async function contractTeamNames(page) {
  const { status, body } = await getJson(page, "/api/data?view=app");
  expect(status, "GET /api/data?view=app must serve the authenticated session").toBe(200);
  const teams = body?.sleeper?.teams || [];
  return teams.map((t) => t?.name).filter(Boolean);
}

/**
 * Seed a draft workspace whose "my team" is a REAL team in the loaded
 * league. See the local source spec for why `feedBudget` must differ
 * from `initialBudget`: /draft auto-syncs budgets from /api/draft-capital
 * on mount, keyed by Sleeper TEAM name, while these are MANAGER names —
 * the two namespaces barely overlap, so an unseeded feedBudget gets
 * zeroed by the sync and the test fails for a reason unrelated to the
 * optimizer. Marking the row as user-edited (feedBudget !== initialBudget)
 * is a first-class state the sync preserves by design.
 */
async function seedWorkspace(page, teamNames, { myRemaining = 400 } = {}) {
  const teams = teamNames.slice(0, 12).map((name, i) => ({
    name,
    initialBudget: i === 0 ? myRemaining : 400,
    feedBudget: 0,
  }));
  await page.addInitScript(
    ([wsKey, syncKey, leagueKey, wsTeams]) => {
      window.localStorage.setItem("next_active_league_v1", leagueKey);
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

async function expectNoBadValueTokens(page, scopeSelector) {
  const bad = await page.evaluate((sel) => {
    const cells = Array.from(document.querySelectorAll(sel));
    return cells
      .map((el) => String(el.textContent || ""))
      .filter((t) => /\bNaN\b|\bundefined\b|\bnull\b/i.test(t));
  }, scopeSelector);
  expect(bad, `cells with NaN/undefined under ${scopeSelector}`).toEqual([]);
}

test.describe("V1-123 Phase 1: Perfect Draft (production)", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("recommends a buyable combination of real rookies on production", async ({
    prodPage: page,
  }, testInfo) => {
    // Lazy chunk + roster-context round trip (4 MB contract, lineup
    // solver, scarcity) + the solve. The default budget is not enough.
    test.setTimeout(180_000);

    const teamNames = await contractTeamNames(page);
    expect(teamNames.length, "the loaded league must carry rosters").toBeGreaterThan(1);
    await seedWorkspace(page, teamNames);

    await page.goto(prodUrl("/draft"), { waitUntil: "domcontentloaded" });

    const panel = page.locator(SEL.perfectDraftPanel);
    await expect(
      panel,
      "the panel returns null on any non-ok response, so invisible means broken",
    ).toBeVisible({ timeout: 90_000 });

    const budgetText = await panel.innerText();
    const seededBudget = budgetText.match(/BUDGET\s*\$([\d,]+)/i);
    expect(seededBudget, "the panel must render a Budget tile").not.toBeNull();
    expect(
      Number(seededBudget[1].replace(/,/g, "")),
      "budget is $0 — the seeded team budget was zeroed, so an empty plan " +
        "is correct and proves nothing about the optimizer",
    ).toBeGreaterThan(0);

    const rows = page.locator(SEL.perfectDraftRow);
    await expect(rows.first()).toBeVisible({ timeout: 60_000 });
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);

    const firstName = (await rows.first().locator("strong").first().innerText()).trim();
    expect(firstName.length).toBeGreaterThan(2);
    expect(firstName).not.toMatch(/^Rookie #/);

    await expectNoBadValueTokens(page, SEL.perfectDraftPanel);
    annotate(testInfo, "perfect-draft", `${rowCount} rows, top pick "${firstName}"`);
  });

  test("never plans to spend more than the budget on production", async ({
    prodPage: page,
  }) => {
    test.setTimeout(180_000);
    const teamNames = await contractTeamNames(page);
    await seedWorkspace(page, teamNames, { myRemaining: 120 });

    await page.goto(prodUrl("/draft"), { waitUntil: "domcontentloaded" });
    const panel = page.locator(SEL.perfectDraftPanel);
    await expect(panel).toBeVisible({ timeout: 90_000 });

    const text = await panel.innerText();
    const budget = text.match(/Budget\s*\$([\d,]+)/i);
    const spend = text.match(/Plan spend\s*\$([\d,]+)/i);
    expect(budget, "the summary must render a Budget tile").not.toBeNull();
    expect(spend, "the summary must render a Plan spend tile").not.toBeNull();
    const toNum = (m) => Number(m[1].replace(/,/g, ""));
    expect(toNum(spend)).toBeLessThanOrEqual(toNum(budget));
  });

  test("says which league state it is in rather than rendering an error on production", async ({
    prodPage: page,
  }) => {
    // A league whose rosters are not loaded must produce NO panel --
    // the documented posture -- rather than a banner or a plan built on
    // placeholders.
    await page.addInitScript(() => {
      window.localStorage.setItem("next_active_league_v1", "dynasty_new");
      window.localStorage.setItem("next_draft_live_sync__dynasty_new", "0");
    });
    await page.goto(prodUrl("/draft"), { waitUntil: "domcontentloaded" });
    await expect(page.locator(SEL.draftBoard).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.locator(SEL.perfectDraftPanel)).toHaveCount(0);
  });
});
