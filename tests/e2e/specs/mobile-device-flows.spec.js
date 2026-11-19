/**
 * STAB-9 (owner directive 2026-11-19) — the parts of the real-device checks
 * that browser automation CAN prove, on the phone projects.
 *
 * THIS IS EMULATION, NOT A PHYSICAL DEVICE.  `mobile-chromium` is Chromium with
 * a phone viewport and touch events; `mobile-390` is Playwright's WebKit with
 * the iPhone 13 device descriptor.  Neither is an iPhone: no real touch
 * hardware, no iOS Safari chrome, no VoiceOver, no home-screen PWA, no iOS
 * service-worker lifecycle.  What passing here means is spelled out per test;
 * what it does NOT mean is the checklist in
 * docs/qa/REAL_DEVICE_CHECKLIST_2026-11-19.md.
 *
 * Tagged @mobile-only: filtered out of desktop-1366 by the project's
 * grepInvert (never test.skip()ped, so it is not counted as a skipped test).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, SEL } = require("../helpers/journey");

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

// ── waivers: the manual add/drop pickers ─────────────────────────────────

/** Open /waivers on a real team (the e2e user has none selected by default). */
async function openWaiversWithTeam(page) {
  await page.goto(pageUrl("/waivers"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  // The team switcher lives in the phone top bar; choose the first team.
  const toggle = page.locator(".team-switcher-toggle:visible").first();
  await expect(toggle).toBeVisible({ timeout: 60_000 });
  await toggle.tap();
  const option = page.locator('.team-switcher-menu [role="option"]').first();
  await expect(option).toBeVisible();
  await option.tap();
  await expect(page.getByRole("region", { name: "Manual add/drop calculator" })).toBeVisible({
    timeout: 60_000,
  });
}

function pickers(page) {
  const calc = page.getByRole("region", { name: "Manual add/drop calculator" });
  return {
    calc,
    drop: calc.getByRole("combobox", { name: /Search drop candidates/i }),
    add: calc.getByRole("combobox", { name: /Search add candidates/i }),
  };
}

test.describe("waivers add/drop pickers on a phone @mobile-only", () => {
  test("a TAP on an option picks it; the list closes and the pick is announced by name", async ({
    authedPage: page,
  }) => {
    await openWaiversWithTeam(page);
    const { calc, drop } = pickers(page);
    await drop.tap();
    const listbox = calc.getByRole("listbox", { name: /Drop candidates/i });
    await expect(listbox).toBeVisible();
    const options = listbox.getByRole("option");
    expect(await options.count(), "the picker offers candidates").toBeGreaterThan(0);
    const first = options.first();
    const name = (await first.locator(".trade-side-search-result-name").innerText()).trim();
    await first.tap();
    // The list is gone, the search box is replaced by the chosen asset, and
    // focus moved to that side's clear button (never dropped on <body>).
    await expect(listbox).toHaveCount(0);
    await expect(calc.locator("[data-picker-clear]").first()).toBeFocused();
    await expect(calc.getByText(name, { exact: false }).first()).toBeVisible();
  });

  test("a SCROLL gesture that starts on an option does not pick it (the #2223 regression)", async ({
    authedPage: page,
  }) => {
    await openWaiversWithTeam(page);
    const { calc, add } = pickers(page);
    await add.tap();
    const listbox = calc.getByRole("listbox", { name: /Add candidates/i });
    await expect(listbox).toBeVisible();
    // Record where touches begin, so the test proves the swipe really
    // started ON an option (otherwise "nothing was picked" proves nothing).
    await page.evaluate(() => {
      window.__touchStarts = [];
      document.addEventListener(
        "touchstart",
        (e) => window.__touchStarts.push(!!(e.target instanceof Element && e.target.closest('[role="option"]'))),
        { capture: true, passive: true },
      );
    });
    const target = await listbox.getByRole("option").first().boundingBox();
    expect(target).not.toBeNull();
    // Chromium: a real CDP touch drag (touchstart, touchmove, touchend), not
    // a tap.  WebKit has no CDP, so there the same sequence is dispatched from
    // the page.  WebKit exposes ``Touch`` but forbids ``new Touch()`` ("Illegal
    // constructor", measured on the mobile-390 project), so the page tries real
    // Touch objects first and otherwise dispatches plain touchstart / touchmove
    // / touchend events.  That still exercises the #2223 regression path:
    // React's onTouchStart is wired to the native "touchstart" event whatever
    // its class, and the defect was a pick on touchstart with no click.
    // Synthetic events never synthesize a click, so nothing here can pick by
    // accident.
    const cdp = await page.context().newCDPSession(page).catch(() => null);
    const x = Math.round(target.x + target.width / 2);
    const y = Math.round(target.y + target.height / 2);
    let method = "cdp-scroll-gesture";
    if (cdp) {
      await cdp.send("Input.synthesizeScrollGesture", {
        x,
        y,
        yDistance: -80,
        gestureSourceType: "touch",
      });
    } else {
      method = await page.evaluate(
        ([px, py]) => {
          const el = document.elementFromPoint(px, py);
          const steps = [
            ["touchstart", 0],
            ["touchmove", -40],
            ["touchend", -80],
          ];
          try {
            const touch = (dy) => new Touch({ identifier: 1, target: el, clientX: px, clientY: py + dy });
            const events = steps.map(
              ([type, dy]) =>
                new TouchEvent(type, {
                  bubbles: true,
                  cancelable: true,
                  touches: type === "touchend" ? [] : [touch(dy)],
                  changedTouches: [touch(dy)],
                }),
            );
            events.forEach((e) => el.dispatchEvent(e));
            return "touch-objects";
          } catch {
            steps.forEach(([type]) => el.dispatchEvent(new Event(type, { bubbles: true, cancelable: true })));
            return "plain-touch-events";
          }
        },
        [x, y],
      );
    }
    test.info().annotations.push({ type: "swipe-synthesis", description: method });
    expect(await page.evaluate(() => window.__touchStarts), "the swipe began on an option").toContain(true);
    await expect(listbox, "scrolling must not choose a candidate").toBeVisible();
    await expect(calc.locator("[data-picker-clear]")).toHaveCount(0);
  });

  test("keyboard: type, ArrowDown to an option, Enter picks it", async ({ authedPage: page }) => {
    await openWaiversWithTeam(page);
    const { calc, drop } = pickers(page);
    await drop.focus();
    await page.keyboard.press("ArrowDown");
    const listbox = calc.getByRole("listbox", { name: /Drop candidates/i });
    await expect(listbox).toBeVisible();
    await expect(drop).toHaveAttribute("aria-expanded", "true");
    const activeId = await drop.getAttribute("aria-activedescendant");
    expect(activeId, "the input points at the active option").toBeTruthy();
    const active = page.locator(`#${activeId}`);
    await expect(active).toHaveAttribute("role", "option");
    await expect(active).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Enter");
    await expect(listbox).toHaveCount(0);
    await expect(calc.locator("[data-picker-clear]").first()).toBeFocused();
  });

  test("accessible names and roles — a proxy for what VoiceOver reads (NOT VoiceOver)", async ({
    authedPage: page,
  }) => {
    await openWaiversWithTeam(page);
    const { calc, drop, add } = pickers(page);
    // Each picker is a named combobox bound to a named listbox.
    for (const [input, which] of [
      [drop, "Drop"],
      [add, "Add"],
    ]) {
      await input.tap();
      await expect(input).toHaveAttribute("aria-autocomplete", "list");
      await expect(input).toHaveAttribute("aria-expanded", "true");
      const listId = await input.getAttribute("aria-controls");
      expect(listId, `${which} combobox controls its listbox`).toBeTruthy();
      const listbox = page.locator(`#${listId}`);
      await expect(listbox).toHaveAttribute("role", "listbox");
      expect(await listbox.getAttribute("aria-label")).toMatch(new RegExp(`${which} candidates`, "i"));
      // Every option has role=option, a non-empty accessible name carrying
      // the player, and a selected state — nothing an AT user must guess.
      const options = listbox.getByRole("option");
      const n = await options.count();
      expect(n).toBeGreaterThan(0);
      for (let i = 0; i < n; i += 1) {
        const o = options.nth(i);
        await expect(o).toHaveAttribute("aria-selected", /true|false/);
        const accessible = await o.evaluate((el) => (el.textContent || "").replace(/\s+/g, " ").trim());
        expect(accessible.length, `${which} option ${i} has a name`).toBeGreaterThan(2);
      }
      await page.keyboard.press("Escape");
      await expect(listbox).toHaveCount(0);
    }
    await expect(calc).toBeVisible();
  });
});

// ── service worker: the update path ──────────────────────────────────────
//
// Emulation caveat, stated once: this drives Chromium's / Playwright-WebKit's
// service-worker implementation.  iOS home-screen PWAs add their own
// lifecycle (a waiting SW is not activated until every app tab closes, the
// app is suspended in the background, updates are checked on foreground);
// none of that is reproduced here.  What this DOES prove is the app's half of
// the contract: when a new worker takes control the page reloads once, the
// old caches are evicted, and private API responses are never at rest.

const SW_VERSION_RE = /chaseupside-v(\d+)/;

// Bounded wait for an active worker.  ``navigator.serviceWorker.ready`` never
// settles when nothing activates, which burned the whole 150 s test budget on
// mobile-390 (E2E run 44519478798) and left no evidence.  This fails in 30 s
// with the registration states instead.
async function waitForActiveWorker(page, timeoutMs = 30_000) {
  const state = await page.evaluate(async (ms) => {
    const outcome = await Promise.race([
      navigator.serviceWorker.ready.then(() => "ready"),
      new Promise((resolve) => setTimeout(() => resolve("timeout"), ms)),
    ]);
    const regs = await navigator.serviceWorker.getRegistrations();
    return {
      outcome,
      controlled: Boolean(navigator.serviceWorker.controller),
      registrations: regs.map((r) => ({
        scope: r.scope,
        script: (r.active || r.waiting || r.installing || {}).scriptURL || null,
        installing: r.installing ? r.installing.state : null,
        waiting: r.waiting ? r.waiting.state : null,
        active: r.active ? r.active.state : null,
      })),
    };
  }, timeoutMs);
  expect(state.outcome, `no service worker became active: ${JSON.stringify(state)}`).toBe("ready");
}

test.describe("service worker update path @mobile-only", () => {
  test("with the worker in control: private API responses are never at rest, and an offline API call is a network failure, not HTML", async ({
    authedPage: page,
    context,
  }) => {
    await page.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    if (!(await page.evaluate(() => "serviceWorker" in navigator))) {
      // Recorded as a SKIP (listed in tests/e2e/skip-baseline.json as
      // unsupported-environment), never a silent pass.
      test.skip(true, "this engine exposes no navigator.serviceWorker on http://127.0.0.1");
    }
    await waitForActiveWorker(page);
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect
      .poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 30_000 })
      .toBe(true);
    // The signed-in board makes private API reads through the worker.
    await expect(page.locator("body")).toContainText(/\w/, { timeout: 30_000 });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
    const apiCalls = await page.evaluate(() =>
      performance
        .getEntriesByType("resource")
        .map((e) => new URL(e.name).pathname)
        .filter((p) => p.startsWith("/api/")),
    );
    expect(apiCalls.length, "the page made API reads while the worker controlled it").toBeGreaterThan(0);

    const stored = await page.evaluate(async () => {
      const out = [];
      for (const key of await caches.keys()) {
        const cache = await caches.open(key);
        for (const req of await cache.keys()) out.push(new URL(req.url).pathname);
      }
      return out;
    });
    const atRest = stored.filter(
      (p) =>
        (p.startsWith("/api/") && !p.startsWith("/api/public/league")) ||
        p.startsWith("/api/public/league/trade-advisor"),
    );
    expect(atRest, "no private (or no-store) API response is held in CacheStorage").toEqual([]);

    // Offline: an API read must fail as a network error.  The pre-v11 worker
    // answered it with the homepage HTML, which the client then tried to parse.
    await context.setOffline(true);
    const offline = await page.evaluate(async () => {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        return { threw: false, type: res.headers.get("content-type") || "", text: (await res.text()).slice(0, 200) };
      } catch (err) {
        return { threw: true, type: "", text: String(err) };
      }
    });
    await context.setOffline(false);
    const looksLikeHtml = /<!doctype html|<html/i.test(offline.text) || /text\/html/i.test(offline.type);
    expect(looksLikeHtml, `offline API read answered ${JSON.stringify(offline)}`).toBe(false);
  });

  test("a new worker takes control, the page reloads once, and caches from older versions are evicted", async ({
    page,
  }) => {
    await page.goto(pageUrl("/login"), { waitUntil: "domcontentloaded" });
    if (!(await page.evaluate(() => "serviceWorker" in navigator))) {
      // Recorded as a SKIP (listed in tests/e2e/skip-baseline.json as
      // unsupported-environment), never a silent pass.
      test.skip(true, "this engine exposes no navigator.serviceWorker on http://127.0.0.1");
    }
    await waitForActiveWorker(page);
    // Reload so the page is SW-controlled (the registrar only wires its
    // controllerchange reload for an already-controlled page).
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect
      .poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 30_000 })
      .toBe(true);
    const before = await page.evaluate(() => caches.keys());
    const current = before.map((k) => SW_VERSION_RE.exec(k)).find(Boolean);
    expect(current, `a versioned cache exists before the update (${before.join(", ")})`).toBeTruthy();
    const stale = `chaseupside-v${Number(current[1]) - 1}-runtime`;
    // What a device that last ran the previous build still holds.
    await page.evaluate(async (name) => {
      const c = await caches.open(name);
      await c.put("/stale-from-previous-build", new Response("old", { status: 200 }));
    }, stale);
    expect(await page.evaluate(() => caches.keys())).toContain(stale);

    // "Deploy": Playwright cannot swap the bytes of /sw.js (the browser's own
    // update fetch is not interceptable), so register the SAME worker code
    // under a new script URL for the same scope.  The browser treats that as a
    // new worker version: install -> skipWaiting -> activate -> claim ->
    // `controllerchange` in the controlled page, which is the event
    // ServiceWorkerRegistrar reloads on.  The activate handler is the real one.
    // Let the page's own registrar finish registering "/sw.js" first: a
    // register() of a different URL that lands BEFORE it is superseded by it
    // (same script as the active worker = no update) and nothing activates.
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(1500);
    let navigations = 0;
    page.on("load", () => {
      navigations += 1;
    });
    const reloaded = page.waitForEvent("load", { timeout: 60_000 });
    await page.evaluate(() => navigator.serviceWorker.register("/sw.js?deploy=2", { scope: "/" }).then(() => true));
    await reloaded;

    // The reloaded page is controlled and the previous build's cache is gone;
    // this build's caches remain.
    await expect
      .poll(() => page.evaluate(() => caches.keys()), { timeout: 30_000, message: "old caches evicted on activate" })
      .not.toContain(stale);
    const after = await page.evaluate(() => caches.keys());
    expect(after.some((k) => k.startsWith(`chaseupside-v${current[1]}-`))).toBe(true);
    await expect
      .poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 30_000 })
      .toBe(true);
    // The reload happened, and the app settles: with no further new worker
    // there is no further reload (no reload loop).  Test artifact, not app
    // behaviour: every page load re-registers the real "/sw.js", which flips
    // this simulated "/sw.js?deploy=2" registration back and costs one more
    // reload; in production the URL never changes between loads.  So wait
    // for the count to stop moving, then require it to stay still.
    expect(navigations, "the new worker's takeover reloaded the page").toBeGreaterThanOrEqual(1);
    await expect
      .poll(
        async () => {
          const seen = navigations;
          await page.waitForTimeout(2500);
          return navigations === seen;
        },
        { timeout: 45_000, message: "the page stops reloading once the worker is stable" },
      )
      .toBe(true);
    await expect(page.locator("body")).toBeVisible();
    // Hand the next test a NORMAL worker.  Under Playwright, WebKit shares
    // service-worker registrations across browser contexts of one browser, so
    // whatever this test leaves is inherited: the simulated "/sw.js?deploy=2"
    // left in place, or an unregistered (empty) registration, made the next
    // SW test on mobile-390 wait forever (E2E 44519478798 and 44533702571,
    // diagnostics: one registration at "/", no installing/waiting/active
    // worker), while a fresh browser always passed.  Every other test leaves
    // an active "/sw.js", so restore exactly that.  Production never registers
    // a second script URL.
    await page
      .evaluate(() => navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(() => true))
      .catch(() => {});
    // Best effort, recorded either way: this restores shared browser state
    // for later tests; it is not part of what this test proves.
    let restored = null;
    for (let i = 0; i < 30 && restored !== "/sw.js"; i += 1) {
      restored = await page
        .evaluate(async () => {
          const reg = await navigator.serviceWorker.getRegistration("/");
          const url = reg && reg.active ? new URL(reg.active.scriptURL) : null;
          return url ? `${url.pathname}${url.search}` : null;
        })
        .catch(() => null);
      if (restored !== "/sw.js") await page.waitForTimeout(1000);
    }
    test.info().annotations.push({ type: "sw-restored", description: String(restored) });
  });
});

