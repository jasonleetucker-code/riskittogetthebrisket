/**
 * /trade — TC-B journey: the immediate Second Opinions tally and Next steps.
 *
 * The page is the production build on the seeded board; the trade is built
 * through the page's own team selector and side search (the same helpers as
 * trade-war-room.spec.js).  Elements are addressed by test id, never by
 * text the TC-C decision headline could also contain.  The partner-evidence
 * request is answered from a fixed payload so the rendering is deterministic;
 * the live route's own answer is pinned by
 * tests/intel/test_manager_scout_offer_evidence_endpoint.py.
 *
 * Runs on every configured project (desktop-1366 and the phone projects).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture, isNavigationAbortedFetch } = require("../helpers/journey");
const { closeTradeSheet, openTradeSearch } = require("../helpers/trade-builder");

const PICK_TOKEN = /\d{4}/;

test.use({ serviceWorkers: "block" });

async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, "the page must not scroll sideways").toBeLessThanOrEqual(sizes.viewport + 1);
}

async function pickTrade(page) {
  const { teams, playerNames } = await contractFixture(page);
  const board = new Set(playerNames);
  for (const [idx, team] of teams.entries()) {
    const give = (team.players || []).find((p) => p && !PICK_TOKEN.test(p) && board.has(p));
    const other = teams.find((t) => t !== team);
    const receive = (other?.players || []).find(
      (p) => p && !PICK_TOKEN.test(p) && board.has(p) && !(team.players || []).includes(p),
    );
    if (give && receive) return { idx, team, other, give, receive };
  }
  throw new Error("no team with a board-resolvable player on the seeded contract");
}

async function addToSide(page, sideLabel, name) {
  const input = await openTradeSearch(page, sideLabel);
  await input.fill(name);
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const result = page
    .locator(".trade-side-search-result")
    .filter({ has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${escaped}$`) }) })
    .first();
  await expect(result).toBeVisible({ timeout: 15_000 });
  await result.click();
  await closeTradeSheet(page);
  await expect(page.getByRole("button", { name: `Remove ${name} from Side ${sideLabel}` })).toBeVisible();
}

test("trade next steps: immediate tally, engine deep links, partner evidence, no sideways scroll", async ({
  authedPage: page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (e) => {
    if (!isNavigationAbortedFetch(e, page)) errors.push(e.message);
  });
  const evidenceRequests = [];
  await page.route(
    (url) => url.pathname === "/api/manager-scout/offer-evidence",
    async (route) => {
      evidenceRequests.push({ url: route.request().url(), body: route.request().postDataJSON() });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify({
          state: "measured",
          tradeCount: 4,
          positionsTheyWouldReceive: [{ position: "WR", receivedBefore: 1, ofPlayersReceived: 5 }],
          picksTheyWouldReceive: null,
          offerShapeForThem: "1-for-1",
          sameShapeBefore: 2,
          tradesWithRequester: 0,
        }),
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

  // The one-glance tally sits outside the folded Second opinions panel.
  const tally = page.getByTestId("trade-opinion-tally");
  await expect(tally).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("trade-opinion-tally-coverage")).toContainText("source families priced every piece");

  // Next steps: each engine opens for this team.
  const next = page.getByTestId("trade-next-actions");
  await expect(next).toBeVisible({ timeout: 30_000 });
  const builder = next.getByTestId("trade-next-builder").getByRole("link");
  await expect(builder).toHaveAttribute("href", new RegExp(`^/arbitrage\\?tool=builder&team=`));
  await expect(next.getByTestId("trade-next-database").getByRole("link")).toHaveAttribute(
    "href",
    /^\/market\/trade-database\?players=/,
  );

  // Partner evidence: asked only on demand, and rendered as counts.
  expect(evidenceRequests).toEqual([]);
  const partner = next.getByTestId("trade-partner-evidence");
  if (await partner.count()) {
    await partner.getByRole("button").click();
    await expect(partner.getByText(/acquired by trade/)).toBeVisible({ timeout: 15_000 });
    expect(evidenceRequests.at(-1).body.theyReceive.map((a) => a.name)).toContain(trade.give);
  }

  await noPageOverflow(page);
  const shot = testInfo.outputPath("trade-next-actions.png");
  await next.screenshot({ path: shot });
  await testInfo.attach("trade-next-actions", { path: shot, contentType: "image/png" });

  // The deep link lands on the tool it names.
  await builder.click();
  await expect(page).toHaveURL(/\/arbitrage\?tool=builder/);
  await expect(page.getByRole("tab", { name: "Package Builder" })).toHaveAttribute("aria-selected", "true", {
    timeout: 30_000,
  });
  expect(errors).toEqual([]);
});
