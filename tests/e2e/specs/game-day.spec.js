/**
 * /game-day — deterministic replay E2E: states, layout, keyboard, axe and
 * refresh-in-place (Game Day U7; #1335 / #1334, owner escalation 2026-09-24).
 *
 * NO NETWORK, NO PRODUCTION DATA.  Every `/api/matchup/intel` answer is a
 * REAL backend payload: `tests/game_day/ui_payloads.py` runs the U5 shared
 * collector and `build_matchup_intel` over the committed U4 replay captures
 * and writes `frontend/__tests__/fixtures/game-day/*.json`
 * (`tests/game_day/test_game_day_ui_fixtures.py` pins that they are exactly
 * what the backend emits).  This spec serves those files to the browser with
 * `page.route`, so the page is the production build rendering production-
 * shaped answers; only the transport is stubbed.  `/api/leagues` is stubbed
 * too so the league context is fixed.
 *
 * Covered, on every viewport project (desktop 1366 and the phone projects):
 * pregame, halftime (live), overtime (win chance withheld with its named
 * reason), live feed down (ESPN 403 → freshness "partial"), stale,
 * week final; no horizontal page scroll; WCAG A/AA axe on each state and on
 * the opened detail; the Best-ball details disclosure reached and opened by
 * keyboard; a background refresh that updates the numbers WITHOUT blanking
 * the page, keeping an opened section open and focus where it was.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const FIXTURES = path.resolve(__dirname, "../../../frontend/__tests__/fixtures/game-day");
const load = (name) => JSON.parse(fs.readFileSync(path.join(FIXTURES, `${name}.json`), "utf-8"));
const ROUTE = "/game-day?team=owner-8&leagueKey=dynasty_main";

const LEAGUES = {
  leagues: [{ key: "dynasty_main", displayName: "Replay league", active: true }],
  defaultKey: "dynasty_main",
  userDefaultKey: "dynasty_main",
};

// A service worker would answer page fetches itself and bypass page.route
// (see admin-guest-pass.spec.js).
test.use({ serviceWorkers: "block" });

/** Serve `current()` for every matchup request; returns a request counter. */
async function serveReplay(page, current, { delayMs = () => 0 } = {}) {
  const calls = { count: 0 };
  // URL predicates, not globs: baseURL is the API origin while pages come
  // from E2E_PAGE_ORIGIN, and a string pattern resolves against baseURL.
  await page.route(
    (url) => url.pathname === "/api/matchup/intel",
    async (route) => {
      calls.count += 1;
      const wait = delayMs(calls.count);
      if (wait) await new Promise((resolve) => setTimeout(resolve, wait));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify(current()),
      });
    },
  );
  await page.route(
    (url) => url.pathname === "/api/leagues",
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LEAGUES) }),
  );
  return calls;
}

async function open(page, payload) {
  await page.goto(pageUrl(ROUTE), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.locator('[data-game-day-ready="true"]')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(`Week ${payload.week} · ${payload.season}`)).toBeVisible();
}

async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, "the page must not scroll sideways").toBeLessThanOrEqual(sizes.viewport + 1);
}

async function scan(page, testInfo, name) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).include("main").analyze();
  await testInfo.attach(`${name}-axe`, {
    body: JSON.stringify(results.violations, null, 2),
    contentType: "application/json",
  });
  expect(results.violations, `${name} must have no WCAG A/AA violations`).toEqual([]);
}

async function image(page, testInfo, name) {
  const file = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: file, animations: "disabled" });
  await testInfo.attach(name, { path: file, contentType: "image/png" });
}

const hero = (page) => page.getByRole("table", { name: /matchup:/ });
const heroSection = (page) => page.locator('section[aria-labelledby="game-day-hero-title"]');

