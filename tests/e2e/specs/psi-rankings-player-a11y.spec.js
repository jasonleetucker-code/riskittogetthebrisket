/**
 * Populated-state accessibility + visual matrix for the two PSI reference
 * routes: /rankings and the Player File (/players/[playerId]).
 *
 * WHY THIS EXISTS
 * ───────────────
 * docs/ui/UI_PARALLEL_LEDGER.md names this as the next safe Lane 6 unit
 * ("populated Rankings/Player File accessibility/visual matrix"), and the
 * implementation contract (§13) is explicit that a scan of a loading
 * skeleton is not accessibility evidence. a11y-axe.spec.js already scans
 * /rankings, but after a fixed 4s sleep with nothing asserting the board
 * had rows — and it never visits the Player File at all. Before this spec
 * no test rendered /players/[playerId] in any form.
 *
 * WHAT "POPULATED" MEANS HERE
 * ───────────────────────────
 * The e2e stack serves the COMMITTED snapshot (exports/latest/, seeded by
 * preflight) — never live production and never a live scrape. Every test
 * below gates on real content before measuring anything:
 *   - the board holds >= 50 rows (gotoRankingsBoard reads aria-rowcount);
 *   - the Player File is reached the way a user reaches it (board name →
 *     quick-view → "Full profile"), and its <h1> is that player's name.
 * No player name is hardcoded: the snapshot refreshes, the structure does
 * not.
 *
 * WHAT IS CHECKED
 * ───────────────
 *   axe WCAG 2.0/2.1 A+AA   zero violations, per populated state (no
 *                           baseline: these are the reference routes)
 *   table semantics         caption-named table, scope="col" on every
 *                           header, aria-sort on exactly the active sort
 *                           column, real <button>s for sortable headers,
 *                           aria-rowcount for the windowed board
 *   keyboard                sort headers reachable with Tab and operable
 *                           with Enter; focus survives the re-sort; the
 *                           quick-view returns focus to its opener; the
 *                           Player File tablist is a roving-tabindex
 *                           widget (Arrow/Home/End)
 *   focus visibility        the focused control paints an outline or ring
 *   mobile (390x844)        no page-level horizontal scroll — only the
 *                           controlled table region may scroll sideways
 *   reduced motion          motion tokens collapse to 0ms and nothing runs
 *                           an infinite animation on the populated page
 *
 * Screenshots are attached as local/CI evidence only. Per the contract
 * (§16) they are NOT production verification, and chart treatment is
 * deliberately out of scope here (#1428 is an owner UI decision).
 */
const { test, expect } = require("../helpers/auth-fixture");
const AxeBuilder = require("@axe-core/playwright").default;
const {
  SEL,
  pageUrl,
  gotoRankingsBoard,
  boardRowCount,
  isMobileProject,
} = require("../helpers/journey");

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

// Each test first waits for the populated board (gotoRankingsBoard budgets
// up to 90s), then runs several axe passes. 240s keeps every declared wait
// below the test's own ceiling (see test_e2e_harness_guards.py).
test.setTimeout(240_000);

// The board's DataTable caption — its accessible name. Anchored on the
// stable leading words so a copy tweak to the column list does not break it.
const BOARD_TABLE_NAME = /^Unified dynasty value board/;

async function scan(page, testInfo, name) {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  await testInfo.attach(`${name}-axe`, {
    body: JSON.stringify(results.violations, null, 2),
    contentType: "application/json",
  });
  expect(
    results.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")),
    })),
    `${name}: populated state must have no WCAG A/AA violations`,
  ).toEqual([]);
}

/**
 * Wait until a re-sorted board has SETTLED before scanning it.
 *
 * /rankings renders rows through `useDeferredValue`. Until the deferred rows
 * catch up (`rowsPending` in app/rankings/page.jsx) the page marks the
 * result count `aria-busy` and dims the whole table panel, headers included,
 * to `opacity: 0.55` — a deliberate, transient "these rows are stale" state.
 * Header text there measures 2.32:1 against the settled 5.63:1
 * (--text-tertiary on --surface-1 over --surface-0, .psi-editorial), so an
 * axe pass that lands inside that window reports color-contrast on every
 * sort header. That was this test's intermittent failure (E2E runs
 * 36132280290, 36160006580, 36208782749). The scan asserts on the settled
 * board the user reads, so wait for the page's own "settled" signals rather
 * than a fixed sleep. The axe rule set is unchanged.
 */
