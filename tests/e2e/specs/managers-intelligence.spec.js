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

// ── Batch D: trade tools seeded from a scouted roster ─────────────────────
//
// GET /api/manager-intel/league is answered by page.route.  The journey opens
// the scouting page on one manager (`?manager=`, the link a searched
// manager's Leagues list carries), picks assets and checks that the tool links
// carry them through the tools' own restore formats — `/trade?share=` and
// `/arbitrage?tool=builder` — without navigating into the tools themselves.

const D_LEAGUE_ID = "1312006700437352448";
const D_OWNER = "735693375101108224";
const D_RECEIPT = {
  id: "geom_q078_v1",
  family: "geom",
  version: "1",
  label: "Geometric Value Adjustment (q = 0.78)",
  classification: "ACTIVE",
};

function dManager(rosterId, ownerUserId, displayName) {
  return {
    rosterId,
    ownerUserId,
    displayName,
    teamName: null,
    orphan: false,
    coOwnerCount: 0,
    record: { wins: 3, losses: 3, ties: null, pointsFor: null },
    valueRank: rosterId,
    roster: {
      playerCount: 2,
      rosterSpots: 9,
      starters: 1,
      bench: 1,
      taxi: 0,
      reserve: 0,
      pricedCount: 1,
      unpricedCount: 1,
      unpricedReasons: { not_on_board: 1 },
      pricedValue: 5000,
      valueNote: null,
      byPosition: {
        RB: { count: 1, pricedCount: 1, unpricedCount: 0, pricedValue: 5000, rank: 1 },
        WR: { count: 1, pricedCount: 0, unpricedCount: 1, pricedValue: null, rank: null },
      },
      topPlayers: [],
      players: [
        { playerId: `p${rosterId}a`, name: `Alpha Back ${rosterId}`, position: "RB",
          slot: "starter", boardName: `Alpha Back ${rosterId}`, value: 5000, rank: 20,
          valueReason: null },
        { playerId: `p${rosterId}z`, name: `Zed Unranked ${rosterId}`, position: "WR",
          slot: "bench", boardName: null, value: null, rank: null,
          valueReason: "not_on_board" },
      ],
    },
    draftCapital: {
      pickOwnershipState: "observed",
      counts: { held: 1, own: 1, acquired: 0, ownTradedAway: 0 },
      pricedValue: 3500,
      picks: [
        { kind: "pick", season: 2027, round: 1, originRosterId: rosterId,
          pickId: `pick:dynasty_main:2027:r1:o${rosterId}`, label: "2027 Round 1",
          boardRowName: "2027 Round 1", value: 3500, valueBasis: "board_row",
          valueReason: null, originOwnerName: displayName, currentOwnerRosterId: rosterId,
          currentOwnerName: displayName, own: true },
      ],
    },
    activity: { trades: 0, playersAdded: 0, playersDropped: 0, lastActivityAt: null },
    tendencies: null,
    tendenciesSource: "manager_scout",
    scout: null,
  };
}

const D_PAYLOAD = {
  status: "ok",
  query: { leagueId: D_LEAGUE_ID },
  league: {
    leagueId: D_LEAGUE_ID,
    name: "Our Dynasty",
    season: "2026",
    format: { superflex: true, teams: 2 },
    registryLeague: true,
    registryKey: "dynasty_main",
  },
  season: "2026",
  currentSeason: "2026",
  window: "30d",
  windowApplied: "30d",
  hasBoard: true,
  managers: [dManager(1, "1001", "Ann"), dManager(2, D_OWNER, "Dana")],
  managerCount: 2,
  ranking: { rankedRosters: 2, withheld: null, note: "" },
  draftCapital: { available: true, valueNote: "" },
  tendencies: { source: "manager_scout", minSample: 3 },
  scout: null,
  tradeTools: {
    leagueScoped: true,
    leagueKey: "dynasty_main",
    reason: null,
    packageModel: D_RECEIPT,
  },
  coverage: {},
  valueBasis: {},
  cached: false,
};

function decodeShare(href) {
  const encoded = new URL(href, "http://x").searchParams.get("share");
  return JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
}

test("Batch D: seed the trade tools from a scouted manager", async ({
  authedPage: page,
}) => {
  await page.route("**/api/manager-intel/league**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(D_PAYLOAD),
    }),
  );
  await page.goto(
    pageUrl(`/managers/league/${D_LEAGUE_ID}?manager=${D_OWNER}`),
    { waitUntil: "domcontentloaded" },
  );
  await awaitStreamSettled(page);
  const tools = page.getByRole("region", { name: "Trade tools for Dana" });
  await expect(tools).toBeVisible({ timeout: 60_000 });

  // The unresolved player is listed, unselectable, and never priced at 0.
  await expect(tools.getByLabel(/Zed Unranked 2/)).toBeDisabled();
  await expect(tools).toContainText("Unresolved: not on the canonical board");

  await tools.getByLabel(/Alpha Back 2/).check();
  await tools.getByLabel(/^2027 Round 1/).check();
  const calc = tools.getByRole("link", { name: "Open in Trade Calculator" });
  const share = decodeShare(await calc.getAttribute("href"));
  expect(share.s[1].p).toEqual(["Alpha Back 2", "2027 Round 1"]);
  expect(share.s[1].a).toEqual([null, "pick:dynasty_main:2027:r1:o2"]);
  expect(share.pm).toBe(D_RECEIPT.id);
  await expect(tools.getByRole("link", { name: "Analyze Trade" })).toBeVisible();

  const builder = await tools
    .getByRole("link", { name: "Package Builder" })
    .getAttribute("href");
  const params = new URL(builder, "http://x").searchParams;
  expect(params.get("tool")).toBe("builder");
  expect(params.get("league")).toBe("dynasty_main");
  expect(params.get("opponent")).toBe(D_OWNER);
});
