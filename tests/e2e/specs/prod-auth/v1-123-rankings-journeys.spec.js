/**
 * V1-123 Phase 1 — rankings journeys on the DEPLOYED production site.
 *
 * Ports the interaction assertions from ../journey-rankings.spec.js
 * (sort, filter, search, player popup, global search) onto a real
 * authenticated production session, extending v1-111-premium-rankings's
 * existing populated-only, read-only-render coverage of the same page.
 *
 * Selectors are copied verbatim from tests/e2e/helpers/journey.js::SEL —
 * production serves the same Next.js build as local, so the same DOM
 * classes apply. Deliberately NOT importing journey.js itself: its
 * gotoRankingsBoard() goes through pageUrl() (the local dev-server
 * origin split), which does not apply here — prod-auth navigation goes
 * through prodUrl() exactly like every other spec in this directory.
 *
 * Read-only over the product: navigation, DOM reads, and one search
 * input fill — no mutating request is made.
 */
const { test, expect, prodUrl, annotate, desktopOnly } = require("./helpers");

const SEL = {
  boardRow: ".ds-table-wrap table tbody tr.rankings-row-clickable",
  playerName: ".rankings-player-name",
  searchInput: ".rankings-controls input.ds-input",
  posSelect: ".rankings-controls select.ds-select",
  overlaySheet: '[role="dialog"]',
  searchResult: ".shell-palette-option",
  searchResultName: ".shell-palette-option-name",
  navSearchButton: ".shell-search-btn",
};

async function boardRowCount(page) {
  return page.evaluate(() => {
    const table = document.querySelector(".ds-table-wrap table");
    if (!table) return 0;
    const declared = table.getAttribute("aria-rowcount");
    if (declared != null) return Math.max(0, Number(declared) - 1);
    return table.querySelectorAll("tbody tr.rankings-row-clickable").length;
  });
}

async function boardPlayerNames(page) {
  return page.locator(SEL.playerName).allInnerTexts();
}

async function gotoRankingsBoard(page) {
  await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });
  const rows = page.locator(SEL.boardRow);
  await expect(rows.first(), "production rankings board should render rows").toBeVisible({
    timeout: 90_000,
  });
  return rows;
}

