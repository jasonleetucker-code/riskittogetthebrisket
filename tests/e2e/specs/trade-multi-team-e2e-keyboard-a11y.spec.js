/**
 * /trade — complete private 2-, 3- and 4-team flows, keyboard only, with
 * axe, focus management, hydration readiness and error recovery (owner
 * directive 2026-10-20 §7, §12; spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md
 * §3.2, §5.1).
 *
 * Complements trade-multi-team.spec.js (pointer flows on Lane A's fixtures).
 * Every step here is driven from the KEYBOARD: Tab to reach a control, the
 * widget's own keys to operate it (native <select> arrows, the side search
 * combobox's ArrowDown / Enter, SegmentedControl and Tabs arrows, Enter on
 * buttons, Escape to close the phone sheet).  Typing a player's name into
 * the search box is keyboard input too.  No `.click()`, `.fill()` or
 * `.selectOption()` on /trade.
 *
 * The trades are REAL: teams, players and owned picks are read from the
 * live contract this stack serves (`/api/data?view=app`), several assets per
 * team, players and a pick, cycle + fan-out routing.  Nothing is mocked
 * except where a test injects a fault on purpose.
 *
 *   - 2 teams: the existing War Room on /api/trade/analyze — build, the
 *     decision, perspective switch (the other team as "my team"), edit,
 *     Clear Trade.
 *   - 3 and 4 teams: the multi-team War Room on /api/trade/analyze-multi —
 *     bindings inferred by id, routing, Analyze, every team's own result,
 *     perspective tabs (no new request), edit a destination (old answer
 *     hidden at once, re-asks by itself), remove an asset, Asset-only mode,
 *     New trade.
 *   - Error recovery (3 teams): a 500 and a network failure each show the
 *     War Room's error with Retry; Retry — by keyboard — reaches the real
 *     answer.
 *   - axe (WCAG 2.0/2.1 A + AA) at every step on the War Room and the open
 *     phone sheet; no sideways scroll; no hydration / page error; focus never
 *     stranded on <body> after an action (soft: reported, flow continues).
 *     Two pre-existing /trade defects are strict only under
 *     E2E_A11Y_STRICT=1 (see KNOWN_AXE_STEPS below).
 *
 * FLAG-ADAPTIVE, never skipped: when the server answers the multi-team
 * route's probe as OFF (`trade_multi_team_analysis`, default OFF — e.g. CI),
 * the 3/4-team tests assert today's static 3+-team panel and stop there; the
 * 2-team test needs no flag.  Screenshots of every step go to
 * E3_SCREENSHOT_DIR when set, else to the test's output folder.
 */
const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const ENDPOINT = "/api/trade/analyze-multi";
const DECISIONS =
  /YES — MAKE THE TRADE|NO — DO NOT MAKE THE TRADE|NOT ENOUGH EVIDENCE|TOO CLOSE|LEAN/;
const PICK_TOKEN = /\d{4}/;
const PICK_2TEAM = process.env.E3_PICK_LABEL || "2027 Pick 1.06";

test.use({ serviceWorkers: "block" });

// ── evidence ─────────────────────────────────────────────────────────────
function shotPath(testInfo, name) {
  const dir = process.env.E3_SCREENSHOT_DIR;
  if (dir) {
    fs.mkdirSync(dir, { recursive: true });
    return path.join(dir, `${testInfo.project.name}-private-${name}.png`);
  }
  return testInfo.outputPath(`${name}.png`);
}

async function shot(target, testInfo, name, { full = false } = {}) {
  await target.screenshot({ path: shotPath(testInfo, name), ...(full ? { fullPage: true } : {}) });
}

