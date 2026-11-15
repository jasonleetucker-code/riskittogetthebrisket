/**
 * /trade — Import from KeepTradeCut, end to end in the browser.
 *
 * Regression for 2026-10-13: every import failed with "Failed to fetch KTC
 * player map." after KTC moved its player map into a JSON <script> element.
 * The backend half (URL parse, both KTC embed forms, the saved-copy ladder,
 * error classes) is pinned without network in
 * tests/trade/test_ktc_import_player_map.py.  This spec pins the browser half:
 * paste a URL -> POST /api/trade/import-ktc -> the returned names join onto
 * board rows -> sides A and B are REPLACED, a third side is left alone, and a
 * failure shows the backend's own reason.
 *
 * The import endpoint is answered by page.route so the spec never depends on
 * keeptradecut.com.  Player names are DERIVED from the served contract, never
 * hardcoded.  Runs on every project (desktop and phone).
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");

test.use({ serviceWorkers: "block" });

const KTC_URL =
  "https://keeptradecut.com/trade-calculator?var=5&pickVal=0&teamOne=1|2&teamTwo=3&format=2&isStartup=0&tep=1";

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

/** Three distinct offensive player names the board prices, plus their positions. */
function pickPlayers(contract) {
  const rows = Array.isArray(contract?.playersArray) ? contract.playersArray : [];
  const seen = new Set();
  const out = [];
  for (const r of rows) {
    const name = r?.displayName;
    const pos = String(r?.position || "").toUpperCase();
    if (!name || seen.has(name) || !["QB", "RB", "WR", "TE"].includes(pos)) continue;
    if (!(Number(r?.rankDerivedValue) > 0)) continue;
    seen.add(name);
    out.push({ name, position: pos });
    if (out.length === 3) break;
  }
  return out;
}

async function submitImport(page) {
  // The KTC row sits behind the "Import trade" control (C3-IMPORT-IMAGE).
  await page.getByRole("button", { name: /^Import trade$/ }).click();
  await page.getByRole("button", { name: /^From KeepTradeCut URL$/ }).click();
  await page.getByLabel("KeepTradeCut trade-calculator URL").fill(KTC_URL);
  await page.getByRole("button", { name: /^Load trade$/ }).click();
}

test("imports a KTC URL into sides A and B and leaves a third side alone", async ({
  authedPage: page,
}) => {
  const { contract } = await contractFixture(page, { view: "array" });
  const players = pickPlayers(contract);
  expect(players, "contract must price three offensive players").toHaveLength(3);
  const [a1, a2, b1] = players;

  await page.route("**/api/trade/import-ktc", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        sourceUrl: KTC_URL,
        sideOne: [
          { ktcId: 1, name: a1.name, position: a1.position, team: "", slug: "", isPick: false },
          { ktcId: 2, name: a2.name, position: a2.position, team: "", slug: "", isPick: false },
        ],
        sideTwo: [{ ktcId: 3, name: b1.name, position: b1.position, team: "", slug: "", isPick: false }],
        unresolved: { sideOne: [], sideTwo: [] },
        playerMap: { source: "live", index: "trade_database_search_index", ageHours: 0, entries: 2011 },
      }),
    }),
  );

  await openTrade(page);
  await page.getByRole("button", { name: /^Add Team$/ }).click();
  await expect(page.getByRole("heading", { name: "Side C" })).toBeVisible();

  await submitImport(page);

  await expect(page.getByText(/KTC import: Loaded 3\/3 players/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: `Add another ${a1.name} to Side A` })).toBeVisible();
  await expect(page.getByRole("button", { name: `Add another ${a2.name} to Side A` })).toBeVisible();
  await expect(page.getByRole("button", { name: `Add another ${b1.name} to Side B` })).toBeVisible();
  // The third side survived the import.
  await expect(page.getByRole("heading", { name: "Side C" })).toBeVisible();
});

test("shows the backend's own reason when KTC cannot be read", async ({ authedPage: page }) => {
  const reason =
    "KeepTradeCut changed its page layout, so its player list could not be read. The importer needs an update.";
  await page.route("**/api/trade/import-ktc", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ ok: false, error: reason, reason: "KtcLayoutChanged" }),
    }),
  );

  await openTrade(page);
  await submitImport(page);

  const banner = page.getByText("Import failed").locator("..");
  await expect(page.getByText("Import failed")).toBeVisible({ timeout: 15_000 });
  await expect(banner).toContainText("changed its page layout");
  await expect(page.getByText("Failed to fetch KTC player map.")).toHaveCount(0);
});
