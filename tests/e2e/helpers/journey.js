/**
 * Shared helpers for the critical-journey specs (journey-*.spec.js,
 * mobile-smoke.spec.js).
 *
 * Conventions (see tests/e2e/README.md):
 *   - Data-driven waits: wait for actual rows/content, never sleep.
 *   - No dependence on exact player names — sample names from the
 *     live board, assert on counts and structure.
 *   - Selectors for redesign-volatile surfaces are centralized HERE
 *     so a UI rewrite only has to update one file to keep the
 *     journeys green.
 */
const { expect } = require("@playwright/test");

// ── Selector registry ──────────────────────────────────────────────────
// The one place the redesign has to keep in sync.  Every selector is
// paired with the user-visible behavior it anchors; when a page is
// rewritten, point these at the new DOM and the journey assertions
// (which encode BEHAVIOR, not markup) should pass unchanged.
const SEL = {
  // /rankings — the board table and its rows (one row per player).
  // R2: the board renders through the ds DataTable primitive; the
  // rankings-row-clickable class is kept as the stable E2E hook.
  boardRow: ".ds-table-wrap table tbody tr.rankings-row-clickable",
  // /rankings — clickable player name inside a row (opens the profile).
  playerName: ".rankings-player-name",
  // /rankings — the controls strip's search input + position <select>
  // (rankings-controls is the stable hook class; controls are ds
  // primitives).
  searchInput: ".rankings-controls input.ds-input",
  posSelect: ".rankings-controls select.ds-select",
  // Any modal overlay: the player profile drawer (ds Drawer) and the
  // command palette (ds Modal) both render role=dialog panels.
  overlaySheet: '[role="dialog"]',
  // Command-palette result rows (R1 CommandPalette).
  searchResult: ".shell-palette-option",
  searchResultName: ".shell-palette-option-name",
  // Top-nav search affordance — renders once the client auth check
  // resolves, so it doubles as the "authenticated UI is hydrated"
  // readiness signal.  (R1 shell.)
  navSearchButton: ".shell-search-btn",
  // /news (R3) — digest-first wire. The page renders one of two feeds
  // depending on the view tab; both row kinds carry a stable hook
  // class alongside their CSS-module class.
  newsControls: ".news-controls",
  newsDigestRow: ".news-digest-row",
  newsStoryRow: ".news-story-row",
  // /news — the player button inside a digest row (opens the profile).
  newsDigestPlayer: ".news-digest-row button",
  // /edge (R3) — market-intelligence screen. Signals are grouped into
  // three families behind a tablist; each family renders ds Panels
  // whose bodies are DataTables.
  edgeSignalTab: '[role="tablist"][aria-label="Signal family"] [role="tab"]',
  edgeSignalTable: '[role="tabpanel"] .ds-table-wrap table',
  edgeSignalRow: '[role="tabpanel"] .ds-table-wrap table tbody tr',
  // /finder (R3) — workflow presets as a tablist over one result table.
  finderWorkflowTab:
    '[role="tablist"][aria-label="Discovery workflow"] [role="tab"]',
  finderFilters: ".finder-filters",
  finderRow: '[role="tabpanel"] .ds-table-wrap table tbody tr',
  // / dashboard (R3) — the war-room terminal. The legacy terminal
  // Panel container is retired; every section is a ds Panel now, so
  // panels are addressed by their accessible heading rather than a
  // .panel--* hook class.
  dashboardCommandBar: '[aria-label="Team command bar"]',
  dashboardStats: '[aria-label="Team aggregates"]',
  dashboardPanel: ".ds-panel",
  dashboardSignalCard: '[aria-label^="Sell signal"], [aria-label^="Buy signal"]',
};

function isMobileProject(testInfo) {
  return testInfo.project.name.startsWith("mobile-");
}

/**
 * Origin for PAGE navigations that must bypass the backend's page
 * proxy.  server.py proxies page routes to Next.js with a 5s timeout;
 * the /league SSR pass regularly exceeds that and 503s — production
 * doesn't have this problem because nginx routes page traffic
 * straight to Next.  Setting E2E_PAGE_ORIGIN (e.g.
 * http://127.0.0.1:3000) reproduces the production topology for page
 * loads while API requests keep the shared baseURL.  When unset
 * (e.g. prod smoke runs against the real domain) paths pass through
 * unchanged.
 */
