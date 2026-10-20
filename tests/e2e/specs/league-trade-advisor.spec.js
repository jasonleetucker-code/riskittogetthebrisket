const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");
const { advisorServed } = require("../helpers/advisor");

// Brisket Trade Advisor — the public League Hub's default tab (spec
// docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §4, §5.2; owner amendment
// 2026-10-20: FAIRNESS ONLY — FAIR TRADE / NOT FAIR / UNABLE TO DETERMINE,
// per team and overall, for 2-, 3- and 4-team trades).  Anonymous; service
// workers blocked.
//
// Two kinds of test:
//
//   - MOCKED flows route the advisor's browser requests to the spec §4
//     fixtures (frontend/__tests__/fixtures/trade-advisor/, produced by the
//     backend lane from real responses).  The fixture's team ids are
//     remapped onto the teams the page actually offers, so the result reads
//     against the trade that was built.
//   - LIVE flows send nothing mocked: real team lists, real asset lists and
//     the real server analysis of 2-, 3- and 4-team trades with several
//     assets.  They need a stack that SERVES the advisor (flag
//     `brisket_trade_advisor` on AND the launch gate open — locally only;
//     production stays off) and skip with that reason otherwise.
//
// What cannot be mocked from the browser is the SERVER's own read of
// /api/public/league/trade-advisor/teams, which decides whether the hub
// offers the advisor at all.  "landing" ALWAYS runs and asserts the right
// landing for whatever the backend says.
//
// Team identities are whatever the page offers, so tests pick teams and
// assets by position, never by name.  Set ADVISOR_SCREENSHOT_DIR to keep
// full-page screenshots of every live flow.

const FIX = path.resolve(__dirname, "..", "..", "..", "frontend", "__tests__", "fixtures", "trade-advisor");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8"));
const SHOTS = process.env.ADVISOR_SCREENSHOT_DIR || "";
const NOT_SERVED = "the backend does not serve the advisor (flag brisket_trade_advisor off, launch gate closed, or route absent)";

test.use({ serviceWorkers: "block" });

function watchPrivate(page) {
  const hits = [];
  page.on("request", (req) => {
    const u = new URL(req.url());
    if (u.pathname.startsWith("/api/data") || u.pathname.startsWith("/api/dynasty-data") || u.pathname.startsWith("/api/trade/")) {
      hits.push(u.pathname);
    }
  });
  return hits;
}

// A fixture answer re-keyed onto the trade that was actually posted: the
// fixture's teams (ascending roster id) map onto the posted teams
// (ascending), and the echoed legs are the posted legs.  The fixture's
// results and fixed copy are untouched.
function remap(answer, post) {
  const ids = post.teams.slice().sort((a, b) => a - b);
  const rows = answer.teams.slice().sort((a, b) => a.rosterId - b.rosterId);
  if (rows.length !== ids.length) throw new Error(`fixture has ${rows.length} teams, trade has ${ids.length}`);
  return {
    ...answer,
    teamCount: ids.length,
    perspectiveRosterId: post.perspectiveRosterId,
    teams: rows.map((t, i) => ({ ...t, rosterId: ids[i], unavailableAssetIds: [] })),
    trade: post.assets.slice().sort((x, y) => (x.id < y.id ? -1 : 1)),
  };
}

// Route the advisor's browser requests to fixtures.  Asset lists are handed
// out by first request: the first team opened gets assets.position_alpha,
// the second the Bravo list, the third and fourth one-player lists.
async function mockAdvisor(page, { analyze = () => ({ status: 200, body: fixture("analyze.not-fair-two-team") }) } = {}) {
  const extra = (id, label) => ({
    ...fixture("assets.pick-ownership-unavailable"),
    assets: [{ id, kind: "player", label, side: "offense", position: "RB", nflTeam: "NYJ", evaluable: true }],
  });
  const lists = [fixture("assets.position_alpha"), fixture("assets.pick-ownership-unavailable"), extra("p:303", "Charlie Back"), extra("p:403", "Delta Back")];
  const byRoster = new Map();
  const posts = [];
  await page.route("**/api/public/league/trade-advisor/teams", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture("teams.success")) }),
  );
  await page.route("**/api/public/league/trade-advisor/teams/*/assets?*", (route) => {
    const rid = new URL(route.request().url()).pathname.split("/").at(-2);
    if (!byRoster.has(rid)) byRoster.set(rid, lists[Math.min(byRoster.size, lists.length - 1)]);
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(byRoster.get(rid)) });
  });
  await page.route("**/api/public/league/trade-advisor/analyze", (route) => {
    const post = JSON.parse(route.request().postData() || "{}");
    posts.push(post);
    const { status, body, headers } = analyze(posts.length);
    const out = status === 200 && body && body.status === "success" ? remap(body, post) : body;
    route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "no-store", ...(headers || {}) }, body: JSON.stringify(out) });
  });
  return { posts };
}

