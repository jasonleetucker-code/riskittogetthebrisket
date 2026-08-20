#!/usr/bin/env node
/**
 * Per-route performance baselines.
 *
 * WHY THIS EXISTS
 * ---------------
 * `docs/C_SERIES_SCOPE_MANIFEST.md` records `C0-PERF-01` as ABSENT:
 * "budgets exist, baselines do not", acceptance "p95 baselines for
 * /rankings, /trade, /league, sharp pages, mobile". It is a hard
 * dependency of `C8-PSI-02` (reference-route migration), for an obvious
 * reason — you cannot show a migration did not cost performance if
 * nobody wrote down what performance was before it.
 *
 * `docs/GLOBAL_PERFORMANCE_STANDARD.md` §2.2 names the metric: **time to
 * first useful state**, p95 <= 2s normal and <= 1s warm. §9 asks for
 * cold and warm, mobile, and payload bytes. This measures those.
 *
 * WHAT "USEFUL" MEANS, AND WHY IT IS DECLARED PER ROUTE
 * ----------------------------------------------------
 * A shell is not a useful state. `/rankings` painting its chrome while
 * the board is empty is not the page working, and a generic metric
 * (load, DOMContentLoaded, FCP) cannot tell those apart — it reports the
 * same number for a route that rendered its data and one that rendered
 * an empty frame.
 *
 * So each route declares the element whose presence means its primary
 * content is on screen. Where the e2e suite already has a marker for a
 * route, this uses THAT one, imported from `tests/e2e/helpers/journey.js`
 * rather than copied — a second definition of "this route is ready"
 * would drift from the suite and quietly measure something else.
 *
 * MISSING IS NEVER ZERO
 * ---------------------
 * If the readiness marker never appears, `usefulMs` is `null` with a
 * reason, never the load time and never 0. A route that failed to render
 * must not be reported as the fastest one on the board — which is what a
 * fallback to `load` would do.
 *
 * `settleMs` IS DELIBERATELY NOT MEASURED. `docs/master-site-audit/
 * PERFORMANCE_AUDIT.md` records that the earlier probe's 21s tier was
 * unresolvable `sleepercdn.com` avatar requests — a container-egress
 * artifact, not a page cost. Anything derived from network quiescence
 * inherits that, so this reports navigation timing and the readiness
 * marker instead.
 *
 * COLD vs WARM
 * ------------
 * Cold = a fresh browser context (empty HTTP cache, no warmed in-memory
 * contract). Warm = a second navigation in the same context. The
 * standard sets different budgets for them, so reporting one number for
 * both would be unmeasurable against it.
 *
 * USAGE
 *   E2E_TEST_SECRET=... node scripts/measure-route-baselines.mjs \
 *     [--runs 5] [--viewport desktop|mobile|both] [--routes /a,/b] \
 *     [--json out.json]
 *
 * Needs the PRODUCTION build running on :3000 and the backend on :8000
 * (a `next dev` first-compile number is meaningless here), plus
 * E2E_TEST_SECRET so the private routes are actually reachable — an
 * anonymous run measures the login redirect.
 */
import fs from "node:fs";
import { createRequire } from "node:module";
import { chromium } from "playwright";

const require = createRequire(import.meta.url);
// One owner for "what marks this route ready" — the e2e suite's table.
const { SEL } = require("../../tests/e2e/helpers/journey.js");

const API = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";
const PAGE_ORIGIN = process.env.E2E_PAGE_ORIGIN || "http://127.0.0.1:3000";
const SECRET = process.env.E2E_TEST_SECRET || "";

// route -> the element whose presence means the PRIMARY content is up.
//
// `note` is not decoration: it records what the marker actually proves,
// so a later reader can tell a real readiness signal from a shell that
// happens to contain a div.
const ROUTES = [
  { path: "/rankings", ready: SEL.boardRow, note: "a board row — the player table has data" },
  { path: "/trade", ready: SEL.tradeControls, note: "the trade control bar" },
  { path: "/league", ready: "main .card, .league-page .card", note: "the first league card" },
  { path: "/market/sharp-tracker", ready: "main table tbody tr", note: "a tracker table row" },
  { path: "/market/sharp-roster-percentage", ready: "main table tbody tr", note: "a roster-percentage row" },
  { path: "/waivers", ready: SEL.waiverBidDesk, note: "the FAAB bid desk" },
  { path: "/trades", ready: SEL.tradeLedgerEntry, note: "a ledger entry" },
  { path: "/", ready: SEL.dashboardStats, note: "the team aggregates block" },
];

