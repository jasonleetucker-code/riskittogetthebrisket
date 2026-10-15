/**
 * /trade — Import trade from screenshot (C3-IMPORT-IMAGE), end to end in the
 * browser.
 *
 * Both endpoints are answered by page.route, so the spec never depends on the
 * OCR engine being installed: GET /api/trade/import-screenshot/status and
 * POST /api/trade/import-screenshot.  What it pins is the browser half:
 *
 *   Import trade -> From screenshot -> a real PNG goes through the browser
 *   downscale (createImageBitmap + canvas) -> ONE image per POST -> the
 *   returned board names join onto board rows -> the user fixes an ambiguous
 *   item, swaps sides -> Replace / Add lands in sides A and B.
 *
 * The screenshot supplies identities and sides only; every value on the
 * page still comes from the board.  Player names are DERIVED from the served
 * contract, never hardcoded.  Runs on every project (desktop and phone; the
 * phone gets the Drawer variant of the same dialog).
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  pageUrl,
  awaitStreamSettled,
  contractFixture,
} = require("../helpers/journey");

test.use({ serviceWorkers: "block" });

// A real 8x8 PNG (decodable by createImageBitmap), built in memory so no
// binary fixture needs committing.
const PNG_8x8 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAD0lEQVR4nGP4jwMwDC0JALoev0Ewkwr8AAAAAElFTkSuQmCC",
  "base64",
);

const STATUS_OK = {
  available: true,
  enabled: true,
  reason: null,
  engine: "tesseract",
  version: "5.3.0",
};

async function openTrade(page) {
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(
    page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ }),
  ).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading player pool..."),
    null,
    {
      timeout: 90_000,
    },
  );
}

/** Four distinct offensive player names the board prices. */
function pickPlayers(contract) {
  const rows = Array.isArray(contract?.playersArray)
    ? contract.playersArray
    : [];
  const seen = new Set();
  const out = [];
  for (const r of rows) {
    const name = r?.displayName;
    const pos = String(r?.position || "").toUpperCase();
    if (!name || seen.has(name) || !["QB", "RB", "WR", "TE"].includes(pos))
      continue;
    if (!(Number(r?.rankDerivedValue) > 0)) continue;
    seen.add(name);
    out.push({ name, position: pos });
    if (out.length === 4) break;
  }
  return out;
}

const ITEM = {
  kind: "player",
  status: "resolved",
  sleeperId: null,
  candidates: [],
  suggestions: [],
  hints: { position: null, team: null },
  reason: null,
  conf: 0.9,
};

function extraction({ sideA, sideB, warnings = [] }) {
  return {
    ok: true,
    imageIndex: 0,
    engine: { name: "tesseract", version: "5.3.0" },
    layout: { kind: "two_column", confidence: 0.9 },
    sides: [
      { label: "Team One", labelSource: "anchor", items: sideA },
      { label: "", labelSource: "position", items: sideB },
    ],
    unassigned: [],
    ignored: [{ raw: "Accept trade", reason: "ui_text" }],
    warnings,
  };
}