// ── a failed request is a classified, retryable state ────────────────────
//
// The board's base-contract request (/api/dynasty-data) is intercepted, so
// this proves the app's handling of a dead / hung network, not anything about
// iOS's network stack or its offline behaviour.

const CONTRACT_URL = (url) => url.pathname === "/api/dynasty-data";

test.describe("failed request -> FailureState -> Try again @mobile-only", () => {
  test("a dropped connection shows a classified failure with a working Try again", async ({
    authedPage: page,
  }) => {
    let failing = true;
    await page.route(CONTRACT_URL, (route) =>
      failing ? route.abort("connectionfailed") : route.continue(),
    );
    await page.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    const failure = page.getByRole("alert").filter({ hasText: /Could not reach the server/i });
    await expect(failure, "an unreachable server is named as such").toBeVisible({ timeout: 60_000 });
    await expect(page.locator(SEL.boardRow), "no stale or fabricated rows while failed").toHaveCount(0);
    failing = false;
    const retry = failure.getByRole("button", { name: "Try again" });
    await expect(retry).toBeVisible();
    await retry.tap();
    await expect(page.locator(SEL.boardRow).first()).toBeVisible({ timeout: 60_000 });
    await expect(failure).toHaveCount(0);
  });

  test("a hung request hits the 25 s contract deadline and says so; Try again then succeeds", async ({
    authedPage: page,
  }) => {
    test.setTimeout(180_000);
    let hanging = true;
    await page.route(CONTRACT_URL, (route) => {
      if (hanging) return; // never answered: the client's own deadline must end it
      return route.continue();
    });
    const t0 = Date.now();
    await page.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    const failure = page.getByRole("alert").filter({ hasText: /Request timed out/i });
    await expect(failure).toBeVisible({ timeout: 60_000 });
    const elapsed = Date.now() - t0;
    expect(elapsed, "not before the 25 s deadline").toBeGreaterThanOrEqual(24_000);
    expect(elapsed, "and not long after it").toBeLessThan(55_000);
    hanging = false;
    await failure.getByRole("button", { name: "Try again" }).tap();
    await expect(page.locator(SEL.boardRow).first()).toBeVisible({ timeout: 60_000 });
  });
});

