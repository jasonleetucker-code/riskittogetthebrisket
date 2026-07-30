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

// Accessible-name patterns for controls whose stable hook is their
// label rather than a class.  Declared ABOVE `SEL` deliberately:
// when two workstreams both append selectors, a declaration sitting
// against SEL's closing brace gets swallowed into the conflict
// block, and the natural resolution then exports a name that was
// never defined — a require()-time ReferenceError that takes out
// every spec while unit tests stay green.  Up here that is
// structurally impossible.
const NAME = {
  waiverRookieToggle: /Include rookies/i,
  waiverPositionFilter: /^Position$/i,
  waiverStrengthFilter: /Upgrade strength/i,
};

// ── Page-title canon ───────────────────────────────────────────────────
// Route → the page's <h1>, mirroring
// frontend/__tests__/helpers/naming-canon.js. Kept in lockstep by
// tests/e2e/test_e2e_harness_guards.py, the same
// parse-the-JS-and-diff idiom tests/api/test_source_registry_parity.py
// already uses for the ranking-source registry.
//
// Why this exists: SEL centralizes redesign-volatile *markup* and did
// its job — not one of the nineteen 2026-07-30 nightly failures was a
// broken CSS hook. What was NOT centralized was the user-facing COPY,
// so PR #625's naming canon ("Trade Builder" → "Trade Calculator",
// "Roster Dashboard" → "Team Strength") broke four assertions across
// three files, each hardcoding the old string. One rename, three files.
// Put a title here, reference it, and the parity test makes the next
// rename a fast-gate failure instead of an overnight one.
const TITLE = {
  "/rankings": "Rankings",
  "/trending": "Trending",
  "/idptc-rookies": "Rookie Board",
  "/players/compare": "Compare Players",
  "/bdvm": "Fundamental Values",
  "/news": "News",
  "/trade": "Trade Calculator",
  "/angle": "Package Builder",
  "/arbitrage": "Arbitrage",
  "/trades": "Trade History",
  "/rosters": "Team Strength",
  "/waivers": "Waivers",
  "/draft": "Draft Board",
  "/phases": "Win-now vs Rebuild",
  "/edge": "Source Disagreement",
  "/market/sharp-tracker": "Sharp Tracker",
  "/league/insider-trading": "Insider Trading",
  "/league": "Hub",
  "/league/activity": "Activity",
  "/league-comparison": "Scoring Comparison",
};

/**
 * The page title for `route`, as an anchored exact-match RegExp.
 *
 * Anchored deliberately. A loose /Trade/i matches the nav group label
 * present on every authenticated page, which is the vacuity class
 * docs/e2e-assertion-audit.md measured: those assertions passed with
 * <main> deleted entirely. Pair this with pageHeading() and the
 * assertion can only pass if the PAGE BODY rendered.
 */