const VIEWPORTS = {
  desktop: { width: 1366, height: 900 },
  mobile: { width: 390, height: 844 },
};

function parseArgs(argv) {
  const out = { runs: 5, viewport: "both", routes: null, json: null, timeout: 45_000 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--runs") out.runs = Number(argv[++i]);
    else if (a === "--viewport") out.viewport = argv[++i];
    else if (a === "--routes") out.routes = argv[++i].split(",").map((s) => s.trim());
    else if (a === "--json") out.json = argv[++i];
    else if (a === "--timeout") out.timeout = Number(argv[++i]);
  }
  return out;
}

/** p-th percentile by nearest-rank; null for an empty sample rather than 0. */
function pct(values, p) {
  const xs = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const rank = Math.max(1, Math.ceil((p / 100) * xs.length));
  return Math.round(xs[rank - 1]);
}

/**
 * One navigation. Returns timings, or a null usefulMs plus a reason.
 *
 * Timing comes from the page's own Navigation Timing / paint entries,
 * not from wall-clock around `goto`, so harness overhead is excluded.
 */
async function measureOnce(page, route, timeoutMs) {

  let readyReason = null;
  let usefulMs = null;
  try {
    await page.goto(`${PAGE_ORIGIN}${route.path}`, {
      waitUntil: "commit",
      timeout: timeoutMs,
    });
    try {
      await page.locator(route.ready).first().waitFor({ state: "attached", timeout: timeoutMs });
      usefulMs = await page.evaluate(() => performance.now());
    } catch {
      readyReason = `readiness marker never appeared within ${timeoutMs}ms`;
    }
    // Navigation Timing is only final once the load event has fired; the
    // readiness wait above usually outlives it, but not always.
    await page.waitForLoadState("load", { timeout: timeoutMs }).catch(() => {});
  } catch (err) {
    return { error: err?.message || String(err) };
  }

  const nav = await page.evaluate(() => {
    const n = performance.getEntriesByType("navigation")[0];
    const fcp = performance
      .getEntriesByType("paint")
      .find((e) => e.name === "first-contentful-paint");
    // Bytes come from Resource Timing, NOT from summing `content-length`
    // response headers. The first version of this probe did the latter
    // and reported ~89 KB for every route on the board — because the
    // contract response is gzipped and chunked and carries no
    // `content-length`, so the multi-MB payload the page actually
    // downloads was silently missing and only the shell assets counted.
    // `encodedBodySize` is the compressed bytes as received.
    const resources = performance.getEntriesByType("resource");
    const encoded =
      resources.reduce((a, r) => a + (r.encodedBodySize || 0), 0) +
      (n?.encodedBodySize || 0);
    const decoded =
      resources.reduce((a, r) => a + (r.decodedBodySize || 0), 0) +
      (n?.decodedBodySize || 0);
    return {
      encodedBytes: encoded || null,
      decodedBytes: decoded || null,
      requestCount: resources.length,
      ttfbMs: n ? Math.round(n.responseStart) : null,
      fcpMs: fcp ? Math.round(fcp.startTime) : null,
      domContentLoadedMs: n ? Math.round(n.domContentLoadedEventEnd) : null,
      loadMs: n && n.loadEventEnd > 0 ? Math.round(n.loadEventEnd) : null,
      domNodes: document.getElementsByTagName("*").length,
      finalUrl: location.pathname,
    };
  });

  return {
    ...nav,
    usefulMs: usefulMs == null ? null : Math.round(usefulMs),
    readyReason,
  };
}

function summarise(samples) {
  const keys = ["ttfbMs", "fcpMs", "usefulMs", "domContentLoadedMs", "loadMs", "encodedBytes", "decodedBytes", "requestCount", "domNodes"];
  const out = {};
  for (const k of keys) {
    const vals = samples.map((s) => s?.[k]).filter((v) => Number.isFinite(v));
    out[k] = { p50: pct(vals, 50), p95: pct(vals, 95), n: vals.length };
  }
  // How many runs produced NO useful state. Reported rather than
  // averaged away: three good runs and two blank frames is not the same
  // page as five good runs, and a percentile over the survivors hides it.
  out.usefulMissing = samples.filter((s) => s && s.usefulMs == null).length;
  out.errors = samples.filter((s) => s?.error).length;
  return out;
}

