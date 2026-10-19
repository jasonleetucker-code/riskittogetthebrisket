#!/usr/bin/env node
/**
 * /trade interaction latency (TC-E).
 *
 * Two questions `measure-route-baselines.mjs` does not answer, measured on the
 * same local stack and with the same conventions (env, test session, unthrottled
 * Chromium, nearest-rank percentiles, a missing observation is `null` with a
 * reason, never 0):
 *
 *   search    keystroke -> first result row painted.  The query is written into
 *             the side search the way React sees typing (native value setter +
 *             a bubbling `input` event) and timed in the page with
 *             `performance.now()` until a result row (or "No matches.") is in
 *             the DOM on a later animation frame -- no driver round trip inside
 *             the timed span.  Each sample starts from an empty field.
 *   trade     completing a two-team trade (the pick that fills Side B) ->
 *             (a) the immediate verdict: the meter's band word, local math;
 *             (b) the Final Decision: the War Room headline, which waits for
 *             its 700 ms debounce plus the real `POST /api/trade/analyze`.
 *             Same click, one clock, so (a) and (b) are directly comparable.
 *
 * Desktop uses the inline search; the phone viewport uses the bottom sheet
 * (TC-D2).  The trade is a real team's player for another team's player from
 * the served contract, with that team selected, so the War Room analyses it.
 *
 * USAGE
 *   E2E_BASE_URL=http://127.0.0.1:8400 E2E_PAGE_ORIGIN=http://127.0.0.1:3400 \
 *   E2E_TEST_SECRET=... PW_CHROMIUM_PATH=... \
 *     node scripts/measure-trade-interaction.mjs [--runs 5] \
 *       [--viewport desktop|mobile|both] [--json out.json]
 */
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";

const API = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";
const PAGE_ORIGIN = process.env.E2E_PAGE_ORIGIN || "http://127.0.0.1:3000";
const SECRET = process.env.E2E_TEST_SECRET || "";

const VIEWPORTS = {
  desktop: { width: 1366, height: 900 },
  mobile: { width: 390, height: 844 },
};
// Fixed, non-private queries: short prefixes (the common typing case), a
// longer name fragment and a structured pick query.
export const QUERIES = ["jo", "mi", "ch", "da", "ke", "bra", "2027 1st", "2026 mid"];
const PICK_TOKEN = /\d{4}/;

export function parseArgs(argv) {
  const out = { runs: 5, viewport: "both", json: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const v = argv[i + 1];
    if (!["--runs", "--viewport", "--json"].includes(a) || !v || v.startsWith("--")) {
      throw new Error("invalid_arguments");
    }
    i += 1;
    if (a === "--runs") out.runs = Number(v);
    else if (a === "--viewport") out.viewport = v;
    else out.json = v;
  }
  if (!Number.isInteger(out.runs) || out.runs < 1 || out.runs > 50) throw new Error("invalid_arguments");
  if (!["desktop", "mobile", "both"].includes(out.viewport)) throw new Error("invalid_arguments");
  return out;
}

/** Nearest-rank percentile over the observed values; null when there are none. */
export function percentile(values, p) {
  const xs = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const rank = Math.max(1, Math.ceil((p / 100) * xs.length));
  return Math.round(xs[rank - 1] * 10) / 10;
}

export function summarise(samples) {
  const values = samples.filter((s) => Number.isFinite(s));
  return {
    n: samples.length,
    observed: values.length,
    missing: samples.length - values.length,
    p50: percentile(values, 50),
    p95: percentile(values, 95),
    max: percentile(values, 100),
  };
}

const API_DIR = new URL("../app/api/", import.meta.url);

/** True when frontend/app/api has a route handler for this path. */
export function nextServesApi(pathname, dir = API_DIR) {
  const segs = pathname.replace(/^\/api\/?/, "").split("/").filter(Boolean);
  const walk = (base, i) => {
    let entries;
    try {
      entries = fs.readdirSync(base, { withFileTypes: true });
    } catch {
      return false;
    }
    if (i === segs.length) return entries.some((e) => e.isFile() && /^route\.(js|ts)$/.test(e.name));
    return entries.some((e) => {
      if (!e.isDirectory()) return false;
      const sub = new URL(`${e.name}/`, base);
      if (e.name === segs[i]) return walk(sub, i + 1);
      if (/^\[\.\.\..+\]$/.test(e.name) || /^\[\[\.\.\..+\]\]$/.test(e.name)) return walk(sub, segs.length);
      if (/^\[.+\]$/.test(e.name)) return walk(sub, i + 1);
      return false;
    });
  };
  return walk(dir, 0);
}

