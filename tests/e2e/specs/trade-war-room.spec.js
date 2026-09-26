/**
 * /trade — Trade War Room journey (#792 / #1173 / #843 / #842, Lane 6).
 *
 * The page is the production build on the seeded board; the trade is built
 * through the page's own team selector and side search.  `POST
 * /api/trade/analyze` is answered from `frontend/__tests__/fixtures/
 * trade-war-room/*.json`, which are REAL analyze output
 * (`tests/trade/war_room_ui_payloads.py`, pinned byte-equal to the backend
 * by `tests/trade/test_war_room_ui_fixtures.py`) — so the layout, 390 px
 * overflow, axe and the Team Context round trip are deterministic here.  The
 * live backend's own analysis is asserted by the prod-auth spec.
 *
 * Runs on every configured project (desktop-1366 and the phone projects).
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const FIXTURES = path.resolve(__dirname, "../../../frontend/__tests__/fixtures/trade-war-room");
const load = (name) => JSON.parse(fs.readFileSync(path.join(FIXTURES, `${name}.json`), "utf-8"));
const PICK_TOKEN = /\d{4}/;

test.use({ serviceWorkers: "block" });

async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, "the page must not scroll sideways").toBeLessThanOrEqual(sizes.viewport + 1);
}

/** A real team, one of its exactly-spelled players, and one player from another team. */
async function pickTrade(page) {
  // `view=app` strips playersArray; the helper's `playerNames` reads
  // whichever encoding the contract carries.
  const { teams, playerNames } = await contractFixture(page);
  const board = new Set(playerNames);
  for (const [idx, team] of teams.entries()) {
    const give = (team.players || []).find((p) => p && !PICK_TOKEN.test(p) && board.has(p));
    const other = teams.find((t) => t !== team);
    const receive = (other?.players || []).find(
      (p) => p && !PICK_TOKEN.test(p) && board.has(p) && !(team.players || []).includes(p),
    );
    if (give && receive) return { idx, team, give, receive };
  }
  throw new Error("no team with a board-resolvable player on the seeded contract");
}

async function addToSide(page, sideLabel, name) {
  const input = page.getByLabel(`Search to add a player to Side ${sideLabel}`);
  await input.click();
  await input.fill(name);
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const result = page
    .locator(".trade-side-search-result")
    .filter({ has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${escaped}$`) }) })
    .first();
  await expect(result).toBeVisible({ timeout: 15_000 });
  await result.click();
  await expect(page.getByRole("button", { name: `Remove ${name} from Side ${sideLabel}` })).toBeVisible();
}

test("trade war room: recommendation, three answers, Asset-Only round trip, no sideways scroll, axe clean", async ({
  authedPage: page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const requests = [];
  await page.route(
    (url) => url.pathname === "/api/trade/analyze",
    async (route) => {
      const body = route.request().postDataJSON() || {};
      requests.push(body);
      const payload = body.useTeamContext === false ? load("asset-only") : load("consolidation");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify({ ...payload, leagueKey: body.leagueKey || payload.leagueKey }),
      });
    },
  );

  const trade = await pickTrade(page);
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
  await page.selectOption("#suggest-team", String(trade.idx));
  await addToSide(page, "A", trade.give);
  await addToSide(page, "B", trade.receive);

  const room = page.locator('[data-war-room="ok"]');
  await expect(room).toBeVisible({ timeout: 30_000 });
  const consolidation = load("consolidation");
  await expect(room.getByText("Make the trade")).toBeVisible();
  for (const lens of ["market", "roster", "feasibility"]) {
    await expect(room.locator(`[data-lens="${lens}"]`)).toBeVisible();
  }
  await expect(room.getByText(consolidation.analysis.reasonsFor[0])).toBeVisible();
  // The page asked about THIS trade for THIS team.
  const first = requests.at(-1);
  expect(first.teamName).toBe(trade.team.name);
  expect(first.playersOut).toContain(trade.give);
  expect(first.playersIn).toContain(trade.receive);
  expect(first.useTeamContext).toBe(true);
  await noPageOverflow(page);
  const axe = await new AxeBuilder({ page }).withTags(TAGS).include('[aria-labelledby="war-room-title"]').analyze();
  await testInfo.attach("war-room-axe", { body: JSON.stringify(axe.violations, null, 2), contentType: "application/json" });
  expect(axe.violations).toEqual([]);
  const shot = testInfo.outputPath("war-room.png");
  await room.screenshot({ path: shot });
  await testInfo.attach("war-room", { path: shot, contentType: "image/png" });

  // Team Context OFF: a new question, roster lens excluded by mode.
  await page.getByRole("radio", { name: "Asset only" }).click();
  await expect(room.getByText(/not included in this analysis/)).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-war-room="ok"] [data-lens="roster"]').getByText("Not included in Asset-Only analysis").first()).toBeVisible();
  expect(requests.at(-1).useTeamContext).toBe(false);
  await noPageOverflow(page);
  expect(errors).toEqual([]);
});
