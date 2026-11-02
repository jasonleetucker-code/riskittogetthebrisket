/**
 * UX navigation audit 2026-11-01 — the real shell, in a real browser.
 *
 * Record: docs/ui/UX_NAVIGATION_AUDIT_2026-11-01.md.  The unit tests pin
 * the nav MODEL (route-inventory.test.js, nav-sections-parity.test.jsx);
 * this spec pins what a person actually meets on a production build:
 *
 *   1. every destination the signed-in shell OFFERS answers (no broken
 *      link, no login bounce, no 404) — read from the live DOM, so a
 *      gated entry the server switched off is simply not offered and not
 *      checked;
 *   2. desktop menus are keyboard operable: Enter opens, ArrowDown moves
 *      into the menu, Escape closes and returns focus to the trigger;
 *   3. the mobile drawer shows the same section groups as the desktop
 *      menu, closes on Escape, and returns focus to Menu;
 *   4. signed-out chrome offers public destinations only, plus Sign in;
 *   5. task journeys from the audit reach their destination in the
 *      measured number of interactions.
 *
 * Runs on desktop-1366 (Chromium), mobile-chromium and mobile-390
 * (WebKit / iPhone 13).  Desktop-only and mobile-only tests check the
 * viewport rather than the project name so a new project inherits them.
 */
const { test, expect } = require("../helpers/auth-fixture");
const AxeBuilder = require("@axe-core/playwright").default;
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");

const isMobile = (page) => (page.viewportSize()?.width ?? 1366) < 768;

async function waitForAuthedChrome(page) {
  // The nav renders nothing until /api/auth/status resolves (TopBar's
  // tri-state guard), so wait for the signed-in chrome before reading it.
  if (isMobile(page)) {
    await expect(page.getByRole("button", { name: "Menu" })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("nav.shell-tabbar a[href='/trade']")).toBeVisible({ timeout: 30_000 });
  } else {
    await expect(page.getByRole("button", { name: "My Team menu" })).toBeVisible({ timeout: 30_000 });
  }
}

async function openDrawer(page) {
  await page.getByRole("button", { name: "Menu" }).click();
  const dialog = page.getByRole("dialog", { name: "Menu" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test.describe("UX nav audit: offered destinations answer", () => {
  test("every signed-in menu destination is a live page (no 404, no login bounce)", async ({
    authedPage,
  }) => {
    test.setTimeout(180_000);
    await authedPage.goto(pageUrl("/more"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);
    await waitForAuthedChrome(authedPage);
    // /more is the site map rendered from the same model as every menu,
    // filtered by the same capability + admin gates — the offer set.
    const hrefs = await authedPage
      .locator("main a.shell-menu-item")
      .evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute("href")))]);
    expect(hrefs.length).toBeGreaterThan(15);
    const failures = [];
    for (const href of hrefs) {
      const res = await authedPage.request.get(pageUrl(href), { maxRedirects: 0 });
      const status = res.status();
      const location = res.headers()["location"] || "";
      if (status >= 400 || location.includes("/login")) {
        failures.push(`${href} -> ${status} ${location}`);
      }
    }
    expect(failures).toEqual([]);
  });
});

/**
 * One test per behaviour, branching on viewport rather than skipping: a
 * test.skip() counts against stack-death-reporter's skip ceiling, and
 * "desktop menu" / "mobile drawer" are the same question (is the one nav
 * model operable here?) asked of two renderings.
 */
test.describe("UX nav audit: menus are operable on each viewport", () => {
  test("desktop: Enter/ArrowDown/Escape; mobile: drawer sections, Escape, focus return, targets", async ({
    authedPage,
  }) => {
    await authedPage.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);
    await waitForAuthedChrome(authedPage);
    const SECTIONS = ["This week", "Roster", "Waivers & FAAB", "Draft & strategy"];

    if (!isMobile(authedPage)) {
      const trigger = authedPage.getByRole("button", { name: "My Team menu" });
      await trigger.focus();
      await authedPage.keyboard.press("Enter");
      const menu = authedPage.getByRole("menu", { name: "My Team" });
      await expect(menu).toBeVisible();
      await expect(trigger).toHaveAttribute("aria-expanded", "true");
      // Section headings are labelled groups (A11Y-02 / NAV-05).
      for (const name of SECTIONS) {
        await expect(menu.getByRole("group", { name })).toBeVisible();
      }
      await authedPage.keyboard.press("ArrowDown");
      await expect(menu.getByRole("menuitem").first()).toBeFocused();
      await authedPage.keyboard.press("Escape");
      await expect(menu).toBeHidden();
      await expect(trigger).toBeFocused();
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      return;
    }

    // Mobile: five tab-bar targets, each at least 44px tall.
    const heights = await authedPage
      .locator("nav.shell-tabbar .shell-tab")
      .evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
    expect(heights.length).toBe(5);
    for (const h of heights) expect(h).toBeGreaterThanOrEqual(44);

    const menuButton = authedPage.getByRole("button", { name: "Menu" });
    const dialog = await openDrawer(authedPage);
    await expect(menuButton).toHaveAttribute("aria-expanded", "true");
    // The SAME section groups as the desktop menu (NAV-05).
    for (const name of SECTIONS) {
      await expect(dialog.getByRole("group", { name })).toBeAttached();
    }
    const overflow = await authedPage.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await authedPage.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(menuButton).toBeFocused();
  });

  test("the OPEN menu (desktop) / drawer (mobile) has no WCAG A/AA violations", async ({
    authedPage,
  }) => {
    // a11y-axe.spec.js scans pages with every menu closed; the menu and
    // drawer only exist in the DOM while open, so they are scanned here.
    await authedPage.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);
    await waitForAuthedChrome(authedPage);
    let include;
    if (isMobile(authedPage)) {
      await openDrawer(authedPage);
      include = '[role="dialog"]';
    } else {
      await authedPage.getByRole("button", { name: "My Team menu" }).click();
      await expect(authedPage.getByRole("menu", { name: "My Team" })).toBeVisible();
      include = '[role="menu"]';
    }
    const results = await new AxeBuilder({ page: authedPage })
      .include(include)
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map((v) => `${v.id} x${v.nodes.length}`),
      "axe violations inside the open nav surface",
    ).toEqual([]);
  });

  test("the skip link is the first focusable and moves to main", async ({ authedPage }) => {
    await authedPage.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);
    await waitForAuthedChrome(authedPage);
    await authedPage.evaluate(() => document.activeElement?.blur());
    await authedPage.keyboard.press("Tab");
    const skip = authedPage.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await authedPage.keyboard.press("Enter");
    await expect(authedPage).toHaveURL(/#main$/);
  });
});