// ── /trade: the 4-team summary bar and the screenshot FAB at 390 px ──────
//
// #2245 gave the FAB a 136 px clearance when the N-team summary bar is on the
// page, sized for the bar's wrapped worst case.  This measures the real
// layout: four teams on the page, then the bar's wrapped-worst-case verdict
// and a larger system font, asserting the bar stays on screen, inside the
// viewport width, and never overlaps the FAB or the bottom nav.

const { closeTradeSheet, openTradeSearch } = require("../helpers/trade-builder");
const { boardRow, isTradeableRow } = require("../helpers/trade-board");
const { contractFixture } = require("../helpers/journey");

const BAR = '[data-testid="trade-multi-summary"]';

/** One priced, uniquely-named player per team, for four distinct teams. */
async function fourPlayers(page) {
  const { contract, teams } = await contractFixture(page, { view: "compact" });
  const holders = new Map();
  for (const t of teams) for (const n of t.players || []) holders.set(n, (holders.get(n) || 0) + 1);
  const out = [];
  for (const t of teams) {
    const name = (t.players || []).find(
      (n) => !/\d{4}/.test(n) && holders.get(n) === 1 && isTradeableRow(boardRow(contract, n)),
    );
    if (name) out.push(name);
    if (out.length === 4) break;
  }
  expect(out.length, "the seeded board has four teams with a priced, unique player").toBe(4);
  return out;
}

