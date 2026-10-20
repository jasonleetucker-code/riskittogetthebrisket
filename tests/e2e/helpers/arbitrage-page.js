/**
 * /arbitrage interaction helpers, shared by the local journey
 * (specs/journey-trade.spec.js), the production-verification spec
 * (specs/prod-auth/v1-123-trade-journeys.spec.js) and the hydration-race
 * regression (specs/arbitrage-hydration-race.spec.js).
 *
 * Why they exist: a HYDRATION RACE that held both prod-auth /arbitrage tests
 * red on every V1 run after the 2026-10-18 "tools first" layout (runs
 * 39311556615, 39345164050).  The tool tabs and the collapsed "Player-level
 * market research" disclosure are in the server-rendered HTML, so the heading
 * and the controls are visible — and `aria-expanded="false"` is already true —
 * long before React has attached their onClick handlers.  On the deployed
 * site the page's JavaScript arrives over a real network, so a click fired as
 * soon as the heading painted landed on inert markup: a real DOM event with
 * no listener, and no replay once hydration finished.  The tab never
 * switched, the disclosure never opened, and the next assertion ran out its
 * full budget with no console or page error (an `assertion` failure, ~1.5 s
 * + the 30 s / 20 s wait).  Locally the chunks load in milliseconds, which is
 * why the same sequence passed in the E2E suite.  Same class this repo
 * already diagnosed in v1-131-nav-gating.spec.js (mobile drawer) and
 * w1-12-public-pregame.spec.js (Full H2H preview CTA).
 *
 * The remedy is a deterministic readiness signal rather than a sleep or a
 * networkidle guess: the "Your team" selector renders with ZERO options on
 * the server (the contract is fetched client-side) and is populated only by a
 * client render after hydration — so a populated selector is the page's own
 * statement that its handlers are live.  It is in the same React tree as the
 * tabs and the disclosure (no Suspense boundary between them), so they
 * hydrate together.  Every click below is then followed by an assertion that
 * it took effect, so a lost click fails at the click, by name.
 */
const { expect } = require("@playwright/test");

const ARBITRAGE_TOOL_TABS = [
  "Golden Upgrades",
  "Package Scan",
  "Best Offer by Opponent",
  "Package Builder",
  "Trade Desk",
];

/**
 * Wait until /arbitrage is hydrated and has its league's teams.
 * Returns the number of team options.
 */
async function awaitArbitrageInteractive(page, { timeout = 60_000 } = {}) {
  const teamSelect = page.getByLabel("Your team");
  await expect
    .poll(async () => teamSelect.locator("option").count(), {
      message:
        "the 'Your team' selector never populated — /arbitrage did not hydrate " +
        "or the contract served no teams, so no control on the page is live yet",
      timeout,
    })
    .toBeGreaterThan(0);
  return teamSelect.locator("option").count();
}

/**
 * Switch to the Package Scan tool and require its pre-scan state.
 * Golden Upgrades must be the default (owner directive 2026-10-18).
 */
async function openPackageScan(page, { timeout = 30_000 } = {}) {
  const tabs = page.getByRole("tab");
  await expect(tabs.first()).toHaveText(ARBITRAGE_TOOL_TABS[0], { timeout });
  await awaitArbitrageInteractive(page);
  const scanTab = page.getByRole("tab", { name: "Package Scan" });
  await scanTab.click();
  await expect(scanTab, "the Package Scan tab click did not select the tab").toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText(/Package scan ready/i)).toBeVisible({ timeout });
}

/**
 * Open the collapsed "Player-level market research" panel and return a
 * locator scoped to it.  Its body is not mounted until opened.
 */
async function openPlayerResearch(page, { timeout = 30_000 } = {}) {
  const disclosure = page.getByRole("button", { name: "Player-level market research" });
  await expect(disclosure).toHaveAttribute("aria-expanded", "false", { timeout });
  await awaitArbitrageInteractive(page);
  await disclosure.click();
  await expect(disclosure, "the research disclosure click did not open the panel").toHaveAttribute(
    "aria-expanded",
    "true",
  );
  // `.last()`: the innermost panel holding the disclosure (an enclosing
  // panel, if a future layout adds one, would also match the filter).
  return page.locator(".ds-panel").filter({ has: disclosure }).last();
}

module.exports = {
  ARBITRAGE_TOOL_TABS,
  awaitArbitrageInteractive,
  openPackageScan,
  openPlayerResearch,
};