test.describe("UX nav audit: signed-out chrome", () => {
  test("offers public destinations only, plus Sign in", async ({ page }) => {
    await page.goto(pageUrl("/league"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(page);
    const privateHrefs = [
      "/rankings",
      "/trade",
      "/waivers",
      "/waiver-advisor",
      "/game-day",
      "/rosters",
      "/league/insider-trading",
      "/settings",
      "/admin",
    ];
    if (isMobile(page)) {
      await expect(page.locator("nav.shell-tabbar a[href='/login']")).toBeVisible({ timeout: 30_000 });
      const dialog = await openDrawer(page);
      for (const href of privateHrefs) {
        await expect(dialog.locator(`a[href="${href}"]`)).toHaveCount(0);
      }
      await expect(dialog.locator('a[href="/league/activity"]')).toBeVisible();
    } else {
      await expect(page.locator("header").getByRole("link", { name: "Sign in" })).toBeVisible({
        timeout: 30_000,
      });
      for (const href of privateHrefs) {
        await expect(page.locator(`header a[href="${href}"]`)).toHaveCount(0);
      }
    }
  });
});

/**
 * Task journeys (audit §6).  Each records the interactions a person needs
 * from the dashboard; the audit's table is the human-readable copy.
 */
test.describe("UX nav audit: task journeys", () => {
  async function viaMenu(page, groupName, itemName) {
    if (isMobile(page)) {
      const dialog = await openDrawer(page);
      await dialog.getByRole("link", { name: new RegExp(`^${itemName}`) }).first().click();
    } else {
      await page.getByRole("button", { name: `${groupName} menu` }).click();
      await page
        .getByRole("menu", { name: groupName })
        .getByRole("menuitem", { name: new RegExp(`^${itemName}`) })
        .click();
    }
  }

  const JOURNEYS = [
    { id: "J1 roster strength", group: "My Team", item: "Team Strength", url: /\/rosters$/, h1: "Team Strength" },
    { id: "J4 evaluate a trade", group: "Trades", item: "Trade Calculator", url: /\/trade$/, h1: "Trade Calculator" },
    { id: "J6 compare values", group: "Rankings", item: "Compare Players", url: /\/players\/compare/, h1: "Compare Players" },
    { id: "J8 playoff chances", group: "League", item: "Hub", url: /\/league$/, h1: null },
    { id: "J9 rookie draft prep", group: "My Team", item: "Draft Board", url: /\/draft$/, h1: null },
    { id: "J11 what changed", group: "League", item: "Activity", url: /\/league\/activity$/, h1: null },
  ];

  for (const j of JOURNEYS) {
    test(`${j.id}: dashboard -> ${j.group} -> ${j.item}`, async ({ authedPage }) => {
      await authedPage.goto(pageUrl("/"), { waitUntil: "domcontentloaded" });
      await waitForAuthedChrome(authedPage);
      await viaMenu(authedPage, j.group, j.item);
      await expect(authedPage).toHaveURL(j.url, { timeout: 30_000 });
      if (j.h1) {
        await expect(authedPage.locator("h1").first()).toHaveText(j.h1, { timeout: 30_000 });
      }
    });
  }

  test("J2 stream an LB: the waiver page links to Weekly IDP Streaming when it is on", async ({
    authedPage,
  }) => {
    await authedPage.goto(pageUrl("/waivers"), { waitUntil: "domcontentloaded" });
    await waitForAuthedChrome(authedPage);
    const available = await authedPage.evaluate(async () => {
      const body = await (await fetch("/api/auth/status")).json();
      return body?.features?.idpStreaming?.available === true;
    });
    const related = authedPage.getByRole("navigation", { name: "Related pages" });
    const link = related.getByRole("link", { name: "Weekly IDP Streaming" });
    if (available) {
      await expect(link).toBeVisible({ timeout: 30_000 });
      await link.click();
      await expect(authedPage).toHaveURL(/\/waiver-advisor\?mode=streaming/);
    } else {
      // Capability off: the contextual link must not offer a dead page.
      await expect(authedPage.locator('a[href="/waiver-advisor?mode=streaming"]')).toHaveCount(0);
    }
  });

  test("J10 research a defender: /rankings/lb lands on the LB-filtered board", async ({
    authedPage,
  }) => {
    await authedPage.goto(pageUrl("/rankings/lb"), { waitUntil: "domcontentloaded" });
    await expect(authedPage).toHaveURL(/\/rankings\?pos=LB/i, { timeout: 30_000 });
  });
});