async function waitForSettledBoard(page) {
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            !document.querySelector('[aria-live="polite"][aria-busy="true"]') &&
            ![...document.querySelectorAll('[role="tabpanel"]')].some(
              (el) => el.style.opacity && el.style.opacity !== "1",
            ),
        ),
      { message: "the re-sorted board must settle (no aria-busy count, no dimmed panel)", timeout: 30_000 },
    )
    .toBe(true);
}

async function noPageOverflow(page, label) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(
    sizes.document,
    `${label}: only a controlled table region may scroll horizontally, never the page`,
  ).toBeLessThanOrEqual(sizes.viewport + 1);
}

async function evidence(page, testInfo, name) {
  const file = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: file, animations: "disabled" });
  await testInfo.attach(name, { path: file, contentType: "image/png" });
}

/** True when the currently focused element paints a focus indicator. */
async function focusedHasVisibleIndicator(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return { ok: false, why: "nothing focused" };
    const s = getComputedStyle(el);
    const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0;
    const ring = s.boxShadow && s.boxShadow !== "none";
    return {
      ok: Boolean(outline || ring),
      why: `${el.tagName.toLowerCase()} outline=${s.outlineStyle}/${s.outlineWidth} box-shadow=${s.boxShadow}`,
    };
  });
}

/** Infinite animations still running — the thing reduced motion must stop. */
async function runningInfiniteAnimations(page) {
  return page.evaluate(() =>
    document
      .getAnimations()
      .filter((a) => {
        if (a.playState !== "running") return false;
        const t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : {};
        return t.iterations === Infinity && Number(t.duration) > 0;
      })
      .map((a) => {
        const target = a.effect && a.effect.target;
        return `${a.animationName || a.constructor.name} on ${
          target ? target.tagName.toLowerCase() + "." + String(target.className || "").slice(0, 60) : "?"
        }`;
      }),
  );
}

function boardTable(page) {
  return page.getByRole("table", { name: BOARD_TABLE_NAME });
}

/**
 * Open the Player File for the first player on the board, through the
 * real convergence path (board name → quick-view → "Full profile").
 * Returns { name, href }.
 */
async function openPlayerFileFromBoard(page) {
  await gotoRankingsBoard(page);
  const nameButton = page.locator(SEL.playerName).first();
  const name = (await nameButton.innerText()).trim();
  expect(name.length, "board's first row must carry a player name").toBeGreaterThan(0);
  await nameButton.click();
  const dialog = page.locator(SEL.overlaySheet).first();
  await expect(dialog).toBeVisible();
  const launcher = dialog.getByRole("link", { name: `Open full profile for ${name}` });
  await expect(launcher).toBeVisible();
  const href = await launcher.getAttribute("href");
  expect(href, "quick-view launcher must point at the Player File route").toMatch(/^\/players\/[^/]+$/);
  await launcher.click();
  await page.waitForURL((url) => url.pathname === href, { timeout: 30_000 });
  await expectPlayerFilePopulated(page, name);
  return { name, href };
}

