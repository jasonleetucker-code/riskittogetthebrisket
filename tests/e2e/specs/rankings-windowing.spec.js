/**
 * V1-106 regression evidence: row windowing on the Rankings board stays
 * ACTIVE as the board grows, on the current post-#984 (Premium Sports
 * Intelligence) renderer.
 *
 * `journey-rankings.spec.js` and `mobile-smoke.spec.js` already assert
 * `boardRowCount() >= 50` (the board's declared SIZE) and
 * `rows.count() > 0` (something is mounted) — but neither discriminates
 * between "windowed" and "every row mounted": both pass identically
 * either way, because `boardRowCount()` reads `aria-rowcount` when
 * present and falls back to the mounted `<tr>` count when it isn't, and
 * a non-empty capped board already clears both bars without touching
 * "Show all" at all. This file closes that gap: it proves the DOM stays
 * BOUNDED once the board is uncapped to its full size, that scrolling
 * moves the window rather than mounting everything, and that turning
 * `virtualize` off makes it RED (verified manually during development —
 * see the PR description for the mutation-proof transcript; not
 * committed as a fixture, since flipping product behavior to fail a
 * test on purpose is not itself something CI should carry).
 *
 * Renders through `components/ds/DataTable.jsx` (`virtualize` +
 * `freezeColumnWidths`, wired in `app/rankings/page.jsx`) — no frontend
 * canonical-value computation here or anywhere this file touches.
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  SEL,
  desktopOnly,
  mobileOnly,
  gotoRankingsBoard,
  boardRowCount,
  attachConsoleGuards,
} = require("../helpers/journey");

// A capped board is a few hundred rows at most; the full board has run
// ~900-1,100 in this repo's history (PR #760's evidence table). 500 is
// comfortably below every observed full-board size and comfortably
// above every observed capped size, so it discriminates "did Show all
// actually grow the board" without hard-coding today's exact count.
const FULL_BOARD_MIN_ROWS = 500;

// However large the board gets, a windowed table only ever mounts a
// viewport's worth of rows plus overscan — this repo's own harness
// evidence (PR #760) measured ~40-60 mounted rows against a board of
// 964-1,109. 200 is a generous multiple of that with headroom for a
// taller viewport or a wider overscan, while still being an order of
// magnitude below FULL_BOARD_MIN_ROWS — so it can only pass if the DOM
// is meaningfully bounded, not merely "less than everything".
const MAX_MOUNTED_ROWS = 200;

async function showAllRows(page) {
  const button = page.getByRole("button", { name: "Show all" });
  await button.click();
  await expect
    .poll(() => boardRowCount(page), {
      message: "board should grow to its full size after Show all",
      timeout: 30_000,
    })
    .toBeGreaterThanOrEqual(FULL_BOARD_MIN_ROWS);
}

/** True total (via aria-rowcount) vs what's actually mounted. */
async function boardShape(page) {
  const total = await boardRowCount(page);
  const mounted = await page.locator(SEL.boardRow).count();
  const declaredRowcount = await page.evaluate(() => {
    const table = document.querySelector(".ds-table-wrap table");
    return table?.getAttribute("aria-rowcount") ?? null;
  });
  return { total, mounted, declaredRowcount };
}

test.describe("V1-106: rankings board windowing stays active at scale", () => {
  test.describe("desktop", () => {
    test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

    test("full board mounts a bounded DOM, not one row per player", async ({
      authedPage: page,
    }) => {
      const guard = attachConsoleGuards(page);
      await gotoRankingsBoard(page);
      await showAllRows(page);

      const { total, mounted, declaredRowcount } = await boardShape(page);

      // Windowed, by the table's own account — this is what screen
      // readers and this test both rely on instead of counting <tr>.
      expect(declaredRowcount, "table should publish aria-rowcount when windowed").not.toBeNull();
      expect(total).toBeGreaterThanOrEqual(FULL_BOARD_MIN_ROWS);
      expect(
        mounted,
        `expected a bounded mount (<=${MAX_MOUNTED_ROWS}) against a ${total}-row board — ` +
          `if this fires, either windowing is off or the window itself has grown unbounded`,
      ).toBeLessThanOrEqual(MAX_MOUNTED_ROWS);

      guard.assertClean();
    });

    test("scrolling moves the window instead of mounting the rest of the board", async ({
      authedPage: page,
    }) => {
      await gotoRankingsBoard(page);
      await showAllRows(page);

      const before = await boardShape(page);
      const firstNameBefore = await page.locator(SEL.playerName).first().innerText();

      // Scroll the page well past the first window's worth of rows.
      await page.evaluate(() => window.scrollBy(0, 6000));
      await expect
        .poll(async () => (await page.locator(SEL.playerName).first().innerText()) !== firstNameBefore, {
          message: "top-of-window player should change after a large scroll",
          timeout: 15_000,
        })
        .toBe(true);

      const after = await boardShape(page);

      // The window slid (different content on screen)...
      const firstNameAfter = await page.locator(SEL.playerName).first().innerText();
      expect(firstNameAfter).not.toBe(firstNameBefore);
      // ...without the mount ballooning: the board's declared total is
      // unchanged and the mounted count is still bounded.
      expect(after.total).toBe(before.total);
      expect(after.mounted).toBeLessThanOrEqual(MAX_MOUNTED_ROWS);
    });
  });

  test.describe("mobile (390x844)", () => {
    test.beforeEach(async ({}, testInfo) => mobileOnly(test, testInfo));

    test("full board mounts a bounded DOM on a phone viewport too", async ({
      authedPage: page,
    }) => {
      const guard = attachConsoleGuards(page);
      await gotoRankingsBoard(page);
      await showAllRows(page);

      const { total, mounted, declaredRowcount } = await boardShape(page);

      expect(declaredRowcount, "table should publish aria-rowcount when windowed").not.toBeNull();
      expect(total).toBeGreaterThanOrEqual(FULL_BOARD_MIN_ROWS);
      expect(
        mounted,
        `mobile mount should stay bounded (<=${MAX_MOUNTED_ROWS}) against a ${total}-row board`,
      ).toBeLessThanOrEqual(MAX_MOUNTED_ROWS);

      guard.assertClean();
    });
  });
});
