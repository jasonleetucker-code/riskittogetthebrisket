const { test, expect } = require("@playwright/test");
const { pageUrl, waitForStreamSettled } = require("../helpers/journey");

// End-to-end coverage for the PUBLIC /league page.  Exercises the
// real Sleeper-backed data flow through the FastAPI backend at
// :8000 + Next.js at :3000.
//
// The test walks every tab, verifies the Home overview card, exercises
// shareable URLs (?tab=, ?owner=, ?week=), and visits the dedicated
// /league/franchise/[owner] and /league/rivalry/[pair] routes.
//
// Critical: also asserts that /league NEVER fetches /api/data (the
// private contract) — that would mean the public isolation is
// broken.  We attach a request listener to confirm.

// Tab labels in render order.  The Draft Capital tab is the default
// landing because /draft-capital was folded into /league — public
// visitors arriving at /league see it first.
const TABS = [
  "Draft Capital",
  "Home",
  "History",
  "Rivalries",
  "Awards",
  "Records",
  "Franchises",
  "Trades",
  "Draft",
  "Weekly",
  "Superlatives",
  "Archives",
];

/**
 * ── Scope of the no-private-endpoints assertion (decided, not drifted)
 *
 * `privateHits` only covers the page this helper navigates to, and
 * every caller navigates to `/league` or `/league?tab=…`.  Sibling
 * routes under `/league/**` — `/league/phases`, `/league/franchise/…`,
 * `/league/player/…` — are NOT watched by the tab-hub test.
 *
 * That narrowness is **deliberate**, and here is the line: this
 * assertion protects the *anonymous public hub* — the surface a
 * stranger lands on, which must never touch the private contract.
 * `/league/phases` (changed by #578) now fetches `/api/data`
 * deliberately: it is auth-gated and shows an explicit "sign in"
 * message to anonymous visitors rather than leaking data.  A fetch to
 * `/api/data` there is correct behaviour, so widening this listener to
 * all of `/league/**` would make the assertion fail on a feature that
 * is working as designed.
 *
 * So: scoped on purpose, not accidentally.  What that leaves uncovered
 * is the *response* side — nothing here asserts that `/api/data` from
 * an anonymous session returns 401 rather than data.  That IS covered,
 * separately and correctly, by
 * `multi-league.spec.js::"/api/data returns 401 without a session"`
 * and `critical-smoke.spec.js`'s auth-gate block.
 *
 * If a future change makes a `/league/**` sub-route fetch the private
 * contract and render it to anonymous visitors, neither this test nor
 * those would catch it.  That gap is recorded in
 * docs/e2e-assertion-audit.md rather than papered over by broadening a
 * listener whose meaning would then be ambiguous.
 */
async function visitLeague(page, path = "/league", { waitForText = null } = {}) {
  const privateHits = [];
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/api/data") || url.includes("/api/rankings/overrides")) {
      privateHits.push(url);
    }
  });
  await page.goto(pageUrl(path), { waitUntil: "domcontentloaded" });
  // Wait for something that only renders AFTER the contract fetch
  // resolves.  "Loading league data..." is replaced with section
  // content once /api/public/league comes back.
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading league data..."),
    null,
    { timeout: 45_000 },
  );
  if (waitForText) {
    await page.waitForFunction(
      (needle) => document.body.innerText.includes(needle),
      waitForText,
      { timeout: 15_000 },
    );
  }
  return privateHits;
}