// Two defects this spec found that PREDATE the multi-team work and live in
// the shared /trade builder (reported to the owning lane, not fixed here):
//   - removing an asset unmounts its row and drops focus to <body>;
//   - the "Owned pick" accent badge on a highlighted search row measures
//     4.48:1 (#a3341c on #e2ceb9), under WCAG 1.4.3's 4.5:1 (since #1441).
// They are asserted when E2E_A11Y_STRICT=1 (the E-3 evidence runs) and
// otherwise recorded as `a11y-known-defect` annotations, so CI does not go
// red on main's existing behaviour while the defect stays visible in the
// report.  Every other axe step and focus check is always strict.
const STRICT = process.env.E2E_A11Y_STRICT === "1";
const KNOWN_AXE_STEPS = new Set(["owned-pick-search"]);

function knownDefect(testInfo, description) {
  testInfo.annotations.push({ type: "a11y-known-defect", description });
}

async function axe(page, testInfo, step, include) {
  const res = await new AxeBuilder({ page }).include(include).withTags(TAGS).analyze();
  const ids = res.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  await testInfo.attach(`axe-${step}`, {
    body: JSON.stringify(res.violations, null, 2),
    contentType: "application/json",
  });
  if (ids.length && process.env.E3_SCREENSHOT_DIR) {
    fs.writeFileSync(
      shotPath(testInfo, `axe-${step}`).replace(/\.png$/, ".json"),
      JSON.stringify(res.violations, null, 2),
    );
  }
  if (ids.length && !STRICT && KNOWN_AXE_STEPS.has(step)) {
    knownDefect(testInfo, `axe at "${step}": ${ids.join("; ")}`);
    return;
  }
  // Soft: every step's scan is reported, and the flow keeps going.
  expect.soft(ids, `axe violations at step "${step}"`).toEqual([]);
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

function guard(page) {
  const problems = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/hydrat|did not match|Minified React error #4(18|19|21|22|23|25)/i.test(t))
      problems.push(`hydration: ${t}`);
  });
  return problems;
}

// ── keyboard primitives ──────────────────────────────────────────────────
async function focused(page) {
  return page.evaluate(() => {
    const a = document.activeElement;
    if (!a || a === document.body) return "body";
    return `${a.tagName.toLowerCase()}${a.id ? `#${a.id}` : ""}[${a.getAttribute("aria-label") || (a.textContent || "").trim().slice(0, 40)}]`;
  });
}

async function tabTo(page, locator, { max = 400, back = false } = {}) {
  const target = locator.first();
  await expect(target).toBeAttached();
  for (let i = 0; i <= max; i += 1) {
    if (
      await target
        .evaluate((el) => el === document.activeElement || el.contains(document.activeElement))
        .catch(() => false)
    ) {
      return i;
    }
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
  }
  throw new Error(
    `not reachable by ${back ? "Shift+Tab" : "Tab"} within ${max} presses; focus is on ${await focused(page)}`,
  );
}

async function press(page, locator) {
  await tabTo(page, locator);
  await page.keyboard.press("Enter");
}

// `known` = the pre-existing Remove defect described above.
async function expectFocusNotLost(page, what, { known = false } = {}) {
  const where = await focused(page);
  if (where === "body" && known && !STRICT) {
    knownDefect(test.info(), `${what}: focus fell to <body>`);
    return;
  }
  expect.soft(where, `${what}: focus fell to <body>`).not.toBe("body");
}

// Native <select>: arrows from the current option to `value`.
async function selectByKeyboard(page, select, value) {
  await tabTo(page, select);
  const values = await select.locator("option").evaluateAll((os) => os.map((o) => o.value));
  const want = values.indexOf(String(value));
  expect(want, `option ${value} exists`).toBeGreaterThanOrEqual(0);
  for (let guardN = 0; guardN < values.length + 2; guardN += 1) {
    const cur = values.indexOf(await select.inputValue());
    if (cur === want) return;
    await page.keyboard.press(cur < want ? "ArrowDown" : "ArrowUp");
  }
  await expect(select).toHaveValue(String(value));
}

