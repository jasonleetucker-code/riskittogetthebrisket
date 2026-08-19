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
    // Authoritative source list straight from the backend — and it is
    // `registered_sources`, NOT `source_runtime.enabled_sources`.
    //
    // This comment used to say the opposite, and it was true when it was
    // written.  F-7 (repaired 2026-08-18) changed what the strip renders
    // from, for a stated reason: `enabled_sources` carries the scraper's
    // run names for the two ANCHOR markets, so a page whose subtitle
    // promises "every ranking source in the pipeline" was rendering 2
    // rows out of 21 and a source that stopped contributing entirely
    // could never appear as missing — it was never in the population.
    // `SourceHealthStrip.jsx` now takes the registry and falls back to
    // the runtime list only when the registry is empty.
    //
    // The test was not updated with it, so it has been asserting 21 === 2
    // ever since.  It mirrors the component's own ladder now rather than
    // pinning one branch of it.
    const statusRes = await page.request.get("/api/status");
    expect(statusRes.status()).toBe(200);
    const status = await statusRes.json();
    const health = status?.source_health || {};
    const registered = Array.isArray(health.registered_sources)
      ? health.registered_sources
      : [];
    const runtimeEnabled = Array.isArray(health.source_runtime?.enabled_sources)
      ? health.source_runtime.enabled_sources
      : [];
    const enabled = registered.length ? registered : runtimeEnabled;
    expect(
      registered.length || runtimeEnabled.length,
      "/api/status must report registered_sources or source_runtime.enabled_sources",
    ).toBeGreaterThan(0);

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

    // Scoped to registry ROWS. `.source-health-name` alone also matches
    // the unattributed-failure block the strip renders when a scrape
    // reports a source it cannot map to a registry key, so an unscoped
    // count silently adds two different populations and this assertion
    // — `=== enabled.length` — breaks on the first partial scrape. It
    // passes today only because the committed snapshot reports none.
    const names = page.locator(".source-health-row .source-health-name");
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