async function expectPlayerFilePopulated(page, name) {
  await expect(page.getByRole("heading", { level: 1, name, exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("tablist", { name: "Player sections" })).toBeVisible();
}

// ── Rankings ─────────────────────────────────────────────────────────────

test.describe("PSI reference a11y matrix: /rankings (populated)", () => {
  test("board table semantics, axe and viewport evidence", async ({ authedPage: page }, testInfo) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await gotoRankingsBoard(page);
    await page.evaluate(() => document.fonts.ready);

    const table = boardTable(page);
    await expect(table).toBeVisible();
    // Windowed board: the true size is published, not just what is mounted.
    expect(await boardRowCount(page)).toBeGreaterThanOrEqual(50);
    expect(Number(await table.getAttribute("aria-rowcount"))).toBeGreaterThan(50);

    // Every header cell is a column header, and exactly one carries aria-sort.
    const headerAudit = await table.evaluate((t) => {
      const ths = [...t.querySelectorAll("thead th")];
      return {
        count: ths.length,
        missingScope: ths.filter((th) => th.getAttribute("scope") !== "col").map((th) => th.textContent.trim()),
        sorted: ths
          .filter((th) => th.hasAttribute("aria-sort"))
          .map((th) => ({ label: th.textContent.trim(), dir: th.getAttribute("aria-sort") })),
        sortButtons: ths.filter((th) => th.querySelector("button.ds-table__sort")).length,
        bodyThs: t.querySelectorAll("tbody th").length,
      };
    });
    expect(headerAudit.count).toBeGreaterThan(3);
    expect(headerAudit.missingScope, "every header must be scope=col").toEqual([]);
    expect(headerAudit.sortButtons, "sortable headers render real buttons").toBeGreaterThan(0);
    expect(headerAudit.sorted, "exactly one column announces the active sort").toHaveLength(1);
    expect(["ascending", "descending"]).toContain(headerAudit.sorted[0].dir);

    await noPageOverflow(page, "/rankings");
    await scan(page, testInfo, "rankings-populated");
    await evidence(page, testInfo, "rankings-populated");

    if (isMobileProject(testInfo)) {
      // The table may be wider than a phone; that width must live in the
      // controlled region, which the user can scroll to reach every column.
      const region = await table.evaluate((t) => {
        const wrap = t.closest(".ds-table-wrap");
        return wrap ? { scroll: wrap.scrollWidth, client: wrap.clientWidth } : null;
      });
      expect(region, "board table must sit inside the ds-table-wrap scroll region").not.toBeNull();
      await noPageOverflow(page, "/rankings after measuring region");
    }
    expect(errors).toEqual([]);
  });

  test("keyboard: sort headers reachable by Tab, operable by Enter, focus stays visible", async ({
    authedPage: page,
  }, testInfo) => {
    await gotoRankingsBoard(page);
    const table = boardTable(page);

    // Start from the board search (keyboard-only from here on) and Tab
    // forward until focus lands on a sortable header button. Bounded, so a
    // header that is unreachable fails instead of looping.
    await page.locator(SEL.searchInput).focus();
    let reached = null;
    for (let i = 0; i < 80 && !reached; i += 1) {
      await page.keyboard.press("Tab");
      reached = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || !el.matches("thead button.ds-table__sort")) return null;
        return el.closest("th").textContent.trim();
      });
    }
    expect(reached, "a sortable column header must be reachable with Tab").not.toBeNull();
    const indicator = await focusedHasVisibleIndicator(page);
    expect(indicator.ok, `focused sort header needs a visible focus indicator (${indicator.why})`).toBe(true);

    await page.keyboard.press("Enter");
    const header = table.locator("thead th", { hasText: reached }).first();
    await expect(header).toHaveAttribute("aria-sort", /ascending|descending/);
    const first = await header.getAttribute("aria-sort");
    // Focus must survive the re-sort (a re-rendered header that drops
    // focus to <body> strands keyboard users at the top of the page).
    const stillOnHeader = await page.evaluate(
      () => !!document.activeElement && document.activeElement.matches("thead button.ds-table__sort"),
    );
    expect(stillOnHeader, "focus must remain on the sort header after sorting").toBe(true);
    await page.keyboard.press("Enter");
    await expect(header).not.toHaveAttribute("aria-sort", first);
    await waitForSettledBoard(page);
    await scan(page, testInfo, "rankings-keyboard-sorted");
  });

  test("keyboard: player quick-view opens from the name and returns focus", async ({
    authedPage: page,
  }, testInfo) => {
    await gotoRankingsBoard(page);
    const opener = page.locator(SEL.playerName).first();
    await opener.focus();
    const indicator = await focusedHasVisibleIndicator(page);
    expect(indicator.ok, `focused player name needs a visible focus indicator (${indicator.why})`).toBe(true);
    await page.keyboard.press("Enter");
    const dialog = page.locator(SEL.overlaySheet).first();
    await expect(dialog).toBeVisible();
    await expect
      .poll(() => dialog.evaluate((d) => d.contains(document.activeElement)), {
        message: "focus must move into the quick-view",
      })
      .toBe(true);
    await scan(page, testInfo, "rankings-quick-view");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(opener).toBeFocused();
  });
});

// ── Player File ──────────────────────────────────────────────────────────