async function segmentTo(page, groupName, label) {
  const group = page.getByRole("radiogroup", { name: groupName }).first();
  await tabTo(page, group.locator('[role="radio"][tabindex="0"]'));
  for (let k = 0; k < 4; k += 1) {
    if ((await group.getByRole("radio", { name: label }).getAttribute("aria-checked")) === "true")
      return;
    await page.keyboard.press("ArrowRight");
  }
  throw new Error(`${groupName}: ${label} not reachable by arrows`);
}

// Add one asset to a side by keyboard.  Inline layout: the side search is a
// combobox (ArrowDown to the option, Enter).  Phone layout: "Add to Side X"
// opens a sheet whose results are buttons reached with Tab.  `match` is
// {name} (exact label) or {assetId}.
async function addByKeyboard(page, testInfo, sideLabel, query, match, { shotName, axeStep } = {}) {
  const inline = page.locator(`input[aria-label="Search to add a player to Side ${sideLabel}"]`);
  const sheetBtn = page.getByRole("button", { name: `Add to Side ${sideLabel}`, exact: true });
  await expect(inline.or(sheetBtn).first()).toBeVisible({ timeout: 60_000 });
  const phone = await sheetBtn.isVisible().catch(() => false);
  const rowFor = (scope) => {
    const rows = scope.locator(".trade-side-search-result");
    if (match.assetId) return rows.and(page.locator(`[data-asset-id="${match.assetId}"]`)).first();
    const escaped = match.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return rows
      .filter({
        has: page.locator(".trade-side-search-result-name", {
          hasText: new RegExp(`^${escaped}$`),
        }),
      })
      .first();
  };
  let uiLabel;
  if (!phone) {
    await tabTo(page, inline);
    await page.keyboard.type(query);
    const list = page.locator(`#trade-search-${sideLabel}-listbox`);
    const row = rowFor(list);
    await expect(row, `search result for ${match.name || match.assetId}`).toBeVisible({
      timeout: 15_000,
    });
    uiLabel = (await row.locator(".trade-side-search-result-name").innerText()).trim();
    const id = await row.getAttribute("id");
    const k = Number(String(id).split("-").pop());
    for (let i = 0; i <= k; i += 1) await page.keyboard.press("ArrowDown");
    await expect(inline).toHaveAttribute("aria-activedescendant", id);
    if (shotName) await shot(page, testInfo, shotName);
    if (axeStep) await axe(page, testInfo, axeStep, `#trade-search-${sideLabel}-listbox`);
    await page.keyboard.press("Enter");
    await page.keyboard.press("Escape"); // clears the query
  } else {
    await press(page, sheetBtn);
    const dialog = page.getByRole("dialog", { name: `Add to Side ${sideLabel}` });
    await expect(dialog).toBeVisible({ timeout: 30_000 });
    const input = dialog.getByLabel(`Search to add a player to Side ${sideLabel}`);
    await expect(input, "the sheet focuses its search").toBeFocused();
    await page.keyboard.type(query);
    const row = rowFor(dialog);
    await expect(row, `search result for ${match.name || match.assetId}`).toBeVisible({
      timeout: 15_000,
    });
    uiLabel = (await row.locator(".trade-side-search-result-name").innerText()).trim();
    await tabTo(page, row);
    if (shotName) await shot(page, testInfo, shotName);
    if (axeStep) await axe(page, testInfo, axeStep, '[role="dialog"]');
    await page.keyboard.press("Enter");
    await expect(input, "focus returns to the search after an add").toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(sheetBtn, "focus returns to the button that opened the sheet").toBeFocused();
  }
  await expect(
    page.getByRole("button", { name: `Remove ${uiLabel} from Side ${sideLabel}` }),
  ).toBeAttached();
  return uiLabel;
}

