/**
 * Critical journey: the rankings board.
 *
 * This is the heart of the redesign safety net — the board is the
 * single most-used surface and the first page any rewrite touches.
 * Every test asserts BEHAVIOR (rows render, sorting reorders,
 * filtering narrows, popup shows the source breakdown, search finds
 * players) rather than pixel/markup details, so the assertions stay
 * meaningful through a UI rewrite.  Selectors live in
 * helpers/journey.js (SEL) — update them there when the DOM changes.
 *
 * Auth: uses the test-only session fixture (skips cleanly when
 * E2E_TEST_SECRET is unset — see helpers/auth-fixture.js).
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  SEL,
  desktopOnly,
  gotoRankingsBoard,
  boardPlayerNames,
  boardRowCount,
  expectNoBadValueTokens,
  attachConsoleGuards,
} = require("../helpers/journey");

test.describe("journey: rankings board", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("board loads with real rows and clean values", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    const rows = await gotoRankingsBoard(page);

    // Structure, not names: every visible row has a non-empty player
    // name and a position token.
    //
    // The >= 50 belongs on the board's SIZE, not on the number of names
    // in the DOM. The table is windowed, so it mounts a viewport's worth
    // of rows by design — asserting on mounted names would report the
    // feature as the failure, and quietly lowering the number would stop
    // this test noticing a board that came back with two rows.
    // journey.js::boardRowCount reads the table's own `aria-rowcount`.
    expect(await boardRowCount(page)).toBeGreaterThanOrEqual(50);
    const names = await boardPlayerNames(page);
    expect(names.length, "no player names rendered").toBeGreaterThan(0);
    expect(names.every((n) => n.trim().length > 0)).toBeTruthy();

    // Rank column (#) counts up from 1 on the default sort.
    const firstRowText = await rows.first().innerText();
    expect(firstRowText).toMatch(/\b1\b/);

    // No NaN/undefined leaking into any board cell.
    await expectNoBadValueTokens(page, `${SEL.boardRow} td`);

    guard.assertClean();
  });

  test("columns sort — clicking Player toggles alphabetical order", async ({ authedPage: page }) => {
    await gotoRankingsBoard(page);

    const header = page.getByRole("columnheader", { name: /^Player/ });
    await expect(header).toBeVisible();

    // Click once → sort by name (ascending or descending, we don't
    // pin which — only that the result is alphabetically ordered).
    await header.click();
    await expect
      .poll(async () => {
        const names = (await boardPlayerNames(page)).map((n) => n.toLowerCase());
        if (names.length < 10) return "too-few-rows";
        const asc = [...names].sort();
        const desc = [...asc].reverse();
        if (names.join("|") === asc.join("|")) return "asc";
        if (names.join("|") === desc.join("|")) return "desc";
        return "unsorted";
      }, { message: "clicking Player header should alphabetize the board", timeout: 15_000 })
      .toMatch(/^(asc|desc)$/);

    const firstOrder = (await boardPlayerNames(page)).join("|");

    // Click again → direction flips (order reverses).
    await header.click();
    await expect
      .poll(async () => (await boardPlayerNames(page)).join("|"), {
        message: "second click should reverse the sort direction",
        timeout: 15_000,
      })
      .not.toBe(firstOrder);
  });

  test("position filter narrows the board to one position", async ({ authedPage: page }) => {
    const rows = await gotoRankingsBoard(page);
    const totalBefore = await rows.count();

    // The position <select> is the first select in the filter bar.
    await page.locator(SEL.posSelect).first().selectOption("QB");

    // Data-driven: wait until the board settles into a QB-only state.
    await expect
      .poll(async () => {
        const texts = await rows.allInnerTexts();
        if (texts.length === 0) return "empty";
        const allQb = texts.every((t) => /\bQB\d*\b/.test(t));
        return allQb ? `qb-only:${texts.length}` : "mixed";
      }, { message: "QB filter should leave only QB rows", timeout: 15_000 })
      .toMatch(/^qb-only:/);

    const totalAfter = await rows.count();
    expect(totalAfter).toBeGreaterThan(0);
    expect(totalAfter).toBeLessThan(totalBefore);

    // Reset back to All restores a bigger board.
    await page.locator(SEL.posSelect).first().selectOption("all");
    await expect
      .poll(() => rows.count(), { timeout: 15_000 })
      .toBeGreaterThan(totalAfter);
  });

  test("search input filters the board by name fragment", async ({ authedPage: page }) => {
    const rows = await gotoRankingsBoard(page);

    // Sample a real name from the live board — no hardcoded players.
    const names = await boardPlayerNames(page);
    const sample = names.find((n) => n.trim().split(/\s+/).length >= 2);
    expect(sample, "expected at least one multi-word player name").toBeTruthy();
    const fragment = sample.trim().split(/\s+/)[1]; // surname fragment

    await page.locator(SEL.searchInput).fill(fragment);
    await expect
      .poll(async () => {
        const visible = await boardPlayerNames(page);
        if (visible.length === 0) return "empty";
        const lower = fragment.toLowerCase();
        return visible.every((n) => n.toLowerCase().includes(lower))
          ? "filtered"
          : "mixed";
      }, { message: `board should narrow to names containing "${fragment}"`, timeout: 15_000 })
      .toBe("filtered");

    await page.locator(SEL.searchInput).fill("");
    await expect.poll(() => rows.count(), { timeout: 15_000 }).toBeGreaterThan(10);
  });

  test("player popup opens with value + source breakdown", async ({ authedPage: page }) => {
    await gotoRankingsBoard(page);

    // Click the first player name → popup sheet.
    await page.locator(SEL.playerName).first().click();
    const sheet = page.locator(SEL.overlaySheet).first();
    await expect(sheet).toBeVisible({ timeout: 15_000 });

    // The popup's contract: our blended value + the per-source
    // breakdown that explains it.
    await expect(sheet).toContainText(/Our Value/i);
    await expect(sheet).toContainText(/Source Breakdown/i, { timeout: 15_000 });

    // Close via the accessible close control.
    await page.getByRole("button", { name: /close player details/i }).click();
    await expect(sheet).not.toBeVisible();
  });

  test("global search ('/' shortcut) finds a player and opens their popup", async ({ authedPage: page }) => {
    await gotoRankingsBoard(page);
    const names = await boardPlayerNames(page);
    const sample = names.find((n) => n.trim().split(/\s+/).length >= 2);
    const fragment = sample.trim().split(/\s+/)[1];

    // The nav search affordance rendering is the signal that the
    // client auth check has resolved — before that, the "/" shortcut
    // is not yet registered.  Data-driven wait, then use the shortcut.
    await expect(page.locator(SEL.navSearchButton)).toBeVisible({ timeout: 30_000 });

    // Focus must not be inside an input for the shortcut to fire.
    await page.locator("h1").first().click();
    await page.keyboard.press("/");

    // R1 command palette — combobox labelled "Search players, picks,
    // and pages".
    const searchInput = page.getByLabel(/search players, picks/i);
    await expect(searchInput).toBeVisible({ timeout: 10_000 });
    await searchInput.fill(fragment);

    // Results are data-driven — wait for actual result rows.
    const results = page.locator(SEL.searchResult);
    await expect(results.first()).toBeVisible({ timeout: 10_000 });
    const resultNames = await page.locator(SEL.searchResultName).allInnerTexts();
    expect(
      resultNames.some((n) => n.toLowerCase().includes(fragment.toLowerCase())),
      `search results should include a name containing "${fragment}"`,
    ).toBeTruthy();

    // Selecting a result opens the player popup.
    await results.first().click();
    const sheet = page.locator(SEL.overlaySheet).first();
    await expect(sheet).toBeVisible({ timeout: 10_000 });
    await expect(sheet).toContainText(/Our Value/i);
  });
});
