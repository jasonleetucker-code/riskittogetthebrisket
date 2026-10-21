/**
 * Brisket Trade Advisor — complete public flows, keyboard only, with axe,
 * focus management, hydration readiness and error recovery (owner directive
 * 2026-10-20 §8, §12, §16 item 8; fairness-only amendment; spec
 * docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §4-§5.2).
 *
 * Complements league-trade-advisor.spec.js (pointer/touch flows).  Every
 * step here is driven from the KEYBOARD: Tab / Shift+Tab to reach a
 * control, the ds widgets' own keys to operate it (Combobox ArrowDown /
 * Enter, SegmentedControl and Tabs arrows, listbox ArrowDown / Enter, native
 * <select> ArrowDown / End, Escape to close the sheet).  No `.click()`, no
 * `.fill()`, no `.selectOption()` on the advisor.
 *
 *   - LIVE keyboard flows for 2-, 3- and 4-team trades with several assets
 *     per team (players and a pick), cycle + fan-out routing, review,
 *     analyze, every team's perspective, edit + re-analyze, new trade and
 *     start over — against the REAL server (nothing mocked).  axe
 *     (WCAG 2.0/2.1 A + AA) runs at every step: landing, builder, open asset
 *     sheet, review, result, each perspective.
 *   - Focus management: the sheet takes focus and traps Tab; Escape / Done
 *     returns focus to the button that opened it; the result moves focus to
 *     its heading; Edit trade / New trade land on the Build-your-trade
 *     heading, Start over on the Which-team-is-yours heading, and Remove on
 *     the neighbouring asset's Remove button (launch gate 8).
 *   - Hydration readiness: nothing stays aria-busy, no React hydration error
 *     or uncaught page error at any step.
 *   - Error recovery (browser-side faults injected on the analyze request,
 *     everything else real): a network failure and a 500 show the retry
 *     banner, and Try again — by keyboard — reaches the real answer.
 *
 * These need a stack that SERVES the advisor (flag `brisket_trade_advisor`
 * ON and the launch gate open — locally only; production stays off).  When
 * the advisor is not served nothing here can run: the server decides at
 * render time whether /league offers it.  So the file registers its tests
 * only when E2E_ADVISOR_E2E=1, instead of adding ~10 skips per project to
 * the CI skip ceiling (stack-death-reporter.js, 70).
 *
 * Screenshots of every step go to E3_SCREENSHOT_DIR when set, else to the
 * test's output folder.
 */
const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const RESULTS = ["FAIR TRADE", "NOT FAIR", "UNABLE TO DETERMINE"];
const TEAM_LABELS = ["FAIR FOR THIS TEAM", "NOT FAIR FOR THIS TEAM", "UNABLE TO DETERMINE"];
const SLOTS = ["Your team", "Trade partner", "Team C", "Team D"];
const FORBIDDEN = /\b(accept|decline|recommend\w*|should|approve|deny)\b/i;

test.use({ serviceWorkers: "block" });

// ── evidence ─────────────────────────────────────────────────────────────
function shotPath(testInfo, name) {
  const dir = process.env.E3_SCREENSHOT_DIR;
  if (dir) {
    fs.mkdirSync(dir, { recursive: true });
    return path.join(dir, `${testInfo.project.name}-public-${name}.png`);
  }
  return testInfo.outputPath(`${name}.png`);
}

async function shot(page, testInfo, name) {
  await page.screenshot({ path: shotPath(testInfo, name), fullPage: true });
}

async function axe(page, testInfo, step, include = '[data-testid="trade-advisor"]') {
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
  // Soft: every step's scan is reported, and the flow keeps going.
  expect.soft(ids, `axe violations at step "${step}"`).toEqual([]);
}

async function noHorizontalScroll(page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(1);
}

// Hydration + runtime guards for the whole test.
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

async function hydrated(page) {
  await expect(page.locator('[data-testid="trade-advisor"] [aria-busy="true"]')).toHaveCount(0, {
    timeout: 30_000,
  });
  await expect(page.locator('[role="tablist"][aria-busy="true"]')).toHaveCount(0, {
    timeout: 30_000,
  });
}