// ── the live league ─────────────────────────────────────────────────────
// n real teams, each with board-priced, uniquely named players; team 1 also
// an early-round owned pick with a canonical id.
async function realTrade(page, n) {
  const { teams, playerNames, contract } = await contractFixture(page);
  const board = contract?.players || {};
  // A name must be unique on the board AND across every roster in the league:
  // two rostered players sharing a display name would make the page's
  // name-based roster evidence (and the test's own expectations) ambiguous.
  const count = new Map();
  for (const p of playerNames) count.set(p, (count.get(p) || 0) + 1);
  const rostered = new Map();
  for (const t of teams)
    for (const p of t.players || []) rostered.set(p, (rostered.get(p) || 0) + 1);
  const usable = (t) =>
    (t.optimalLineup?.bench || t.players || []).filter(
      (p) =>
        p &&
        !PICK_TOKEN.test(p) &&
        count.get(p) === 1 &&
        rostered.get(p) === 1 &&
        // priced and not quarantined on the board: the trade should be
        // judgeable, so a missing value is not what the flow measures
        Number(board[p]?.rankDerivedValue) > 0 &&
        board[p]?.quarantined !== true,
    );
  const chosen = [];
  for (const [idx, t] of teams.entries()) {
    const players = usable(t);
    // An early-round pick in the nearest classes (far-future late rounds are
    // derived / can be quarantined; a judgeable trade is the point here).
    const pick = (t.pickDetails || [])
      .filter((d) => d && d.assetId && d.label && Number(d.round) <= 3)
      .sort((x, y) => Number(x.season) - Number(y.season) || Number(x.round) - Number(y.round))[0];
    if (players.length < 3) continue;
    if (chosen.length === 1 && !pick) continue;
    chosen.push({
      idx,
      rosterId: Number(t.roster_id),
      name: t.name,
      players: players.slice(0, 3),
      pick,
    });
    if (chosen.length === n) break;
  }
  expect(chosen, `${n} usable teams on the live contract`).toHaveLength(n);
  return chosen;
}

async function openTrade(page) {
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading player pool..."),
    null,
    { timeout: 90_000 },
  );
  // Hydration readiness: ds controls drop aria-busy once handlers attach.
  await expect(
    page.locator(
      'main [role="radiogroup"][aria-busy="true"], main [role="tablist"][aria-busy="true"]',
    ),
  ).toHaveCount(0, { timeout: 30_000 });
  await page.locator("body").focus();
}

function watchMulti(page) {
  const seen = { trades: [], probes: 0, responses: [] };
  page.on("request", (req) => {
    if (new URL(req.url()).pathname !== ENDPOINT || req.method() !== "POST") return;
    const body = req.postDataJSON() || {};
    if (Array.isArray(body.teams)) seen.trades.push(body);
    else seen.probes += 1;
  });
  page.on("response", async (res) => {
    if (new URL(res.url()).pathname !== ENDPOINT) return;
    try {
      const body = await res.json();
      if (Array.isArray(body?.teams))
        seen.responses.push({
          status: res.status(),
          body,
          cache: res.headers()["cache-control"] || "",
        });
    } catch {
      /* aborted */
    }
  });
  return seen;
}