async function chooseTeam(page, label, position) {
  const input = page.getByRole("combobox", { name: label });
  await input.click();
  const options = page.getByRole("listbox", { name: label }).getByRole("option");
  await options.nth(position).click();
}

async function chooseCount(page, n) {
  const count = page.getByRole("radiogroup", { name: "Teams involved" }).locator("visible=true").first();
  await count.getByRole("radio", { name: String(n) }).click();
}

async function addAssets(page, panelIndex, labels) {
  await page.getByTestId(`advisor-panel-${panelIndex}`).getByRole("button", { name: "+ Add player or pick" }).click();
  const sheet = page.getByTestId("advisor-asset-sheet");
  await expect(sheet.getByTestId("advisor-asset-list")).toBeVisible();
  for (const label of labels) await sheet.getByRole("option", { name: new RegExp(label) }).click();
  await sheet.getByRole("button", { name: "Done" }).click();
}

// Live lists: add the first `players` evaluable players, plus one pick when
// asked and the team has one.  Returns the labels added.
async function addLiveAssets(page, panelIndex, { players = 2, pick = false } = {}) {
  await page.getByTestId(`advisor-panel-${panelIndex}`).getByRole("button", { name: "+ Add player or pick" }).click();
  const sheet = page.getByTestId("advisor-asset-sheet");
  const list = sheet.getByTestId("advisor-asset-list");
  await expect(list).toBeVisible({ timeout: 30_000 });
  const added = [];
  const take = async (n) => {
    const options = list.locator('[role="option"]:not([aria-disabled="true"])');
    const count = await options.count();
    for (let i = 0, got = 0; i < count && got < n; i += 1) {
      const option = options.nth(0);
      const meta = await option.textContent();
      if (/can't be evaluated/.test(meta || "")) break;
      added.push(((await option.locator("span span").first().textContent()) || "").trim());
      await option.click();
      got += 1;
    }
  };
  await take(players);
  if (pick) {
    await sheet.getByRole("radio", { name: "Picks" }).click();
    if (await list.count()) await take(1);
    await sheet.getByRole("radio", { name: "All" }).click();
  }
  await sheet.getByRole("button", { name: "Done" }).click();
  return added;
}

// Route every leg of a 3+-team trade: each team's first asset to its first
// destination option, every later one to its last — so every team both
// sends and receives (a cycle plus one-to-many fan-out).
async function routeLive(page, labelsByPanel) {
  for (const labels of labelsByPanel) {
    for (let j = 0; j < labels.length; j += 1) {
      const select = page.getByRole("combobox", { name: `Send ${labels[j]} to` });
      const values = await select.locator("option:not([disabled])").evaluateAll((os) => os.map((o) => o.value));
      await select.selectOption(j === 0 ? values[0] : values[values.length - 1]);
    }
  }
}

async function openAdvisor(page) {
  await page.goto(pageUrl("/league"));
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("combobox", { name: "Your team" })).toBeVisible({ timeout: 30_000 });
  // Hydration gate (ds useHydrated): the team-count control and hub tabs
  // render disabled + aria-busy until React attaches handlers.
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
}

async function buildTwoTeamTrade(page) {
  await chooseTeam(page, "Your team", 0);
  await expect(page.getByRole("heading", { name: /Select trade partner/ })).toBeVisible();
  await chooseTeam(page, "Trade partner", 1);
  await addAssets(page, 0, ["Alpha Quarterback"]);
  await addAssets(page, 1, ["Bravo Star"]);
}

