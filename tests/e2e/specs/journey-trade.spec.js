/**
 * Critical journey: trade surfaces.
 *
 *   - /trade      — the trade builder (calculator) renders and accepts input
 *   - /trades     — trade history renders (cards or explicit empty state)
 *   - /rankings?screen= — a screen deep-link actually narrows the board
 *   - /arbitrage  — the board-vs-market scan resolves to trades or an
 *     explicit empty state
 *   - POST /api/trade/finder — the same engine at the API level
 *
 * The last two used to be one test pointed at /finder and named after
 * the arbitrage board, which was two different surfaces confused for
 * one.  /finder is now a redirect shim into /rankings; see the comment
 * above those tests.  The old header here also said "no UI consumes this
 * endpoint today", which stopped being true when /arbitrage shipped as
 * its caller.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  desktopOnly,
  attachConsoleGuards,
  pageUrl,
  SEL,
  pageHeading,
  titleFor,
} = require("../helpers/journey");

test.describe("journey: trade surfaces", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("/trade renders the builder with working controls", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });

    // Header renders, then the player pool finishes loading (the
    // "Loading player pool..." sentinel clears once /api/data lands).
    // Was `body` + /Trade Builder/i: loose on a nav label present on
    // every authed page (so it passed with <main> deleted — see
    // docs/e2e-assertion-audit.md) AND wrong after the #625 rename.
    // The page's own <h1>, anchored to the canon, fixes both.
    await expect(pageHeading(page, titleFor("/trade"))).toBeVisible({
      timeout: 30_000,
    });
    await page.waitForFunction(
      () => !document.body.innerText.includes("Loading player pool..."),
      null,
      { timeout: 60_000 },
    );

    // Core builder controls exist once data is ready.
    await expect(page.getByRole("button", { name: /Swap Sides|Rotate Sides/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Clear Trade/ })).toBeVisible();

    guard.assertClean();
  });

  test("/trades renders history (real trades or explicit empty state)", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/trades"), { waitUntil: "domcontentloaded" });

    // R4 replaced the "Loading trade data..." sentinel with a skeleton,
    // so waiting for that string to vanish is now vacuous — and the
    // page title renders immediately, which would make the old
    // assertion pass before any data landed.  Wait for real settled
    // content instead: either a ledger entry or the explicit empty
    // state.  Both are data-driven; neither exists mid-load.
    const settled = page
      .locator(SEL.tradeLedgerEntry)
      .or(page.getByText(/No trades found/i));
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });

    guard.assertClean();
  });

  // ── What replaced "/finder renders the arbitrage board" ──────────
  //
  // That test asserted one page and was named after a different one, and
  // both halves of the confusion are now covered separately.
  //
  // /finder was a board FILTER — presets over sourceRankSpread /
  // confidenceBucket / isSingleSource / rookie.  It computed no
  // board-versus-market comparison at all, despite a stale header
  // comment there once calling it "the arbitrage blotter".  It is now a
  // redirect shim into /rankings and its presets are the Screens
  // dropdown, so its coverage belongs on /rankings (first test below).
  //
  // The actual board-vs-market engine (src/trade/finder.py) is /arbitrage,
  // which had NO e2e coverage at all — so the old test's *name* described
  // something real that nothing was testing (second test below).
  //
  // Deleting the stale test outright would have dropped both.

  test("a /rankings screen deep-link narrows the board to its question", async ({
    authedPage: page,
  }) => {
    const guard = attachConsoleGuards(page);

    // ``?screen=wr-gaps`` seeds the board view on mount (rankings
    // page.jsx). An unknown key deliberately falls through to the
    // default board rather than wedging, so asserting the URL loaded is
    // NOT enough — we have to prove the filter actually applied.
    await page.goto(pageUrl("/rankings?screen=wr-gaps"), {
      waitUntil: "domcontentloaded",
    });

    // Still the rankings board, not a 404 or a redirect somewhere else.
    // NOTE `pageHeading` RETURNS a locator — it asserts nothing on its
    // own, so it must be wrapped in expect(). A bare `await
    // pageHeading(...)` is a silent no-op.
    await expect(pageHeading(page, titleFor("/rankings"))).toBeVisible({
      timeout: 60_000,
    });

    const rows = page.locator(SEL.boardRow);
    await expect(rows.first(), "screened board should render rows").toBeVisible({
      timeout: 60_000,
    });
    const count = await rows.count();
    expect(count, "wr-gaps must match at least one player on the snapshot").toBeGreaterThan(0);

    // The screen's definition: WRs only. This is what makes the test
    // non-vacuous — the DEFAULT board is all positions, so if the
    // ?screen= seeding silently failed, non-WR rows would appear here.
    //
    // Addressed by `data-col`, not `nth-child`: the board's column set is
    // built conditionally (the Fund-gap column appears only while BDVM
    // serves an ok payload), so an ordinal selector would keep passing
    // while reading a different column.
    const positions = await page
      .locator(`${SEL.boardRow} td[data-col="pos"]`)
      .allInnerTexts();
    expect(positions.length, "pos column should be addressable").toBeGreaterThan(0);
    // The cell renders "WR" plus the position rank ("WR12"), so match the
    // leading token rather than requiring exact equality.
    const nonWr = positions
      .map((p) => p.trim())
      .filter((p) => p && !/^WR\b/.test(p));
    expect(nonWr, `wr-gaps returned non-WR rows: ${nonWr.slice(0, 5).join(", ")}`).toEqual([]);

    guard.assertClean();
  });

  test("/arbitrage scans and renders either trades or an explicit empty state", async ({
    authedPage: page,
  }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/arbitrage"), { waitUntil: "domcontentloaded" });

    await expect(pageHeading(page, titleFor("/arbitrage"))).toBeVisible({
      timeout: 30_000,
    });

    // Before any scan the page states what it wants, rather than showing
    // an empty table that reads like a broken board.
    await expect(page.getByText(/Pick a team and scan/i)).toBeVisible({
      timeout: 30_000,
    });

    // The team selector populates from the live contract; wait for a real
    // option rather than clicking into a disabled control.
    const teamSelect = page.getByLabel("Your team");
    await expect
      .poll(async () => (await teamSelect.locator("option").count()), {
        message: "team selector should populate from the contract",
        timeout: 60_000,
      })
      .toBeGreaterThan(0);

    // Click INSIDE the poll: the first click can land before React has
    // attached handlers and is then simply lost. Same remedy as the
    // archives race (public-league.spec.js).
    //
    // But NOT "click every tick". Re-clicking is not idempotent here —
    // `run()` sets `running: true`, and BOTH settled states are gated
    // on `!running` (arbitrage/page.jsx:283,289). So a click fired on
    // the same tick that the previous scan finished tears the result
    // straight back down, and since the click happened before the read,
    // the read always saw zero. That is not a hypothetical: it failed
    // deterministically, with 30+ trade cards visible in the trace.
    //
    // Hence: READ FIRST, and only click when no scan is in flight.
    // `disabled={running || dataLoading || !effectiveTeam}` makes
    // `isEnabled()` the page's own statement that a click is safe.
    const scan = page.getByRole("button", { name: /Find arbitrage|Scanning/i });
    const settled = page
      .locator(SEL.arbitrageTradeCard)
      .or(page.getByText(/No arbitrage found/i));

    await expect
      .poll(
        async () => {
          const count = await settled.count();
          if (count > 0) return count;
          if (await scan.isEnabled()) await scan.click();
          return 0;
        },
        {
          message: "scan should resolve to trades or the explicit empty state",
          timeout: 90_000,
          intervals: [500, 1000, 2000, 3000, 5000],
        },
      )
      .toBeGreaterThan(0);

    // Both outcomes are legitimate on a committed snapshot — what is NOT
    // legitimate is neither appearing, which is what the poll rules out.
    // Asserting "trades exist" would make this test hostage to whether
    // the frozen board happens to contain an arbitrage opportunity.
    guard.assertClean();
  });

  test("POST /api/trade/finder returns arbitrage trades for a real roster", async ({ authedPage: page }) => {
    // Pull a real team name from the live contract — no hardcoded names.
    const dataRes = await page.request.get("/api/data?view=app");
    expect(dataRes.status()).toBe(200);
    const contract = await dataRes.json();
    const teams = contract?.sleeper?.teams || [];
    // Was `test.skip(teams.length === 0, ...)`.  The committed snapshot
    // carries 12 Sleeper teams (verified 2026-07-27), so the gate never
    // fired — and it masked exactly the documented multi-league failure
    // mode (`sleeperDataReady: false`), reporting an empty roster
    // pipeline as "nothing to test" inside a green run.  Assert the
    // precondition instead so that regression fails loudly.
    expect(
      teams.length,
      "contract served no Sleeper rosters — the finder cannot be exercised, " +
        "and this is the sleeperDataReady:false regression, not an absent fixture",
    ).toBeGreaterThan(0);

    const myTeam = teams[0].name;
    const res = await page.request.post("/api/trade/finder", {
      data: { myTeam, opponentTeams: ["all"] },
    });
    expect(res.status(), await res.text().catch(() => "")).toBe(200);
    const body = await res.json();

    expect(Array.isArray(body.trades), "finder response must carry a trades array").toBeTruthy();
    expect(body).toHaveProperty("metadata");
    expect(body).toHaveProperty("leagueKey");

    // Without this, the loop below never executes on an empty array and
    // a test named "returns arbitrage trades for a real roster" passes
    // when the engine returns none — which is exactly the regression
    // #556 fixed (the finder silently dropping every IDP asset).  The
    // structural check has to come before the per-trade checks.
    expect(
      body.trades.length,
      "finder returned zero trades for a real roster — the engine is dropping assets",
    ).toBeGreaterThan(0);

    // Each has both sides populated with valued assets.
    for (const trade of body.trades.slice(0, 5)) {
      expect(Array.isArray(trade.give)).toBeTruthy();
      expect(Array.isArray(trade.receive)).toBeTruthy();
      expect(trade.give.length).toBeGreaterThan(0);
      expect(trade.receive.length).toBeGreaterThan(0);
      for (const asset of [...trade.give, ...trade.receive]) {
        expect(String(asset.name || "").length).toBeGreaterThan(0);
      }
    }
  });
});
