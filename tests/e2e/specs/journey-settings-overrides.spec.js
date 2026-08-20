/**
 * Critical journey: settings source-toggle round-trip.
 *
 * The single-source-of-truth override path (see CLAUDE.md): toggling a
 * source on /settings must fire POST /api/rankings/overrides — there is
 * NO frontend ranking engine.  What the response must carry changed in
 * #875: custom source weighting is WITHDRAWN
 * (`_SOURCE_OVERRIDES_DISABLED` in src/api/data_contract.py), because a
 * user-weighted board published under rankDerivedValue is a second
 * canonical valuation truth.  The round-trip is still asserted
 * end-to-end; the response must now carry the withdrawal contract — an
 * explicit warning, no custom mix reported active, the toggled source
 * still blended — and the rankings page must NOT show the custom-mix
 * badge.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 * State: settings live in localStorage — each test gets a fresh
 * browser context, so toggles never leak between tests.
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  desktopOnly,
  gotoRankingsBoard,
  attachConsoleGuards,
  boardRowCount,
  pageUrl,
} = require("../helpers/journey");

test.describe("journey: settings source toggles", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("settings lists every registered ranking source with a toggle", async ({ authedPage: page }) => {
    // Authoritative registry size from the backend.
    const regRes = await page.request.get("/api/rankings/sources");
    expect(regRes.status()).toBe(200);
    const registry = await regRes.json();
    const sources = registry.sources || registry;
    const registeredCount = Array.isArray(sources)
      ? sources.length
      : Object.keys(sources).length;
    expect(registeredCount).toBeGreaterThan(3);

    await page.goto(pageUrl("/settings"), { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText(/Ranking Sources/i, { timeout: 30_000 });

    // One include-in-blend toggle per registered dynasty source.
    const toggles = page.locator('input.settings-src-toggle[aria-label^="Include "]');
    await expect(toggles.first()).toBeVisible({ timeout: 30_000 });
    expect(await toggles.count()).toBeGreaterThanOrEqual(registeredCount);
  });

  test("toggling a source round-trips, and the withdrawn custom mix is ignored rather than applied", async ({ authedPage: page }) => {
    // Each overrides POST rebuilds the full blend server-side on a
    // memo miss (CPU-seconds per call), and this journey triggers it
    // twice — once from /settings, once when /rankings rehydrates.
    // Give the whole round-trip more than the default budget.
    test.setTimeout(180_000);
    const guard = attachConsoleGuards(page);

    // Collect the app's base-contract fallback warnings from the START of
    // the journey.  This listener used to be attached further down, after
    // the first round-trip had already been asserted — so it watched an
    // arbitrary window that began once the thing it was diagnosing had
    // already succeeded.  Its output is now folded into the badge failure
    // message below, which is the only place it is read.
    const fallbackWarnings = [];
    page.on("console", (msg) => {
      if (msg.type() !== "warning") return;
      const text = msg.text() || "";
      if (text.includes("/api/rankings/overrides") || text.includes("falling through to base contract")) {
        fallbackWarnings.push(text);
      }
    });

    // Registry lookup so the toggled control can be mapped back to its
    // source KEY: the withdrawal contract below is asserted in key
    // vocabulary (`rankingsOverride.enabledSources` carries registry
    // keys, while the toggle's aria-label carries the display name).
    const regRes = await page.request.get("/api/rankings/sources");
    expect(regRes.status()).toBe(200);
    const registrySources = ((await regRes.json()).sources || []).filter(Boolean);

    await page.goto(pageUrl("/settings"), { waitUntil: "domcontentloaded" });
    const toggles = page.locator('input.settings-src-toggle[aria-label^="Include "]');
    await expect(toggles.first()).toBeVisible({ timeout: 30_000 });

    // Pick the first currently-enabled toggle and switch it off.
    const enabledToggle = toggles.and(page.locator(":checked")).first();
    await expect(enabledToggle).toBeVisible({ timeout: 15_000 });
    const toggleLabel = (await enabledToggle.getAttribute("aria-label")) || "";
    const toggledDisplayName = toggleLabel
      .replace(/^Include /, "")
      .replace(/ in blend$/, "");
    const disabledKey = registrySources.find(
      (s) => s.displayName === toggledDisplayName,
    )?.key;
    expect(
      disabledKey,
      `the toggle labelled ${JSON.stringify(toggleLabel)} must resolve to a registry source key`,
    ).toBeTruthy();

    // The round-trip contract: the click must fire POST
    // /api/rankings/overrides and it must succeed.  60s budget: the
    // POST only fires after useDynastyData's base-contract fetch
    // (~5 MB) settles, which can take a while on a busy runner.
    const [overridesResponse] = await Promise.all([
      page.waitForResponse(
        (res) =>
          res.url().includes("/api/rankings/overrides") &&
          res.request().method() === "POST",
        { timeout: 60_000 },
      ),
      enabledToggle.click(),
    ]);
    expect(
      overridesResponse.status(),
      "overrides endpoint should answer the toggle successfully",
    ).toBe(200);

    // Read the delta by REPLAYING the captured body through the API
    // request context — deliberately NOT `overridesResponse.json()`.
    // Playwright's `.json()` waits for the browser to finish loading
    // the response body, and the app drains this ~4.7 MB body only
    // after its base-contract fetch resolves
    // (dynasty-data.js::_postOverridesAndMerge); when it falls through
    // to the base contract instead, the body is never consumed,
    // `.json()` has no timeout of its own, and the test burns its whole
    // budget — the 180s retry hang in E2E runs 140/142.  The replay
    // posts the byte-identical body straight to the backend: the memo
    // key is derived from the request's normalized inputs, so the
    // replay is served from the same slot the page's own POST
    // populated, with no dependence on the page draining anything.
    const postData = overridesResponse.request().postData();
    expect(postData, "the toggle POST must carry a JSON body").toBeTruthy();
    const overridesUrl = new URL(overridesResponse.url());
    const replay = await page.request.post(
      overridesUrl.pathname + overridesUrl.search,
      {
        headers: { "content-type": "application/json" },
        data: postData,
        timeout: 60_000,
      },
    );
    expect(
      replay.status(),
      "replaying the captured overrides body against the backend should succeed",
    ).toBe(200);
    const delta = await replay.json();

    // The delta payload really is a delta carrying recomputed
    // per-player rows.  (The assertion this replaces counted `delta`'s
    // top-level keys after falling through `delta.players ||
    // delta.playersDelta || delta` — neither key exists on the delta
    // shape, so it was vacuously green on any non-empty response.)
    expect(delta.mode, "the ?view=delta response must be a delta").toBe(
      "delta",
    );
    expect(Array.isArray(delta.rankingsDelta?.players)).toBe(true);
    expect(delta.rankingsDelta.players.length).toBeGreaterThan(50);

    // The withdrawal contract (#875, `_SOURCE_OVERRIDES_DISABLED` in
    // src/api/data_contract.py): user source weighting must not mint a
    // second canonical board.  The endpoint accepts the toggle, but
    // 1) it says explicitly that the weighting was ignored,
    expect(
      delta.warnings || [],
      "the overrides response must state that custom weighting is withdrawn",
    ).toEqual(
      expect.arrayContaining([
        expect.stringContaining("custom source weighting is disabled"),
      ]),
    );
    // 2) it reports no custom mix as active,
    const rankingsOverride = delta.rankingsOverride || {};
    expect(
      rankingsOverride.isCustomized,
      "no custom mix may be reported as active",
    ).toBe(false);
    // 3) and the toggled-off source stays in the blend.
    expect(
      rankingsOverride.enabledSources || [],
      "the disabled source must still be blended — the override is ignored, not applied",
    ).toContain(disabledKey);

    // The rankings board must still render, and /rankings must re-fire
    // its own overrides POST on hydration — the round-trip machinery is
    // intact even though the weighting itself is withdrawn.
    //
    // This block used to `test.skip` when the badge never appeared AND
    // the app had logged its base-contract fallback warning.  That reads
    // as honest — the first round-trip IS hard-asserted above — but
    // docs/e2e-assertion-audit.md measured the skip firing ROUTINELY,
    // reason "...Failed to fetch".  A product degradation that reports as
    // a green skip is the one thing tests/e2e/README.md's convention 5
    // forbids: "Skip cleanly on absent INFRA — never on absent DATA."  A
    // degraded overrides endpoint is the product failing, not absent
    // infrastructure.
    //
    // The audit's own remedy was "a floor on consecutive skips, or
    // removal once the endpoint is reliable".  Playwright keeps no
    // cross-run state, so a consecutive-skip floor means a new counter
    // in e2e.yml — more machinery than the thing it guards, firing a day
    // late, and a second place where "green" gets computed.
    //
    // So: removal, with a MORE specific assertion in its place rather
    // than a weaker one.  /rankings fires its OWN overrides POST during
    // hydration; that second round-trip is what the badge depends on and
    // what the skip was silently forgiving.  Assert it directly, so a
    // failure says "the second overrides POST returned 503" instead of
    // "badge missing, cause unknown".  The underlying fragility is
    // docs/e2e-assertion-audit.md §3.3 — the Next proxy routes' hard 3s
    // abort — which is product-side and not this spec's to hide.
    //
    // Note this also restores guard.assertClean() below: test.skip()
    // throws, so on the skip path every browser console error collected
    // on this journey was discarded too.
    // NOTE: only `.status()` is read off this response — it is
    // header-derived and safe.  Its BODY is deliberately never read:
    // see the replay note above for why `.json()` on a page-initiated
    // overrides response can hang for the whole test budget.
    const rehydrateOverrides = page
      .waitForResponse(
        (res) =>
          res.url().includes("/api/rankings/overrides") &&
          res.request().method() === "POST",
        { timeout: 90_000 },
      )
      .catch(() => null);

    const rows = await gotoRankingsBoard(page);
    // WINDOWED BOARD: `rows.count()` counts MOUNTED rows, and since #912
    // the board mounts roughly a viewport's worth (~28) instead of all
    // ~1,100.  Asserting >50 mounted rows would now fail on a correct
    // board.  `boardRowCount` reads the table's published `aria-rowcount`,
    // which is the true logical total — the quantity this assertion was
    // always about.  `rows.count() > 0` keeps the separate claim that
    // something is actually on screen.
    expect(await boardRowCount(page)).toBeGreaterThan(50);
    expect(await rows.count(), "no board rows mounted").toBeGreaterThan(0);

    const rehydrateResponse = await rehydrateOverrides;
    expect(
      rehydrateResponse,
      "/rankings should re-fire the overrides POST on hydration — without it the custom mix is never applied",
    ).not.toBeNull();
    expect(
      rehydrateResponse.status(),
      "the /rankings-side overrides round-trip should also recompute successfully",
    ).toBe(200);

    // The custom-mix badge must NOT appear: the backend ignored the
    // weighting, so showing the badge would claim a custom board that
    // was never produced.  (This spec asserted the badge VISIBLE until
    // #875 withdrew custom weighting — the stale expectation behind the
    // failures in E2E runs 140/142.)  10s wait: the board rendered and
    // the rehydrate POST completed above, so anything that would mount
    // the badge has already happened.
    const badge = page.locator('[aria-label="Custom source mix active"]').first();
    const badgeVisible = await badge
      .waitFor({ state: "visible", timeout: 10_000 })
      .then(() => true)
      .catch(() => false);
    expect(
      badgeVisible,
      `the custom-mix badge must NOT appear while source weighting is withdrawn — showing it would claim an override the backend ignored${
        fallbackWarnings.length > 0
          ? ` — the app logged a base-contract fallback: ${fallbackWarnings[0]}`
          : ""
      }`,
    ).toBe(false);

    guard.assertClean();
  });
});
