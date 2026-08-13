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
  "/market/sharp-roster-percentage": "Sharp Roster Percentage",
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
  // /draft — the Perfect Draft budget optimizer. Code-split behind
  // React.lazy with a null Suspense fallback, so there is no loading
  // marker: visibility of the panel itself is the only readiness gate,
  // and it needs a generous timeout (lazy chunk + roster-context round
  // trip + the solve). It renders nothing at all when the roster context
  // is unavailable, so a spec must assert on rows, not on a heading.
  perfectDraftPanel: ".perfect-draft-panel",
  perfectDraftRow: ".perfect-draft-panel .ds-table-wrap table tbody tr",
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
  // /arbitrage — the UI caller for src/trade/finder.py (board-vs-market).
  // One card per candidate trade; ``arbitrage-trade-card`` is the stable
  // hook beside the hashed CSS-module class.
  //
  // NOT to be confused with the retired /finder, which was a board
  // FILTER (presets over sourceRankSpread / confidenceBucket /
  // isSingleSource / rookie) and computed no board-versus-market
  // comparison at all.  Its selectors (`finderWorkflowTab`,
  // `finderFilters`, `finderRow`) are deleted here along with the route:
  // /finder is now a redirect shim into /rankings, and its presets
  // live on as the Screens dropdown (`SCREENS`, lib/edge-helpers.js).
  //
  // The confusion was load-bearing, not cosmetic: a stale header comment
  // on /finder once called it "the arbitrage blotter", which made an
  // earlier audit record a phantom second implementation competing with
  // this engine (see the header of frontend/app/arbitrage/page.jsx).
  arbitrageTradeCard: ".arbitrage-trade-card",
  // / dashboard (R3) — the war-room terminal. The legacy terminal
  // Panel container is retired; every section is a ds Panel now, so
  // panels are addressed by their accessible heading rather than a
  // .panel--* hook class.
  dashboardCommandBar: '[aria-label="Team command bar"]',
  dashboardStats: '[aria-label="Team aggregates"]',
  dashboardPanel: ".ds-panel",
  dashboardSignalCard:
    '[aria-label^="Sell signal"], [aria-label^="Buy signal"]',
};

function isMobileProject(testInfo) {
  return testInfo.project.name.startsWith("mobile-");
}

/**
 * Origin for PAGE navigations.
 *
 * Pages live on Next.js; the API lives on FastAPI.  `baseURL` is the
 * API origin, so every page navigation goes through here and every
 * API request keeps `baseURL`.  Setting E2E_PAGE_ORIGIN (e.g.
 * http://127.0.0.1:3000) points pages at Next; when unset (e.g. prod
 * smoke against the real domain, where nginx fronts both) paths pass
 * through unchanged.
 *
 * That is now a plain statement of the topology.  It used to be a
 * WORKAROUND, and the difference is worth recording because it is why
 * this helper exists at all: server.py used to proxy page routes to
 * Next, and specs had to route around it for two reasons.  The proxy's
 * 5s timeout could not absorb the /league SSR pass, so it 503'd.  And
 * more seriously, `_proxy_next` took a path string rather than a
 * Request and so structurally could not forward cookies — a proxied
 * page rendered the ANONYMOUS shell while /api/auth/status on the same
 * origin returned authenticated:true.  A spec that navigated without
 * this wrapper silently asserted against the logged-out page.
 *
 * #555 deleted the proxy.  The backend serves no pages, so a bare
 * navigation now 404s loudly instead of quietly testing /login, and
 * this helper is the ordinary way to reach a page rather than a
 * defence against one.  Its behaviour is unchanged — do not "simplify"
 * it away by moving `baseURL` to :3000, which would break every API
 * request in the suite, session minting first
 * (auth-fixture.js posts to `${baseURL}/api/test/create-session`, and
 * there is no Next bridge route for /api/test).
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
 * Why an empty board is empty — asked only when the wait below fails.
 *
 * ── The problem this exists to end ─────────────────────────────────
 * "rankings board should render rows / element(s) not found" is the
 * suite's most-repeated failure and its least informative.  #753 is the
 * live instance: the page renders "No player data available" — which
 * `rankings/page.jsx` shows under `!loading && !error && rows.length
 * === 0` — so the fetch COMPLETED, raised nothing, and produced no
 * rows.  Exactly two things do that, and they want opposite fixes:
 *
 *   1. the payload carried NO PLAYERS (a serving/priming problem);
 *   2. the payload carried rows with NO RANK STAMPS, so `buildRows`
 *      fail-fasts by design and returns [] (a pipeline/stamping
 *      problem — see frontend/lib/dynasty-data.js).
 *
 * AMENDED: there is a THIRD cause, and it was the real one. The page's
 * contract comes from the Next BRIDGE route on the page origin, not from
 * the backend this probe used to interrogate. That route aborts after a
 * 4s idle timeout and falls back to an on-disk snapshot; the committed
 * seed carries no rank stamps, so case (2) is produced by the BRIDGE
 * while the backend is perfectly healthy. Probing only the backend
 * reported "the pipeline is not stamping" and sent several
 * investigations at the wrong subsystem. Both origins are probed below.
 *
 * Nothing in a screenshot, the a11y snapshot, or `error-context.md`
 * separates them: both render the same empty state.  The second logs a
 * `console.error`, but the spec's own console guard asserts at the END
 * of a test and so never runs when this readiness wait fails first —
 * which is why two sessions have now had to download artifacts and
 * still could not tell.
 *
 * So ask the server directly, at the moment of failure.  Diagnostic
 * only: it runs on the failure path, changes no assertion, and is
 * written so it can never itself throw (a broken probe must not
 * replace a real failure message with its own stack).
 */