const STATES = [
  {
    name: "pregame",
    check: async (page) => {
      await expect(heroSection(page).getByText("Upcoming", { exact: true })).toBeVisible();
      await expect(hero(page).getByRole("columnheader", { name: "Score now" })).toHaveCount(0);
      await expect(hero(page).getByRole("columnheader", { name: "Win chance" })).toBeVisible();
      await expect(page.getByText(/^Current · as of/)).toBeVisible();
    },
  },
  {
    name: "halftime",
    check: async (page) => {
      await expect(heroSection(page).getByText("Live", { exact: true })).toBeVisible();
      await expect(hero(page).getByText("Sleeper shows 26.8")).toBeVisible();
      await expect(page.locator('[data-game-id="2026_3_ATL_GB"]')).toContainText("Halftime");
    },
  },
  {
    name: "overtime",
    check: async (page) => {
      await expect(page.getByText("Overtime in ATL @ GB: win chance paused.")).toBeVisible();
      await expect(hero(page).getByText("Paused").first()).toBeVisible();
      await expect(hero(page).getByText(/%$/)).toHaveCount(0);
    },
  },
  {
    name: "live-feed-down",
    check: async (page) => {
      await expect(page.getByText(/^Partial · as of .* · live game feed unavailable$/)).toBeVisible();
      await expect(page.getByText(/Game status unknown for ATL @ GB/)).toBeVisible();
      await expect(hero(page).getByText(/%$/)).toHaveCount(0);
    },
  },
  {
    name: "pending",
    check: async (page) => {
      await expect(page.getByText("Computing the forecast")).toBeVisible();
      await expect(hero(page).getByText("Computing…").first()).toBeVisible();
      await expect(hero(page).getByText(/%$/)).toHaveCount(0);
      await expect(page.getByText("Win chance paused")).toHaveCount(0);
    },
  },
  {
    name: "stale",
    check: async (page) => {
      await expect(page.getByText(/^Stale · as of .*\(2 h old\)/)).toBeVisible();
      await expect(page.getByText("These numbers are out of date")).toBeVisible();
    },
  },
  {
    name: "week-final",
    check: async (page) => {
      await expect(hero(page).getByRole("columnheader", { name: "Final score" })).toBeVisible();
      await expect(hero(page).getByText("WIN")).toBeVisible();
      await expect(page.getByRole("heading", { name: "What matters now" })).toHaveCount(0);
    },
  },
];

