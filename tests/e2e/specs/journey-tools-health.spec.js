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
    // Authoritative population straight from the backend.  The strip
    // renders `source_health.registered_sources` — the ranking-source
    // REGISTRY, the population the page is entitled to expect — not
    // `source_runtime.enabled_sources`, which carries the scraper's
    // own run names for the two ANCHOR markets ("KTC", "IDPTradeCalc").
    // This spec asserted the runtime list until F-7 (2026-08-18)
    // repopulated the component (SourceHealthStrip.jsx:100-114), which
    // left the old assertion demanding 21 === 2.
    const statusRes = await page.request.get("/api/status");
    expect(statusRes.status()).toBe(200);
    const status = await statusRes.json();
    const health = status?.source_health || {};
    const registered = health.registered_sources;
    expect(
      Array.isArray(registered) && registered.length > 0,
      "/api/status must report a non-empty source_health.registered_sources — the registry is compiled in, so an empty list means the backend broke, not that there is nothing to render",
    ).toBeTruthy();

    // The status block and the registry endpoint must agree on the
    // population — catches either side drifting from the other.  This
    // is what keeps the expectation contract-derived instead of a
    // magic row count that goes stale the next time a source lands.
    const regRes = await page.request.get("/api/rankings/sources");
    expect(regRes.status()).toBe(200);
    const registry = await regRes.json();
    const registryKeys = (registry.sources || [])
      .map((s) => s && s.key)
      .filter(Boolean);
    expect(
      [...new Set(registryKeys)].sort(),
      "source_health.registered_sources must be exactly the ranking-source registry",
    ).toEqual([...registered].sort());

    await page.goto(pageUrl("/tools/source-health"), {
      waitUntil: "domcontentloaded",
    });
    await expect(pageHeading(page, /Source Health/i)).toBeVisible({
      timeout: 60_000,
    });

    const strip = page.locator('[aria-label="Scrape source health"]');

    // 90s budget: the strip's own fetch goes through the Next
    // `/api/status` proxy, which aborts at 3s and falls back to a
    // render without this aria-label (see docs/e2e-assertion-audit.md
    // §3.3).  The component retries every 60s, so spanning one refresh
    // cycle makes this deterministic instead of load-sensitive.
    await expect(strip).toBeVisible({ timeout: 90_000 });
    await expect(strip).toContainText(/Sources/i);

    await page.locator(".source-health-toggle").click();

    const names = page.locator(".source-health-row .source-health-name");
    await expect
      .poll(() => names.count(), {
        message: `expanding the strip should reveal ${registered.length} per-source rows`,
        timeout: 30_000,
      })
      .toBe(registered.length);

    // SET equality, not just a count: the rendered names must be
    // exactly the registered population.  A bare count passes when one
    // source is dropped and another duplicated; one-directional
    // containment passes when a source silently vanishes.  This single
    // assertion catches missing, extra, duplicated and invented rows.
    const rendered = (await names.allInnerTexts())
      .map((t) => t.trim())
      .filter(Boolean);
    expect(
      [...rendered].sort(),
      "the strip must render one row per registered source — no more, no fewer",
    ).toEqual([...registered].sort());

    // A source the pipeline could not measure must SAY so — "not
    // measured" / "no rows" — never render as a healthy count.  Pinning
    // the vocabulary keeps missing data from displaying as
    // zero-but-fine (MISSING IS NEVER ZERO, applied to the UI).
    const countTexts = await page
      .locator(".source-health-row .source-health-count")
      .allInnerTexts();
    expect(countTexts.length).toBe(registered.length);
    for (const text of countTexts) {
      expect(
        text.trim(),
        `per-source status "${text.trim()}" is outside the strip's declared vocabulary`,
      ).toMatch(/^(not measured|no rows|[\d,]+ rows)$/);
    }

    // Sources the backend measured at zero are surfaced in the missing
    // line — and the line must be absent when nothing is missing, so
    // absence of data is reported rather than dressed up as health.
    const missing = Array.isArray(health.missing_sources)
      ? health.missing_sources
      : [];
    const missingLine = page.locator(".source-health-missing");
    if (missing.length > 0) {
      await expect(missingLine).toBeVisible();
      for (const name of missing) {
        await expect(missingLine).toContainText(name);
      }
    } else {
      await expect(missingLine).toHaveCount(0);
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

    // Poll the VALUE being asserted, not a different selector and then a
    // one-shot read of this one.
    //
    // The row <li> and its name <span> are emitted together
    // (tools/trade-coverage/page.jsx:201-203), so a matched row count can
    // never mean "rows without names". The observed failure was the list
    // re-rendering in the gap between the row poll above and this read —
    // the page fans out one request per team and re-renders as each
    // lands — which surfaced as `Received array: []` on an otherwise
    // healthy page, then passed on retry. Polling the rows and reading
    // the names is two observations of a moving list; this is one.
    const nameCells = page.locator(".trade-coverage-team-name");
    await expect
      .poll(
        async () => {
          const names = (await nameCells.allInnerTexts()).map((t) => t.trim());
          return teamNames.filter((n) => !names.includes(n)).length;
        },
        {
          message: `every contract team (${teamNames.length}) must appear in the audit`,
          timeout: 60_000,
        },
      )
      .toBe(0);

    // Re-read once settled, so the per-team failure below names the exact
    // missing team rather than reporting a count.
    const renderedNames = (await nameCells.allInnerTexts()).map((t) => t.trim());
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