// Build an n-team (n >= 3) trade by keyboard.  Returns per-side plans with
// the on-screen labels.  `false` when the server's flag is OFF (the static
// panel is asserted instead).
async function buildMulti(page, testInfo, n, teams, stepName) {
  await selectByKeyboard(page, page.locator("#suggest-team"), String(teams[0].idx));
  for (let k = 2; k < n; k += 1) await press(page, page.getByRole("button", { name: "Add Team" }));
  await expect(page.locator(`#trade-side-${"ABCD"[n - 1]}`)).toBeVisible();
  const sides = teams.map((t, i) => ({ ...t, label: "ABCD"[i], gives: [] }));
  // Players first: each side's team is proven by id before its own pick is
  // searched (owned picks come from the bound team's inventory).
  for (const [i, side] of sides.entries()) {
    const k = i === 0 ? 3 : 2;
    for (const name of side.players.slice(0, k)) {
      const uiLabel = await addByKeyboard(
        page,
        testInfo,
        side.label,
        name,
        { name },
        i === 0 && side.gives.length === 0 ? { shotName: stepName("02-search") } : {},
      );
      side.gives.push({ kind: "player", uiLabel });
    }
  }
  const binding = page.locator("#trade-side-team-0");
  const limit = page.getByTestId("war-room-multi-team-limit");
  await expect(binding.or(limit).first()).toBeVisible({ timeout: 30_000 });
  if (await limit.isVisible().catch(() => false)) {
    await expect(binding).toHaveCount(0);
    await expect(page.getByTestId("multi-team-analyze")).toHaveCount(0);
    await shot(page, testInfo, stepName("flag-off-static-panel"), { full: true });
    return false;
  }
  for (const [i, side] of sides.entries()) {
    await expect(
      page.locator(`#trade-side-team-${i}`),
      `Side ${side.label} bound by roster`,
    ).toHaveValue(String(side.rosterId));
  }
  const b = sides[1];
  const pickQuery = b.pick.label.replace(/\s*\(.*\)$/, "");
  const pickLabel = await addByKeyboard(
    page,
    testInfo,
    b.label,
    pickQuery,
    { assetId: b.pick.assetId },
    { axeStep: "owned-pick-search" },
  );
  b.gives.push({ kind: "pick", uiLabel: pickLabel });
  return sides;
}

// Cycle + fan-out: side i's first asset → side i+1, the rest → side i+2.
async function routeByKeyboard(page, sides) {
  const n = sides.length;
  for (const [i, side] of sides.entries()) {
    for (const [j, g] of side.gives.entries()) {
      g.to = j === 0 ? (i + 1) % n : (i + 2) % n;
      await selectByKeyboard(
        page,
        page.getByRole("combobox", { name: `Send ${g.uiLabel} to which side` }),
        String(g.to),
      );
    }
  }
}

async function analyzeMulti(page, seen, expected) {
  await press(page, page.getByTestId("multi-team-analyze"));
  await expect(
    page.getByTestId("multi-team-summary").or(page.getByTestId("multi-team-error")).first(),
  ).toBeVisible({ timeout: 120_000 });
  await expect.poll(() => seen.responses.length).toBe(expected);
}