function pageUrl(path) {
  let origin = process.env.E2E_PAGE_ORIGIN;
  if (origin === undefined) {
    // Default: when the Playwright webServer boots the stack itself
    // (no E2E_BASE_URL), the Next.js origin is always local :3000.
    // When targeting an external stack (E2E_BASE_URL set — e.g. the
    // prod smoke run through nginx), pages stay same-origin unless
    // the caller opts in explicitly.
    origin = process.env.E2E_BASE_URL ? "" : "http://127.0.0.1:3000";
  }
  origin = origin.replace(/\/+$/, "");
  return origin ? origin + path : path;
}

/**
 * Gate a spec to desktop chromium.  Mobile coverage lives in
 * mobile-smoke.spec.js; running the desktop journeys against every
 * viewport project would multiply runtime without adding signal.
 */
function desktopOnly(test, testInfo) {
  test.skip(
    isMobileProject(testInfo),
    "desktop journey — mobile coverage lives in mobile-smoke.spec.js",
  );
}

/** Gate a spec to the chromium mobile viewport project. */
function mobileOnly(test, testInfo) {
  test.skip(
    testInfo.project.name !== "mobile-chromium",
    "mobile smoke runs on the mobile-chromium project only",
  );
}

/**
 * Navigate to /rankings and wait for the board to be populated with
 * real data rows.  Data-driven: waits for actual <tr> elements, not
 * timers.  Returns the row locator.
 */
async function gotoRankingsBoard(page, { minRows = 50 } = {}) {
  await page.goto("/rankings", { waitUntil: "domcontentloaded" });
  const rows = page.locator(SEL.boardRow);
  await expect(rows.first(), "rankings board should render rows").toBeVisible({
    timeout: 60_000,
  });
  await expect
    .poll(() => rows.count(), {
      message: `rankings board should render at least ${minRows} rows`,
      timeout: 30_000,
    })
    .toBeGreaterThanOrEqual(minRows);
  return rows;
}

/** Visible player names on the board, in render order. */
async function boardPlayerNames(page) {
  return page.locator(SEL.playerName).allInnerTexts();
}

/**
 * Assert none of the given cells contain NaN/undefined artifacts —
 * the classic symptom of a broken value pipeline reaching the UI.
 */
async function expectNoBadValueTokens(page, scopeSelector) {
  const bad = await page.evaluate((sel) => {
    const cells = Array.from(document.querySelectorAll(sel));
    return cells
      .map((el) => String(el.textContent || ""))
      .filter((t) => /\bNaN\b|\bundefined\b|\bnull\b/i.test(t));
  }, scopeSelector);
  expect(bad, `cells with NaN/undefined under ${scopeSelector}`).toEqual([]);
}

/**
 * Collect browser console errors, filtering known noise.  Call
 * ``assertClean()`` at the end of the test.  (Same contract as the
 * old utils/app.js guard, rebuilt for the Next.js frontend.)
 */
function attachConsoleGuards(page, { allow = [] } = {}) {
  const defaultAllow = [
    // Chrome resource noise (404 favicons, aborted prefetches).
    "Failed to load resource",
    // Next.js dev overlay ping when running against `next dev`.
    "[HMR]",
    // Service-worker registration fetching /sw.js through the backend
    // proxy can 404 in test topologies — benign, the app runs fine
    // without the SW.
    "was received when fetching the script",
  ];
  const allowList = [...defaultAllow, ...allow];
  const consoleErrors = [];
  const pageErrors = [];

  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text() || "";
    if (allowList.some((frag) => text.includes(frag))) return;
    consoleErrors.push(text);
  });
  page.on("pageerror", (err) => {
    const text = String(err && err.stack ? err.stack : err);
    if (allowList.some((frag) => text.includes(frag))) return;
    pageErrors.push(text);
  });

  return {
    assertClean() {
      expect.soft(consoleErrors, "unexpected browser console errors").toEqual([]);
      expect.soft(pageErrors, "unexpected page errors").toEqual([]);
    },
    consoleErrors,
    pageErrors,
  };
}

module.exports = {
  SEL,
  isMobileProject,
  pageUrl,
  desktopOnly,
  mobileOnly,
  gotoRankingsBoard,
  boardPlayerNames,
  expectNoBadValueTokens,
  attachConsoleGuards,
};