/**
 * Count rank stamps across BOTH encodings.
 *
 * The two carry different field names and a payload may have either:
 * `playersArray` rows use `canonicalConsensusRank`; the legacy `players`
 * dict uses `_canonicalConsensusRank` (src/api/data_contract.py:8346).
 *
 * Checking only the array — which this helper used to do — reports zero
 * for EVERY healthy `view=app` response, because server.py:2150 pops
 * `playersArray` from the runtime view by design. That made the "no rank
 * stamps" branch below fire on every failure regardless of cause, and it
 * sent multiple investigations at the scrape pipeline, which was never
 * the problem.
 */
/**
 * Fetch one contract URL and summarise it. Never throws — a broken probe
 * must not replace a real failure message with its own stack.
 */
async function _probeContract(page, url) {
  try {
    const res = await page.request.get(url, { timeout: 30_000 });
    const status = res.status();
    if (!res.ok()) {
      return { ok: false, status, count: 0, stamped: 0, summary: `HTTP ${status}` };
    }
    const body = await res.json();
    const arr = Array.isArray(body?.playersArray) ? body.playersArray : [];
    const legacy = body && typeof body.players === "object" ? Object.keys(body.players) : [];
    const count = arr.length || legacy.length;
    const stamped = _countRankStamps(body);
    return {
      ok: true,
      status,
      count,
      stamped,
      summary:
        `HTTP ${status}, playerCount=${body?.playerCount ?? "?"}, ` +
        `playersArray=${arr.length}, legacyPlayers=${legacy.length}, ` +
        `rankStamps=${stamped}`,
    };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      count: 0,
      stamped: 0,
      summary: `probe threw: ${err?.message || err}`,
    };
  }
}

function _countRankStamps(body) {
  const arr = Array.isArray(body?.playersArray) ? body.playersArray : [];
  let stamped = arr.filter((p) => p && p.canonicalConsensusRank != null).length;
  if (stamped === 0 && body?.players && typeof body.players === "object") {
    stamped = Object.values(body.players).filter(
      (p) => p && p._canonicalConsensusRank != null,
    ).length;
  }
  return stamped;
}

async function _diagnoseEmptyBoard(page) {
  try {
    // Probe BOTH origins, because they are different processes and only
    // one of them served the page.
    //
    // `page.request.get("/api/...")` resolves against `baseURL` (:8000,
    // FastAPI). The page under test loads from `E2E_PAGE_ORIGIN` (:3000,
    // Next) and gets its contract from the Next BRIDGE route, which has
    // its own 4s idle timeout and its own disk fallback
    // (frontend/app/api/dynasty-data/route.js). So the old single probe
    // measured a healthy backend while the page had been served something
    // else entirely — and reported the two as one payload.
    //
    // The give-away in the field was a legacyPlayers count that matched
    // neither on-disk snapshot.
    // A bare path resolves against `baseURL` (the backend). `pageUrl()`
    // prefixes the page origin, which is where the bridge lives. In the
    // prod-smoke topology (nginx fronts both) `pageUrl()` returns the bare
    // path and the two probes coincide, which is correct there.
    const backend = await _probeContract(page, "/api/data?view=app");
    const bridge = await _probeContract(page, pageUrl("/api/dynasty-data?view=app"));

    const lines = [
      `backend (baseURL) /api/data?view=app -> ${backend.summary}`,
      `bridge  (page origin) /api/dynasty-data?view=app -> ${bridge.summary}`,
    ];

    // The page consumes the BRIDGE, so it decides the verdict.
    const b = bridge;
    if (!b.ok) {
      lines.push(
        ` => THE BRIDGE FAILED (${b.status}). The page never received a contract.` +
          (backend.ok
            ? " The backend answered fine, so this is the Next bridge route or the" +
              " link between them — check its 4s idle timeout and disk fallback," +
              " not the scrape pipeline."
            : " The backend also failed, so start there."),
      );
    } else if (b.count === 0) {
      lines.push(" => THE PAYLOAD IS EMPTY: serving/priming problem, not rendering.");
    } else if (b.stamped === 0) {
      lines.push(
        " => ROWS BUT NO RANK STAMPS in the payload the PAGE received." +
          " buildRows fail-fasts by design." +
          (backend.stamped > 0
            ? " The backend's own payload IS stamped, so the bridge served a" +
              " different (probably on-disk) snapshot — investigate the bridge."
            : " The backend is unstamped too — investigate the pipeline."),
      );
    } else {
      lines.push(
        " => The payload looks serveable, so the board had data and still did not" +
          " render it. That points at the client, not the contract.",
      );
    }
    return lines.join("\n      ");
  } catch (err) {
    return `board diagnostic failed to run: ${err && err.message}`;
  }
}