async function mockEndpoints(page, { status = STATUS_OK, body }) {
  const posts = [];
  await page.route("**/api/trade/import-screenshot/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(status),
    }),
  );
  await page.route("**/api/trade/import-screenshot", (route) => {
    const req = route.request();
    if (req.method() !== "POST") return route.fallback();
    posts.push(req.postDataJSON());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  return posts;
}

async function openScreenshotDialog(page) {
  await page
    .getByRole("button", { name: /^Import trade$/ })
    .first()
    .click();
  await page.getByRole("button", { name: /^From screenshot$/ }).click();
  const dialog = page.getByRole("dialog", {
    name: "Import trade from screenshot",
  });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function uploadScreenshot(dialog) {
  await dialog.getByTestId("ds-dropzone-input").setInputFiles({
    name: "trade.png",
    mimeType: "image/png",
    buffer: PNG_8x8,
  });
  await expect(dialog.getByRole("region", { name: "Side A" })).toBeVisible({
    timeout: 30_000,
  });
}

function resultNamed(page, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page
    .locator(".trade-side-search-results .trade-side-search-result")
    .filter({
      has: page.locator(".trade-side-search-result-name", {
        hasText: new RegExp(`^${escaped}$`),
      }),
    })
    .first();
}

async function addToSideA(page, name) {
  const input = page.getByLabel("Search to add a player to Side A");
  await input.click();
  await input.fill(name);
  await expect(resultNamed(page, name)).toBeVisible({ timeout: 15_000 });
  await resultNamed(page, name).click();
  await expect(
    page.getByRole("button", { name: `Add another ${name} to Side A` }),
  ).toBeVisible();
}

test("reviews a screenshot, fixes an ambiguous item, swaps, and replaces the trade", async ({
  authedPage: page,
}) => {
  const { contract } = await contractFixture(page, { view: "array" });
  const players = pickPlayers(contract);
  expect(players, "contract must price four offensive players").toHaveLength(4);
  const [existing, a1, a2, b1] = players;

  const posts = await mockEndpoints(page, {
    body: extraction({
      sideA: [
        { ...ITEM, raw: a1.name, boardName: a1.name, lineIndex: 0 },
        {
          ...ITEM,
          raw: "ambiguous name",
          boardName: null,
          status: "needs_confirmation",
          lineIndex: 1,
          candidates: [
            {
              sleeperId: null,
              boardName: a2.name,
              position: a2.position,
              team: null,
            },
            {
              sleeperId: null,
              boardName: b1.name,
              position: b1.position,
              team: null,
            },
          ],
        },
      ],
      sideB: [{ ...ITEM, raw: b1.name, boardName: b1.name, lineIndex: 0 }],
      warnings: ["pick_owner_not_established"],
    }),
  });

  await openTrade(page);
  await addToSideA(page, existing.name);

  const dialog = await openScreenshotDialog(page);
  await uploadScreenshot(dialog);

  // One image, one request, sent as a data URL from the browser downscale.
  expect(posts).toHaveLength(1);
  expect(posts[0].index).toBe(0);
  expect(String(posts[0].image)).toMatch(/^data:image\/(png|jpeg);base64,/);

  await expect(dialog.getByText("Ignored text (1)")).toBeVisible();
  await expect(dialog.getByText(/pick owners aren't shown/i)).toBeVisible();

  // The ambiguous item blocks the import until the user chooses.
  const replace = dialog.getByRole("button", { name: "Replace current trade" });
  await expect(replace).toBeDisabled();
  await dialog
    .getByLabel("Choose the asset for “ambiguous name”")
    .selectOption("0");
  await expect(replace).toBeEnabled();

  // Neutral sides: the screenshot's left is not assumed to be the user's.
  await dialog.getByRole("button", { name: "Swap sides" }).click();
  await replace.click();

  await expect(dialog).toBeHidden();
  await expect(
    page.getByText("Imported 3 assets from screenshot"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Add another ${b1.name} to Side A` }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Add another ${a1.name} to Side B` }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Add another ${a2.name} to Side B` }),
  ).toBeVisible();
  // Replaced, not appended.
  await expect(
    page.getByRole("button", {
      name: `Add another ${existing.name} to Side A`,
    }),
  ).toHaveCount(0);
});

test("adds a screenshot's assets to an existing trade", async ({
  authedPage: page,
}) => {
  const { contract } = await contractFixture(page, { view: "array" });
  const [existing, a1, b1] = pickPlayers(contract);

  await mockEndpoints(page, {
    body: extraction({
      sideA: [{ ...ITEM, raw: a1.name, boardName: a1.name, lineIndex: 0 }],
      sideB: [{ ...ITEM, raw: b1.name, boardName: b1.name, lineIndex: 0 }],
    }),
  });

  await openTrade(page);
  await addToSideA(page, existing.name);
  const dialog = await openScreenshotDialog(page);
  await uploadScreenshot(dialog);
  await dialog.getByRole("button", { name: "Add to current trade" }).click();

  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("button", {
      name: `Add another ${existing.name} to Side A`,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Add another ${a1.name} to Side A` }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Add another ${b1.name} to Side B` }),
  ).toBeVisible();
});

test("explains when the server cannot read screenshots and Cancel changes nothing", async ({
  authedPage: page,
}) => {
  await mockEndpoints(page, {
    status: {
      available: false,
      enabled: true,
      reason: "tesseract_not_installed",
      engine: "tesseract",
      version: null,
    },
    body: {},
  });
  await openTrade(page);
  const dialog = await openScreenshotDialog(page);
  await expect(
    dialog.getByText("Screenshot reading isn't set up yet"),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Choose screenshots" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(/Imported .* from screenshot/)).toHaveCount(0);
});

test("hides From screenshot when the feature is disabled", async ({
  authedPage: page,
}) => {
  await mockEndpoints(page, {
    status: {
      available: false,
      enabled: false,
      reason: "disabled",
      engine: "tesseract",
      version: null,
    },
    body: {},
  });
  await openTrade(page);
  await page
    .getByRole("button", { name: /^Import trade$/ })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: /^From KeepTradeCut URL$/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^From screenshot$/ }),
  ).toHaveCount(0);
});