async function addPlayer(page, sideLabel, name) {
  const input = await openTradeSearch(page, sideLabel);
  await input.fill(name);
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const result = page
    .locator(".trade-side-search-result")
    .filter({ has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${escaped}$`) }) })
    .first();
  await expect(result, `search result for ${name}`).toBeVisible({ timeout: 15_000 });
  await result.click();
  await closeTradeSheet(page);
}

/** Boxes of the bar, the FAB and every other pinned box, from the live DOM. */
const MEASURE = (barSelector) => {
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom };
  };
  const bar = document.querySelector(barSelector);
  const fab = document.querySelector(".screenshot-fab");
  const nav = document.querySelector(".shell-tabbar");
  return {
    bar: bar && rect(bar),
    fab: fab && rect(fab),
    nav: nav ? rect(nav) : null,
    viewport: { w: document.documentElement.clientWidth, h: window.innerHeight },
    docWidth: document.documentElement.scrollWidth,
  };
};

const overlapArea = (a, b) =>
  Math.max(0, Math.min(a.right, b.right) - Math.max(a.x, b.x)) *
  Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y));

async function expectBarClear(page, label) {
  const m = await page.evaluate(MEASURE, BAR);
  expect(m.bar, `${label}: the summary bar is on the page`).not.toBeNull();
  expect(m.docWidth, `${label}: no sideways scroll`).toBeLessThanOrEqual(m.viewport.w + 1);
  expect(m.bar.x, `${label}: bar inside the left edge`).toBeGreaterThanOrEqual(-1);
  expect(m.bar.right, `${label}: bar inside the right edge`).toBeLessThanOrEqual(m.viewport.w + 1);
  expect(m.bar.bottom, `${label}: bar fully on screen`).toBeLessThanOrEqual(m.viewport.h + 1);
  // Both neighbours must exist, or "no overlap" proves nothing.
  expect(m.fab, `${label}: the screenshot FAB is on the page`).not.toBeNull();
  expect(m.nav, `${label}: the bottom tab bar is on the page`).not.toBeNull();
  expect(
    overlapArea(m.bar, m.fab),
    `${label}: the screenshot FAB does not cover the bar (bar ${JSON.stringify(m.bar)} fab ${JSON.stringify(m.fab)})`,
  ).toBe(0);
  expect(overlapArea(m.bar, m.nav), `${label}: the bottom nav does not cover the bar`).toBe(0);
  expect(m.fab.bottom, `${label}: the FAB sits above the bar`).toBeLessThanOrEqual(m.bar.y + 1);
  return m;
}

test.describe("4-team summary bar at 390 px @mobile-only", () => {
  test("the bar, the FAB and the bottom nav never overlap — natural text, worst-case verdict, larger font", async ({
    authedPage: page,
  }) => {
    const players = await fourPlayers(page);
    await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(page);
    await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
      timeout: 60_000,
    });
    await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
      timeout: 90_000,
    });
    await page.getByRole("button", { name: "Add Team" }).click();
    await page.getByRole("button", { name: "Add Team" }).click();
    await expect(page.locator("#trade-side-D")).toBeVisible();
    for (const [i, name] of players.entries()) await addPlayer(page, "ABCD"[i], name);

    const bar = page.locator(BAR);
    await expect(bar).toBeVisible({ timeout: 30_000 });
    const sides = await bar.locator("a > span").first().locator("> span").count();
    expect(sides, "one net per team").toBe(4);

    await expectBarClear(page, "as rendered");

    // The wrapped worst case the 136 px clearance was sized for: the final
    // verdict naming all four teams.  Injected (React will not re-render in
    // this window), so the geometry is measured, not assumed.
    await bar.evaluate((el) => {
      const verdict = el.querySelector("a > span:last-child");
      verdict.textContent =
        "Final: A not fair · B unable to determine · C not fair · D unable to determine — each team's decision is in the War Room";
    });
    const worst = await expectBarClear(page, "worst-case verdict");
    expect(worst.bar.h, "the worst case really is a taller bar than the 2-team tray (74 px)").toBeGreaterThan(74);

    // A larger system font (iOS Dynamic Type): the page's root size up 25 %.
    await page.addStyleTag({ content: "html { font-size: 125% !important; }" });
    await expectBarClear(page, "125% font");
  });
});

// ── auction: what is reachable without a live room ───────────────────────
//
// A live room cannot be created on the offline suite stack (creating one needs
// the site-owner account, and /api/auction/auth/me reports
// siteOwnerAvailable:false for the test user), and its state payload is too
// large to fake honestly.  So the LIVE ROOM IS NOT AUTOMATED — it is item 5 of
// docs/qa/REAL_DEVICE_CHECKLIST_2026-11-19.md.  What is checked here is the
// auction's own entry and room-gate screens at 390 px: they render, and every
// primary control on them is at least 44 px tall.

const AUCTION_SCREENS = [
  ["/auction", /Site owner|Sign in/i],
  ["/auction/join", /./],
  ["/auction/a11y-probe", /./],
];

test.describe("auction entry screens at 390 px @mobile-only", () => {
  for (const [route, expected] of AUCTION_SCREENS) {
    test(`${route} renders and its primary controls are >= 44 px`, async ({ authedPage: page }) => {
      await page.goto(pageUrl(route), { waitUntil: "domcontentloaded" });
      await awaitStreamSettled(page);
      await expect(page.locator("body")).toContainText(expected, { timeout: 30_000 });
      await page.waitForLoadState("networkidle", { timeout: 2_000 }).catch(() => {});
      const { small, measured } = await page.evaluate(() => {
        const out = [];
        let measured = 0;
        const vw = document.documentElement.clientWidth;
        const controls = document.querySelectorAll(
          "button, a.ds-btn, [role='button'], input:not([type='hidden']), select",
        );
        for (const el of controls) {
          const s = getComputedStyle(el);
          if (s.display === "none" || s.visibility === "hidden") continue;
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) continue;
          if (el.closest("[aria-hidden='true']")) continue;
          if (r.right < 0 || r.x > vw) continue;
          measured += 1;
          if (r.height < 43.5) {
            const name = (el.textContent || el.getAttribute("aria-label") || el.type || "").trim().slice(0, 40);
            out.push(`${el.tagName.toLowerCase()} "${name}" ${Math.round(r.width)}x${Math.round(r.height)}`);
          }
        }
        return { small: out, measured };
      });
      expect(measured, `${route}: the screen has controls to measure`).toBeGreaterThan(0);
      expect(small, `${route}: controls shorter than 44 px`).toEqual([]);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${route}: no sideways scroll`).toBeLessThanOrEqual(1);
    });
  }
});