// ── tests ────────────────────────────────────────────────────────────────
test("private 2-team trade by keyboard: build, decision, other team's perspective, edit, Clear Trade", async ({
  authedPage: page,
}, testInfo) => {
  test.setTimeout(300_000);
  const problems = guard(page);
  const analyses = [];
  page.on("request", (req) => {
    if (new URL(req.url()).pathname === "/api/trade/analyze" && req.method() === "POST")
      analyses.push(req.postDataJSON() || {});
  });
  const multi = watchMulti(page);
  page.on("response", async (res) => {
    if (process.env.E3_DEBUG && new URL(res.url()).pathname === "/api/trade/analyze") {
      console.log(
        "ANALYZE",
        res.status(),
        res.request().postData(),
        (await res.text().catch(() => "")).slice(0, 400),
      );
    }
  });
  const [ta, tb] = await realTrade(page, 2);
  await openTrade(page);
  await selectByKeyboard(page, page.locator("#suggest-team"), String(ta.idx));
  const a = [];
  const b = [];
  for (const name of ta.players.slice(0, 2))
    a.push(await addByKeyboard(page, testInfo, "A", name, { name }));
  for (const name of tb.players.slice(0, 2))
    b.push(await addByKeyboard(page, testInfo, "B", name, { name }));
  // A market pick on Side B (the 2-team path prices board rows).
  b.push(await addByKeyboard(page, testInfo, "B", PICK_2TEAM, { name: PICK_2TEAM }));

  const room = page.locator('[aria-labelledby="war-room-title"]').first();
  await expect(page.locator('[data-war-room="ok"]')).toBeVisible({ timeout: 120_000 });
  await expect(room.getByTestId("decision-headline")).toHaveText(DECISIONS);
  expect(analyses.at(-1).teamName).toBe(ta.name);
  for (const x of a) expect(analyses.at(-1).playersOut).toContain(x);
  expect(multi.trades, "2 teams never use the multi-team route").toHaveLength(0);
  await noPageOverflow(page);
  await shot(page, testInfo, "2team-01-built", { full: true });
  await shot(room, testInfo, "2team-02-decision");
  await axe(page, testInfo, "2team-decision", '[aria-labelledby="war-room-title"]');

  // Perspective: the other team as "my team" — a new question for that team.
  const before = analyses.length;
  await selectByKeyboard(page, page.locator("#suggest-team"), String(tb.idx));
  await expect.poll(() => analyses.length, { timeout: 60_000 }).toBeGreaterThan(before);
  await expect(page.locator('[data-war-room="ok"]')).toBeVisible({ timeout: 120_000 });
  expect(analyses.at(-1).teamName).toBe(tb.name);
  for (const x of b.filter((y) => !PICK_TOKEN.test(y)))
    expect(analyses.at(-1).playersOut).toContain(x);
  await expect(room.getByTestId("decision-headline")).toHaveText(DECISIONS);
  await shot(room, testInfo, "2team-03-perspective-other-team");
  await axe(page, testInfo, "2team-perspective", '[aria-labelledby="war-room-title"]');

  // Edit: remove one of Side A's players → re-asks.
  const n0 = analyses.length;
  await press(page, page.getByRole("button", { name: `Remove ${a[1]} from Side A` }));
  await expectFocusNotLost(page, "2-team after Remove", { known: true });
  await expect.poll(() => analyses.length, { timeout: 60_000 }).toBeGreaterThan(n0);
  await expect(page.locator('[data-war-room="ok"]')).toBeVisible({ timeout: 120_000 });
  expect(analyses.at(-1).playersIn).not.toContain(a[1]);
  await shot(room, testInfo, "2team-04-edited");

  // Clear Trade.
  await press(page, page.getByRole("button", { name: "Clear Trade" }));
  await expect(page.locator("#trade-side-A")).toContainText("No assets yet.");
  await expect(page.locator("#trade-side-B")).toContainText("No assets yet.");
  await expectFocusNotLost(page, "2-team after Clear Trade");
  await shot(page, testInfo, "2team-05-cleared");
  expect(problems).toEqual([]);
});

