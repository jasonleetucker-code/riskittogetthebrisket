/**
 * /trade — multi-team Trade War Room (owner directive 2026-10-20 §7; spec
 * docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §3.2).
 *
 * A real 3-team own-league structure is built through the page's own
 * controls on the seeded board: Add Team, per-side search, the per-asset
 * destination menus, and the side cards' "League team" binding (inferred by
 * id from the rosters).  Then Analyze.
 *
 *   1. route-mocked — `POST /api/trade/analyze-multi` answers the flag probe
 *      as ON and the analysis from `frontend/__tests__/fixtures/trade-multi/
 *      three-team-team-context.json` (REAL engine output, Lane A), so the
 *      per-team layout, perspective switch, 390 px overflow and axe are
 *      deterministic.  The request body must be exactly that fixture's
 *      ledger, or the mock refuses it.
 *   2. flag OFF (mocked 503) — today's behaviour: the static 3+-team panel,
 *      no team binding, no Analyze.
 *   3. live stack — no mock.  Adapts to the running server's flag instead of
 *      skipping: flag ON must produce a real per-team analysis; flag OFF must
 *      produce the static panel.  The local verification boots the backend
 *      with RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS=1.
 *
 * Screenshots go to E2E_SCREENSHOT_DIR when set (local evidence), else to the
 * test's output folder.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;
const { closeTradeSheet, openTradeSearch } = require("../helpers/trade-builder");

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const FIXTURE = JSON.parse(
  fs.readFileSync(
    path.resolve(
      __dirname,
      "../../../frontend/__tests__/fixtures/trade-multi/three-team-team-context.json",
    ),
    "utf-8",
  ),
);
const ENDPOINT = "/api/trade/analyze-multi";

test.use({ serviceWorkers: "block" });

function shotPath(testInfo, name) {
  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (dir) {
    fs.mkdirSync(dir, { recursive: true });
    return path.join(dir, `${testInfo.project.name}-${name}.png`);
  }
  return testInfo.outputPath(`${name}.png`);
}

async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, "the page must not scroll sideways").toBeLessThanOrEqual(
    sizes.viewport + 1,
  );
}

// The fixture's structure, in builder terms: who sends what, to which side.
// Side A = roster 1, B = roster 2, C = roster 4 (ascending rosterId).
function plan() {
  const sideOf = new Map(FIXTURE.teams.map((t, i) => [t.rosterId, i]));
  return FIXTURE.teams.map((t, i) => ({
    label: "ABC"[i],
    team: t.team.name,
    rosterId: t.rosterId,
    gives: t.gives.map((g) => ({
      kind: g.kind,
      label: g.label,
      assetId: g.assetId,
      to: sideOf.get(g.toRosterId),
    })),
  }));
}

async function addAsset(page, sideLabel, asset) {
  const input = await openTradeSearch(page, sideLabel);
  let result;
  if (asset.kind === "pick") {
    // An owned pick is searched by its tier label and picked by its canonical
    // league pick id from the side team's own picks (labels can repeat).
    await input.fill(asset.label.replace(/\s*\(.*\)$/, ""));
    result = page.locator(`.trade-side-search-result[data-asset-id="${asset.assetId}"]`).first();
  } else {
    await input.fill(asset.label);
    const escaped = asset.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    result = page
      .locator(".trade-side-search-result")
      .filter({ has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${escaped}$`) }) })
      .first();
  }
  await expect(result, `search result for ${asset.label}`).toBeVisible({ timeout: 15_000 });
  // The line's on-screen label (an owned pick shows its own label).
  asset.uiLabel = (await result.locator(".trade-side-search-result-name").innerText()).trim();
  await result.click();
  await closeTradeSheet(page);
}

async function buildThreeTeamTrade(page) {
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
  await page.getByRole("button", { name: "Add Team" }).click();
  await expect(page.locator("#trade-side-C")).toBeVisible();
  const sides = plan();
  // Players first, so each side's team is proven by id before its own picks
  // are searched (an owned pick is offered from the bound team's inventory).
  for (const side of sides) {
    for (const g of side.gives.filter((x) => x.kind === "player")) await addAsset(page, side.label, g);
  }
  return sides;
}

async function routeAndPick(page, sides) {
  for (const side of sides) {
    for (const g of side.gives.filter((x) => x.kind === "pick")) await addAsset(page, side.label, g);
  }
  for (const side of sides) {
    for (const g of side.gives) {
      const select = page.getByRole("combobox", { name: `Send ${g.uiLabel || g.label} to which side` });
      await select.selectOption(String(g.to));
    }
  }
}

test("multi-team War Room: 3-team trade, every team's own result, perspective switch, no sideways scroll, axe clean", async ({
  authedPage: page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const analyses = [];
  await page.route(
    (url) => url.pathname === ENDPOINT,
    async (route) => {
      const body = route.request().postDataJSON() || {};
      if (!Array.isArray(body.teams)) {
        // The page's flag probe: the route answers ON with a 400 for {}.
        return route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ error: "invalid_request", message: "The request body is malformed.", field: "teams" }),
        });
      }
      analyses.push(body);
      const same =
        JSON.stringify(body.teams) === JSON.stringify(FIXTURE.teams.map((t) => t.rosterId)) &&
        JSON.stringify((body.assets || []).map((a) => [a.id, a.from, a.to])) ===
          JSON.stringify(FIXTURE.ledger.legs.map((l) => [l.id, l.from, l.to]));
      return route.fulfill({
        status: same ? 200 : 400,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify(
          same
            ? { ...FIXTURE, leagueKey: body.leagueKey || FIXTURE.leagueKey }
            : { error: "invalid_trade", message: "The mock expected the fixture's ledger." },
        ),
      });
    },
  );

  const sides = await buildThreeTeamTrade(page);
  // Each side is bound to its league team by roster id, inferred from holdings.
  for (const [i, side] of sides.entries()) {
    await expect(page.locator(`#trade-side-team-${i}`)).toHaveValue(String(side.rosterId));
  }
  await routeAndPick(page, sides);
  // Destination menus name the bound team, not just the side letter.
  await expect(
    page.getByRole("combobox", { name: `Send ${sides[0].gives[0].uiLabel} to which side` }).locator("option:checked"),
  ).toHaveText(`Side B · ${sides[1].team}`);
  // The browser's 3-team reading is labelled preliminary.
  await expect(page.getByTestId("trade-meter-preliminary")).toBeVisible();

  const room = page.locator('[data-war-room^="multi-"]');
  await room.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("multi-team-not-ready")).toHaveCount(0);
  const shotBuilder = shotPath(testInfo, "multi-team-builder");
  await page.locator("#trade-side-A").screenshot({ path: shotBuilder });
  await page.getByTestId("multi-team-analyze").click();
  await expect(page.getByTestId("multi-team-summary")).toBeVisible({ timeout: 30_000 });
  expect(analyses).toHaveLength(1);
  expect(analyses[0].useTeamContext).toBe(true);

  for (const t of FIXTURE.teams) {
    const row = page.getByTestId("multi-team-summary").locator(`[data-summary-team="${t.rosterId}"]`);
    await expect(row).toContainText(t.team.name);
    await expect(row).toContainText(t.categoryText);
  }
  // Decision and market fairness are two separately labelled answers (C4).
  const first = FIXTURE.teams[0];
  await expect(page.getByTestId("multi-team-decision")).toHaveText(first.analysis.decision.headlineText);
  await expect(room.locator('[data-answer="decision"] dt')).toHaveText("Decision");
  await expect(room.locator('[data-answer="fairness"] dt')).toHaveText("Market fairness");
  // The meter and tray now carry the final per-team words.
  await expect(page.getByTestId("trade-meter-final").first()).toBeVisible();

  await noPageOverflow(page);
  const axe = await new AxeBuilder({ page }).withTags(TAGS).include('[aria-labelledby="war-room-title"]').analyze();
  await testInfo.attach("multi-team-war-room-axe", {
    body: JSON.stringify(axe.violations, null, 2),
    contentType: "application/json",
  });
  expect(axe.violations).toEqual([]);
  const shot1 = shotPath(testInfo, "multi-team-result");
  await room.screenshot({ path: shot1 });
  await testInfo.attach("multi-team-result", { path: shot1, contentType: "image/png" });

  // Perspective switch: another team's own answer, no new request.
  const second = FIXTURE.teams[1];
  await room.getByRole("tab", { name: second.team.name }).click();
  await expect(page.getByTestId("multi-team-decision")).toHaveText(second.analysis.decision.headlineText);
  for (const g of second.gives) {
    const dest = FIXTURE.teams.find((t) => t.rosterId === g.toRosterId).team.name;
    await expect(page.getByTestId("multi-team-gives").locator(`[data-asset-id="${g.assetId}"]`)).toContainText(
      `→ ${dest}`,
    );
  }
  expect(analyses).toHaveLength(1);
  await noPageOverflow(page);
  const shot2 = shotPath(testInfo, "multi-team-perspective");
  await room.screenshot({ path: shot2 });
  await testInfo.attach("multi-team-perspective", { path: shot2, contentType: "image/png" });

  // Edit → the old answer disappears at once and the trade re-asks by itself
  // (the mock refuses the changed ledger, which the War Room says plainly).
  await page.getByRole("combobox", { name: `Send ${sides[1].gives[0].uiLabel} to which side` }).selectOption("2");
  await expect(page.getByTestId("multi-team-summary")).toHaveCount(0);
  await expect(page.getByTestId("multi-team-error")).toBeVisible({ timeout: 15_000 });
  expect(analyses.length).toBeGreaterThanOrEqual(2);

  // New trade: empty sides, no bindings, no result.
  await page.getByTestId("multi-team-reset").click();
  await expect(page.locator("#trade-side-A")).toContainText("No assets yet.");
  expect(errors).toEqual([]);
});

test("multi-team War Room: flag OFF keeps today's static 3+-team panel", async ({ authedPage: page }) => {
  let probed = 0;
  await page.route(
    (url) => url.pathname === ENDPOINT,
    async (route) => {
      probed += 1;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "multi_team_analysis_disabled", message: "Multi-team trade analysis is not enabled." }),
      });
    },
  );
  await buildThreeTeamTrade(page);
  await expect(page.getByTestId("war-room-multi-team-limit")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#trade-side-team-0")).toHaveCount(0);
  await expect(page.getByTestId("multi-team-analyze")).toHaveCount(0);
  expect(probed).toBe(1);
});

test("multi-team War Room: live stack answers per its own flag", async ({ authedPage: page }, testInfo) => {
  const sides = await buildThreeTeamTrade(page);
  const binding = page.locator("#trade-side-team-0");
  const limit = page.getByTestId("war-room-multi-team-limit");
  await expect(binding.or(limit).first()).toBeVisible({ timeout: 30_000 });
  if (await limit.isVisible().catch(() => false)) {
    // Flag OFF on this server: today's behaviour, nothing to analyze.
    await expect(binding).toHaveCount(0);
    return;
  }
  await routeAndPick(page, sides);
  const room = page.locator('[data-war-room^="multi-"]');
  await page.getByTestId("multi-team-analyze").click();
  await expect(page.getByTestId("multi-team-summary").or(page.getByTestId("multi-team-error")).first()).toBeVisible({
    timeout: 120_000,
  });
  await expect(page.getByTestId("multi-team-error")).toHaveCount(0);
  await expect(room.getByRole("tab")).toHaveCount(3);
  for (const side of sides) {
    await expect(page.getByTestId("multi-team-summary")).toContainText(side.team);
  }
  // One decision per team, from the server; never blank.
  await expect(page.getByTestId("multi-team-decision")).not.toBeEmpty();
  await noPageOverflow(page);
  const shot = shotPath(testInfo, "multi-team-live");
  await room.screenshot({ path: shot });
  await testInfo.attach("multi-team-live", { path: shot, contentType: "image/png" });
});
