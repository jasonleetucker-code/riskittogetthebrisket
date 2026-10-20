/**
 * /arbitrage — server-rendered controls are honestly NOT-YET-INTERACTIVE
 * until React hydrates them, and become live the moment it does.
 *
 * The real-user defect (recorded by PR #1867, which fixed only the specs):
 * the tool tabs, the Team context / Asset only switch and the collapsed
 * "Player-level market research" disclosure are in the server-rendered
 * HTML, painted and labelled long before the page JavaScript arrives on a
 * slow network.  A click in that window landed on markup with no listener
 * and React never replays it — the control looked live and silently did
 * nothing.  The ds primitives (Tabs, SegmentedControl, CollapsiblePanel)
 * now render those controls `disabled` + `aria-busy="true"` until they are
 * hydrated (the HYDRATION GATE note in frontend/components/ds/Tabs.jsx).
 *
 * This spec holds every Next.js JS chunk for CHUNK_DELAY_MS so the
 * pre-hydration window is wide and deterministic, then asserts:
 *   1. non-vacuity — the page really is painted and NOT yet hydrated;
 *   2. the controls say so: disabled, aria-busy, and (after the 400 ms
 *      grace that keeps fast loads from flashing) visibly dimmed with a
 *      progress cursor — not a live-looking control that eats a click;
 *   3. a click issued straight away, with NO app-specific readiness wait,
 *      takes effect: Playwright's actionability check waits for the control
 *      to become enabled, which only happens once its handler is attached.
 *      (Before the gate, this exact sequence lost the click.)
 *
 * Self-contained: every /api request is answered from a fixed synthetic
 * payload, so it needs only the Next server — no backend, no session
 * minting.  middleware.js only checks that a session cookie is present.
 *
 * Run against just a Next server:
 *   E2E_BASE_URL=http://127.0.0.1:3000 E2E_PAGE_ORIGIN=http://127.0.0.1:3000 \
 *     npx playwright test --config tests/e2e/playwright.config.js hydration-gate-arbitrage
 */
const { test, expect } = require("@playwright/test");
const {
  pageUrl,
  pageHeading,
  titleFor,
  awaitStreamSettled,
} = require("../helpers/journey");

const CHUNK_DELAY_MS = 4_000;

test.use({ serviceWorkers: "block" });

function player(rank, name, position, assetClass, value, market) {
  const marketKey =
    assetClass === "idp" ? "idpTradeCalc" : "ktcCrowdTradesSfTep";
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

const PLAYERS = [
  player(1, "Synthetic Quarterback", "QB", "offense", 9000, 7200),
  player(2, "Synthetic Receiver", "WR", "offense", 8000, 6400),
  player(3, "Synthetic Linebacker", "LB", "idp", 5000, 3900),
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
        players: ["Synthetic Quarterback"],
      },
      {
        name: "Synthetic Beta",
        ownerId: "owner-b",
        roster_id: 2,
        players: ["Synthetic Receiver", "Synthetic Linebacker"],
      },
    ],
  },
};

async function gotoArbitrageWithSlowJs(page) {
  const origin = new URL(pageUrl("/arbitrage"));
  await page
    .context()
    .addCookies([
      {
        name: "jason_session",
        value: "e2e-synthetic",
        domain: origin.hostname,
        path: "/",
      },
    ]);
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
      if (path.startsWith("/api/dynasty-data") || path === "/api/data")
        return json(200, CONTRACT);
      if (path === "/api/auth/status")
        return json(200, { authenticated: true, username: "e2e-synthetic" });
      // Anything else is explicitly absent — the tools must still render.
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
  await page.goto(origin.toString(), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(pageHeading(page, titleFor("/arbitrage"))).toBeVisible({
    timeout: 30_000,
  });
  // Non-vacuity: painted, and NOT hydrated (the team selector is server-
  // rendered empty and filled by a client render).  If this stops holding
  // the window is gone and this spec proves nothing — raise CHUNK_DELAY_MS.
  expect(
    await page.getByLabel("Your team").locator("option").count(),
    "the page hydrated before the first assertion — the pre-hydration window this spec needs is gone",
  ).toBe(0);
}

async function expectVisiblyBusy(locator) {
  // The dim waits 400 ms (ds.css) so fast loads never flash; poll past it.
  await expect
    .poll(
      async () =>
        locator.evaluate((el) => Number(getComputedStyle(el).opacity)),
      {
        message:
          "a not-yet-interactive control must read as such, not as a live control",
        timeout: 2_000,
      },
    )
    .toBeLessThan(1);
  expect(await locator.evaluate((el) => getComputedStyle(el).cursor)).toBe(
    "progress",
  );
}

test.describe("/arbitrage hydration gate", () => {
  test("tool tabs: not-yet-interactive before hydration, and an immediate click still lands", async ({
    page,
  }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await gotoArbitrageWithSlowJs(page);

    const tablist = page.getByRole("tablist", {
      name: "Trade discovery tools",
    });
    const scanTab = page.getByRole("tab", { name: "Package Scan" });
    await expect(tablist).toHaveAttribute("aria-busy", "true");
    await expect(scanTab).toBeDisabled();
    // Busy is not "nothing selected": the default tool still reads selected.
    await expect(
      page.getByRole("tab", { name: "Golden Upgrades" }),
    ).toHaveAttribute("aria-selected", "true");
    await expectVisiblyBusy(scanTab);

    const mode = page.getByRole("radiogroup", { name: "Analysis mode" });
    if (await mode.count()) {
      await expect(mode).toHaveAttribute("aria-busy", "true");
      await expect(mode.getByRole("radio").first()).toBeDisabled();
    }

    // No readiness helper: the click waits for the control to be enabled,
    // i.e. for its handler to exist.
    await scanTab.click();
    await expect(scanTab, "the early tab click was lost").toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(tablist).not.toHaveAttribute("aria-busy", /.*/);
    await expect(page.getByText(/Package scan ready/i)).toBeVisible({
      timeout: 30_000,
    });
    expect(errors).toEqual([]);
  });

  test("research disclosure: not-yet-interactive before hydration, and an immediate click still opens it", async ({
    page,
  }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await gotoArbitrageWithSlowJs(page);

    const disclosure = page.getByRole("button", {
      name: "Player-level market research",
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await expect(disclosure).toBeDisabled();
    await expect(disclosure).toHaveAttribute("aria-busy", "true");
    await expectVisiblyBusy(disclosure);

    await disclosure.click();
    await expect(
      disclosure,
      "the early disclosure click was lost",
    ).toHaveAttribute("aria-expanded", "true");
    await expect(disclosure).toBeEnabled();
    await expect(disclosure).not.toHaveAttribute("aria-busy", /.*/);
    const research = page
      .locator(".ds-panel")
      .filter({ has: disclosure })
      .last();
    await expect(research.getByRole("table")).toBeVisible({ timeout: 30_000 });
    expect(errors).toEqual([]);
  });
});