test.describe("public /league page", () => {
  test("renders league page, switches tabs, and never touches private endpoints", async ({ page }) => {
    // Walking 12 tabs and waiting for each to actually render its own
    // content does not fit the default 90s budget — the old version fit
    // only because it slept 150ms and asserted nothing about rendering.
    test.setTimeout(240_000);
    // Visit via ?tab=overview so we have a deterministic "waitForText"
    // anchor (Draft Capital is the default tab but fetches client-side,
    // which would require a different readiness signal).
    const privateHits = await visitLeague(page, "/league?tab=overview", {
      waitForText: "At a glance",
    });

    // On mobile (≤768px) the tab row is hidden and sections are selected
    // via a <select> dropdown; on desktop, each tab is a <button>.
    //
    // This used to probe which control was live:
    //
    //     const useMobile = await mobileSelect.isVisible().catch(() => false);
    //
    // and that `.catch` turned "I could not tell" into "desktop".  When
    // React 19.2's deferred Suspense reveal left a staged copy of the page
    // in the DOM, `getByLabel("Select league section")` resolved to TWO
    // elements, `isVisible()` threw a strict-mode violation, the catch
    // swallowed it, and the test walked the DESKTOP branch on a 390px
    // viewport — where `.desktop-only` is `display:none` (globals.css).
    // Every one of the twelve buttons was then legitimately absent, and
    // the failure reported "league sub-nav is missing tabs: <all 12>",
    // which reads like the nav was deleted.  That is the nightly's
    // mobile-chromium flake, and the message sent every reader after the
    // wrong defect.
    //
    // Two changes.  Settle the stream first, so the duplicate that caused
    // it cannot exist.  Then decide from the VIEWPORT, which is a fact
    // about the run rather than a probe that can throw: the breakpoint is
    // 768px and `isMobileProject` already encodes the same split for the
    // project matrix.
    await waitForStreamSettled(page);
    const width = page.viewportSize()?.width ?? 1366;
    const useMobile = width <= 768;
    const mobileSelect = page.getByLabel("Select league section");

    // ── What this test does and does NOT prove ────────────────────
    // The old loop clicked every tab, slept `waitForTimeout(150)`, and
    // asserted only that no private endpoint was hit.  It never
    // checked a tab control existed: `getByRole(...).first().click()`
    // on a renamed tab throws, but a tab silently *dropped* from
    // SUB_TABS would simply never be clicked, and the test would still
    // pass.  It also used the bare sleep the README forbids.
    //
    // What it now proves: every tab in TABS is present as a working
    // control, and walking the whole set touches no private endpoint.
    // A dropped or renamed tab fails here.
    //
    // What it deliberately does NOT prove: that each section renders
    // its own content.  Measured 2026-07-27, /league SSRs in ~7.8s and
    // its 2.6 MB payload exceeds Next's 2 MB data-cache ceiling ("Failed
    // to set Next.js data cache for /api/public/league"), so sections
    // hydrate lazily and a rapid 12-tab walk reads an identical
    // 2718-char body for every tab.  Per-section content is therefore
    // asserted in public-league-visual.spec.js, which does one fresh
    // navigation per section — the access pattern the lazy loading
    // actually supports.  Asserting it here too would produce a flake,
    // not coverage.  See docs/e2e-assertion-audit.md §3.4.
    const missingTabs = [];

    for (const label of TABS) {
      if (useMobile) {
        await mobileSelect.selectOption({ label });
        continue;
      }
      const btn = page.getByRole("button", { name: label, exact: true }).first();
      if ((await btn.count()) === 0) {
        missingTabs.push(label);
        continue;
      }
      await btn.click();
    }

    expect(
      missingTabs,
      `league sub-nav is missing tabs: ${missingTabs.join(", ")}`,
    ).toEqual([]);

    // The walk must leave the page functional, not crashed.
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();

    expect(privateHits, `private endpoints were touched: ${privateHits.join(", ")}`).toHaveLength(0);
  });

  test("deep links via ?tab= query param land on the right tab", async ({ page }) => {
    await visitLeague(page, "/league?tab=awards", { waitForText: "award" });
  });

  test("franchise deep link via ?owner= opens the selected franchise", async ({ page, request }) => {
    const res = await request.get("/api/public/league");
    const body = await res.json();
    const ownerId = body?.league?.managers?.[0]?.ownerId;
    expect(ownerId).toBeTruthy();

    await visitLeague(
      page,
      `/league?tab=franchise&owner=${encodeURIComponent(ownerId)}`,
      { waitForText: "Season results" },
    );
  });

  test("dedicated /league/franchise/[owner] route renders", async ({ page, request }) => {
    const res = await request.get("/api/public/league");
    const body = await res.json();
    const ownerId = body?.league?.managers?.[0]?.ownerId;
    expect(ownerId).toBeTruthy();

    await page.goto(pageUrl(`/league/franchise/${encodeURIComponent(ownerId)}`), {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      () => document.body.innerText.includes("Cumulative")
        && document.body.innerText.includes("Season results"),
      null,
      { timeout: 45_000 },
    );
    await expect(page.getByText("← League home").first()).toBeVisible();
  });

  test("dedicated /league/rivalry/[pair] route renders when pair exists", async ({ page, request }) => {
    const res = await request.get("/api/public/league/rivalries");
    const body = await res.json();
    const rivalries = body?.data?.rivalries || [];
    // Was `test.skip(!rivalries.length)`.  The committed snapshot
    // serves 45 rivalries (verified 2026-07-27), so the gate never
    // fired — it only stood ready to convert a real "the rivalry
    // aggregation stopped producing pairs" regression into an
    // invisible skip.  Assert the precondition instead.
    expect(
      rivalries.length,
      "public league contract must expose rivalry pairs — zero means the rivalry aggregation broke",
    ).toBeGreaterThan(0);
    const [a, b] = rivalries[0].ownerIds;
    const slug = `${encodeURIComponent(a)}-vs-${encodeURIComponent(b)}`;
    await page.goto(pageUrl(`/league/rivalry/${slug}`), { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () => document.body.innerText.includes("Head-to-head")
        && document.body.innerText.includes("Memorable meetings"),
      null,
      { timeout: 45_000 },
    );
  });

  test("archives filter narrows the result set", async ({ page }) => {
    await visitLeague(page, "/league?tab=archives", { waitForText: "Public archives" });

    // The test's NAME promised narrowing; the body only counted rows
    // once and asserted `> 0`, so it passed with a filter that did
    // nothing at all.  It also slept 500ms instead of waiting on data.
    // Assert the actual contract: applying a narrower filter must
    // reduce the row count, and clearing it must restore.
    // Scoped to the archives table. `table tbody tr` counted EVERY
    // table on /league — weekly, luck, power, draft, draft-capital and
    // rivalries all use `.table-wrap` too — so the number being
    // asserted on was not this section's row count.
    const rows = page.locator(".archives-table table tbody tr");

    // The kind buttons render their own count ("Matchups (158)"), so
    // the expected row count is readable from the control itself.
    // Waiting for THAT is falsifiable. The old wait was
    // `.toBeGreaterThan(0)` immediately after the click, which the
    // PRE-click trades table already satisfied — so it captured a
    // stale count and the later comparison was against the wrong
    // number. That is how this test reported 190 (the unfiltered
    // trades total) while claiming to measure matchups.
    const matchupsBtn = page.getByRole("button", { name: /^Matchups \(\d+\)$/ });
    const declared = Number((await matchupsBtn.innerText()).match(/\((\d+)\)/)[1]);

    // Click INSIDE the poll, because the first one can land before
    // React has attached its handlers and is then simply lost.
    //
    // `visitLeague` waits for the text "Public archives". That wait has
    // CHANGED MEANING as of 2026-07-30 and is now strictly stronger:
    // the section is no longer server-rendered (it was ~737 KB of a
    // ~960 KB document), so "Public archives" appears only once the
    // client fetch has landed and the component has rendered with data
    // — it waits on data, not on markup. Previously the string was in
    // the SSR HTML, so it proved the markup arrived and nothing about
    // interactivity, and against production that gap was real: a
    // ~960 KB RSC payload takes long enough to hydrate to race a test
    // that clicks the moment the text appears.
    //
    // That gap is what made the suite ~46% flaky rather than broken.
    // Across 30 consecutive scheduled runs the results were
    // FFFF.SFFSFSSSSSSFSFSFFSS.FSFFF — 13 passes, 15 failures,
    // interleaved. A genuinely inert control fails every time; an
    // interleaved record is a race, and the same spec passed
    // consistently in the nightly, where the committed snapshot is
    // small and hydration is quick.
    //
    // Re-clicking is safe: the handler is `setKind(k.key)`, so extra
    // clicks set the same value. Nothing here is loosened — the
    // assertion is still the exact declared row count.
    await expect
      .poll(
        async () => {
          await matchupsBtn.click();
          return rows.count();
        },
        {
          message: `clicking Matchups should render its declared ${declared} rows`,
          timeout: 30_000,
          intervals: [250, 500, 1000, 2000, 3000],
        },
      )
      .toBe(Math.min(declared, 500)); // the section caps its render at 500
    const matchupRows = await rows.count();

    // Season filter is the narrowing control.  Pick the first specific
    // season offered and require a strictly smaller set than "all".
    const seasonSelect = page.locator("select").filter({ hasText: /\d{4}/ }).first();
    const hasSeasonFilter = await seasonSelect.count();
    if (hasSeasonFilter) {
      const options = await seasonSelect.locator("option").allInnerTexts();
      const specific = options.find((o) => /^\d{4}$/.test(o.trim()));
      expect(
        specific,
        `archives season filter offered no concrete season: ${options.join(", ")}`,
      ).toBeTruthy();
      // Same shape as the click above: re-select inside the poll so a
      // pre-hydration change event cannot be swallowed. Selecting the
      // same option repeatedly is idempotent.
      await expect
        .poll(
          async () => {
            await seasonSelect.selectOption({ label: specific });
            return rows.count();
          },
          {
            message: `selecting season ${specific} should narrow the archive rows below ${matchupRows}`,
            timeout: 30_000,
            intervals: [250, 500, 1000, 2000],
          },
        )
        .toBeLessThan(matchupRows);

      // Stronger than "fewer rows": every surviving row must BE the
      // selected season. A filter that drops rows for the wrong reason
      // passes the count check and fails this one. Skipped when the
      // filter legitimately empties the table (the live board has
      // seasons with no matchups at all), because `every` on an empty
      // list is vacuously true and would assert nothing.
      const remaining = await rows.count();
      if (remaining > 0) {
        const seasons = await rows.locator("td:first-child").allInnerTexts();
        expect(
          seasons.every((s) => s.trim() === specific),
          `rows left after selecting ${specific}: ${[...new Set(seasons.map((s) => s.trim()))].join(", ")}`,
        ).toBe(true);
      }
    } else {
      // No season control in this build — then the section-type
      // buttons are the only filter, so prove THOSE narrow: a
      // different archive type must yield a different row count.
      await page.getByRole("button", { name: /Trades/i }).first().click();
      await expect
        .poll(() => rows.count(), {
          message: "switching archive type should change the row set",
          timeout: 15_000,
        })
        .not.toBe(matchupRows);
    }
  });

  test("public contract payload never includes private field names", async ({ request }) => {
    const res = await request.get("/api/public/league");
    expect(res.status()).toBe(200);
    const body = await res.text();
    const lower = body.toLowerCase();
    for (const banned of [
      '"ourvalue":',
      '"edgesignals":',
      '"edgescore":',
      '"tradefinder":',
      '"siteweights":',
      '"siteoverrides":',
      '"rankderivedvalue":',
      '"arbitragescore":',
    ]) {
      expect(lower, `banned field ${banned} leaked into public contract`).not.toContain(banned);
    }
  });

  test("/league page has an OG title (server-rendered metadata)", async ({ request }) => {
    const res = await request.get(pageUrl("/league"));
    expect(res.status()).toBe(200);
    const html = await res.text();
    expect(html).toMatch(/<meta property="og:title"/i);
    expect(html).toMatch(/<meta property="og:description"/i);
  });

  test("/league?tab=overview SSRs with overview content (no loading flash)", async ({ request }) => {
    // Server-rendered /league?tab=overview hits the overview content
    // directly — HTML should contain the overview headlines, not the
    // fallback "Loading" text.
    const res = await request.get(pageUrl("/league?tab=overview"));
    const html = await res.text();
    expect(html).toMatch(/At a glance|Defending champion|Featured rivalry/);
  });

  test("/draft-capital redirects into the folded /league tab", async ({ request }) => {
    const res = await request.get(pageUrl("/draft-capital"), { maxRedirects: 0 });
    expect(res.status()).toBeGreaterThanOrEqual(300);
    expect(res.status()).toBeLessThan(400);
    const location = res.headers().location || "";
    expect(location).toMatch(/\/league\?tab=draft-capital/);
  });

  test("per-matchup recap route is reachable with real data", async ({ page, request }) => {
    const matchupsRes = await request.get("/api/public/league/matchups");
    expect(matchupsRes.status()).toBe(200);
    const body = await matchupsRes.json();
    const matchups = body.matchups || [];
    // Was `test.skip(!first)`.  The committed snapshot serves 158
    // matchups (verified 2026-07-27); the gate never fired and would
    // have hidden an empty matchup feed as a green skip.
    expect(
      matchups.length,
      "public league contract must expose matchups — zero means the matchup feed broke",
    ).toBeGreaterThan(0);
    const first = matchups[0];
    await page.goto(
      pageUrl(`/league/weekly/${encodeURIComponent(first.season)}/${encodeURIComponent(first.week)}/${encodeURIComponent(first.matchupId)}`),
      { waitUntil: "domcontentloaded" },
    );
    await expect(page.getByText("Game summary").first()).toBeVisible({ timeout: 15_000 });
  });

  test("player-journey route is reachable with real data", async ({ page, request }) => {
    const playersRes = await request.get("/api/public/league/players");
    expect(playersRes.status()).toBe(200);
    const players = (await playersRes.json()).players || [];
    // Was `test.skip(!pid)`.  The committed snapshot serves 968
    // named+positioned players (verified 2026-07-27); the gate never
    // fired, and an identity-mapping regression that stripped names
    // would have skipped green instead of failing.
    expect(
      players.length,
      "public league player index must not be empty",
    ).toBeGreaterThan(0);
    const named = players.find((p) => p.playerName && p.position);
    expect(
      named,
      "public league players must carry playerName + position — a bare id list means identity mapping broke",
    ).toBeTruthy();
    const pid = named.playerId;
    await page.goto(pageUrl(`/league/player/${encodeURIComponent(pid)}`), {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByText("Impact by manager").first()).toBeVisible({ timeout: 15_000 });
  });

  test("CSV export endpoint serves text/csv", async ({ request }) => {
    const res = await request.get("/api/public/league/history.csv");
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toMatch(/text\/csv/);
  });

  test("metrics endpoint exposes snapshot cache counters", async ({ request }) => {
    const res = await request.get("/api/public/league/metrics");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("metrics.rebuild_count");
    expect(body).toHaveProperty("metrics.cache_hit");
    expect(body).toHaveProperty("metrics.total_served");
  });

  test("teamAssignment section returns 12 manager slots (Phase A)", async ({
    request,
  }) => {
    // The Team Assignment section is registered as eager so the
    // aggregate /api/public/league response carries it.  It also
    // resolves through /api/public/league/{section}.  Pin both: the
    // section endpoint must 200 and the assignments array must
    // cover every manager in the league.
    const res = await request.get("/api/public/league/teamAssignment");
    expect(res.status()).toBe(200);
    const json = await res.json();
    const data = json.data || json.body || json;
    const assignments = (data && data.assignments) || [];
    expect(Array.isArray(assignments)).toBeTruthy();
    expect(assignments.length).toBeGreaterThanOrEqual(8); // realistic floor
    // Every assignment must have a non-empty NFL teams list — a
    // manager with zero NFL teams means the favorite map + roster
    // scoring both whiffed, which is a regression we want to catch.
    for (const a of assignments) {
      expect(a.nflTeams, `${a.displayName} has no NFL teams`).toBeTruthy();
      expect(a.nflTeams.length).toBeGreaterThan(0);
    }
  });

  test("faabAnalytics lazy section returns documented shape (Phase B5)", async ({
    request,
  }) => {
    // FAAB analytics is a lazy section — only addressable through
    // /api/public/league/{section}.  Powers the /waivers FAAB
    // recommender's calibration step.  Shape regression here =
    // recommender shape regression on next user click.
    const res = await request.get("/api/public/league/faabAnalytics");
    expect(res.status()).toBe(200);
    const json = await res.json();
    const data = json.data || json.body || json;
    for (const k of [
      "leagueBudget",
      "leagueAvgWinningBid",
      "leagueMedianWinningBid",
      "totalBidsAnalyzed",
      "positionBids",
      "tierBids",
      "teamAggression",
      "recentWins",
      "playerHistory",
    ]) {
      expect(data, `faabAnalytics missing ${k}`).toHaveProperty(k);
    }
    expect(typeof data.leagueBudget).toBe("number");
    expect(Array.isArray(data.recentWins)).toBeTruthy();
    expect(typeof data.positionBids).toBe("object");
    expect(typeof data.tierBids).toBe("object");
  });
});