// ── keyboard primitives ──────────────────────────────────────────────────
async function focused(page) {
  return page.evaluate(() => {
    const a = document.activeElement;
    if (!a || a === document.body) return "body";
    return `${a.tagName.toLowerCase()}${a.id ? `#${a.id}` : ""}[${a.getAttribute("aria-label") || (a.textContent || "").trim().slice(0, 40)}]`;
  });
}

/**
 * Press Tab (or Shift+Tab) until `locator` holds focus.  Fails if it is not
 * reachable within `max` presses — i.e. the control is not in the tab order.
 */
async function tabTo(page, locator, { max = 80, back = false } = {}) {
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

// Launch gate 8 (WCAG 2.4.3): after Edit trade / Remove / New trade / Start
// over the pressed control unmounts, and focus must land on the named
// target — never on <body>.  Hard assertions since the Lane D fix.
async function expectFocusOn(page, locator, what) {
  expect(await focused(page), `${what}: focus fell to <body>`).not.toBe("body");
  await expect(locator, `${what}: focus target`).toBeFocused();
}

// Combobox: ArrowDown opens on the current/first enabled option, ArrowDown
// moves, Enter chooses.  `skip` = how many enabled options to move past.
async function comboChoose(page, label, skip) {
  const input = page.getByRole("combobox", { name: label });
  await tabTo(page, input);
  await page.keyboard.press("ArrowDown");
  await expect(input).toHaveAttribute("aria-expanded", "true");
  for (let i = 0; i < skip; i += 1) await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(input).toHaveAttribute("aria-expanded", "false");
  const value = await input.inputValue();
  expect(value, `${label} chose a team`).not.toBe("");
  return value;
}

// SegmentedControl "Teams involved": roving tabindex, arrows select.
async function chooseCountByKeyboard(page, n) {
  const group = page
    .getByRole("radiogroup", { name: "Teams involved" })
    .locator("visible=true")
    .first();
  await tabTo(page, group.locator('[role="radio"][tabindex="0"]'));
  for (let guardN = 0; guardN < 6; guardN += 1) {
    if (
      (await group
        .getByRole("radio", { name: String(n), exact: true })
        .getAttribute("aria-checked")) === "true"
    )
      return;
    await page.keyboard.press("ArrowRight");
  }
  throw new Error(`team count ${n} not reachable by arrows`);
}

// The asset sheet: open by keyboard, prove focus moved inside and Tab is
// trapped, add players (and a pick) with the listbox keys, close with Done
// (or Escape), prove focus returned to the opener.
async function addAssetsByKeyboard(
  page,
  testInfo,
  panelIndex,
  { players, pick, close = "done", shotName, axeStep },
) {
  const opener = page
    .getByTestId(`advisor-panel-${panelIndex}`)
    .getByRole("button", { name: "+ Add player or pick" });
  await tabTo(page, opener);
  await page.keyboard.press("Enter");
  const sheet = page.getByTestId("advisor-asset-sheet");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // Focus moved into the dialog.
  await expect.poll(() => dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
  const list = sheet.getByTestId("advisor-asset-list");
  await expect(list).toBeVisible({ timeout: 30_000 });

  const added = [];
  const takeFromList = async (n) => {
    await tabTo(page, list);
    // Indices of evaluable options not already in the trade.
    const metas = await list
      .locator('[role="option"]')
      .evaluateAll((os) =>
        os.map((o) => ({
          disabled: o.getAttribute("aria-disabled") === "true",
          text: o.textContent || "",
        })),
      );
    const want = [];
    for (let i = 0; i < metas.length && want.length < n; i += 1) {
      if (!metas[i].disabled && !/can't be evaluated/.test(metas[i].text)) want.push(i);
    }
    let active = -1;
    for (const idx of want) {
      while (active < idx) {
        await page.keyboard.press("ArrowDown");
        active += 1;
      }
      const option = list.locator('[role="option"]').nth(idx);
      added.push(((await option.locator("span span").first().textContent()) || "").trim());
      await page.keyboard.press("Enter");
      await expect(option).toHaveAttribute("aria-selected", "true");
    }
    return want.length;
  };

  const gotPlayers = await takeFromList(players);
  expect(gotPlayers, `team ${panelIndex} has ${players} evaluable players`).toBe(players);
  if (pick) {
    // "Show" segmented control → Picks (roving tabindex; arrows select).
    const show = sheet.getByRole("radiogroup", { name: "Show" });
    await tabTo(page, show.locator('[role="radio"][tabindex="0"]'), { back: true });
    for (let k = 0; k < 4; k += 1) {
      if (
        (await show.getByRole("radio", { name: "Picks" }).getAttribute("aria-checked")) === "true"
      )
        break;
      await page.keyboard.press("ArrowRight");
    }
    if (await list.count()) await takeFromList(1);
  }
  // Focus trap: Tab from the last control wraps inside the dialog.
  for (let i = 0; i < 12; i += 1) await page.keyboard.press("Tab");
  expect(
    await dialog.evaluate((d) => d.contains(document.activeElement)),
    "Tab stays trapped in the sheet",
  ).toBe(true);

  if (shotName) await shot(page, testInfo, shotName);
  if (axeStep) await axe(page, testInfo, axeStep, '[role="dialog"]');

  if (close === "escape") {
    await page.keyboard.press("Escape");
  } else {
    await tabTo(page, sheet.getByRole("button", { name: "Done" }));
    await page.keyboard.press("Enter");
  }
  await expect(dialog).toHaveCount(0);
  await expect(opener, "focus returns to the button that opened the sheet").toBeFocused();
  return added;
}

// Native <select>: ArrowDown from the placeholder takes the first team,
// End takes the last.
async function routeByKeyboard(page, label, which) {
  const select = page.getByRole("combobox", { name: `Send ${label} to` });
  await tabTo(page, select);
  await page.keyboard.press(which === "first" ? "Home" : "End");
  if ((await select.inputValue()) === "") await page.keyboard.press("ArrowDown");
  await expect(select, `${label} has a destination`).not.toHaveValue("");
  return select.inputValue();
}

async function openAdvisor(page) {
  await page.goto(pageUrl("/league"));
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("combobox", { name: "Your team" })).toBeVisible({ timeout: 30_000 });
  await hydrated(page);
}

function watchAdvisor(page) {
  const seen = { analyze: [], privateHits: [] };
  page.on("response", async (res) => {
    const u = new URL(res.url());
    if (
      u.pathname.startsWith("/api/data") ||
      u.pathname.startsWith("/api/dynasty-data") ||
      u.pathname.startsWith("/api/trade/")
    ) {
      seen.privateHits.push(u.pathname);
    }
    if (u.pathname.endsWith("/trade-advisor/analyze")) {
      let body = null;
      try {
        body = await res.json();
      } catch {
        /* aborted */
      }
      seen.analyze.push({
        status: res.status(),
        cache: res.headers()["cache-control"] || "",
        body,
      });
    }
  });
  return seen;
}

// Fairness consistency (spec §2 R2): overall is FAIR only when every team is
// FAIR; otherwise NOT FAIR if any team is, else UNABLE.
function expectOverallConsistent(body) {
  const per = body.teams.map((t) => t.result);
  const want = per.includes("NOT_FAIR")
    ? "NOT_FAIR"
    : per.includes("UNABLE_TO_DETERMINE")
      ? "UNABLE_TO_DETERMINE"
      : "FAIR";
  expect(body.overall.result, `overall vs per-team ${per.join(",")}`).toBe(want);
}

// ── tests ────────────────────────────────────────────────────────────────
const LIVE = process.env.E2E_ADVISOR_E2E === "1";

// Registered only against a stack that serves the advisor (see header).
if (LIVE)
  test.describe("Brisket Trade Advisor — keyboard-only live flows + a11y", () => {
    for (const n of [2, 3, 4]) {
      test(`keyboard-only ${n}-team trade: build, route, review, analyze, every perspective, edit, new trade, start over`, async ({
        page,
      }, testInfo) => {
        test.setTimeout(300_000);
        const problems = guard(page);
        const seen = watchAdvisor(page);
        const step = (k, name) => `${n}team-${String(k).padStart(2, "0")}-${name}`;

        await openAdvisor(page);
        await shot(page, testInfo, step(1, "landing"));
        await axe(page, testInfo, "landing");

        // 1. Your team, by keyboard from the top of the page.
        await page.locator("body").focus();
        await comboChoose(page, "Your team", 0);
        await expect(
          page.getByRole("heading", { name: /Select (trade partner|the other teams)/ }),
        ).toBeVisible({ timeout: 30_000 });
        await hydrated(page);

        // 2. Team count + partners.
        if (n > 2) await chooseCountByKeyboard(page, n);
        for (let i = 1; i < n; i += 1) await comboChoose(page, SLOTS[i], i);
        await shot(page, testInfo, step(2, "teams"));
        await axe(page, testInfo, "teams-chosen");

        // 3. Several assets per team; team 1 also a pick.  Alternate Done /
        // Escape so both close paths prove focus return.
        const labels = [];
        for (let i = 0; i < n; i += 1) {
          labels.push(
            await addAssetsByKeyboard(page, testInfo, i, {
              players: i === 0 && n > 2 ? 3 : 2,
              pick: i === 1,
              close: i % 2 ? "escape" : "done",
              shotName: i === 1 ? step(3, "asset-sheet") : undefined,
              axeStep: i === 1 ? "asset-sheet" : undefined,
            }),
          );
        }

        // 4. Destinations (3+ teams): first asset → first team, rest → last.
        const analyze = page.getByRole("button", { name: "Analyze trade" });
        if (n > 2) {
          await expect(analyze, "unrouted trade cannot be analyzed").toBeDisabled();
          await expect(page.getByRole("list", { name: "Before you can analyze" })).toBeVisible();
          for (const team of labels) {
            for (let j = 0; j < team.length; j += 1)
              await routeByKeyboard(page, team[j], j === 0 ? "first" : "last");
          }
        }
        // 5. Review: every leg appears in the summary.
        const summary = page.getByTestId("advisor-summary");
        for (const team of labels) for (const l of team) await expect(summary).toContainText(l);
        await expect(analyze).toBeEnabled();
        await noHorizontalScroll(page);
        await shot(page, testInfo, step(4, "review"));
        await axe(page, testInfo, "review");

        // 6. Analyze by keyboard; focus moves to the result heading.
        await tabTo(page, analyze);
        await page.keyboard.press("Enter");
        const result = page.getByTestId("advisor-result");
        await expect(result).toBeVisible({ timeout: 60_000 });
        await expect(page.getByRole("heading", { name: "Is this trade fair?" })).toBeFocused();
        const overall = (await result.getByTestId("advisor-overall-label").textContent()).trim();
        expect(RESULTS).toContain(overall);
        await expect(result.getByTestId("advisor-team-results").getByRole("listitem")).toHaveCount(
          n,
        );
        await expect(result).not.toContainText(FORBIDDEN);
        await expect(page.getByRole("status").filter({ hasText: overall })).toHaveCount(1);
        await noHorizontalScroll(page);
        await shot(page, testInfo, step(5, "result"));
        await axe(page, testInfo, "result");
        expect(seen.analyze).toHaveLength(1);
        expect(seen.analyze[0].status).toBe(200);
        expect(seen.analyze[0].cache).toMatch(/no-store/);
        expect(seen.analyze[0].body.teams).toHaveLength(n);
        expectOverallConsistent(seen.analyze[0].body);
        // Enum-only record of what the real engine answered (value-free).
        fs.writeFileSync(
          shotPath(testInfo, step(5, "result")).replace(/\.png$/, ".json"),
          JSON.stringify({
            overall: seen.analyze[0].body.overall.result,
            teams: seen.analyze[0].body.teams.map((t) => [t.rosterId, t.result, t.reasonCode]),
          }),
        );

        // 7. Perspective: Tabs arrows, every team, no new request.
        const tabs = result.getByRole("tab");
        await expect(tabs).toHaveCount(n);
        await tabTo(page, result.locator('[role="tab"][aria-selected="true"]'));
        for (let i = 0; i < n; i += 1) {
          const sel = result.locator('[role="tab"][aria-selected="true"]');
          await expect(sel).toBeFocused();
          const panel = result.getByTestId("advisor-team-view");
          await expect(panel).toHaveAttribute(
            "aria-labelledby",
            (await sel.getAttribute("id")) || "",
          );
          expect(TEAM_LABELS).toContain(
            (await result.getByTestId("advisor-team-verdict-label").textContent()).trim(),
          );
          await shot(page, testInfo, step(6, `perspective-${i + 1}`));
          if (i === 0 || i === n - 1) await axe(page, testInfo, `perspective-${i + 1}`);
          await page.keyboard.press("ArrowRight");
        }
        expect(seen.analyze, "perspective switch sends nothing").toHaveLength(1);

        // 8. Edit by keyboard: legs intact, focus not stranded; remove one
        // asset, then re-analyze the edited trade.
        await tabTo(page, result.getByRole("button", { name: "Edit trade" }));
        await page.keyboard.press("Enter");
        await expect(page.getByTestId("advisor-panel-0")).toContainText(labels[0][0]);
        await expectFocusOn(page, page.getByRole("heading", { name: /Build your trade/ }), "after Edit trade");
        await shot(page, testInfo, step(7, "edit"));
        // Remove your team's last asset: it was routed to the last team,
        // which also receives from every other team, so every team still both
        // sends and receives and the edited trade is analyzable at once.
        const removed = labels[0][labels[0].length - 1];
        const removeBtn = page.getByRole("button", { name: `Remove ${removed}` });
        await tabTo(page, removeBtn);
        await page.keyboard.press("Enter");
        await expect(page.getByTestId("advisor-panel-0")).not.toContainText(removed);
        // Focus steps back to the previous asset's Remove in the same team.
        await expectFocusOn(
          page,
          page.getByRole("button", { name: `Remove ${labels[0][labels[0].length - 2]}` }),
          "after Remove",
        );
        await expect(analyze).toBeEnabled();
        await tabTo(page, analyze);
        {
          await page.keyboard.press("Enter");
          await expect(result).toBeVisible({ timeout: 60_000 });
          await expect(page.getByRole("heading", { name: "Is this trade fair?" })).toBeFocused();
          expect(seen.analyze).toHaveLength(2);
          expectOverallConsistent(seen.analyze[1].body);
          expect(seen.analyze[1].body.trade.map((l) => l.id)).toHaveLength(
            labels.flat().length - 1,
          );
          await shot(page, testInfo, step(8, "reanalyzed"));
          // 9. New trade keeps the teams, clears the assets.
          await tabTo(page, result.getByRole("button", { name: "New trade" }));
          await page.keyboard.press("Enter");
          await expect(page.getByTestId("advisor-panel-0")).toContainText("Nothing added yet.");
          await expectFocusOn(page, page.getByRole("heading", { name: /Build your trade/ }), "after New trade");
          await shot(page, testInfo, step(9, "new-trade"));
        }
        // 10. Start over (from a result) clears everything.  Back to two
        // teams first, then one asset each.
        if (n > 2) await chooseCountByKeyboard(page, 2);
        await addAssetsByKeyboard(page, testInfo, 0, { players: 1, pick: false });
        await addAssetsByKeyboard(page, testInfo, 1, { players: 1, pick: false });
        await tabTo(page, analyze);
        await expect(analyze).toBeEnabled();
        await page.keyboard.press("Enter");
        await expect(result).toBeVisible({ timeout: 60_000 });
        await tabTo(page, result.getByRole("button", { name: "Start over" }));
        await page.keyboard.press("Enter");
        await expect(page.getByRole("combobox", { name: "Your team" })).toHaveValue("");
        await expectFocusOn(page, page.getByRole("heading", { name: /Which team is yours\?/ }), "after Start over");
        await shot(page, testInfo, step(10, "start-over"));

        expect(seen.privateHits, "no private endpoint touched").toEqual([]);
        expect(problems, "hydration / page errors").toEqual([]);
      });
    }

    test("error recovery by keyboard: network failure and 500 show retry; Try again reaches the real answer", async ({
      page,
    }, testInfo) => {
      test.setTimeout(240_000);
      const problems = guard(page);
      let calls = 0;
      await page.route("**/api/public/league/trade-advisor/analyze", async (route) => {
        calls += 1;
        if (calls === 1) return route.abort("failed");
        if (calls === 2) {
          return route.fulfill({
            status: 500,
            contentType: "text/html",
            body: "<html>Internal Server Error</html>",
          });
        }
        return route.continue();
      });
      await openAdvisor(page);
      await page.locator("body").focus();
      await comboChoose(page, "Your team", 0);
      await comboChoose(page, "Trade partner", 1);
      await addAssetsByKeyboard(page, testInfo, 0, { players: 2, pick: false });
      await addAssetsByKeyboard(page, testInfo, 1, { players: 1, pick: true, close: "escape" });
      const analyze = page.getByRole("button", { name: "Analyze trade" });

      for (const fault of ["network", "500"]) {
        await tabTo(page, analyze);
        await page.keyboard.press("Enter");
        const banner = page.getByText("No answer from the trade advisor");
        await expect(banner, `retry banner after ${fault}`).toBeVisible({ timeout: 30_000 });
        await expect(page.getByTestId("advisor-result")).toHaveCount(0);
        // The trade is intact and nothing leaked from the fault body.
        await expect(page.getByTestId("advisor-panel-0").getByRole("listitem")).toHaveCount(2);
        await expect(page.getByTestId("trade-advisor")).not.toContainText(
          /Internal Server Error|Traceback|stack/i,
        );
        await shot(page, testInfo, `error-${fault}`);
        await axe(page, testInfo, `error-${fault}`);
        if (fault === "500") {
          // Try again from the banner (keyboard) — the third call is real.
          await tabTo(page, page.getByRole("button", { name: "Try again" }));
          await page.keyboard.press("Enter");
        }
      }
      const result = page.getByTestId("advisor-result");
      await expect(result).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole("heading", { name: "Is this trade fair?" })).toBeFocused();
      expect(RESULTS).toContain(
        (await result.getByTestId("advisor-overall-label").textContent()).trim(),
      );
      await expect(page.getByText("No answer from the trade advisor")).toHaveCount(0);
      expect(calls).toBe(3);
      await shot(page, testInfo, "error-recovered");
      expect(problems).toEqual([]);
    });

    test("asset list failure recovers in the sheet; the sheet's Try again is keyboard-reachable", async ({
      page,
    }, testInfo) => {
      const problems = guard(page);
      let failed = 0;
      await page.route("**/api/public/league/trade-advisor/teams/*/assets?*", async (route) => {
        if (failed === 0) {
          failed += 1;
          return route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({
              status: "error",
              reason: "not_ready",
              message: "The league's data is still loading. Try again in a minute.",
            }),
          });
        }
        return route.continue();
      });
      await openAdvisor(page);
      await page.locator("body").focus();
      await comboChoose(page, "Your team", 0);
      const opener = page
        .getByTestId("advisor-panel-0")
        .getByRole("button", { name: "+ Add player or pick" });
      await tabTo(page, opener);
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog");
      const alert = dialog.getByRole("alert");
      await expect(alert).toBeVisible({ timeout: 30_000 });
      await shot(page, testInfo, "assets-error");
      await axe(page, testInfo, "assets-error", '[role="dialog"]');
      await tabTo(page, alert.getByRole("button", { name: "Try again" }));
      await page.keyboard.press("Enter");
      await expect(dialog.getByTestId("advisor-asset-list")).toBeVisible({ timeout: 30_000 });
      await page.keyboard.press("Escape");
      await expect(opener).toBeFocused();
      expect(failed).toBe(1);
      expect(problems).toEqual([]);
    });

    test("hydration readiness: SSR team picker is real markup, then interactive with no hydration error", async ({
      page,
      request,
    }) => {
      const problems = guard(page);
      // The server-rendered HTML already carries the team step (not a spinner).
      const html = await (await request.get(pageUrl("/league"))).text();
      expect(html).toContain("Which team is yours?");
      expect(html).not.toMatch(/rankDerivedValue|"value":/);
      await page.goto(pageUrl("/league"));
      await awaitStreamSettled(page);
      await hydrated(page);
      // Interactive: the combobox opens from the keyboard right after readiness.
      const input = page.getByRole("combobox", { name: "Your team" });
      await page.locator("body").focus();
      await tabTo(page, input);
      await page.keyboard.press("ArrowDown");
      await expect(input).toHaveAttribute("aria-expanded", "true");
      await expect(
        page.getByRole("listbox", { name: "Your team" }).getByRole("option").first(),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(input).toHaveAttribute("aria-expanded", "false");
      expect(problems).toEqual([]);
    });
  });