for (const state of STATES) {
  test(`game-day ${state.name}: renders the replay payload, no sideways scroll, axe clean`, async ({
    authedPage: page,
  }, testInfo) => {
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const payload = load(state.name);
    await serveReplay(page, () => payload);
    await open(page, payload);
    await state.check(page);
    // The hierarchy: hero, then the collapsed detail disclosures.
    await expect(page.getByRole("button", { name: "Best-ball details" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await expect(page.getByRole("button", { name: "Data info" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await noPageOverflow(page);
    await scan(page, testInfo, state.name);
    await image(page, testInfo, state.name);
    expect(errors).toEqual([]);
  });
}

test("game-day: Best-ball details and a game's players open by keyboard; opened detail stays axe clean", async ({
  authedPage: page,
}, testInfo) => {
  const payload = load("halftime");
  await serveReplay(page, () => payload);
  await open(page, payload);
  const disclosure = page.getByRole("button", { name: "Best-ball details" });
  let reached = false;
  for (let i = 0; i < 120 && !reached; i += 1) {
    await page.keyboard.press("Tab");
    reached = await disclosure.evaluate((el) => el === document.activeElement);
  }
  expect(reached, "the disclosure must be reachable with Tab").toBe(true);
  await page.keyboard.press("Enter");
  await expect(disclosure).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("heading", { name: "Currently counting" }).first()).toBeVisible();

  const tnf = page.locator('[data-game-id="2026_3_ATL_GB"]');
  const players = tnf.getByRole("button", { name: /players/i });
  await players.focus();
  await page.keyboard.press("Enter");
  await expect(players).toHaveAttribute("aria-expanded", "true");
  await expect(tnf.getByRole("table")).toBeVisible();

  await page.getByRole("button", { name: "Data info" }).click();
  await expect(page.getByRole("table", { name: /data sources and their freshness/ })).toBeVisible();
  await noPageOverflow(page);
  await scan(page, testInfo, "details-open");
  await image(page, testInfo, "details-open");
});

test("game-day: a refresh updates in place — no blank, sections stay open, focus stays", async ({
  authedPage: page,
}, testInfo) => {
  const first = load("halftime");
  const second = JSON.parse(JSON.stringify(first));
  second.team.scoreNow.bestBallFromBankedPoints = 44.4;
  second.team.outcome.winMatchupPct = 64.2;
  let current = first;
  // The refresh's response is held for 1.5 s so the in-between state is
  // observable: the old answer must still be on screen, marked updating.
  const calls = await serveReplay(page, () => current, {
    delayMs: (n) => (n > 1 ? 1500 : 0),
  });
  await open(page, first);
  const root = await page.locator('[data-game-day-ready="true"]').elementHandle();

  await page.getByRole("button", { name: "Data info" }).click();
  await expect(page.getByRole("table", { name: /data sources and their freshness/ })).toBeVisible();
  const refresh = page.getByRole("button", { name: /Refresh|Updating/ });
  await refresh.focus();
  current = second;
  await page.keyboard.press("Enter");

  // Mid-refresh: previous content still rendered, a local status says so.
  await expect(page.getByText("Updating this matchup…")).toBeVisible();
  await expect(hero(page).getByText("31.1")).toBeVisible();
  await expect(page.locator('[data-game-day-ready="true"][aria-busy="true"]')).toHaveCount(1);

  await expect(hero(page).getByText("44.4")).toBeVisible();
  await expect(hero(page).getByText("64.2%")).toBeVisible();
  expect(calls.count).toBe(2);
  // Same DOM root (no remount, so no scroll jump), section still open,
  // focus still on the control that asked for the refresh.
  expect(await root.evaluate((el) => el.isConnected)).toBe(true);
  await expect(page.getByRole("button", { name: "Data info" })).toHaveAttribute("aria-expanded", "true");
  await expect(refresh).toBeFocused();
  await image(page, testInfo, "after-refresh");
});

/**
 * TEAM SWITCHER (owner directive 2026-09-25).  Answers are served by the
 * requested `team`: owner-8 and owner-10 are REAL payloads (the two sides of
 * one halftime generation); owner-3 is LABELLED SYNTHETIC — owner-8's real
 * payload re-keyed — used only as a third distinct identity for the race.
 * owner-10's answer is held for 2.5 s so a quick A -> C switch leaves it in
 * flight: it must never replace C.
 */
function byTeam() {
  const mine = load("halftime");
  const opponent = load("halftime-opponent");
  const third = JSON.parse(JSON.stringify(mine));
  const t = third.leagueTeams.find((x) => x.ownerId === "owner-3");
  third.team = { ...third.team, ownerId: "owner-3", rosterId: t.rosterId, displayName: t.displayName };
  return { "owner-8": mine, "owner-10": opponent, "owner-3": third };
}

async function serveByTeam(page, payloads, slowTeam) {
  const seen = [];
  await page.route(
    (url) => url.pathname === "/api/matchup/intel",
    async (route) => {
      const qs = new URL(route.request().url()).searchParams;
      const team = qs.get("team");
      seen.push({ team, leagueKey: qs.get("leagueKey") });
      if (team === slowTeam) await new Promise((resolve) => setTimeout(resolve, 2500));
      const body = payloads[team];
      await route.fulfill({
        status: body ? 200 : 404,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify(body || { error: "team_not_found", leagueKey: "dynasty_main" }),
      });
    },
  );
  await page.route(
    (url) => url.pathname === "/api/leagues",
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LEAGUES) }),
  );
  return seen;
}

test("game-day: switch team A -> B -> C in the selected league; stale answers never land", async ({
  authedPage: page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const payloads = byTeam();
  const seen = await serveByTeam(page, payloads, "owner-10");
  await open(page, payloads["owner-8"]);
  const picker = page.getByRole("combobox", { name: "Viewing team" });
  await expect(picker).toBeVisible();
  await expect(picker).toHaveValue("owner-8");
  await expect(hero(page).locator("caption")).toContainText("Team 8 versus Team 10");
  await noPageOverflow(page);

  // Reachable by keyboard, before the hero's own controls.
  await page.locator("body").focus();
  let reached = false;
  for (let i = 0; i < 80 && !reached; i += 1) {
    await page.keyboard.press("Tab");
    reached = await picker.evaluate((el) => el === document.activeElement);
  }
  expect(reached, "the team picker must be reachable with Tab").toBe(true);

  // A: the opponent (held in flight), then quickly C.
  await picker.selectOption("owner-10");
  await expect(page).toHaveURL(/team=owner-10/);
  await expect(page.getByText(/Loading .*matchup/)).toBeVisible();
  await picker.selectOption("owner-3");
  await expect(page).toHaveURL(/team=owner-3/);
  await expect(page).toHaveURL(/leagueKey=dynasty_main/);
  await expect(hero(page).locator("caption")).toContainText("Team 3 versus");
  await expect(picker).toHaveValue("owner-3");
  // Outlive the held owner-10 answer: C stays on screen.
  await page.waitForTimeout(3000);
  await expect(hero(page).locator("caption")).toContainText("Team 3 versus");
  await expect(page.locator('[data-game-day-team="owner-3"]')).toHaveCount(1);
  await noPageOverflow(page);
  await scan(page, testInfo, "team-switched");
  await image(page, testInfo, "team-switched");

  // Back walks to the previous team; this time its answer lands.
  await page.goBack();
  await expect(page).toHaveURL(/team=owner-10/);
  await expect(hero(page).locator("caption")).toContainText("Team 10 versus Team 8", {
    timeout: 15_000,
  });
  const opp = payloads["owner-10"].team.outcome.winMatchupPct.toFixed(1);
  await expect(hero(page).getByRole("row", { name: /Team 10/ }).first()).toContainText(`${opp}%`);
  await expect(picker).toHaveValue("owner-10");

  // Refresh keeps the chosen team.
  await page.reload({ waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(hero(page).locator("caption")).toContainText("Team 10 versus Team 8", {
    timeout: 30_000,
  });
  // Every request stayed in the selected league.
  expect(seen.map((r) => r.team)).toEqual(expect.arrayContaining(["owner-8", "owner-10", "owner-3"]));
  expect(new Set(seen.map((r) => r.leagueKey))).toEqual(new Set(["dynasty_main"]));
  await noPageOverflow(page);
  await image(page, testInfo, "team-after-reload");
  expect(errors).toEqual([]);
});

/**
 * LIVE MEDIAN RACE (owner directive 2026-09-26).  Real replay payloads; the
 * board is the backend's `medianRace` block.  Covers every viewport project:
 * all rosters once, the league-median summary, no sideways scroll, axe clean,
 * a row tap switching Game Day through ?team=, and long team names that wrap
 * between words only.
 */
test("game-day median race: the whole league, a row switches the team, no sideways scroll, axe clean", async ({
  authedPage: page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const payloads = byTeam();
  // LABELLED SYNTHETIC: long real-shaped team names on the board.
  for (const p of Object.values(payloads)) {
    for (const t of p.medianRace.teams) {
      if (t.rosterId === "1") t.teamName = "The Rossini Panini Dynasty Collective of Greater Brisketville";
      if (t.rosterId === "2") t.teamName = "Supercalifragilisticexpialidocious";
    }
  }
  await serveByTeam(page, payloads, null);
  await open(page, payloads["owner-8"]);
  const race = page.locator('section[aria-labelledby="median-race-title"]');
  await expect(race.getByRole("heading", { name: "Live median race" })).toBeVisible();
  const rows = race.getByRole("list", { name: /beat the median/ }).getByRole("listitem");
  await expect(rows).toHaveCount(payloads["owner-8"].leagueTeams.length);
  await expect(race.getByText("Projected final")).toBeVisible();
  await expect(race.locator('[aria-current="true"]')).toHaveCount(1);
  await noPageOverflow(page);
  const splits = await race.evaluate((root) => {
    const out = [];
    for (const el of root.querySelectorAll("li [class*='teamName']")) {
      const text = el.firstChild;
      if (!text || text.nodeType !== 3) continue;
      let i = 0;
      for (const word of text.textContent.split(" ")) {
        if (word) {
          const r = document.createRange();
          r.setStart(text, i);
          r.setEnd(text, i + word.length);
          if (new Set([...r.getClientRects()].map((q) => Math.round(q.top))).size > 1) out.push(word);
        }
        i += word.length + 1;
      }
    }
    return out;
  });
  expect(splits, "no word of a team name may be split across lines").toEqual([]);
  await scan(page, testInfo, "median-race");
  const shot = testInfo.outputPath("median-race.png");
  await race.screenshot({ path: shot });
  await testInfo.attach("median-race", { path: shot, contentType: "image/png" });

  // A row is a team switch: tap Team 10's row.
  await race.locator('li[data-roster-id="10"] button').click();
  await expect(page).toHaveURL(/team=owner-10/);
  await expect(hero(page).locator("caption")).toContainText("Team 10 versus Team 8", { timeout: 15_000 });
  await expect(page.getByRole("combobox", { name: "Viewing team" })).toHaveValue("owner-10");
  await expect(race.locator('li[data-roster-id="10"] [aria-current="true"]')).toHaveCount(1);
  await noPageOverflow(page);
  expect(errors).toEqual([]);
});