function titleFor(route) {
  const title = TITLE[route];
  if (!title) {
    throw new Error(
      `No canon title for ${route}. Add it to TITLE in ` +
        `tests/e2e/helpers/journey.js and to CANON in ` +
        `frontend/__tests__/helpers/naming-canon.js — the parity test ` +
        `requires both.`,
    );
  }
  return new RegExp(`^${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
}


// ── Selector registry ──────────────────────────────────────────────────
// The one place the redesign has to keep in sync.  Every selector is
// paired with the user-visible behavior it anchors; when a page is
// rewritten, point these at the new DOM and the journey assertions
// (which encode BEHAVIOR, not markup) should pass unchanged.
const SEL = {
  // ── R4: draft war room + trade surfaces ──────────────────────────
  // Stable hook classes the R4 pages set on their ds Panels/controls,
  // so the copy inside them can keep evolving without touching specs.
  // /waivers — the controls rail and the FAAB bid desk.
  waiverControls: ".waivers-controls",
  waiverBidDesk: ".waivers-bid-desk",
  // /waivers — rival-contention table rows (FAAB v2 sealed-auction read).
  waiverRivalRow: ".waivers-bid-desk .ds-table-wrap table tbody tr",
  // /trade — the control bar and the per-side ledger panels.
  tradeControls: ".trade-controls",
  tradeSide: ".trade-page .ds-panel",
  tradeStickyTray: ".trade-sticky-tray",
  // /trades — ledger entries (each is a Panel linking into /trade).
  tradeLedgerEntry: ".trades-page a.ds-panel",
  tradesControls: ".trades-controls",
  // /angle — the pitch form and the ranked-package table rows.
  angleForm: ".angle-form",
  anglePackageRow: ".angle-page .ds-table-wrap table tbody tr",
  // /draft — the war-room board panel and its rows.
  draftBoard: ".draft-board-panel",
  draftBoardRow: ".draft-board-panel tbody tr",
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
 *
 * Post-R1 this is a CORRECTNESS requirement, not just a timeout
 * workaround: served through the proxy, "/" renders the ANONYMOUS
 * landing shell even with a valid session cookie — /api/auth/status
 * returns authenticated:true while the proxied page still shows
 * "Sign In" — whereas Next serves the authed dashboard for the same
 * cookie.  Any spec asserting on signed-in chrome must navigate
 * through here or it silently tests the logged-out page.
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
  // MUST go through pageUrl() — see its 30-line warning above. This
  // line was a bare `page.goto("/rankings")` until 2026-07-30, which
  // resolved against baseURL (the FastAPI page proxy on :8000).
  // `_proxy_next` forwards no cookies (server.py:2891-2896, and
  // server.py:12539-12545 says so outright), so once
  // frontend/middleware.js landed on 2026-07-29 every such navigation
  // 307'd to /login and the board never existed. That single missing
  // wrapper was ELEVEN of the nightly suite's nineteen failures —
  // six rankings journeys, the settings-override round-trip, two
  // mobile smokes and two chart smokes — every one of them reported
  // as "rankings board should render rows / element(s) not found",
  // which reads like a dead pipeline and was a dead cookie.
  await page.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
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
 * The page's own <h1>.
 *
 * ── Why this exists ────────────────────────────────────────────────
 * The R1 shell renders a persistent sidebar/tab-bar carrying the word
 * "Trade", "Rosters", "Settings", "News", "Team Strength" … on EVERY
 * route.  So a body-level `toContainText(/Trade/i)` passes on a page
 * whose entire body failed to render — the nav link alone satisfies
 * it.  Four such assertions were the whole of the signed-in page
 * coverage before this audit (see docs/e2e-assertion-audit.md).
 *
 * The shell owns NO <h1>: every page title comes from `ui/PageHeader`
 * or `ds/PageHeader`, both of which render the page's single <h1>
 * (verified 2026-07-27 — `grep -rn "<h1" frontend/components` returns
 * only those two files, plus /settings' inline one).  Matching on the
 * <h1>'s accessible name therefore proves the PAGE BODY rendered, and
 * it survives the design-system rewrite because it pins a role and an
 * accessible name rather than a class, colour or font.
 */
function pageHeading(page, name) {
  return page.getByRole("heading", { level: 1, name });
}

/**
 * Fetch the live contract once and return the fields specs build
 * data-derived assertions from.
 *
 * Assertions anchored on these fail when the pipeline stops serving
 * rosters or players — the regression class that "a heading exists"
 * can never detect.  Never assert on a hardcoded name: the snapshot
 * refreshes nightly.
 */
async function contractFixture(page, { view = "app" } = {}) {
  const res = await page.request.get(`/api/data?view=${view}`);
  expect(res.status(), `GET /api/data?view=${view} must serve the suite`).toBe(200);
  const contract = await res.json();
  const teams = contract?.sleeper?.teams || [];
  const playersArray = Array.isArray(contract?.playersArray)
    ? contract.playersArray
    : [];
  const playerNames = playersArray.length
    ? playersArray.map((p) => p?.displayName).filter(Boolean)
    : Object.keys(contract?.players || {});
  return {
    contract,
    teams,
    teamNames: teams.map((t) => t?.name).filter(Boolean),
    playerNames,
  };
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
  NAME,
  TITLE,
  titleFor,
  isMobileProject,
  pageUrl,
  desktopOnly,
  mobileOnly,
  gotoRankingsBoard,
  boardPlayerNames,
  pageHeading,
  contractFixture,
  expectNoBadValueTokens,
  attachConsoleGuards,
};
