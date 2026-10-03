/**
 * /trade on a phone — repeatable assets and Early/Mid/Late market picks
 * (owner decision 2026-10-03).
 *
 *   1. Searching a future year shows that year's Early / Mid / Late 1st
 *      market references in the first (market) group, ahead of any owned
 *      picks, inside a bounded scrollable dropdown — the defect was owned
 *      picks crowding them out on an iPhone with the keyboard up.  Add
 *      Mid, increment to 5 with "+", and the side's raw total is exactly
 *      5x one copy.
 *   2. Search a player, add, increment to 5, same exact-multiple check.
 *
 * Years and players are DERIVED from the seeded contract, never hardcoded:
 * the year is the earliest one whose three tier rows are priced and
 * unsuppressed.  Runs on the phone projects (mobile-chromium 390x844, and
 * the webkit iPhone projects when they are explicitly run); skipped on
 * desktop.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");

test.use({ serviceWorkers: "block" });

const TIERS = ["Early", "Mid", "Late"];
const PICK_TOKEN = /\d{4}/;

function rowOf(contract, name) {
  const dict = contract?.players || {};
  if (dict[name]) return dict[name];
  return (contract?.playersArray || []).find((p) => p?.displayName === name) || null;
}

function priced(contract, name) {
  const row = rowOf(contract, name);
  if (!row || row.pickGenericSuppressed) return false;
  return Number(row.rankDerivedValue) > 0;
}

/** Earliest year whose Early/Mid/Late 1st rows are all priced and unsuppressed. */
function tierYear(contract, names) {
  const years = new Set();
  for (const n of names) {
    const m = /^(\d{4}) (?:Early|Mid|Late) 1st$/.exec(n);
    if (m) years.add(Number(m[1]));
  }
  for (const y of [...years].sort()) {
    if (TIERS.every((t) => priced(contract, `${y} ${t} 1st`))) return y;
  }
  return null;
}

async function openTrade(page) {
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
}

function resultNamed(page, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page
    .locator(".trade-side-search-results .trade-side-search-result")
    .filter({ has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${escaped}$`) }) })
    .first();
}

/** Raw total of Side A, read from the exact-number data attribute. */
async function sideARaw(page) {
  const v = await page.locator("[data-side-raw]").first().getAttribute("data-side-raw");
  return Number(v);
}

async function incrementTo(page, name, n) {
  const plus = page.getByRole("button", { name: `Add another ${name} to Side A` });
  for (let i = 1; i < n; i += 1) await plus.click();
  const line = page.getByRole("group", { name: `${name} quantity` });
  await expect(line.getByTestId("trade-asset-quantity")).toHaveText(String(n));
}

test.describe("mobile /trade: repeatable assets and market picks", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("mobile"), "phone viewport flow");
  });

  test("search a future year → Early/Mid/Late visible → add Mid → x5 → total updates", async ({
    authedPage: page,
  }) => {
    const { contract, playerNames } = await contractFixture(page);
    const year = tierYear(contract, playerNames);
    test.skip(year == null, "seeded contract carries no priced future tier rows");

    await openTrade(page);
    const input = page.getByLabel("Search to add a player to Side A");
    await input.click();
    await input.fill(String(year));

    const box = page.locator(".trade-side-search-results");
    await expect(box).toBeVisible({ timeout: 15_000 });
    // The dropdown is bounded and scrolls, so it cannot run off under the keyboard.
    const overflowY = await box.evaluate((el) => getComputedStyle(el).overflowY);
    expect(overflowY).toBe("auto");
    const boxHeight = await box.evaluate((el) => el.getBoundingClientRect().height);
    expect(boxHeight).toBeLessThanOrEqual(322);

    // Early / Mid / Late 1st are in the FIRST group and visible without scrolling.
    const firstGroup = box.getByRole("group").first();
    for (const tier of TIERS) {
      const name = `${year} ${tier} 1st`;
      await expect(firstGroup.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${name}$`) })).toBeVisible();
      const r = await resultNamed(page, name).boundingBox();
      const b = await box.boundingBox();
      expect(r.y + r.height, `${name} visible inside the dropdown`).toBeLessThanOrEqual(b.y + b.height + 1);
    }

    const mid = `${year} Mid 1st`;
    await resultNamed(page, mid).click();
    await expect(page.getByRole("button", { name: `Remove ${mid} from Side A` })).toBeVisible();
    const one = await sideARaw(page);
    expect(one).toBeGreaterThan(0);

    await incrementTo(page, mid, 5);
    await expect.poll(() => sideARaw(page)).toBe(5 * one);

    // "−" removes exactly one copy.
    await page.getByRole("button", { name: `Remove one ${mid} from Side A` }).click();
    await expect.poll(() => sideARaw(page)).toBe(4 * one);
  });

  test("search a player → add → x5 → total updates", async ({ authedPage: page }) => {
    const { contract, playerNames } = await contractFixture(page);
    const player = playerNames.find((n) => !PICK_TOKEN.test(n) && priced(contract, n));
    test.skip(!player, "seeded contract carries no priced player");

    await openTrade(page);
    const input = page.getByLabel("Search to add a player to Side A");
    await input.click();
    await input.fill(player);
    await expect(resultNamed(page, player)).toBeVisible({ timeout: 15_000 });
    await resultNamed(page, player).click();
    await expect(page.getByRole("button", { name: `Remove ${player} from Side A` })).toBeVisible();
    const one = await sideARaw(page);
    expect(one).toBeGreaterThan(0);

    // The same player stays searchable after the first add.
    await input.fill(player);
    await expect(resultNamed(page, player)).toBeVisible({ timeout: 15_000 });
    await input.fill("");

    await incrementTo(page, player, 5);
    await expect.poll(() => sideARaw(page)).toBe(5 * one);

    // The − / + controls are finger-sized on a phone.
    const plusBox = await page.getByRole("button", { name: `Add another ${player} to Side A` }).boundingBox();
    expect(plusBox.height).toBeGreaterThanOrEqual(44);
    expect(plusBox.width).toBeGreaterThanOrEqual(44);
  });
});
