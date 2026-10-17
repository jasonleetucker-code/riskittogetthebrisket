/**
 * /managers — Manager Intelligence (C6-MGR-02 Batch A), end to end in the
 * browser.
 *
 * GET /api/manager-intel/profile is answered by page.route, so the spec never
 * calls Sleeper.  What it pins is the browser half: search -> portfolio table
 * -> expand a player to his leagues -> filter -> deep link -> an unknown user
 * shows the backend's message.  Unpriced players render "—", never 0.  Runs
 * on every project (desktop and phone).
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, SEL } = require("../helpers/journey");

test.use({ serviceWorkers: "block" });

const PROFILE = {
  status: "ok",
  query: "dynastyfan",
  manager: {
    userId: "1001",
    username: "dynastyfan",
    displayName: "Dynasty Fan",
  },
  season: "2026",
  scope: "dynasty",
  leagueCounts: { dynasty: 2, keeper: 0, redraft: 1, unknown: 0 },
  leaguesInScope: 2,
  truncated: false,
  maxLeagues: 60,
  leaguesUnreadable: 0,
  leagues: [
    {
      leagueId: "L1",
      name: "Alpha Dynasty",
      format: { superflex: true, tePremium: true, idp: true, teams: 12 },
      state: "ok",
      coOwned: false,
      record: { wins: 4, losses: 2, ties: 0 },
      playerCount: 2,
    },
    {
      leagueId: "L2",
      name: "Beta Dynasty",
      format: { superflex: false, teams: 10 },
      state: "ok",
      coOwned: true,
      record: { wins: 1, losses: 5, ties: 0 },
      playerCount: 1,
    },
  ],
  players: [
    {
      playerId: "4046",
      name: "Justin Jefferson",
      position: "WR",
      nflTeam: "MIN",
      age: 27,
      value: 9500,
      overallRank: 2,
      leagues: [
        { leagueId: "L1", slot: "starter" },
        { leagueId: "L2", slot: "bench" },
      ],
      leaguesOwned: 2,
      exposure: {
        owned: 2,
        eligibleLeagues: 2,
        eligibilityUnknownLeagues: 0,
        share: 1,
      },
    },
    {
      playerId: "9999",
      name: "Obscure Linebacker",
      position: "LB",
      nflTeam: "NYJ",
      age: null,
      value: null,
      overallRank: null,
      leagues: [{ leagueId: "L1", slot: "taxi" }],
      leaguesOwned: 1,
      exposure: {
        owned: 1,
        eligibleLeagues: 1,
        eligibilityUnknownLeagues: 0,
        share: 1,
      },
    },
  ],
  summary: {
    leaguesRead: 2,
    ownedInstances: 3,
    uniquePlayers: 2,
    offenseInstances: 2,
    idpInstances: 1,
    ageMedian: 27,
    ageKnownPlayers: 1,
    top10InstanceShare: 1,
    byFormat: {
      superflex: {
        leagues: 1,
        instances: 2,
        pricedInstances: 1,
        boardValue: 9500,
      },
    },
  },
  valueBasis: {
    note: "Values are the canonical board's; they are summed only over Superflex leagues.",
  },
  hasBoard: true,
  cached: false,
};

async function mockProfile(page) {
  const calls = [];
  await page.route("**/api/manager-intel/profile**", async (route) => {
    const url = new URL(route.request().url());
    const username = url.searchParams.get("username");
    calls.push(username);
    if (username === "ghost") {
      return route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({
          error: "not_found",
          message: "No Sleeper user named 'ghost'.",
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PROFILE),
    });
  });
  return calls;
}

async function openManagers(page, path = "/managers") {
  await page.goto(pageUrl(path), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(
    page.getByRole("heading", { level: 1, name: /^Manager Intelligence$/ }),
  ).toBeVisible({ timeout: 60_000 });
  // The shell's search button renders only once the client has hydrated;
  // typing before that is wiped when React takes over the controlled input.
  // (Attached, not visible: the phone layout hides it behind the menu.)
  await expect(page.locator(SEL.navSearchButton).first()).toBeAttached({
    timeout: 60_000,
  });
}

test("search, expand, filter and deep link a manager portfolio", async ({
  authedPage: page,
}) => {
  const calls = await mockProfile(page);
  await openManagers(page);

  await page.getByLabel("Sleeper username").fill("dynastyfan");
  await page.getByRole("button", { name: "Look up" }).click();
  await expect(
    page.getByRole("heading", { name: "Dynasty Fan" }),
  ).toBeVisible();
  expect(calls).toEqual(["dynastyfan"]);

  const table = page.getByRole("table");
  const lbRow = table.locator("tr", { hasText: "Obscure Linebacker" });
  await expect(lbRow).toContainText("—");
  await expect(table).toContainText("2 / 2 (100%)");

  await page
    .getByRole("button", { name: "Show leagues for Justin Jefferson" })
    .click();
  const detail = page.getByRole("list", {
    name: "Leagues for Justin Jefferson",
  });
  await expect(detail).toContainText("Alpha Dynasty");
  await expect(detail).toContainText("Bench");

  await page.getByLabel("Position").selectOption("LB");
  await expect(table).not.toContainText("Justin Jefferson");

  await expect(page).toHaveURL(/username=dynastyfan/);
  await openManagers(page, "/managers?username=dynastyfan");
  await expect(
    page.getByRole("heading", { name: "Dynasty Fan" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "dynastyfan" })).toBeVisible();
});

test("an unknown user shows the backend's message", async ({
  authedPage: page,
}) => {
  await mockProfile(page);
  await openManagers(page);
  await page.getByLabel("Sleeper username").fill("ghost");
  await page.getByRole("button", { name: "Look up" }).click();
  await expect(page.getByText("No Sleeper user named 'ghost'.")).toBeVisible();
});
