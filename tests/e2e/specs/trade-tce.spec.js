/**
 * /trade TC-E journeys — accessibility and reliability on the real stack,
 * desktop (1366) and phone (390).
 *
 *   - keyboard building: the desktop side search is a combobox (ArrowDown /
 *     Enter adds without leaving the input); on the phone the "Add to Side"
 *     button opens the sheet from the keyboard, Tab reaches a result and Enter
 *     adds it;
 *   - the drilldown tabs move with the arrow keys; the More group closes on
 *     Escape and focus returns to its trigger;
 *   - the final decision is announced once, politely, in the page's one
 *     verdict live region (and nothing else on the page announces progress);
 *   - axe (WCAG 2.0/2.1 A + AA) is clean on a POPULATED trade: search list
 *     open on desktop, and with the War Room's answer on screen on both.
 *
 * `POST /api/trade/analyze` is answered from the real-output fixtures (as in
 * trade-war-room.spec.js); everything else is the seeded stack.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;

test.use({ serviceWorkers: "block" });

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const FIXTURES = path.resolve(__dirname, "../../../frontend/__tests__/fixtures/trade-war-room");
const CONSOLIDATION = JSON.parse(fs.readFileSync(path.join(FIXTURES, "consolidation.json"), "utf-8"));
const PICK_TOKEN = /\d{4}/;

async function pickTrade(page) {
  const { teams, playerNames } = await contractFixture(page);
  const board = new Set(playerNames);
  for (const [idx, team] of teams.entries()) {
    const give = (team.players || []).find((p) => p && !PICK_TOKEN.test(p) && board.has(p));
    const other = teams.find((t) => t !== team);
    const receive = (other?.players || []).find(
      (p) => p && !PICK_TOKEN.test(p) && board.has(p) && !(team.players || []).includes(p),
    );
    if (give && receive) return { idx, give, receive };
  }
  throw new Error("no team with a board-resolvable player on the seeded contract");
}

async function axeClean(page, label) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`),
    `axe violations (${label})`,
  ).toEqual([]);
}

/** Desktop: type, ArrowDown to the exact row, Enter. */
async function keyboardAddInline(page, side, name) {
  const input = page.getByRole("combobox", { name: `Search to add a player to Side ${side}` });
  await input.focus();
  await input.fill(name);
  const listbox = page.getByRole("listbox", { name: `Results for Side ${side}` });
  await expect(listbox).toBeVisible({ timeout: 15_000 });
  const options = listbox.getByRole("option");
  const count = await options.count();
  let target = -1;
  for (let i = 0; i < count; i += 1) {
    const text = (await options.nth(i).locator(".trade-side-search-result-name").textContent()).trim();
    if (text === name) {
      target = i;
      break;
    }
  }
  expect(target, `${name} is offered`).toBeGreaterThanOrEqual(0);
  for (let i = 0; i <= target; i += 1) await input.press("ArrowDown");
  const activeId = await input.getAttribute("aria-activedescendant");
  expect(activeId).toBe(await options.nth(target).getAttribute("id"));
  await input.press("Enter");
  await expect(page.getByRole("button", { name: `Remove ${name} from Side ${side}` })).toBeVisible();
  await expect(input).toBeFocused();
  await expect(input).toHaveValue("");
}

