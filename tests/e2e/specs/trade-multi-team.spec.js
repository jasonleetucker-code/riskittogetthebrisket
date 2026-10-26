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
 * Board drift (#1918).  The seeded board is the committed exports/latest
 * snapshot, refreshed from the REAL league every few hours.  The fixture is
 * a recorded trade on the 2026-10-20 rosters; on 2026-10-21 its pick ("2027
 * Mid 1st (from Kich)") was traded away on Sleeper, so the route-mocked
 * tests could no longer find it in its sender's inventory.  The route-mocked
 * tests therefore PIN the served board to the fixture's own state for the
 * six traded assets (`pinFixtureBoard`): each one sits on the roster the
 * fixture's ledger says sends it, priced and not withheld, as the engine saw
 * it.  Every other row, team and pick is the live seeded board.  The live
 * test cannot be pinned (a flag-ON server verifies ownership against its own
 * rosters), so it builds its trade from the served board instead
 * (`livePlan`).
 *
 * Screenshots go to E2E_SCREENSHOT_DIR when set (local evidence), else to the
 * test's output folder.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;
const { closeTradeSheet, openTradeSearch } = require("../helpers/trade-builder");
const { TRADE_DATA_VIEW, boardRow, isTradeableRow } = require("../helpers/trade-board");

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

// ── The board the route-mocked tests run on ─────────────────────────────
//
// The board responses the page reads, rewritten by `mutate` in place.  One
// route for every rewrite a test needs (a second `page.route` on the same
// URL would shadow the first rather than compose with it).
async function routeBoard(page, mutate) {
  await page.route(
    (url) => url.pathname.startsWith("/api/dynasty-data") || url.pathname === "/api/data",
    async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      mutate(body);
      await route.fulfill({ response: res, json: body });
    },
  );
}

const PLAYER_ID = /^p:(.+)$/;

/**
 * Pin the served board to the fixture's own state for the fixture's traded
 * assets, and only those: each player and the owned pick moves to the roster
 * the fixture's ledger sends it from (removed from whoever holds it today),
 * and each player row carries the fixture engine's own evidence — priced
 * (`valueState: "priced"`), so not quarantined, not stale, and its leg value
 * where the live row has none.  What the board cannot supply at all (a row
 * that left the board, a pick no team holds) is reported in
 * `state.problems`, never invented.
 */
function pinFixtureBoard(body, state) {
  const teams = body?.sleeper?.teams;
  const legs = FIXTURE.teams.flatMap((t) => t.gives.map((g) => ({ ...g, fromRosterId: t.rosterId })));
  if (Array.isArray(teams) && teams.length) {
    const byRoster = new Map(teams.map((t) => [Number(t.roster_id ?? t.rosterId), t]));
    for (const leg of legs) {
      const owner = byRoster.get(leg.fromRosterId);
      if (!owner) {
        state.problems.add(`roster ${leg.fromRosterId} is not on the served board`);
        continue;
      }
      if (leg.kind === "player") {
        const id = PLAYER_ID.exec(leg.assetId)?.[1];
        for (const t of teams) {
          t.players = (t.players || []).filter((n) => n !== leg.label);
          t.playerIds = (t.playerIds || []).filter((x) => String(x) !== id);
        }
        owner.players = [...(owner.players || []), leg.label];
        if (id) owner.playerIds = [...(owner.playerIds || []), id];
      } else {
        let detail = null;
        for (const t of teams) {
          const held = (t.pickDetails || []).find((d) => d?.assetId === leg.assetId);
          if (!held) continue;
          detail = held;
          t.pickDetails = t.pickDetails.filter((d) => d !== held);
          const i = (t.picks || []).indexOf(held.label);
          if (i >= 0) t.picks = t.picks.filter((_, k) => k !== i);
        }
        if (!detail) {
          state.problems.add(`no team holds ${leg.assetId} on the served board`);
          continue;
        }
        owner.pickDetails = [...(owner.pickDetails || []), { ...detail, ownerRosterId: leg.fromRosterId }];
        owner.picks = [...(owner.picks || []), detail.label];
        if (owner.pickOwnershipState !== "observed") {
          state.problems.add(`roster ${leg.fromRosterId}'s pick ownership is ${owner.pickOwnershipState}`);
        }
      }
    }
    state.rosters += 1;
  }
  const rows = [
    ...(Array.isArray(body?.playersArray) ? body.playersArray : []),
    ...Object.values(body?.players || {}),
  ];
  if (rows.length) {
    for (const leg of legs.filter((g) => g.kind === "player")) {
      const matches = rows.filter((r) => r?.displayName === leg.label || r?.canonicalName === leg.label);
      if (body?.players?.[leg.label] && !matches.includes(body.players[leg.label])) {
        matches.push(body.players[leg.label]); // the legacy dict is keyed by name
      }
      if (!matches.length) state.problems.add(`${leg.label} is not on the served board`);
      for (const r of matches) {
        r.quarantined = false;
        if (r.confidenceAxes?.freshness === "low") r.confidenceAxes = { ...r.confidenceAxes, freshness: "high" };
        if (!(Number(r.rankDerivedValue) > 0)) r.rankDerivedValue = leg.value;
      }
    }
    state.boards += 1;
  }
}

// Route-mocked tests: pin the board (plus any `extra` rewrite on top), and
// assert — once the page has read the board — that the pin found everything.
async function pinBoard(page, extra = null) {
  const state = { problems: new Set(), rosters: 0, boards: 0 };
  await routeBoard(page, (body) => {
    pinFixtureBoard(body, state);
    if (extra) extra(body);
  });
  return state;
}

// WAITS for the page to have read a pinned board, then asserts.  The
// "Loading player pool..." wait in `buildThreeTeamTrade` can pass before the
// page has even rendered that text (CI mobile, 2026-10-25: 694 ms, the board
// request still inside `routeBoard`), so reading the counters synchronously
// races the board fetch.  Same assertions, polled on the page's own budget.
async function expectPinned(state) {
  await expect
    .poll(() => state.rosters, { message: "the page read a board carrying the league's rosters", timeout: 90_000 })
    .toBeGreaterThan(0);
  await expect
    .poll(() => state.boards, { message: "the page read a board carrying player rows", timeout: 90_000 })
    .toBeGreaterThan(0);
  expect([...state.problems], "the fixture's assets exist on the served board").toEqual([]);
}

// ── The live test's trade, from the served board ────────────────────────
//
// Three teams by roster id, each sending one player only it holds — a row
// the page prices (valued, not withheld) under a name that is unique on the
// board, so search and team inference are unambiguous — around a cycle
// (A → B → C → A), plus one owned pick of the first team whose board row is
// priced, sent to C.  `null` when the board cannot form one.
function livePlan(contract) {
  const teams = [...(contract?.sleeper?.teams || [])].sort(
    (a, b) => Number(a.roster_id ?? a.rosterId) - Number(b.roster_id ?? b.rosterId),
  );
  const holders = new Map();
  for (const t of teams) for (const n of t.players || []) holders.set(n, (holders.get(n) || 0) + 1);
  const names = new Map();
  for (const r of contract?.playersArray || []) {
    if (r?.displayName) names.set(r.displayName, (names.get(r.displayName) || 0) + 1);
  }
  const playerOf = (team) =>
    (team.players || [])
      .filter((n) => !/\d{4}/.test(n) && holders.get(n) === 1 && names.get(n) === 1)
      .map((n) => ({ n, row: boardRow(contract, n) }))
      .filter(({ row }) => isTradeableRow(row))
      .sort((x, y) => Number(y.row.rankDerivedValue) - Number(x.row.rankDerivedValue))[0] || null;
  const pickOf = (team) =>
    team.pickOwnershipState === "observed"
      ? (team.pickDetails || []).find((d) => d?.assetId && isTradeableRow(boardRow(contract, d.boardRowName))) ||
        null
      : null;
  const chosen = [];
  for (const t of teams) {
    const player = playerOf(t);
    if (!player) continue;
    if (!chosen.length && !pickOf(t)) continue;
    chosen.push({ t, player });
    if (chosen.length === 3) break;
  }
  if (chosen.length < 3) return null;
  return chosen.map(({ t, player }, i) => {
    const gives = [{ kind: "player", label: player.n, assetId: null, to: (i + 1) % 3 }];
    if (i === 0) {
      const pick = pickOf(t);
      gives.push({ kind: "pick", label: pick.label, assetId: pick.assetId, to: 2 });
    }
    return { label: "ABC"[i], team: t.name, rosterId: Number(t.roster_id ?? t.rosterId), gives };
  });
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

async function buildThreeTeamTrade(page, { pin = null, sides = plan() } = {}) {
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
  if (pin) await expectPinned(pin);
  await page.getByRole("button", { name: "Add Team" }).click();
  await expect(page.locator("#trade-side-C")).toBeVisible();
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

  const pin = await pinBoard(page);
  const sides = await buildThreeTeamTrade(page, { pin });
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
  const pin = await pinBoard(page);
  await buildThreeTeamTrade(page, { pin });
  await expect(page.getByTestId("war-room-multi-team-limit")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#trade-side-team-0")).toHaveCount(0);
  await expect(page.getByTestId("multi-team-analyze")).toHaveCount(0);
  expect(probed).toBe(1);
});

test("multi-team War Room: live stack answers per its own flag", async ({ authedPage: page }, testInfo) => {
  // No pin: a flag-ON server verifies ownership against its own rosters, so
  // the trade is built from what the served board says each team holds.
  const { contract } = await contractFixture(page, { view: TRADE_DATA_VIEW });
  const live = livePlan(contract);
  expect(live, "the served board holds three teams with a priced player each and a priced owned pick").not.toBeNull();
  const sides = await buildThreeTeamTrade(page, { sides: live });
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

// F2: a traded asset the evidence gates withhold (quarantined / stale) is
// WITHHELD — never priced, never 0 — on the browser's preliminary meter (from
// the board row's own `quarantined` stamp) and in the War Room (from the
// engine's per-leg `valueState`).  The board row is marked quarantined by
// rewriting the page's own board response.  The analysis answer is the real
// fixture with that one leg's engine fields set the way Lane A's engine sets
// them: valueState "quarantined", value null, and each team it touches
// carrying the engine's own withheld answer (decision, category, UNABLE
// fairness) taken from the engine-generated quarantined fixture
// (tests/trade/multi_team_withheld_payloads.py), with its asset name swapped.
const ENGINE_WITHHELD = JSON.parse(
  fs.readFileSync(
    path.resolve(
      __dirname,
      "../../../frontend/__tests__/fixtures/trade-multi-withheld/three-team-quarantined-asset.json",
    ),
    "utf-8",
  ),
);
test("multi-team War Room: a quarantined asset is withheld on the preliminary meter and in the War Room (F2)", async ({
  authedPage: page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const sender = FIXTURE.teams[1];
  const leg = sender.gives.find((g) => g.kind === "player" && g.toRosterId !== FIXTURE.teams[0].rosterId);
  expect(leg, "the fixture routes a player between the second and third team").toBeTruthy();
  const receiver = FIXTURE.teams.find((t) => t.rosterId === leg.toRosterId);
  const untouched = FIXTURE.teams.find((t) => t.rosterId !== sender.rosterId && t.rosterId !== receiver.rosterId);

  // The board: the seeded contract pinned to the fixture (see the header),
  // with that one row quarantined on top of the pin.
  let boardRewrites = 0;
  const pin = await pinBoard(page, (body) => {
    for (const r of body.playersArray || []) {
      if (r?.displayName === leg.label || r?.canonicalName === leg.label) {
        r.quarantined = true;
        boardRewrites += 1;
      }
    }
    if (body.players && body.players[leg.label]) body.players[leg.label].quarantined = true;
  });

  const withheldFixture = structuredClone(FIXTURE);
  const unable = (f) => ({
    ...f,
    state: "UNABLE",
    level: null,
    reasonCode: "evaluation_unavailable",
    gap: null,
    largerAdjustedSide: null,
    largerPackageUtility: null,
    relativePct: null,
  });
  // The engine's own answer for a team whose part of the trade carries a
  // quarantined asset (its sender, roster 2, in the engine fixture).
  const engineTeam = ENGINE_WITHHELD.teams.find((t) =>
    t.gives.some((g) => g.valueState === "quarantined"),
  );
  const engineAsset = engineTeam.gives.find((g) => g.valueState === "quarantined").label;
  const engineDecision = () =>
    JSON.parse(JSON.stringify(engineTeam.analysis.decision).split(engineAsset).join(leg.label));
  const touchedIds = new Set([sender.rosterId, receiver.rosterId]);
  for (const t of withheldFixture.teams) {
    for (const row of [...t.gives, ...t.receives]) {
      if (row.assetId === leg.assetId) {
        row.valueState = "quarantined";
        row.value = null;
      }
    }
    if (!touchedIds.has(t.rosterId)) continue;
    t.fairness = unable(t.fairness);
    t.analysis.decision = engineDecision();
    t.category = engineTeam.category;
    t.categoryText = engineTeam.categoryText;
    t.categoryReason = engineTeam.categoryReason;
  }
  withheldFixture.summary.perTeam = withheldFixture.summary.perTeam.map((p) =>
    touchedIds.has(p.rosterId)
      ? { ...p, fairness: "UNABLE", category: engineTeam.category, headline: engineTeam.analysis.decision.headline }
      : p,
  );
  withheldFixture.summary.lines = withheldFixture.teams.map((t) => `${t.team.name}: ${t.categoryText}.`);
  // The engine's raw conservation sums only legs priced in BOTH views
  // (team_verdicts.conservation), so the withheld leg leaves both totals —
  // as in the engine's own quarantined fixture.  Keeping the original total
  // would be a response no real engine can produce.
  expect(typeof leg.value).toBe("number");
  const cons = withheldFixture.summary.conservation;
  cons.pricedRawSent -= leg.value;
  cons.pricedRawReceived -= leg.value;
  expect(ENGINE_WITHHELD.summary.conservation.pricedRawSent).toBe(
    ENGINE_WITHHELD.teams
      .flatMap((t) => t.gives)
      .filter((g) => g.valueState === "priced")
      .reduce((acc, g) => acc + g.value, 0),
  );

  await page.route(
    (url) => url.pathname === ENDPOINT,
    async (route) => {
      const body = route.request().postDataJSON() || {};
      if (!Array.isArray(body.teams)) {
        return route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ error: "invalid_request", message: "The request body is malformed.", field: "teams" }),
        });
      }
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
            ? { ...withheldFixture, leagueKey: body.leagueKey || withheldFixture.leagueKey }
            : { error: "invalid_trade", message: "The mock expected the fixture's ledger." },
        ),
      });
    },
  );

  const sides = await buildThreeTeamTrade(page, { pin });
  expect(boardRewrites, `the board carries ${leg.label}`).toBeGreaterThan(0);
  for (const [i, side] of sides.entries()) {
    await expect(page.locator(`#trade-side-team-${i}`)).toHaveValue(String(side.rosterId));
  }
  await routeAndPick(page, sides);

  // Preliminary meter: the two teams the asset touches are WITHHELD with the
  // reason; the untouched team keeps its gap; no band for the trade.
  const sideIdx = (rid) => FIXTURE.teams.findIndex((t) => t.rosterId === rid);
  const cells = page.locator(".trade-meter-multi-val");
  await expect(cells).toHaveCount(3);
  await expect(cells.nth(sideIdx(sender.rosterId))).toHaveAttribute("data-team-state", "withheld");
  await expect(cells.nth(sideIdx(receiver.rosterId))).toHaveAttribute("data-team-state", "withheld");
  await expect(cells.nth(sideIdx(untouched.rosterId))).toHaveAttribute("data-team-state", "priced");
  await expect(cells.nth(sideIdx(sender.rosterId))).toContainText(`${leg.label} (sent, quarantined)`);
  await expect(cells.nth(sideIdx(receiver.rosterId))).toContainText(`${leg.label} (received, quarantined)`);
  await expect(page.locator(".trade-meter-verdict").first()).toHaveText("Withheld");
  await expect(page.getByTestId("trade-multi-summary")).toContainText("Preliminary — not determinable");

  // The War Room: the server's own answer, with the withheld leg named.
  const room = page.locator('[data-war-room^="multi-"]');
  await room.scrollIntoViewIfNeeded();
  await page.getByTestId("multi-team-analyze").click();
  await expect(page.getByTestId("multi-team-summary")).toBeVisible({ timeout: 30_000 });
  const summary = page.getByTestId("multi-team-summary");
  for (const t of [sender, receiver]) {
    await expect(
      summary.locator(`[data-summary-team="${t.rosterId}"] [data-testid="multi-team-summary-withheld"]`),
    ).toContainText(`withheld, not determinable: ${leg.label} quarantined`);
  }
  await expect(
    summary.locator(`[data-summary-team="${untouched.rosterId}"] [data-testid="multi-team-summary-withheld"]`),
  ).toHaveCount(0);
  // The whole-trade raw total excludes the withheld leg and says so — it is
  // never presented as the value of every asset moved.
  const consLine = page.getByTestId("multi-team-conservation");
  const pricedCount = cons.assetsSent - 1;
  await expect(consLine).toContainText(
    `The ${pricedCount} priced assets are worth ${cons.pricedRawSent.toLocaleString("en-US")} in raw board value on both sides`,
  );
  await expect(page.getByTestId("multi-team-conservation-excluded")).toContainText(
    `${leg.label} (Value withheld: quarantined (not trusted))`,
  );
  await expect(consLine).not.toContainText(
    `${FIXTURE.summary.conservation.pricedRawSent.toLocaleString("en-US")} in raw board value`,
  );
  await room.getByRole("tab", { name: sender.team.name }).click();
  const panel = room.locator(`[data-team-result="${sender.rosterId}"]`);
  await expect(panel.getByTestId("multi-team-decision")).toHaveText(engineTeam.analysis.decision.headlineText);
  await expect(panel.getByTestId("multi-team-fairness")).toHaveText("Unable to determine");
  await expect(panel.getByTestId("multi-team-value-withheld")).toContainText(
    `${leg.label} (Value withheld: quarantined (not trusted))`,
  );
  await expect(panel.locator(`[data-asset-id="${leg.assetId}"]`)).toContainText("Value withheld: quarantined");
  await expect(panel.locator('tr[data-package="send"]')).toHaveAttribute("data-package-state", "unknown");
  await noPageOverflow(page);
  const shot = shotPath(testInfo, "multi-team-withheld");
  await room.screenshot({ path: shot });
  await testInfo.attach("multi-team-withheld", { path: shot, contentType: "image/png" });
  expect(errors).toEqual([]);
});