/**
 * Navigate to /rankings and wait for the board to be populated with
 * real data rows.  Data-driven: waits for actual <tr> elements, not
 * timers.  Returns the row locator.
 */
async function gotoRankingsBoard(page, { minRows = 50 } = {}) {
  // MUST go through pageUrl() — see its note above. This line was a
  // bare `page.goto("/rankings")` until 2026-07-30, which resolved
  // against baseURL (then the FastAPI page proxy on :8000).
  // `_proxy_next` forwarded no cookies — it took a path string, not a
  // Request, so it could not — and so once frontend/middleware.js
  // landed on 2026-07-29 every such navigation 307'd to /login and the
  // board never existed. (#555 has since deleted the proxy, so the same
  // mistake would now 404 rather than mislead.) That single missing
  // wrapper was ELEVEN of the nightly suite's nineteen failures —
  // six rankings journeys, the settings-override round-trip, two
  // mobile smokes and two chart smokes — every one of them reported
  // as "rankings board should render rows / element(s) not found",
  // which reads like a dead pipeline and was a dead cookie.
  await page.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
  const rows = page.locator(SEL.boardRow);
  // Collected only to be reported alongside a failure — buildRows' own
  // fail-fast announces itself here and nowhere else a failing readiness
  // wait can see. Attached after goto so it captures the board's fetch.
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    // The URL must be captured HERE or it is gone. Chrome's "Failed to load
    // resource: the server responded with a status of 502" text does NOT
    // name the resource — the URL lives only on msg.location(). Recording
    // msg.text() alone turned a sourceable failure into a mystery: a real
    // run printed "404, 404, 502, 503, 503, 404, 404" with no way to tell
    // which endpoint produced which, and sourcing the 502 afterwards took
    // a full sweep of every bridge route.
    //
    // With the URL, that same line reads as what it is: a timing ladder of
    // one backend stall, each client abort budget firing in turn.
    const where = msg.location?.() || {};
    const url = where.url ? ` <- ${where.url}` : "";
    consoleErrors.push((msg.text() + url).slice(0, 300));
  });
  try {
    await expect(rows.first(), "rankings board should render rows").toBeVisible(
      {
        timeout: 60_000,
      },
    );
  } catch (err) {
    // Re-throw with the diagnosis appended. The original message and
    // Playwright's call log are preserved verbatim — this only adds.
    const diag = await _diagnoseEmptyBoard(page);
    const seen = consoleErrors.length
      ? `\nconsole errors during load:\n  - ${consoleErrors.join("\n  - ")}`
      : "\nconsole errors during load: none (so buildRows' zero-rank-stamps " +
        "fail-fast did NOT fire).";
    err.message = `${err.message}\n\n[board diagnostic] ${diag}${seen}`;
    throw err;
  }
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
  expect(res.status(), `GET /api/data?view=${view} must serve the suite`).toBe(
    200,
  );
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
/**
 * Wait until React has finished swapping streamed content into place.
 *
 * WHY THIS EXISTS, and why it is NOT a loosened assertion (#716).
 *
 * Routes with a `loading.jsx` — /waivers and /arbitrage among them — are
 * wrapped by the App Router in a Suspense boundary and streamed. The server
 * sends the page body inside `<div hidden id="S:n">`, then an inline
 * `$RC("B:n","S:n")` moves it into place. For a brief window around that swap
 * the document can satisfy a selector TWICE, and Playwright's strict mode
 * throws on the spot rather than retrying — so a spec that asserts during the
 * window fails with "resolved to 2 elements" on a page that is completely
 * healthy a few milliseconds later.
 *
 * Measured on /waivers, 25 loads per arm: asserting immediately caught the
 * window 1/25; asserting after this helper, 0/25. Under load (CI) the first
 * number is far worse — 13-20% per detector across four detector points, which
 * is why the suite was effectively unable to go green.
 *
 * CRITICALLY, this does not weaken the #709 detector. The bug those strict
 * locators exist to catch is a PERSISTENT duplicate — a build that renders
 * every page twice, forever. That survives streaming completion and still
 * trips strict mode here. What this removes is only the transient window,
 * which is normal React streaming and not a defect in anything.
 *
 * Keyed on React's own machinery (`div[hidden][id^="S:"]` staging containers
 * and `template[id^="B:"]` boundary markers) rather than on `div[hidden]`
 * generally, so an app component that legitimately renders a hidden div cannot
 * make this hang.
 */
async function awaitStreamSettled(page, { timeout = 30_000 } = {}) {
  await page
    .waitForFunction(
      () =>
        !document.querySelector('div[hidden][id^="S:"]') &&
        !document.querySelector('template[id^="B:"]'),
      null,
      { timeout },
    )
    // A route that never streamed has nothing to settle; that is a pass, not a
    // failure. Swallowing here keeps this usable as an unconditional prelude.
    .catch(() => {});
}

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
      expect
        .soft(consoleErrors, "unexpected browser console errors")
        .toEqual([]);
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
  awaitStreamSettled,
};