const args = parseArgs(process.argv.slice(2));
if (!SECRET) {
  console.error("E2E_TEST_SECRET is unset. Private routes would redirect to /login,");
  console.error("and this would report the login page's numbers under their names.");
  process.exit(2);
}

const routes = args.routes
  ? ROUTES.filter((r) => args.routes.includes(r.path))
  : ROUTES;
const viewports =
  args.viewport === "both" ? ["desktop", "mobile"] : [args.viewport];

const browser = await chromium.launch({
  executablePath: process.env.PW_CHROMIUM_PATH || undefined,
  args: ["--no-sandbox"],
});

const report = { measuredAt: new Date().toISOString(), runs: args.runs, routes: {} };

for (const vp of viewports) {
  for (const route of routes) {
    const cold = [];
    const warm = [];
    for (let i = 0; i < args.runs; i++) {
      // A FRESH CONTEXT per cold run. Reusing one and clearing cookies
      // would leave the HTTP cache and the service-worker-less memory
      // cache warm, so "cold" would silently be a second warm number.
      const ctx = await browser.newContext({
        baseURL: API,
        viewport: VIEWPORTS[vp],
        isMobile: vp === "mobile",
        hasTouch: vp === "mobile",
      });
      const sess = await ctx.request.post(`${API}/api/test/create-session`, {
        headers: { Authorization: `Bearer ${SECRET}` },
        timeout: 60_000,
      });
      if (!sess.ok()) {
        console.error(`could not mint session: ${sess.status()}`);
        await ctx.close();
        continue;
      }
      const page = await ctx.newPage();
      cold.push(await measureOnce(page, route, args.timeout));
      warm.push(await measureOnce(page, route, args.timeout));
      await ctx.close();
    }
    const key = `${vp} ${route.path}`;
    report.routes[key] = {
      viewport: vp,
      path: route.path,
      readySelector: route.ready,
      readyMeans: route.note,
      cold: summarise(cold),
      warm: summarise(warm),
    };
    const c = report.routes[key].cold;
    const w = report.routes[key].warm;
    console.log(
      `${key.padEnd(42)} cold p95 useful ${String(c.usefulMs.p95 ?? "—").padStart(6)}ms · ` +
        `warm p95 ${String(w.usefulMs.p95 ?? "—").padStart(6)}ms · ` +
        `cold p95 fcp ${String(c.fcpMs.p95 ?? "—").padStart(5)}ms` +
        (c.usefulMissing || w.usefulMissing
          ? `  ⚠ ${c.usefulMissing + w.usefulMissing} run(s) never reached a useful state`
          : ""),
    );
  }
}

await browser.close();

if (args.json) {
  fs.writeFileSync(args.json, JSON.stringify(report, null, 2));
  console.log(`\nwrote ${args.json}`);
}

// The standard's targets, checked but NOT enforced: this run establishes
// the baseline, and failing the build on the first measurement would
// make recording the truth expensive. Enforcement is a separate,
// deliberate step once the numbers are agreed.
const OVER = [];
for (const [key, r] of Object.entries(report.routes)) {
  if (Number.isFinite(r.cold.usefulMs.p95) && r.cold.usefulMs.p95 > 2000) {
    OVER.push(`${key}: cold p95 useful ${r.cold.usefulMs.p95}ms > 2000ms (standard §2.2)`);
  }
  if (Number.isFinite(r.warm.usefulMs.p95) && r.warm.usefulMs.p95 > 1000) {
    OVER.push(`${key}: warm p95 useful ${r.warm.usefulMs.p95}ms > 1000ms (standard §2.2)`);
  }
}
if (OVER.length) {
  console.log(`\n${OVER.length} measurement(s) over the standard's target:`);
  for (const line of OVER) console.log(`  ${line}`);
} else {
  console.log("\nAll measured routes inside the standard's targets.");
}
