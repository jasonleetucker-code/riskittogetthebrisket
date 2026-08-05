/**
 * Critical journey: the /tools/* health & diagnostic pages.
 *
 * These are the pages the owner opens when something looks wrong, so a
 * silent break here costs twice: the surface is down AND the tool for
 * noticing it is down.  Neither page had any e2e coverage before this
 * spec — `/tools/source-health` and `/tools/ros-data-health` appeared
 * in no spec at all, and `/tools/trade-coverage` appeared only in
 * critical-smoke's anonymous-redirect list (which asserts the login
 * gate, not that the page works).
 *
 * Assertion policy: every assertion below is derived from a live API
 * payload fetched inside the test — the real source registry, the real
 * Sleeper team list.  Nothing asserts on chrome, class names, colours
 * or fonts, so the design-system rewrite can proceed underneath.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  desktopOnly,
  pageUrl,
  pageHeading,
  contractFixture,
  attachConsoleGuards,
} = require("../helpers/journey");

test.describe("journey: /tools health pages", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("/tools/source-health lists real scraper sources from /api/status", async ({
    authedPage: page,
  }) => {
    // Authoritative source list straight from the backend:
    // `source_health.sources_detail`, one registry-keyed row per source
    // the pipeline ingests.
    //
    // This assertion used to read `source_runtime.enabled_sources` and
    // require the rendered rows to EQUAL it — i.e. it pinned the defect
    // as the contract.  That list is the legacy browser scraper's own
    // run plan (4 names) while the board blends 21 registered sources,
    // so the spec passed while the page hid a 17-source outage
    // (W05-F001 / W23-F007).
    const statusRes = await page.request.get("/api/status");
    expect(statusRes.status()).toBe(200);
    const status = await statusRes.json();
    const detail = status?.source_health?.sources_detail || [];
    const enabled = detail.map((r) => r.key);
    expect(
      Array.isArray(detail),
      "/api/status must report source_health.sources_detail",
    ).toBeTruthy();

    // Every source the board actually serves has to appear on the page
    // dedicated to source health — that is the whole claim its subtitle
    // makes.
    const served = Object.keys(status?.served_source_coverage || {});
    for (const key of served) {
      expect(
        enabled,
        `${key} votes on the served board but /api/status.source_health does not list it`,
      ).toContain(key);
    }

    await page.goto(pageUrl("/tools/source-health"), {
      waitUntil: "domcontentloaded",
    });
    await expect(pageHeading(page, /Source Health/i)).toBeVisible({
      timeout: 60_000,
    });

    const strip = page.locator('[aria-label="Scrape source health"]');

    // `SourceHealthStrip` renders null when the backend reports zero
    // enabled sources (components/SourceHealthStrip.jsx:129).  Both
    // states are asserted rather than skipped, so the component's
    // contract is pinned either way.
    if (enabled.length === 0) {
      await expect(
        strip,
        "backend reports no enabled sources, so the strip must render nothing",
      ).toHaveCount(0);
      return;
    }

    // 90s budget: the strip's own fetch goes through the Next
    // `/api/status` proxy, which aborts at 3s and falls back to a
    // silent null render (see docs/e2e-assertion-audit.md §3.3).  The
    // component retries every 60s, so spanning one refresh cycle makes
    // this deterministic instead of load-sensitive.
    await expect(strip).toBeVisible({ timeout: 90_000 });
    await expect(strip).toContainText(/Sources/i);

    await page.locator(".source-health-toggle").click();

    const names = page.locator(".source-health-name");
    await expect
      .poll(() => names.count(), {
        message: `expanding the strip should reveal ${enabled.length} per-source rows`,
        timeout: 30_000,
      })
      .toBe(enabled.length);

    // Every source the page names must be one the backend actually
    // reports.  Catches a stale hardcoded list or a mangled mapping —
    // the failure mode where the page looks healthy while describing
    // sources that no longer exist.
    const rendered = (await names.allInnerTexts()).map((t) => t.trim()).filter(Boolean);
    for (const name of rendered) {
      expect(
        enabled,
        `source-health rendered "${name}", which /api/status does not list as enabled`,
      ).toContain(name);
    }
  });

  test("/tools/trade-coverage audits every Sleeper team in the contract", async ({
    authedPage: page,
  }) => {
    const guard = attachConsoleGuards(page);
    const { teamNames } = await contractFixture(page);
    expect(teamNames.length, "contract must carry Sleeper teams").toBeGreaterThan(0);

    await page.goto(pageUrl("/tools/trade-coverage"), {
      waitUntil: "domcontentloaded",
    });
    await expect(pageHeading(page, /Trade Coverage Audit/i)).toBeVisible({
      timeout: 60_000,
    });

    // One row per team, carrying that team's real name.  The page fans
    // out one request per team, so a partial render (the common failure
    // when the fan-out throws midway) shows up as a short row list.
    const rows = page.locator(".trade-coverage-row");
    await expect
      .poll(() => rows.count(), {
        message: `expected one audit row per contract team (${teamNames.length})`,
        timeout: 60_000,
      })
      .toBe(teamNames.length);

    const renderedNames = (await page.locator(".trade-coverage-team-name").allInnerTexts())
      .map((t) => t.trim());
    for (const name of teamNames) {
      expect(renderedNames, `team "${name}" missing from the coverage audit`).toContain(
        name,
      );
    }

    // The scan counter must reach every team — this is the page's own
    // statement that it finished the fan-out rather than stalling.
    await expect(page.locator(".trade-coverage-summary")).toContainText(
      new RegExp(`${teamNames.length}\\s*/\\s*${teamNames.length}`),
      { timeout: 60_000 },
    );

    // Player counts come from the contract's rosters, so they must be
    // real positive integers — "0 players" for every team is the
    // signature of rosters loading as empty shells.
    const playerCells = await page
      .locator(".trade-coverage-row .trade-coverage-cell:nth-child(3)")
      .allInnerTexts();
    const counts = playerCells.map((t) => Number(t.trim())).filter((n) => Number.isFinite(n));
    expect(counts.length).toBe(teamNames.length);
    expect(
      counts.every((n) => n > 0),
      `every team should carry players; got ${JSON.stringify(counts)}`,
    ).toBeTruthy();

    // NOTE — deliberately NOT asserted: the Δ7/30/90/180 columns and
    // "Total Value".  Those come from `/api/terminal`, which has no
    // Next.js proxy route (frontend/app/api/ defines 21 handlers and
    // terminal is not one of them).  Served from the Next origin — the
    // topology `E2E_PAGE_ORIGIN` selects — a relative
    // `fetch("/api/terminal")` 404s, so those columns render "—" here
    // while working fine in production behind nginx.  Asserting on
    // them would pin a topology artifact, not product behaviour.  See
    // docs/e2e-assertion-audit.md §3.1.
    guard.assertClean();
  });
});