for (const n of [3, 4]) {
  test(`private ${n}-team trade by keyboard: bind, route, analyze, every team's result, perspective, edit, remove, asset-only, new trade`, async ({
    authedPage: page,
  }, testInfo) => {
    test.setTimeout(420_000);
    const problems = guard(page);
    const seen = watchMulti(page);
    const step = (name) => `${n}team-${name}`;
    const teams = await realTrade(page, n);
    await openTrade(page);
    await shot(page, testInfo, step("01-open"));
    const sides = await buildMulti(page, testInfo, n, teams, step);
    if (sides === false) return; // flag OFF on this server: static panel asserted

    const room = page.locator('[data-war-room^="multi-"]');
    // Every asset starts with a default destination (the next side), so the
    // trade is already analyzable; nothing is sent until Analyze.
    await expect(page.getByTestId("multi-team-analyze")).toBeEnabled();
    await routeByKeyboard(page, sides);
    await expect(page.getByTestId("multi-team-not-ready")).toHaveCount(0);
    await expect(
      page
        .getByRole("combobox", { name: `Send ${sides[0].gives[0].uiLabel} to which side` })
        .locator("option:checked"),
    ).toHaveText(`Side B · ${sides[1].name}`);
    await expect(page.getByTestId("trade-meter-preliminary").first()).toBeVisible();
    await noPageOverflow(page);
    await shot(page, testInfo, step("03-routed-review"), { full: true });
    await axe(page, testInfo, "routed-review", '[aria-labelledby="war-room-title"]');
    expect(seen.trades, "nothing is analyzed before Analyze").toHaveLength(0);

    // Analyze.
    await analyzeMulti(page, seen, 1);
    await expect(page.getByTestId("multi-team-error")).toHaveCount(0);
    const res = seen.responses[0];
    expect(res.status).toBe(200);
    expect(res.cache).toMatch(/no-store/);
    expect(res.body.teams).toHaveLength(n);
    const body = seen.trades[0];
    expect(body.teams.slice().sort((x, y) => x - y)).toEqual(
      sides.map((s) => s.rosterId).sort((x, y) => x - y),
    );
    expect(body.assets).toHaveLength(sides.reduce((k, s) => k + s.gives.length, 0));
    expect(body.useTeamContext).toBe(true);
    for (const t of res.body.teams) {
      const row = page
        .getByTestId("multi-team-summary")
        .locator(`[data-summary-team="${t.rosterId}"]`);
      await expect(row).toContainText(t.categoryText);
    }
    await expect(page.getByTestId("multi-team-decision")).toHaveText(DECISIONS);
    await expect(room.locator('[data-answer="decision"] dt')).toHaveText("Decision");
    await expect(room.locator('[data-answer="fairness"] dt')).toHaveText("Market fairness");
    await expect(page.getByTestId("trade-meter-final").first()).toBeVisible();
    await noPageOverflow(page);
    await shot(room, testInfo, step("04-result"));
    await axe(page, testInfo, "result", '[aria-labelledby="war-room-title"]');
    fs.writeFileSync(
      shotPath(testInfo, step("04-result")).replace(/\.png$/, ".json"),
      JSON.stringify({
        rosters: res.body.rosters,
        teams: res.body.teams.map((t) => [
          t.rosterId,
          t.analysis?.decision?.headline,
          t.categoryText,
          t.marketFairness?.state || t.fairness?.state || null,
        ]),
      }),
    );

    // Perspective: Tabs arrows through every team; one response serves all.
    const tabs = room.getByRole("tab");
    await expect(tabs).toHaveCount(n);
    await tabTo(page, room.locator('[role="tab"][aria-selected="true"]'));
    for (let i = 0; i < n; i += 1) {
      const sel = room.locator('[role="tab"][aria-selected="true"]');
      await expect(sel).toBeFocused();
      const name = (await sel.innerText()).trim();
      const team = res.body.teams.find((t) => (t.team?.name || "") === name);
      expect(team, `tab ${name} is a team in the response`).toBeTruthy();
      await expect(page.getByTestId("multi-team-decision")).toHaveText(
        team.analysis.decision.headlineText,
      );
      for (const g of team.gives)
        await expect(
          page.getByTestId("multi-team-gives").locator(`[data-asset-id="${g.assetId}"]`),
        ).toBeVisible();
      await shot(room, testInfo, step(`05-perspective-${i + 1}`));
      if (i === n - 1)
        await axe(page, testInfo, `perspective-${i + 1}`, '[aria-labelledby="war-room-title"]');
      await page.keyboard.press("ArrowRight");
    }
    expect(seen.trades, "perspective switch sends nothing").toHaveLength(1);

    // Edit a destination: the old answer disappears at once, then re-asks.
    const g = sides[0].gives[1];
    g.to = 1;
    await selectByKeyboard(
      page,
      page.getByRole("combobox", { name: `Send ${g.uiLabel} to which side` }),
      "1",
    );
    await expect(page.getByTestId("multi-team-summary")).toHaveCount(0);
    await expect(page.getByTestId("multi-team-summary")).toBeVisible({ timeout: 120_000 });
    await expect.poll(() => seen.responses.length).toBe(2);
    expect(seen.trades[1].assets.filter((l) => l.to === sides[1].rosterId).length).toBeGreaterThan(
      seen.trades[0].assets.filter((l) => l.to === sides[1].rosterId).length,
    );
    await shot(room, testInfo, step("06-edited-destination"));

    // Remove side A's last asset (every team still sends and receives).
    const last = sides[0].gives[sides[0].gives.length - 1];
    await press(page, page.getByRole("button", { name: `Remove ${last.uiLabel} from Side A` }));
    await expectFocusNotLost(page, `${n}-team after Remove`, { known: true });
    await expect(page.getByTestId("multi-team-summary")).toBeVisible({ timeout: 120_000 });
    await expect.poll(() => seen.responses.length).toBe(3);
    expect(seen.trades[2].assets).toHaveLength(seen.trades[1].assets.length - 1);
    await shot(room, testInfo, step("07-removed"));

    // Asset-only mode, by keyboard: a new question with Team Context off.
    await segmentTo(page, "Analysis mode", "Asset only");
    await expect.poll(() => seen.trades.length, { timeout: 60_000 }).toBe(4);
    expect(seen.trades[3].useTeamContext).toBe(false);
    await expect(page.getByTestId("multi-team-summary")).toBeVisible({ timeout: 120_000 });
    await expect(room.getByText(/Asset only: roster fit/)).toBeVisible();
    await shot(room, testInfo, step("08-asset-only"));
    await axe(page, testInfo, "asset-only", '[aria-labelledby="war-room-title"]');
    await segmentTo(page, "Analysis mode", "Team context");

    // New trade: empty sides, no bindings, no result.
    await press(page, page.getByTestId("multi-team-reset"));
    await expect(page.locator("#trade-side-A")).toContainText("No assets yet.");
    await expect(page.getByTestId("multi-team-summary")).toHaveCount(0);
    await expectFocusNotLost(page, `${n}-team after New trade`);
    await shot(page, testInfo, step("09-new-trade"), { full: true });
    await noPageOverflow(page);
    expect(problems).toEqual([]);
  });
}