/** Phone: open the sheet from the keyboard, Tab to the exact row, Enter. */
async function keyboardAddSheet(page, side, name) {
  const open = page.getByRole("button", { name: `Add to Side ${side}`, exact: true });
  const dialog = page.getByRole("dialog", { name: `Add to Side ${side}` });
  // Selecting the team re-renders the side panels, so a focus taken in the
  // same tick can land on a node that is then replaced and the Enter goes
  // nowhere (CI mobile, 2026-10-18).  Re-take focus until it holds; the
  // sheet still has to open from the keyboard.
  await expect(async () => {
    if (await dialog.isVisible()) return;
    await open.focus();
    await expect(open).toBeFocused({ timeout: 1_000 });
    await page.keyboard.press("Enter");
    await expect(dialog).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 20_000 });
  const input = dialog.getByLabel(`Search to add a player to Side ${side}`);
  await expect(input).toBeFocused();
  await input.fill(name);
  const row = dialog
    .locator(".trade-side-search-result")
    .filter({ has: page.locator(".trade-side-search-result-name", { hasText: name }) })
    .first();
  await expect(row).toBeVisible({ timeout: 15_000 });
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press("Tab");
    if (await row.evaluate((el) => el === document.activeElement)) break;
  }
  await expect(row).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("status")).toHaveText(new RegExp(`Added ${name}`));
  await dialog.getByRole("button", { name: "Done" }).press("Enter");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // The Drawer returns focus to its opener.
  await expect(open).toBeFocused();
  await expect(page.getByRole("button", { name: `Remove ${name} from Side ${side}` })).toBeVisible();
}

test("trade TC-E: keyboard build, tabs, More menu, one polite verdict announcement, axe clean", async ({
  authedPage: page,
}, testInfo) => {
  const phone = testInfo.project.name.startsWith("mobile");
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route(
    (url) => url.pathname === "/api/trade/analyze",
    async (route) => {
      const body = route.request().postDataJSON() || {};
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify({ ...CONSOLIDATION, leagueKey: body.leagueKey || CONSOLIDATION.leagueKey }),
      });
    },
  );

  const trade = await pickTrade(page);
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
  await page.getByRole("button", { name: "Clear Trade", exact: true }).click();
  await page.selectOption("#suggest-team", String(trade.idx));

  // ── The More group opens from the keyboard and Escape closes it, focus on
  //    its trigger (its actions are disabled until the trade has assets, so
  //    the trigger is where a keyboard user is).
  const more = page.getByRole("button", { name: "More", exact: true });
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Download CSV" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Download CSV" })).toHaveCount(0);
  await expect(more).toBeFocused();

  // ── Keyboard building.
  if (phone) {
    await keyboardAddSheet(page, "A", trade.give);
    await keyboardAddSheet(page, "B", trade.receive);
  } else {
    await keyboardAddInline(page, "A", trade.give);
    // axe with the search list open (combobox + listbox + options).
    const input = page.getByRole("combobox", { name: "Search to add a player to Side B" });
    await input.focus();
    await input.fill(trade.receive.slice(0, 3));
    await expect(page.getByRole("listbox", { name: "Results for Side B" })).toBeVisible();
    await input.press("ArrowDown");
    await axeClean(page, "search list open");
    await input.press("Escape");
    await keyboardAddInline(page, "B", trade.receive);
  }

  // ── The final decision is announced once, politely; nothing else on the
  //    page is a live region announcing progress.
  const announcer = page.getByTestId("trade-verdict-announcer");
  await expect(announcer).toHaveAttribute("aria-live", "polite");
  await expect(announcer).toHaveText(
    new RegExp(`^Final decision: ${CONSOLIDATION.analysis.decision.headlineText}`),
    { timeout: 30_000 },
  );
  await expect(page.locator("[data-war-room]").getByRole("status")).toHaveCount(0);
  await expect(page.getByTestId("decision-summary").getByRole("status")).toHaveCount(0);

  // ── Drilldown tabs move with the arrow keys (roving tabindex).
  const valueTab = page.getByRole("tab", { name: "Value" });
  await valueTab.focus();
  await page.keyboard.press("ArrowRight");
  const rosterTab = page.getByRole("tab", { name: "Roster" });
  await expect(rosterTab).toBeFocused();
  await expect(rosterTab).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Reasoning" })).toHaveAttribute("aria-selected", "true");

  // ── axe on the populated trade with the decision on screen.
  await expect(page.locator('[data-war-room="ok"]')).toBeVisible({ timeout: 30_000 });
  await axeClean(page, phone ? "phone, decision on screen" : "desktop, decision on screen");

  expect(errors, "no uncaught page errors").toEqual([]);
});
