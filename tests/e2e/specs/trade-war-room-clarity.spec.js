/**
 * /trade — Trade War Room clarity and loading (owner directive 2026-10-19,
 * "Trade Calculator Clarity", Part 1 + the frontend of Part 4; Lane 6).
 *
 * The page is the production build on the seeded board; the trade is built
 * through the page's own team selector and side search.  `POST
 * /api/trade/analyze` is ROUTE-MOCKED with
 * `frontend/__tests__/fixtures/trade-war-room-mock/aj-brown-herbert.json` — a
 * payload in the analyze endpoint's real shape carrying the values the owner
 * observed on the live War Room (A.J. Brown in, Justin Herbert out).  Those
 * values are NOT expected production output: every expectation below is
 * derived from the fixture's fields with the War Room's declared rounding
 * rules (trade value to the nearest point; points per week to one decimal,
 * magnitude half away from zero; percentages to the nearest percent).
 *
 * Proves, on desktop-1366 and mobile-chromium:
 *   - while the analysis runs, the calculator's trade value shows at once and
 *     NO recommendation (never a provisional YES / NO);
 *   - the answer: one recommendation, two reasons, the three plain rows;
 *   - the detail opens, axe (WCAG 2.0/2.1 A + AA) is clean on the War Room
 *     with every section open, and nothing scrolls sideways at 375 px;
 *   - a failed analysis keeps the trade value and recovers through Retry.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;
const { closeTradeSheet, openTradeSearch } = require("../helpers/trade-builder");

test.use({ serviceWorkers: "block" });

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const FIXTURE = path.resolve(
  __dirname,
  "../../../frontend/__tests__/fixtures/trade-war-room-mock/aj-brown-herbert.json",
);
const AJ = JSON.parse(fs.readFileSync(FIXTURE, "utf-8"));
const PICK_TOKEN = /\d{4}/;
const SECTIONS = [
  "Lineup impact, player by player",
  "Your lineup before and after",
  "Arguments, objections and uncertainty",
  "Sources, simulations and methodology",
];

// ── Expected copy, derived from the fixture with the declared rounding ──
const whole = (n) => Math.round(n).toLocaleString("en-US");
const tenth = (n) => (Math.round(Math.abs(n) * 10 + 1e-9) / 10).toFixed(1);
const market = AJ.analysis.lenses.market.detail;
const rosterDetail = AJ.analysis.lenses.roster.detail;
const incoming = rosterDetail.players.find((p) => p.role === "incoming");
const EXPECT = {
  headline: AJ.analysis.decision.headlineText,
  value:
    `You receive ${whole(market.receivingValue)} and send ${whole(market.sendingValue)}, ` +
    `so you give ${whole(-market.vaAdjustedGap)} more than you get.`,
  impact: `Your projected lineup scores about ${tenth(rosterDetail.ppg)} ${
    rosterDetail.ppg > 0 ? "more" : "fewer"
  } points per week.`,
  fit: "The trade fits. No player cut needed.",
  lineup: `${incoming.name} makes your best lineup in ${Math.round(
    incoming.lineupEntryPctAfter,
  )}% of simulated weeks.`,
};

async function noPageOverflow(page, label) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, `the page must not scroll sideways (${label})`).toBeLessThanOrEqual(
    sizes.viewport + 1,
  );
}

/** A real team, one of its exactly-spelled players, and one player from another team. */
async function pickTrade(page) {
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
  const input = await openTradeSearch(page, sideLabel);
  await input.fill(name);
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const result = page
    .locator(".trade-side-search-result")
    .filter({
      has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${escaped}$`) }),
    })
    .first();
  await expect(result).toBeVisible({ timeout: 15_000 });
  await result.click();
  await closeTradeSheet(page);
  await expect(
    page.getByRole("button", { name: `Remove ${name} from Side ${sideLabel}` }),
  ).toBeVisible();
}

/** The fixture, answered for THIS request's league and team. */
function answerFor(body) {
  return JSON.stringify({
    ...AJ,
    leagueKey: body.leagueKey || AJ.leagueKey,
    team: { ...AJ.team, name: body.teamName || AJ.team.name },
  });
}

async function openTrade(page) {
  const trade = await pickTrade(page);
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading player pool..."),
    null,
    {
      timeout: 90_000,
    },
  );
  await page.selectOption("#suggest-team", String(trade.idx));
  await addToSide(page, "A", trade.give);
  await addToSide(page, "B", trade.receive);
  return trade;
}

test("war room clarity: value at once while loading, plain answer, detail, axe, no sideways scroll", async ({
  authedPage: page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  // Hold every analysis until the test releases it, so the loading state is
  // observed deterministically rather than raced.
  let release;
  const gate = new Promise((r) => (release = r));
  const requests = [];
  await page.route(
    (url) => url.pathname === "/api/trade/analyze",
    async (route) => {
      const body = route.request().postDataJSON() || {};
      requests.push(body);
      await gate;
      // A request the page has since aborted (a newer question) cannot be
      // fulfilled; that is the page working, not a test failure.
      await route
        .fulfill({
          status: 200,
          contentType: "application/json",
          headers: { "Cache-Control": "no-store" },
          body: answerFor(body),
        })
        .catch(() => {});
    },
  );

  const trade = await openTrade(page);
  const room = page.locator('section[aria-labelledby="war-room-title"]');

  // ── Loading: the calculator's trade value at once, no recommendation.
  await expect(room).toHaveAttribute("data-war-room", "loading", { timeout: 30_000 });
  await expect(room.getByText("Analyzing this trade…")).toBeVisible();
  await expect(room.getByTestId("war-room-trade-value")).toBeVisible();
  await expect(room.locator('[data-lens="market"]')).toContainText(
    "The calculator's totals above. The personalized analysis is still running.",
  );
  // ...and they ARE the calculator's totals: the same raw figures the
  // Immediate result table shows (Side A is the team's, so it is "send").
  const rawRow = page.getByTestId("trade-immediate-result").getByRole("row", { name: /^Raw/ });
  const [, sideA, sideB] = await rawRow.locator("th, td").allInnerTexts();
  await expect(room.getByTestId("war-room-trade-value")).toContainText(
    `You receive ${sideB.trim()} and send ${sideA.trim()}`,
  );
  await expect(room.getByTestId("decision-headline")).toHaveCount(0);
  await expect(room).not.toContainText(/MAKE THE TRADE|TOO CLOSE|NOT ENOUGH EVIDENCE/);
  // The trade itself is untouched while it loads.
  await expect(
    page.getByRole("button", { name: `Remove ${trade.give} from Side A` }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Remove ${trade.receive} from Side B` }),
  ).toBeVisible();
  await expect.poll(() => requests.length, { timeout: 30_000 }).toBeGreaterThan(0);
  const shotLoading = testInfo.outputPath("war-room-loading.png");
  await room.screenshot({ path: shotLoading });
  await testInfo.attach("war-room-loading", { path: shotLoading, contentType: "image/png" });

  // ── The answer.
  release();
  await expect(room).toHaveAttribute("data-war-room", "ok", { timeout: 30_000 });
  await expect(room.getByTestId("decision-headline")).toHaveText(EXPECT.headline);
  await expect(room.getByTestId("decision-reasons").getByRole("listitem")).toHaveCount(2);
  // Confidence in plain English: the level, then what limits it — never the
  // backend's internal axis names or all-caps codes.
  await expect(room.getByTestId("decision-confidence")).toContainText(/^Medium confidence\./);
  await expect(room.getByTestId("decision-confidence")).not.toContainText(
    /assetEvidence|[A-Z]{3,}/,
  );
  await expect(room.getByTestId("war-room-trade-value")).toHaveText(EXPECT.value);
  await expect(room.getByTestId("war-room-weekly-impact")).toHaveText(EXPECT.impact);
  await expect(room.getByTestId("war-room-roster-fit")).toHaveText(EXPECT.fit);
  const last = requests.at(-1);
  expect(last.teamName).toBe(trade.team.name);
  expect(last.playersOut).toContain(trade.give);
  expect(last.playersIn).toContain(trade.receive);
  await noPageOverflow(page, "answer");
  const shotAnswer = testInfo.outputPath("war-room-answer.png");
  await room.screenshot({ path: shotAnswer });
  await testInfo.attach("war-room-answer", { path: shotAnswer, contentType: "image/png" });

  // ── Detail on request.
  for (const name of SECTIONS) {
    const toggle = room.getByRole("button", { name });
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
  }
  await expect(room.getByTestId("war-room-lineup-sentences")).toContainText(EXPECT.lineup);
  await expect(room.getByTestId("war-room-simulation-explained")).toContainText(
    `about ±${tenth(rosterDetail.standardError)} points per week (its standard error)`,
  );
  await noPageOverflow(page, "detail open");
  const axe = await new AxeBuilder({ page })
    .withTags(TAGS)
    .include('[aria-labelledby="war-room-title"]')
    .analyze();
  await testInfo.attach("war-room-clarity-axe", {
    body: JSON.stringify(axe.violations, null, 2),
    contentType: "application/json",
  });
  expect(axe.violations).toEqual([]);
  const shotDetail = testInfo.outputPath("war-room-detail.png");
  await room.screenshot({ path: shotDetail });
  await testInfo.attach("war-room-detail", { path: shotDetail, contentType: "image/png" });

  // ── The narrowest supported phone: 375 px, nothing scrolls sideways.
  if (testInfo.project.name !== "desktop-1366") {
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(room.getByTestId("decision-headline")).toBeVisible();
    await noPageOverflow(page, "375 px");
    const shot375 = testInfo.outputPath("war-room-375.png");
    await room.screenshot({ path: shot375 });
    await testInfo.attach("war-room-375", { path: shot375, contentType: "image/png" });
  }
  expect(errors).toEqual([]);
});

test("war room clarity: a failed analysis keeps the trade value and recovers through Retry", async ({
  authedPage: page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let calls = 0;
  await page.route(
    (url) => url.pathname === "/api/trade/analyze",
    async (route) => {
      calls += 1;
      const body = route.request().postDataJSON() || {};
      if (calls === 1) {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ error: "data_not_ready" }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: answerFor(body),
      });
    },
  );
  await openTrade(page);
  const room = page.locator('section[aria-labelledby="war-room-title"]');
  await expect(room).toHaveAttribute("data-war-room", "error", { timeout: 30_000 });
  await expect(room.getByTestId("war-room-error")).toContainText(
    "this league's data is still loading on the server",
  );
  await expect(room.getByTestId("war-room-trade-value")).toBeVisible();
  await expect(room.locator('[data-lens="market"]')).toContainText("did not finish");
  await expect(room.getByTestId("decision-headline")).toHaveCount(0);
  await room.getByRole("button", { name: "Retry" }).click();
  await expect(room).toHaveAttribute("data-war-room", "ok", { timeout: 30_000 });
  await expect(room.getByTestId("decision-headline")).toHaveText(EXPECT.headline);
  await noPageOverflow(page, "after retry");
  expect(errors).toEqual([]);
});
