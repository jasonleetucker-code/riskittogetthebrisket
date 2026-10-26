/**
 * /arbitrage — the tool tab and the research disclosure must survive a slow
 * hydration.  Regression for the V1 production failure of
 * prod-auth/v1-123-trade-journeys.spec.js (runs 39311556615, 39345164050):
 * both /arbitrage browser tests failed on prod-desktop AND prod-mobile while
 * POST /api/trade/finder passed, because the specs clicked server-rendered
 * controls before React had attached their handlers.  On the deployed site
 * the page JavaScript crosses a real network; locally it does not, so the
 * race never showed here.
 *
 * This spec makes the network slow on purpose: every Next.js JS chunk is
 * held for CHUNK_DELAY_MS, which leaves the server-rendered heading, tabs and
 * disclosure visible-but-inert for that long — production's shape, made
 * deterministic.  It then drives the page through the SAME helpers the
 * production spec uses (helpers/arbitrage-page.js).  With the old sequence
 * (click as soon as the heading painted) the tab click is lost and "Package
 * scan ready" never appears; the disclosure stays aria-expanded="false".
 *
 * Self-contained: every /api request is answered from a fixed synthetic
 * payload (two teams, a handful of players), so it needs only the Next
 * server — no backend, no session minting — and runs the same in the
 * self-booted stack.  The session cookie is a placeholder: middleware.js
 * only checks that one is present, and every API it would authorize is
 * mocked.
 *
 * Run against just a Next server:
 *   E2E_BASE_URL=http://127.0.0.1:3000 E2E_PAGE_ORIGIN=http://127.0.0.1:3000 \
 *     npx playwright test --config tests/e2e/playwright.config.js arbitrage-hydration-race
 */
const { test, expect } = require("@playwright/test");
const { pageUrl, pageHeading, titleFor, awaitStreamSettled } = require("../helpers/journey");
const {
  ARBITRAGE_TOOL_TABS,
  openPackageScan,
  openPlayerResearch,
} = require("../helpers/arbitrage-page");

const CHUNK_DELAY_MS = 3_000;

test.use({ serviceWorkers: "block" });

function player(rank, name, position, assetClass, value, market) {
  const marketKey = assetClass === "idp" ? "idpTradeCalc" : "ktcCrowdTradesSfTep";
  return {
    playerId: `syn-${rank}`,
    canonicalName: name,
    displayName: name,
    position,
    assetClass,
    rankDerivedValue: value,
    canonicalConsensusRank: rank,
    confidenceBucket: "high",
    quarantined: false,
    values: { overall: value, finalAdjusted: value, displayValue: value },
    canonicalSiteValues: { [marketKey]: market },
  };
}

// Values above the market by 20-30% so the default "Buy arbitrage, 5%+"
// research view has rows, in BOTH player populations.
const PLAYERS = [
  player(1, "Synthetic Quarterback", "QB", "offense", 9000, 7200),
  player(2, "Synthetic Receiver", "WR", "offense", 8000, 6400),
  player(3, "Synthetic Runner", "RB", "offense", 7000, 5600),
  player(4, "Synthetic Linebacker", "LB", "idp", 5000, 3900),
  player(5, "Synthetic Edge", "DL", "idp", 4500, 3600),
];

const CONTRACT = {
  contractVersion: "2026-03-10.v2",
  payloadView: "array",
  playerCount: PLAYERS.length,
  playersArray: PLAYERS,
  sleeper: {
    positions: {},
    teams: [
      {
        name: "Synthetic Alpha",
        ownerId: "owner-a",
        roster_id: 1,
        players: ["Synthetic Quarterback", "Synthetic Linebacker"],
      },
      {
        name: "Synthetic Beta",
        ownerId: "owner-b",
        roster_id: 2,
        players: ["Synthetic Receiver", "Synthetic Runner", "Synthetic Edge"],
      },
    ],
  },
};

async function mockApiAndSlowChunks(page) {
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      const json = (status, body) =>
        route.fulfill({
          status,
          contentType: "application/json",
          headers: { "Cache-Control": "no-store" },
          body: JSON.stringify(body),
        });
      if (path.startsWith("/api/dynasty-data") || path === "/api/data") {
        return json(200, CONTRACT);
      }
      if (path === "/api/auth/status") {
        return json(200, { authenticated: true, username: "e2e-synthetic" });
      }
      // Everything else the shell asks for is absent, explicitly — the page
      // must still render its tools (same posture as a cold backend).
      return json(404, { error: "not_mocked" });
    },
  );
  await page.route(
    (url) => url.pathname.startsWith("/_next/static/chunks/"),
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, CHUNK_DELAY_MS));
      await route.continue();
    },
  );
}

async function gotoArbitrageBeforeHydration(page) {
  const origin = new URL(pageUrl("/arbitrage"));
  await page.context().addCookies([
    { name: "jason_session", value: "e2e-synthetic", domain: origin.hostname, path: "/" },
  ]);
  await mockApiAndSlowChunks(page);
  await page.goto(origin.toString(), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(pageHeading(page, titleFor("/arbitrage"))).toBeVisible({ timeout: 30_000 });
  // Non-vacuity: the controls ARE painted and the page is NOT yet hydrated
  // (the team selector is server-rendered empty and filled client-side).
  // If this ever stops holding, the race window is gone and this spec no
  // longer proves anything — raise CHUNK_DELAY_MS rather than delete it.
  await expect(page.getByRole("tab").first()).toHaveText(ARBITRAGE_TOOL_TABS[0]);
  expect(
    await page.getByLabel("Your team").locator("option").count(),
    "the page hydrated before the first interaction — the race window this spec needs is gone",
  ).toBe(0);
}

test.describe("/arbitrage survives a slow hydration", () => {
  test("Package Scan tab opens when clicked before hydration finished", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await gotoArbitrageBeforeHydration(page);

    await openPackageScan(page);

    const opponent = page.getByLabel("Opponent");
    await expect(opponent.locator("option")).toHaveText(["All teams", "Synthetic Beta"]);
    await expect(page.getByRole("button", { name: "Find trade packages" })).toBeEnabled();
    expect(errors).toEqual([]);
  });

  test("player-level research opens and its Players filter works before hydration finished", async ({
    page,
  }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await gotoArbitrageBeforeHydration(page);

    const research = await openPlayerResearch(page);
    await expect(research.getByText("Visible", { exact: true })).toBeVisible();
    const rows = research.getByRole("table").locator("tbody tr");
    await expect(rows).toHaveCount(PLAYERS.length);

    const players = research.getByLabel("Players", { exact: true });
    await players.selectOption("defense");
    await expect(rows).toHaveCount(2);
    await players.selectOption("offense");
    await expect(rows).toHaveCount(3);
    await players.selectOption("both");
    await expect(rows).toHaveCount(PLAYERS.length);
    expect(errors).toEqual([]);
  });
});