test.describe("PSI reference a11y matrix: /players/[playerId] (populated)", () => {
  test("reached from the board: every section passes axe, no page overflow", async ({
    authedPage: page,
  }, testInfo) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const { name } = await openPlayerFileFromBoard(page);

    // A player the board ranks first is priced: the headline tile must show
    // a number, not the honest "not priced" missing state.
    await expect(page.getByText("Our Value", { exact: true })).toBeVisible();
    await expect(page.getByText("not priced", { exact: true })).toHaveCount(0);

    const tablist = page.getByRole("tablist", { name: "Player sections" });
    const tabs = tablist.getByRole("tab");
    const labels = await tabs.allInnerTexts();
    expect(labels.map((l) => l.trim())).toEqual(["Overview", "Market", "Trades", "Performance", "Intel"]);

    for (const label of labels.map((l) => l.trim())) {
      const tab = tablist.getByRole("tab", { name: label, exact: true });
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected", "true");
      const panelId = await tab.getAttribute("aria-controls");
      const panel = page.locator(`[id="${panelId}"]`);
      await expect(panel).toBeVisible();
      await expect(panel).toHaveAttribute("role", "tabpanel");
      await expect(panel).toHaveAttribute("aria-labelledby", await tab.getAttribute("id"));
      // Section content arrives from its own requests; measure it settled,
      // not mid-flight. A route that never goes idle is not a failure here.
      await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
      await noPageOverflow(page, `Player File / ${label}`);
      await scan(page, testInfo, `player-file-${label.toLowerCase()}`);
      if (label === "Overview" || label === "Market") {
        await evidence(page, testInfo, `player-file-${label.toLowerCase()}`);
      }
    }
    await testInfo.attach("measurement-context", {
      body: JSON.stringify(
        {
          sha: process.env.EVIDENCE_SHA || "unrecorded",
          origin: page.url(),
          player: name,
          viewport: page.viewportSize(),
          data: "committed snapshot (exports/latest) — not production",
        },
        null,
        2,
      ),
      contentType: "application/json",
    });
    expect(errors).toEqual([]);
  });

  test("keyboard: roving-tabindex tablist and visible focus", async ({ authedPage: page }, testInfo) => {
    await openPlayerFileFromBoard(page);
    const tablist = page.getByRole("tablist", { name: "Player sections" });
    const tab = (label) => tablist.getByRole("tab", { name: label, exact: true });

    // One tab stop: only the selected tab is in the tab order.
    const tabIndexes = await tablist
      .getByRole("tab")
      .evaluateAll((els) => els.map((e) => e.getAttribute("tabindex")));
    expect(tabIndexes.filter((t) => t === "0")).toHaveLength(1);

    // Reach the tablist from the keyboard. Getting here took mouse clicks
    // (board name → quick-view → Full profile), and after a pointer
    // interaction Chromium does not paint :focus-visible for a scripted
    // focus() — so a scripted focus would measure the heuristic, not the
    // style. Tab forward (bounded) until the one tab stop is reached.
    let onTab = false;
    for (let i = 0; i < 40 && !onTab; i += 1) {
      await page.keyboard.press("Tab");
      onTab = await page.evaluate(() => document.activeElement?.getAttribute("role") === "tab");
    }
    expect(onTab, "the Player sections tablist must be reachable with Tab").toBe(true);
    await expect(tab("Overview")).toBeFocused();
    const indicator = await focusedHasVisibleIndicator(page);
    expect(indicator.ok, `focused tab needs a visible focus indicator (${indicator.why})`).toBe(true);

    await page.keyboard.press("ArrowRight");
    await expect(tab("Market")).toBeFocused();
    await expect(tab("Market")).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("End");
    await expect(tab("Intel")).toBeFocused();
    await expect(tab("Intel")).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Home");
    await expect(tab("Overview")).toBeFocused();
    await expect(tab("Overview")).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowLeft");
    await expect(tab("Intel")).toBeFocused();
  });

  test("direct deep link renders the same populated file", async ({ authedPage: page }, testInfo) => {
    const { name, href } = await openPlayerFileFromBoard(page);
    // Cold load of the same URL — the path a shared link takes.
    await page.goto(pageUrl(href), { waitUntil: "domcontentloaded" });
    await expectPlayerFilePopulated(page, name);
    await noPageOverflow(page, "Player File deep link");
    await scan(page, testInfo, "player-file-deep-link");
  });
});

// ── Reduced motion, both routes ──────────────────────────────────────────

test("reduced motion: tokens collapse and no infinite animation runs on either reference route", async ({
  authedPage: page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await gotoRankingsBoard(page);
  const motion = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--motion-base").trim(),
  );
  expect(motion, "--motion-base must collapse under prefers-reduced-motion").toMatch(/^0(ms|s)?$/);
  expect(await runningInfiniteAnimations(page), "/rankings under reduced motion").toEqual([]);

  const nameButton = page.locator(SEL.playerName).first();
  const name = (await nameButton.innerText()).trim();
  await nameButton.click();
  const launcher = page
    .locator(SEL.overlaySheet)
    .first()
    .getByRole("link", { name: `Open full profile for ${name}` });
  await launcher.click();
  await expectPlayerFilePopulated(page, name);
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  expect(await runningInfiniteAnimations(page), "Player File under reduced motion").toEqual([]);
  await evidence(page, testInfo, "player-file-reduced-motion");
});
