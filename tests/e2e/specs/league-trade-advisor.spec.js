const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");
const { advisorServed } = require("../helpers/advisor");

// Brisket Trade Advisor — the public League Hub's default tab (design §8,
// §11 group E).  Anonymous; service workers blocked; the advisor's three
// public endpoints ROUTE-MOCKED in the browser from the frozen §4 fixtures
// the backend unit pins against real responses
// (frontend/__tests__/fixtures/trade-advisor/).
//
// What cannot be mocked from the browser is the SERVER's own read of
// /api/public/league/trade-advisor/teams, which decides whether the hub
// offers the advisor at all (flag `brisket_trade_advisor`, default OFF, and
// the route only exists once the backend unit lands).  So:
//
//   - "landing" ALWAYS runs and asserts the right landing for whatever the
//     backend says: the advisor when served, Overview (with no advisor tab
//     and nothing broken) when it is not.
//   - the flow tests need the advisor served; they skip with that reason
//     otherwise (3 per project — inside the reporter's skip ceiling).
//
// Team identities in the flow tests are whatever the page offers (the real
// E2E league when SSR answered, the fixture teams when the browser asked),
// so the tests pick teams by position, never by name.

const FIX = path.resolve(__dirname, "..", "..", "..", "frontend", "__tests__", "fixtures", "trade-advisor");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8"));

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

// Route the advisor's browser requests to fixtures.  Asset lists are handed
// out by first request: the first team opened gets assets.value_desc, the
// second assets.alpha, the third a one-player list.
async function mockAdvisor(page, { analyze = () => ({ status: 200, body: fixture("analyze.favorable") }) } = {}) {
  const lists = [fixture("assets.value_desc"), fixture("assets.alpha"), {
    ...fixture("assets.alpha"),
    assets: [{ id: "p:302", kind: "player", label: "Charlie Back", side: "offense", position: "RB", nflTeam: "NYJ", evaluable: true }],
  }];
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
    posts.push(JSON.parse(route.request().postData() || "{}"));
    const { status, body, headers } = analyze(posts.length);
    route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "no-store", ...(headers || {}) }, body: JSON.stringify(body) });
  });
  return { posts };
}

async function chooseTeam(page, label, position) {
  const input = page.getByRole("combobox", { name: label });
  await input.click();
  const options = page.getByRole("listbox", { name: label }).getByRole("option");
  await options.nth(position).click();
}

async function addAssets(page, panelIndex, labels) {
  await page.getByTestId(`advisor-panel-${panelIndex}`).getByRole("button", { name: "+ Add player or pick" }).click();
  const sheet = page.getByTestId("advisor-asset-sheet");
  await expect(sheet.getByTestId("advisor-asset-list")).toBeVisible();
  for (const label of labels) await sheet.getByRole("option", { name: new RegExp(label) }).click();
  await sheet.getByRole("button", { name: "Done" }).click();
}

async function openAdvisor(page) {
  await page.goto(pageUrl("/league"));
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("combobox", { name: "Your team" })).toBeVisible({ timeout: 30_000 });
}

async function buildTwoTeamTrade(page) {
  await chooseTeam(page, "Your team", 0);
  await expect(page.getByRole("heading", { name: /Select trade partner/ })).toBeVisible();
  await chooseTeam(page, "Trade partner", 1);
  await addAssets(page, 0, ["Alpha Quarterback"]);
  await addAssets(page, 1, ["Bravo Star"]);
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
      await expect(page.getByText("Evaluate trades using our league's scoring, roster construction, and dynasty market.")).toBeVisible();
      await expect(page.getByRole("heading", { name: /Which team are you evaluating for\?/ })).toBeVisible();
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

  test("two-team flow: build, review, analyze, every category, edit and Back", async ({ page, request }) => {
    test.skip(!(await advisorServed(request)), "the backend does not serve the advisor (flag brisket_trade_advisor off or route absent)");
    test.setTimeout(180_000);
    const categories = [
      fixture("analyze.favorable"),
      fixture("analyze.strongly-unfavorable"),
      fixture("analyze.roster-limit"),
      fixture("analyze.unavailable-asset"),
    ];
    const privateHits = watchPrivate(page);
    const { posts } = await mockAdvisor(page, { analyze: (n) => ({ status: 200, body: categories[Math.min(n - 1, categories.length - 1)] }) });
    await openAdvisor(page);
    await buildTwoTeamTrade(page);
    const summary = page.getByTestId("advisor-summary");
    await expect(summary).toContainText("Alpha Quarterback");
    await expect(summary).toContainText("Bravo Star");
    await noHorizontalScroll(page);

    for (const expected of categories) {
      await page.getByRole("button", { name: "Analyze trade" }).click();
      const result = page.getByTestId("advisor-result");
      await expect(result.getByTestId("advisor-headline")).toHaveText(expected.headline);
      await expect(result.getByText(expected.message, { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("heading", { name: "Trade analysis" })).toBeFocused();
      await noHorizontalScroll(page);
      if (expected === categories[0]) {
        // Back from a result returns to the builder with the legs intact.
        await page.goBack();
        await expect(page.getByTestId("advisor-panel-0")).toContainText("Alpha Quarterback");
        await page.goForward();
        await expect(result.getByTestId("advisor-headline")).toHaveText(expected.headline);
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

  test("three-team builder shows the honest UNAVAILABLE result; 409 and 429 recover", async ({ page, request }) => {
    test.skip(!(await advisorServed(request)), "the backend does not serve the advisor (flag brisket_trade_advisor off or route absent)");
    test.setTimeout(180_000);
    const answers = [
      { status: 409, body: fixture("error.stale-assets") },
      { status: 429, body: { ...fixture("error.rate-limited"), retryAfterSeconds: 2 }, headers: { "retry-after": "2" } },
      { status: 200, body: fixture("analyze.multi-team-unsupported") },
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

    const count = page.getByRole("radiogroup", { name: "Teams involved" }).locator("visible=true").first();
    await count.getByRole("radio", { name: "3" }).click();
    await expect(page.getByText(/more than two teams yet/)).toBeVisible();
    await chooseTeam(page, "Team C", 2);
    await addAssets(page, 2, ["Charlie Back"]);
    for (const [label, idx] of [["Alpha Quarterback", 1], ["Bravo Star", 2], ["Charlie Back", 0]]) {
      const select = page.getByRole("combobox", { name: `Send ${label} to` });
      const values = await select.locator("option:not([disabled])").evaluateAll((os) => os.map((o) => o.value));
      await select.selectOption(values[Math.min(idx, values.length - 1)] ?? values[0]);
    }
    await noHorizontalScroll(page);
    await page.getByRole("button", { name: "Analyze trade" }).click();
    const result = page.getByTestId("advisor-result");
    await expect(result.getByTestId("advisor-headline")).toHaveText("NO RECOMMENDATION");
    await expect(result.getByText("Recommendations for trades with more than two teams aren't available yet.")).toBeVisible();
    await expect(result.getByRole("button", { name: "Try again" })).toHaveCount(0);
  });

  test("navigation: Back across tabs, the landing button, and Overview back-links", async ({ page, request }) => {
    test.skip(!(await advisorServed(request)), "the backend does not serve the advisor (flag brisket_trade_advisor off or route absent)");
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