test.describe("V1-123 Phase 1: rankings journeys (production)", () => {
  test("columns sort — clicking Player toggles alphabetical order", async ({
    prodPage: page,
  }, testInfo) => {
    await gotoRankingsBoard(page);
    const header = page.getByRole("columnheader", { name: /^Player/ });
    await expect(header).toBeVisible();

    await header.click();
    await expect
      .poll(
        async () => {
          const names = (await boardPlayerNames(page)).map((n) => n.toLowerCase());
          if (names.length < 10) return "too-few-rows";
          const asc = [...names].sort();
          const desc = [...asc].reverse();
          if (names.join("|") === asc.join("|")) return "asc";
          if (names.join("|") === desc.join("|")) return "desc";
          return "unsorted";
        },
        { message: "clicking Player header should alphabetize the board", timeout: 20_000 },
      )
      .toMatch(/^(asc|desc)$/);

    const firstOrder = (await boardPlayerNames(page)).join("|");
    await header.click();
    await expect
      .poll(async () => (await boardPlayerNames(page)).join("|"), {
        message: "second click should reverse the sort direction",
        timeout: 20_000,
      })
      .not.toBe(firstOrder);
    annotate(testInfo, "sort", "asc/desc toggled and reversed on the real production board");
  });

  test("position filter narrows the production board to one position", async ({
    prodPage: page,
  }, testInfo) => {
    const rows = await gotoRankingsBoard(page);
    const totalBefore = await boardRowCount(page);

    await page.locator(SEL.posSelect).first().selectOption("QB");
    await expect
      .poll(
        async () => {
          const texts = await rows.allInnerTexts();
          if (texts.length === 0) return "empty";
          const allQb = texts.every((t) => /\bQB\d*\b/.test(t));
          return allQb ? `qb-only:${texts.length}` : "mixed";
        },
        { message: "QB filter should leave only QB rows", timeout: 20_000 },
      )
      .toMatch(/^qb-only:/);

    const totalAfter = await boardRowCount(page);
    expect(totalAfter).toBeGreaterThan(0);
    expect(totalAfter).toBeLessThan(totalBefore);

    await page.locator(SEL.posSelect).first().selectOption("all");
    await expect
      .poll(() => boardRowCount(page), { timeout: 20_000 })
      .toBeGreaterThan(totalAfter);
    annotate(
      testInfo,
      "position-filter",
      `${totalBefore} -> ${totalAfter} (QB) -> restored, on the real production board`,
    );
  });

  test("search input filters the production board by name fragment", async ({
    prodPage: page,
  }, testInfo) => {
    await gotoRankingsBoard(page);
    const names = await boardPlayerNames(page);
    const sample = names.find((n) => n.trim().split(/\s+/).length >= 2);
    expect(sample, "expected at least one multi-word player name").toBeTruthy();
    const fragment = sample.trim().split(/\s+/)[1];

    await page.locator(SEL.searchInput).fill(fragment);
    await expect
      .poll(
        async () => {
          const visible = await boardPlayerNames(page);
          if (visible.length === 0) return "empty";
          const lower = fragment.toLowerCase();
          return visible.every((n) => n.toLowerCase().includes(lower)) ? "filtered" : "mixed";
        },
        { message: `board should narrow to names containing "${fragment}"`, timeout: 20_000 },
      )
      .toBe("filtered");

    await page.locator(SEL.searchInput).fill("");
    await expect.poll(() => boardRowCount(page), { timeout: 20_000 }).toBeGreaterThan(10);
    annotate(testInfo, "name-search", `filtered on "${fragment}" and cleared, on production`);
  });

  test("player popup opens with value + source breakdown on production", async ({
    prodPage: page,
  }, testInfo) => {
    await gotoRankingsBoard(page);
    await page.locator(SEL.playerName).first().click();
    const sheet = page.locator(SEL.overlaySheet).first();
    await expect(sheet).toBeVisible({ timeout: 20_000 });

    await expect(sheet).toContainText(/Our Value/i);
    await expect(sheet).toContainText(/Source Breakdown/i, { timeout: 20_000 });

    await page.getByRole("button", { name: /close player details/i }).click();
    await expect(sheet).not.toBeVisible();
    annotate(testInfo, "player-popup", "opened with Our Value + Source Breakdown, closed cleanly");
  });

  test("global search ('/' shortcut) finds a player and opens their popup on production", async ({
    prodPage: page,
  }, testInfo) => {
    // .shell-search-btn lives in components/shell/TopBar.jsx — "the
    // desktop shell header (R1)" per that file's own docstring. Mobile
    // uses a different chrome (the bottom tab bar's Menu drawer, covered
    // by v1-123-mobile-nav.spec.js), so this affordance genuinely does
    // not exist at the prod-mobile viewport. Confirmed by a real failed
    // run (33768425785): the other four interactions in this file
    // (sort/filter/search/popup) all passed on prod-mobile; only this
    // desktop-chrome-specific shortcut did not exist to find.
    desktopOnly(test, testInfo);
    await gotoRankingsBoard(page);
    const names = await boardPlayerNames(page);
    const sample = names.find((n) => n.trim().split(/\s+/).length >= 2);
    expect(sample, "expected at least one multi-word player name").toBeTruthy();
    const fragment = sample.trim().split(/\s+/)[1];

    await expect(page.locator(SEL.navSearchButton)).toBeVisible({ timeout: 30_000 });
    await page.locator("h1").first().click();
    await page.keyboard.press("/");

    const searchInput = page.getByLabel(/search players, picks/i);
    await expect(searchInput).toBeVisible({ timeout: 15_000 });
    await searchInput.fill(fragment);

    const results = page.locator(SEL.searchResult);
    await expect(results.first()).toBeVisible({ timeout: 15_000 });
    const resultNames = await page.locator(SEL.searchResultName).allInnerTexts();
    expect(
      resultNames.some((n) => n.toLowerCase().includes(fragment.toLowerCase())),
      `search results should include a name containing "${fragment}"`,
    ).toBeTruthy();

    await results.first().click();
    const sheet = page.locator(SEL.overlaySheet).first();
    await expect(sheet).toBeVisible({ timeout: 15_000 });
    await expect(sheet).toContainText(/Our Value/i);
    annotate(testInfo, "global-search", `"/" shortcut found "${fragment}" on production and opened its popup`);
  });
});