test("private 3-team error recovery by keyboard: 500 and network failure show Retry; Retry reaches the real answer", async ({
  authedPage: page,
}, testInfo) => {
  test.setTimeout(300_000);
  const problems = guard(page);
  let calls = 0;
  await page.route(
    (url) => url.pathname === ENDPOINT,
    async (route) => {
      const body = route.request().postDataJSON() || {};
      if (!Array.isArray(body.teams)) return route.continue(); // the real flag probe
      calls += 1;
      if (calls === 1) {
        return route.fulfill({
          status: 500,
          contentType: "text/html",
          body: "<html>Internal Server Error</html>",
        });
      }
      if (calls === 2) return route.abort("failed");
      return route.continue();
    },
  );
  const seen = watchMulti(page);
  const teams = await realTrade(page, 3);
  await openTrade(page);
  const sides = await buildMulti(page, testInfo, 3, teams, (s) => `errors-${s}`);
  if (sides === false) return;
  await routeByKeyboard(page, sides);
  await press(page, page.getByTestId("multi-team-analyze"));
  for (const fault of ["500", "network"]) {
    const err = page.getByTestId("multi-team-error");
    await expect(err, `War Room error after ${fault}`).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("multi-team-summary")).toHaveCount(0);
    await expect(page.locator('[aria-labelledby="war-room-title"]')).not.toContainText(
      /Internal Server Error|Traceback/,
    );
    await shot(page.locator('[aria-labelledby="war-room-title"]'), testInfo, `errors-${fault}`);
    await axe(page, testInfo, `error-${fault}`, '[aria-labelledby="war-room-title"]');
    await press(
      page,
      page.locator('[aria-labelledby="war-room-title"]').getByRole("button", { name: "Retry" }),
    );
  }
  await expect(page.getByTestId("multi-team-summary")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("multi-team-error")).toHaveCount(0);
  expect(calls).toBe(3);
  expect(seen.responses.at(-1).status).toBe(200);
  await shot(page.locator('[aria-labelledby="war-room-title"]'), testInfo, "errors-recovered");
  expect(problems).toEqual([]);
});
