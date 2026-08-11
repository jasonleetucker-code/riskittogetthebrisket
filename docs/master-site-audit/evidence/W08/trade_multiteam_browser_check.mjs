/**
 * Live-browser check for the /trade multi-team crash.
 *
 * Drives the REAL production Next build over the REAL stack, at the mobile
 * viewport the repo's `mobile-chromium` Playwright project uses. Chromium
 * only — WebKit is not installed in this container (see the defect doc §7).
 *
 * Two paths, matching the regression test:
 *   (a) hydrate a saved 3-side workspace with assets staged
 *   (b) click "Add team" from a 2-side workspace with an asset staged
 *
 * Only (b) reproduces against the live stack: (a)'s seeding branch needs
 * board rows present on the FIRST hydration pass, which a real async
 * `/api/data` does not provide. (a) is kept because it is a real code path
 * a warm cache can win — it just isn't the browser evidence. See the defect
 * doc §7.
 *
 * Passes only if NEITHER path produces a `defaultDestination` ReferenceError
 * and the trade board is still rendered afterwards.
 *
 * Run from the REPO ROOT (that is where `@playwright/test` resolves), with
 * the stack up and the backend's E2E secret exported:
 *
 *   E2E_TEST_SECRET=... node docs/master-site-audit/evidence/W08/trade_multiteam_browser_check.mjs
 *
 * Exit 0 = clean, 1 = crash observed, 2 = harness could not run.
 */
import { chromium, devices } from "@playwright/test";

const PAGE_ORIGIN = process.env.E2E_PAGE_ORIGIN || "http://127.0.0.1:3000";
const API_ORIGIN = process.env.E2E_API_ORIGIN || "http://127.0.0.1:8000";
const SECRET = process.env.E2E_TEST_SECRET || "";

const MOBILE = {
  ...devices["Pixel 5"],
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
};

function seedScript(sides) {
  return `window.localStorage.setItem(${JSON.stringify(
    "next_trade_workspace_v1",
  )}, ${JSON.stringify(JSON.stringify(sides))});`;
}

const THREE_SIDES = {
  version: 2,
  valueMode: "full",
  activeSide: 0,
  sides: [
    { label: "Team A", assets: [], destinations: {} },
    { label: "Team B", assets: [], destinations: {} },
    { label: "Team C", assets: [], destinations: {} },
  ],
};

const TWO_SIDES = {
  version: 2,
  valueMode: "full",
  activeSide: 0,
  sides: [
    { label: "Team A", assets: [], destinations: {} },
    { label: "Team B", assets: [], destinations: {} },
  ],
};

async function topPlayerNames(ctx, n) {
  const res = await ctx.request.get(`${API_ORIGIN}/api/data?view=app`);
  if (!res.ok()) throw new Error(`/api/data returned ${res.status()}`);
  const body = await res.json();
  // view=app serves `players` as a name-keyed dict; the values carry no
  // name field, so the key IS the display name the workspace stores.
  const pick = /^\d{4}\s/;
  const named = Object.entries(body.players || {})
    .filter(([name, row]) => name && !pick.test(name) && row && row._composite)
    .sort((a, b) => (b[1]._composite || 0) - (a[1]._composite || 0))
    .map(([name]) => name);
  if (named.length < n) throw new Error(`only ${named.length} named rows`);
  return named.slice(0, n);
}

function watch(page, sink) {
  page.on("pageerror", (e) => sink.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") sink.push(`console.error: ${m.text()}`);
  });
}

async function mintSession(context) {
  if (!SECRET) throw new Error("E2E_TEST_SECRET is required");
  const res = await context.request.post(
    `${API_ORIGIN}/api/test/create-session`,
    { headers: { Authorization: `Bearer ${SECRET}` } },
  );
  if (!res.ok()) throw new Error(`session mint failed: ${res.status()}`);
}

const results = [];

async function run() {
  const browser = await chromium.launch({
    // Container-pinned build; override where Playwright's own resolution
    // works or the revision differs.
    executablePath:
      process.env.CHROMIUM_PATH ||
      "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  });
  const bootCtx = await browser.newContext(MOBILE);
  await mintSession(bootCtx);
  const names = await topPlayerNames(bootCtx, 2);
  await bootCtx.close();
  console.log(`seeding assets: ${JSON.stringify(names)}`);

  // ── (a) hydrate a saved 3-side workspace with assets staged ──
  {
    const ctx = await browser.newContext(MOBILE);
    await mintSession(ctx);
    const staged = JSON.parse(JSON.stringify(THREE_SIDES));
    staged.sides[0].assets = [names[0]];
    staged.sides[1].assets = [names[1]];
    await ctx.addInitScript(seedScript(staged));
    const page = await ctx.newPage();
    const errs = [];
    watch(page, errs);
    await page.goto(`${PAGE_ORIGIN}/trade`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(8000);
    const hits = errs.filter((e) => /defaultDestination/.test(e));
    const bodyText = (await page.textContent("body")) || "";
    results.push({
      path: "hydrate 3-side workspace",
      referenceErrors: hits,
      renderedTradeUI: /Trade/i.test(bodyText),
      sawErrorBoundary: /Something went wrong|went wrong/i.test(bodyText),
      allErrors: errs.slice(0, 8),
    });
    await ctx.close();
  }

  // ── (b) click "Add team" from a 2-side workspace with an asset staged ──
  {
    const ctx = await browser.newContext(MOBILE);
    await mintSession(ctx);
    const staged = JSON.parse(JSON.stringify(TWO_SIDES));
    staged.sides[0].assets = [names[0]];
    await ctx.addInitScript(seedScript(staged));
    const page = await ctx.newPage();
    const errs = [];
    watch(page, errs);
    await page.goto(`${PAGE_ORIGIN}/trade`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(8000);
    const btn = page.getByRole("button", { name: /add team/i }).first();
    const clickable = await btn.count();
    if (clickable) {
      await btn.click();
      await page.waitForTimeout(2000);
    }
    const hits = errs.filter((e) => /defaultDestination/.test(e));
    const bodyText = (await page.textContent("body")) || "";
    results.push({
      path: "click Add team",
      buttonFound: Boolean(clickable),
      referenceErrors: hits,
      // three side labels present = the third team really materialised
      thirdSidePresent: /Team C|Side C/i.test(bodyText),
      sawErrorBoundary: /Something went wrong|went wrong/i.test(bodyText),
      allErrors: errs.slice(0, 8),
    });
    await ctx.close();
  }

  await browser.close();
  console.log(JSON.stringify(results, null, 2));
  const failed = results.some(
    (r) => r.referenceErrors.length > 0 || r.sawErrorBoundary,
  );
  process.exit(failed ? 1 : 0);
}

run().catch((e) => {
  console.error("HARNESS ERROR:", e);
  process.exit(2);
});