async function tradeFromContract(ctx) {
  const res = await ctx.request.get(`${API}/api/data?view=app`);
  if (!res.ok()) throw new Error(`contract_${res.status()}`);
  const data = await res.json();
  const teams = data?.sleeper?.teams || [];
  const names = new Set(
    (data.playersArray || []).map((r) => r?.displayName || r?.canonicalName).filter(Boolean)
      .concat(Object.keys(data.players || {})),
  );
  for (const [idx, team] of teams.entries()) {
    const give = (team.players || []).find((p) => p && !PICK_TOKEN.test(p) && names.has(p));
    const other = teams.find((t) => t !== team);
    const receive = (other?.players || []).find(
      (p) => p && !PICK_TOKEN.test(p) && names.has(p) && !(team.players || []).includes(p),
    );
    if (give && receive) return { idx, give, receive };
  }
  throw new Error("no_resolvable_trade");
}

async function openSearch(page, side, mobile) {
  if (mobile) {
    await page.getByRole("button", { name: `Add to Side ${side}`, exact: true }).click();
    await page.getByRole("dialog", { name: `Add to Side ${side}` }).waitFor();
  }
  const input = page.getByLabel(`Search to add a player to Side ${side}`);
  await input.click();
  return input;
}

async function closeSheet(page, mobile) {
  if (!mobile) return;
  await page.getByRole("dialog").getByRole("button", { name: "Done" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached" });
}

/** Keystroke -> first result row painted, timed inside the page. */
async function timeSearch(page, side, query) {
  return page.evaluate(
    ({ side, query }) =>
      new Promise((resolve) => {
        const input = document.querySelector(
          `input[aria-label="Search to add a player to Side ${side}"]`,
        );
        if (!input) return resolve({ ms: null, reason: "no_input" });
        const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        const results = () =>
          document.querySelector(".trade-side-search-result, .trade-side-search-empty");
        // Start from an empty field so the sample is "results appear".
        setValue.call(input, "");
        input.dispatchEvent(new Event("input", { bubbles: true }));
        const start = () => {
          if (results()) return requestAnimationFrame(start);
          const t0 = performance.now();
          setValue.call(input, query);
          input.dispatchEvent(new Event("input", { bubbles: true }));
          const tick = () => {
            if (results()) return resolve({ ms: performance.now() - t0 });
            if (performance.now() - t0 > 10_000) return resolve({ ms: null, reason: "timeout" });
            requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(start);
      }),
    { side, query },
  );
}

/** The pick that completes the trade -> meter verdict and War Room headline. */
async function timeCompletion(page, name) {
  return page.evaluate(
    (name) =>
      new Promise((resolve) => {
        const row = [...document.querySelectorAll(".trade-side-search-result")].find(
          (el) => el.querySelector(".trade-side-search-result-name")?.textContent.trim() === name,
        );
        if (!row) return resolve({ immediateMs: null, decisionMs: null, reason: "no_result_row" });
        const verdict = () =>
          [...document.querySelectorAll(".trade-meter-verdict")].some((el) => el.textContent.trim());
        const decision = () =>
          Boolean(document.querySelector('[data-testid="decision-headline"]')?.textContent.trim());
        const out = { immediateMs: null, decisionMs: null };
        const t0 = performance.now();
        // The inline list picks on mousedown; the phone sheet on click.
        row.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        row.click();
        const tick = () => {
          const t = performance.now() - t0;
          if (out.immediateMs == null && verdict()) out.immediateMs = t;
          if (out.decisionMs == null && decision()) out.decisionMs = t;
          if ((out.immediateMs != null && out.decisionMs != null) || t > 30_000) return resolve(out);
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }),
    name,
  );
}

/**
 * Type the exact name and wait for its row; `pick` also picks it in the same
 * in-page step (no blur window).  Setup only -- never timed -- so up to two retries are
 * allowed when the list closed under the driver (focus moved by a re-render).
 */
async function typeAndFind(page, side, name, mobile, pick) {
  const find = (args) => {
    const row = [...document.querySelectorAll(".trade-side-search-result")].find(
      (el) => el.querySelector(".trade-side-search-result-name")?.textContent.trim() === args.name,
    );
    if (!row) return false;
    if (args.pick) {
      row.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
      row.click();
    }
    return true;
  };
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const input = await openSearch(page, side, mobile);
    await input.fill(name);
    try {
      await page.waitForFunction(find, { name, pick }, { timeout: 15_000, polling: "raf" });
      return attempt;
    } catch (err) {
      if (attempt === 2) {
        const seen = await page.evaluate(() => ({
          active: document.activeElement?.getAttribute("aria-label") || document.activeElement?.tagName,
          rows: [...document.querySelectorAll(".trade-side-search-result-name")].map((e) => e.textContent.trim()).slice(0, 5),
          dialogs: document.querySelectorAll('[role="dialog"]').length,
        }));
        throw new Error(`setup_find_failed ${side} ${name}: ${JSON.stringify(seen)}`);
      }
      await closeSheet(page, mobile).catch(() => {});
      // Blur and let the page settle before asking again (focus state, a
      // re-rendered builder).
      await page.evaluate(() => document.activeElement?.blur?.());
      await page.waitForTimeout(500);
    }
  }
  return 0;
}
const addAsset = (page, side, name, mobile) => typeAndFind(page, side, name, mobile, true);
const findAsset = (page, side, name, mobile) => typeAndFind(page, side, name, mobile, false);

async function measureViewport(browser, vp, runs) {
  const mobile = vp === "mobile";
  const ctx = await browser.newContext({
    baseURL: API,
    viewport: VIEWPORTS[vp],
    isMobile: mobile,
    hasTouch: mobile,
  });
  // Production topology: nginx sends /api/* straight to the backend.  The local
  // Next server bridges only some routes (no /api/trade/analyze, simulate or
  // simulate-mc), so a page request Next has no route handler for goes to the
  // backend directly; everything Next serves is left alone.
  await ctx.route(
    (url) =>
      url.origin === new URL(PAGE_ORIGIN).origin &&
      url.pathname.startsWith("/api/") &&
      !nextServesApi(url.pathname),
    async (route) => {
      const target = route.request().url().replace(new URL(PAGE_ORIGIN).origin, new URL(API).origin);
      try {
        const response = await route.fetch({ url: target });
        await route.fulfill({ response });
      } catch {
        await route.abort().catch(() => {});
      }
    },
  );
  const search = [];
  const immediate = [];
  const decision = [];
  const notes = [];
  try {
    const session = await ctx.request.post(`${API}/api/test/create-session`, {
      headers: { Authorization: `Bearer ${SECRET}` },
      timeout: 60_000,
    });
    if (!session.ok()) throw new Error("session_failed");
    const trade = await tradeFromContract(ctx);
    const page = await ctx.newPage();
    await page.goto(`${PAGE_ORIGIN}/trade`, { waitUntil: "domcontentloaded" });
    await page.locator(".trade-controls").waitFor({ timeout: 90_000 });
    await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
      timeout: 90_000,
    });
    await page.selectOption("#suggest-team", String(trade.idx));

    // Search: one warm-up pass (not recorded), then `runs` passes over QUERIES.
    await openSearch(page, "A", mobile);
    for (let r = 0; r <= runs; r++) {
      for (const q of QUERIES) {
        const s = await timeSearch(page, "A", q);
        if (r > 0) search.push(s.ms);
        if (r > 0 && s.ms == null) notes.push(`search ${q}: ${s.reason}`);
      }
    }
    await closeSheet(page, mobile);

    // Completion: clear, add Side A, then time the Side B pick.  One warm-up.
    for (let r = 0; r <= runs; r++) {
      await page.getByRole("button", { name: "Clear Trade" }).click();
      await page.locator('[data-testid="decision-headline"]').waitFor({ state: "detached" }).catch(() => {});
      await addAsset(page, "A", trade.give, mobile);
      await closeSheet(page, mobile);
      await findAsset(page, "B", trade.receive, mobile);
      const t = await timeCompletion(page, trade.receive);
      await closeSheet(page, mobile);
      if (r > 0) {
        immediate.push(t.immediateMs);
        decision.push(t.decisionMs);
        if (t.reason) notes.push(`trade: ${t.reason}`);
      }
    }
  } finally {
    await ctx.close();
  }
  return {
    searchMs: summarise(search),
    immediateVerdictMs: summarise(immediate),
    finalDecisionMs: summarise(decision),
    notes,
  };
}

export async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (!SECRET) {
    console.error("session_secret_missing");
    return 2;
  }
  const viewports = args.viewport === "both" ? ["desktop", "mobile"] : [args.viewport];
  const browser = await chromium.launch({
    executablePath: process.env.PW_CHROMIUM_PATH || undefined,
    args: ["--no-sandbox"],
  });
  const report = {
    measuredAt: new Date().toISOString(),
    runs: args.runs,
    queries: QUERIES,
    protocol: {
      search: "empty field -> query set via native setter + input event -> first result row in the DOM on an animation frame; performance.now() in the page",
      trade: "Side B pick (mousedown/click dispatched in the page) -> meter band word present / War Room decision headline present; one clock",
      warmup: "one unrecorded pass per measure",
      apiTopology: "page /api/* requests routed straight to the backend (production nginx topology)",
      profile: "unthrottled",
      percentile: "nearest-rank",
      browserVersion: browser.version(),
    },
    viewports: {},
  };
  try {
    for (const vp of viewports) {
      report.viewports[vp] = await measureViewport(browser, vp, args.runs);
      const r = report.viewports[vp];
      console.log(
        `${vp}: search p50 ${r.searchMs.p50}ms p95 ${r.searchMs.p95}ms (n=${r.searchMs.observed}); ` +
          `immediate verdict p50 ${r.immediateVerdictMs.p50}ms p95 ${r.immediateVerdictMs.p95}ms (n=${r.immediateVerdictMs.observed}); ` +
          `final decision p50 ${r.finalDecisionMs.p50}ms p95 ${r.finalDecisionMs.p95}ms (n=${r.finalDecisionMs.observed})`,
      );
      if (r.notes.length) console.log(`  notes: ${r.notes.join("; ")}`);
    }
  } finally {
    await browser.close();
  }
  if (args.json) fs.writeFileSync(args.json, JSON.stringify(report, null, 2));
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((err) => {
      console.error(`measure_failed: ${err?.message || err}`);
      process.exitCode = 1;
    });
}