// Every public analyze body: value-free (spec §4.3 numeric allowlist, no
// floats, no private keys).
const NUMERIC_KEYS = new Set(["rosterId", "originRosterId", "teamCount", "season", "round", "minTeams", "maxTeams", "maxLegs", "retryAfterSeconds", "maxBytes", "perspectiveRosterId", "from", "to"]);
const BLOCKED_KEYS = /^(value|valueState|gap|largerAdjustedSide|relativePct|band|level|category|categoryText|headline|decision|simulation|analysis|fairness|packageModel|fairnessBands|decisionRunIds|tradeRunId|analysisTiming|rankDerivedValue)$/;
function assertValueFree(node, trail = "$") {
  if (Array.isArray(node)) return node.forEach((x, i) => assertValueFree(x, `${trail}[${i}]`));
  if (node && typeof node === "object") {
    for (const [k, v] of Object.entries(node)) {
      expect(BLOCKED_KEYS.test(k), `${trail}.${k} is a private key`).toBe(false);
      if (typeof v === "number") {
        expect(Number.isInteger(v), `${trail}.${k} is a float`).toBe(true);
        expect(NUMERIC_KEYS.has(k) || /rosterIds\[/.test(`${trail}.${k}`), `${trail}.${k} is not an allowlisted number`).toBe(true);
      } else if (Array.isArray(v) && v.some((x) => typeof x === "number")) {
        expect(k, `${trail}.${k} carries numbers`).toBe("teams");
      }
      assertValueFree(v, `${trail}.${k}`);
    }
  }
}

async function shot(page, testInfo, name) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${testInfo.project.name}-${name}.png`), fullPage: true });
}

async function noHorizontalScroll(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(1);
}

test.describe("Brisket Trade Advisor", () => {
  test("landing: the advisor when served, otherwise Overview — never a broken hub", async ({ page, request }) => {
    const served = await advisorServed(request);
    const privateHits = watchPrivate(page);
    await page.goto(pageUrl("/league"));
    await awaitStreamSettled(page);
    if (served) {
      await expect(page.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText("Check whether a trade is fair, by our league's dynasty market.")).toBeVisible();
      await expect(page.getByRole("heading", { name: /Which team is yours\?/ })).toBeVisible();
    } else {
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toHaveCount(0);
      await expect(page.locator("#league-panel-overview")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("tab", { name: "Trade Advisor" })).toHaveCount(0);
      await expect(page.getByText(/League data unavailable|Section unavailable/)).toHaveCount(0);
      // Flag off = main: the Overview markup is in the SERVER-rendered
      // HTML and the tab is labelled "Home" (desktop tab row).
      const html = await (await request.get(pageUrl("/league"))).text();
      expect(html).toMatch(/At a glance|Defending champion|Featured rivalry/);
      if ((page.viewportSize()?.width ?? 1366) > 768) {
        await expect(page.getByRole("tab", { name: "Home", exact: true })).toHaveCount(1);
        await expect(page.getByRole("tab", { name: "Overview", exact: true })).toHaveCount(0);
      }
    }
    // Deep links to other tabs keep working either way.
    await page.goto(pageUrl("/league?tab=awards"));
    await awaitStreamSettled(page);
    await expect(page.locator("#league-panel-awards")).toBeVisible({ timeout: 30_000 });
    expect(privateHits, `private endpoints touched: ${privateHits.join(", ")}`).toEqual([]);
  });

  test("two-team flow (mocked): build, review, analyze, every result, edit and Back", async ({ page, request }) => {
    test.skip(!(await advisorServed(request)), NOT_SERVED);
    test.setTimeout(180_000);
    const results = [fixture("analyze.not-fair-two-team"), fixture("analyze.fair-two-team"), fixture("analyze.unable-asset")];
    const privateHits = watchPrivate(page);
    const { posts } = await mockAdvisor(page, { analyze: (n) => ({ status: 200, body: results[Math.min(n - 1, results.length - 1)] }) });
    await openAdvisor(page);
    await buildTwoTeamTrade(page);
    const summary = page.getByTestId("advisor-summary");
    await expect(summary).toContainText("Alpha Quarterback →");
    await expect(summary).toContainText("Bravo Star ←");
    await noHorizontalScroll(page);

    for (const expected of results) {
      await page.getByRole("button", { name: "Analyze trade" }).click();
      const result = page.getByTestId("advisor-result");
      await expect(result.getByTestId("advisor-overall-label")).toHaveText(expected.overall.label);
      await expect(result.getByText(expected.overall.reasonText, { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("heading", { name: "Is this trade fair?" })).toBeFocused();
      await expect(result.getByRole("tab")).toHaveCount(2);
      await expect(result).not.toContainText(/accept|decline|recommend/i);
      await noHorizontalScroll(page);
      if (expected === results[0]) {
        // Back from a result returns to the builder with the legs intact.
        // The result's history entry is pushed after the result renders;
        // wait for it, or Back can leave the app entirely.
        await expect(page).toHaveURL(/step=result/);
        await page.goBack();
        await expect(page.getByTestId("advisor-panel-0")).toContainText("Alpha Quarterback");
        await page.goForward();
        await expect(result.getByTestId("advisor-overall-label")).toHaveText(expected.overall.label);
      }
      await page.getByRole("button", { name: "Edit trade" }).click();
    }
    // The body carries identities and routing only.
    for (const body of posts) {
      expect(Object.keys(body).sort()).toEqual(["assets", "perspectiveRosterId", "teams"]);
      for (const leg of body.assets) expect(Object.keys(leg).sort()).toEqual(["from", "id", "to"]);
    }
    const html = await page.content();
    expect(html).not.toMatch(/rankDerivedValue|aria-posinset|aria-setsize/);
    expect(privateHits).toEqual([]);

    const axe = await new AxeBuilder({ page }).include('[data-testid="trade-advisor"]').withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(axe.violations.map((v) => v.id)).toEqual([]);
  });

  test("three-team builder (mocked): preconditions, routing, every team's result; 409 and 429 recover", async ({ page, request }) => {
    test.skip(!(await advisorServed(request)), NOT_SERVED);
    test.setTimeout(180_000);
    const answers = [
      { status: 409, body: fixture("error.stale-assets") },
      { status: 429, body: { ...fixture("error.rate-limited"), retryAfterSeconds: 2 }, headers: { "retry-after": "2" } },
      { status: 200, body: fixture("analyze.three-team-fair") },
    ];
    await mockAdvisor(page, { analyze: (n) => answers[Math.min(n - 1, answers.length - 1)] });
    await openAdvisor(page);
    await buildTwoTeamTrade(page);

    await page.getByRole("button", { name: "Analyze trade" }).click();
    await expect(page.getByText("Rosters changed")).toBeVisible();
    await page.getByRole("button", { name: "Analyze trade" }).click();
    await expect(page.getByTestId("advisor-cooldown")).toBeVisible();
    await expect(page.getByRole("button", { name: "Analyze trade" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Analyze trade" })).toBeEnabled({ timeout: 10_000 });

    await chooseCount(page, 3);
    await expect(page.getByText(/more than two teams yet/)).toHaveCount(0);
    await chooseTeam(page, "Team C", 2);
    await addAssets(page, 2, ["Charlie Back"]);
    await expect(page.getByRole("button", { name: "Analyze trade" })).toBeDisabled();
    for (const [label, idx] of [["Alpha Quarterback", 0], ["Bravo Star", 1], ["Charlie Back", 0]]) {
      const select = page.getByRole("combobox", { name: `Send ${label} to` });
      const values = await select.locator("option:not([disabled])").evaluateAll((os) => os.map((o) => o.value));
      await select.selectOption(values[Math.min(idx, values.length - 1)]);
    }
    await noHorizontalScroll(page);
    await page.getByRole("button", { name: "Analyze trade" }).click();
    const result = page.getByTestId("advisor-result");
    await expect(result.getByTestId("advisor-overall-label")).toHaveText("FAIR TRADE");
    await expect(result.getByText(fixture("analyze.three-team-fair").overall.note)).toBeVisible();
    await expect(result.getByRole("tab")).toHaveCount(3);
    await expect(result.getByRole("button", { name: "Try again" })).toHaveCount(0);
  });

  for (const n of [2, 3, 4]) {
    test(`live ${n}-team trade: the real server judges every team; perspective switch; value-free; mobile-safe`, async ({ page, request }, testInfo) => {
      test.skip(!(await advisorServed(request)), NOT_SERVED);
      test.setTimeout(240_000);
      const privateHits = watchPrivate(page);
      const responses = [];
      page.on("response", async (res) => {
        if (res.url().includes("/api/public/league/trade-advisor/")) {
          try {
            responses.push({ url: res.url(), status: res.status(), body: await res.json(), cache: res.headers()["cache-control"] || "" });
          } catch {
            /* non-JSON */
          }
        }
      });
      await openAdvisor(page);
      await chooseTeam(page, "Your team", 0);
      await expect(page.getByRole("heading", { name: /Select (trade partner|the other teams)/ })).toBeVisible();
      if (n > 2) await chooseCount(page, n);
      const slots = ["Trade partner", "Team C", "Team D"].slice(0, n - 1);
      for (let i = 0; i < slots.length; i += 1) await chooseTeam(page, slots[i], i + 1);
      const labels = [];
      for (let i = 0; i < n; i += 1) {
        labels.push(await addLiveAssets(page, i, { players: i === 0 && n > 2 ? 3 : 2, pick: i === 1 }));
      }
      await expect(page.getByRole("button", { name: "Analyze trade" })).toBeDisabled({ timeout: 1_000 }).catch(() => {});
      if (n > 2) await routeLive(page, labels);
      const analyze = page.getByRole("button", { name: "Analyze trade" });
      await expect(analyze).toBeEnabled();
      await noHorizontalScroll(page);
      await shot(page, testInfo, `${n}team-1-review`);

      await analyze.click();
      const result = page.getByTestId("advisor-result");
      await expect(result).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole("heading", { name: "Is this trade fair?" })).toBeFocused();
      const overall = (await result.getByTestId("advisor-overall-label").textContent()).trim();
      expect(["FAIR TRADE", "NOT FAIR", "UNABLE TO DETERMINE"]).toContain(overall);
      const rows = result.getByTestId("advisor-team-results").getByRole("listitem");
      await expect(rows).toHaveCount(n);
      const tabs = result.getByRole("tab");
      await expect(tabs).toHaveCount(n);
      await expect(result).not.toContainText(/\b(accept|decline|recommend\w*|should|approve|deny)\b/i);
      await noHorizontalScroll(page);
      await shot(page, testInfo, `${n}team-2-result`);

      // Perspective switch: every team's own row of the SAME response.
      const posts = () => responses.filter((r) => r.url.endsWith("/analyze")).length;
      const before = posts();
      for (let i = n - 1; i >= 0; i -= 1) {
        await tabs.nth(i).click();
        await expect(tabs.nth(i)).toHaveAttribute("aria-selected", "true");
        const label = (await result.getByTestId("advisor-team-verdict-label").textContent()).trim();
        expect(["FAIR FOR THIS TEAM", "NOT FAIR FOR THIS TEAM", "UNABLE TO DETERMINE"]).toContain(label);
      }
      await tabs.nth(n - 1).click();
      await shot(page, testInfo, `${n}team-3-perspective`);
      expect(posts()).toBe(before);

      // Every advisor response this page saw is value-free and uncached.
      const analyzed = responses.filter((r) => r.url.endsWith("/analyze"));
      expect(analyzed).toHaveLength(1);
      expect(analyzed[0].status).toBe(200);
      expect(analyzed[0].cache).toMatch(/no-store/);
      expect(analyzed[0].body.teams).toHaveLength(n);
      for (const r of responses) assertValueFree(r.body);
      // The page itself carries no board value either.
      expect(await page.content()).not.toMatch(/rankDerivedValue|"gap"|"band"|aria-posinset/);
      expect(privateHits).toEqual([]);

      const axe = await new AxeBuilder({ page }).include('[data-testid="trade-advisor"]').withTags(["wcag2a", "wcag2aa"]).analyze();
      expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((x) => x.target.join(" ")).join(" | ")}`)).toEqual([]);

      // Edit keeps the trade; Start over clears it.
      await page.getByRole("button", { name: "Edit trade" }).click();
      await expect(page.getByTestId("advisor-panel-0")).toContainText(labels[0][0]);
      await page.getByRole("button", { name: "Analyze trade" }).click();
      await expect(result).toBeVisible({ timeout: 60_000 });
      await page.getByRole("button", { name: "Start over" }).click();
      await expect(page.getByRole("combobox", { name: "Your team" })).toHaveValue("");
    });
  }

  test("navigation: Back across tabs, the landing button, and Overview back-links", async ({ page, request }) => {
    test.skip(!(await advisorServed(request)), NOT_SERVED);
    await mockAdvisor(page);
    await page.goto(pageUrl("/"));
    const hub = page.getByRole("link", { name: "Go to League Hub" });
    if (await hub.count()) {
      await hub.first().click();
      await expect(page.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeVisible({ timeout: 30_000 });
    } else {
      await openAdvisor(page);
    }
    const width = page.viewportSize()?.width ?? 1366;
    if (width <= 768) {
      await page.getByLabel("Select league section").selectOption({ label: "Overview" });
    } else {
      await page.getByRole("tab", { name: "Overview", exact: true }).first().click();
    }
    await expect(page).toHaveURL(/tab=overview/);
    await page.goBack();
    await expect(page).not.toHaveURL(/tab=/);
    await expect(page.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeVisible();
    await noHorizontalScroll(page);
  });
});
