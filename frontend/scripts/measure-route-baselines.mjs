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
 * Rankings and Trade use explicit visible, data-bearing probes. Other legacy
 * routes retain their inventory markers but fail with unsupported_predicate
 * until a reviewed primary-content predicate is defined.
 * So each supported route declares the element whose presence means its primary
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
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";

const require = createRequire(import.meta.url);
// One owner for "what marks this route ready" — the e2e suite's table.
const { SEL, baselineUsefulState } = require("../../tests/e2e/helpers/journey.js");

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
  { path: "/trade", ready: SEL.tradeControls, note: "visible controls and an eligible result for the fixed a search" },
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

export function parseArgs(argv) {
  const out = { runs: 5, viewport: "both", routes: null, json: null, timeout: 45_000, auth: "local-test" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!["--runs", "--viewport", "--routes", "--json", "--timeout", "--auth"].includes(a) || !argv[i + 1] || argv[i + 1].startsWith("--")) throw new Error("invalid_arguments");
    if (a === "--auth") out.auth = argv[++i];
    else if (a === "--runs") out.runs = Number(argv[++i]);
    else if (a === "--viewport") out.viewport = argv[++i];
    else if (a === "--routes") out.routes = argv[++i].split(",").map((s) => s.trim());
    else if (a === "--json") out.json = argv[++i];
    else if (a === "--timeout") out.timeout = Number(argv[++i]);
  }
  if (!["local-test", "production-cookie"].includes(out.auth) || !Number.isInteger(out.runs) || out.runs < 1 || out.runs > 100 ||
      !["desktop", "mobile", "both"].includes(out.viewport) ||
      !Number.isFinite(out.timeout) || out.timeout < 1 || out.timeout > 120000 ||
      (out.routes && (!out.routes.length || new Set(out.routes).size !== out.routes.length ||
       out.routes.some(path => !ROUTES.some(route => route.path === path))))) throw new Error("invalid_arguments");
  return out;
}

/** p-th percentile by nearest-rank; null for an empty sample rather than 0. */
function pct(values, p) {
  const xs = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const rank = Math.max(1, Math.ceil((p / 100) * xs.length));
  return xs[rank - 1];
}

/**
 * One navigation. Returns timings, or a null usefulMs plus a reason.
 *
 * Timing comes from the page's own Navigation Timing / paint entries,
 * not from wall-clock around `goto`, so harness overhead is excluded.
 */
export async function measureOnce(page, route, timeoutMs, origin = PAGE_ORIGIN) {

  let readyReason = null;
  let usefulMs = null;
  let terminalState = "missing";
  let navigationStatus = null;
  try {
    const response = await page.goto(`${origin}${route.path}`, {
      waitUntil: "commit",
      timeout: timeoutMs,
    });
    const status = response?.status();
    if (!Number.isInteger(status) || status < 200 || status >= 400) return { ...failedSample("navigation_status"), navigationStatus: Number.isInteger(status) ? status : null };
    navigationStatus = status;
    if (new URL(page.url()).origin !== new URL(origin).origin || new URL(page.url()).pathname !== route.path) return failedSample("route_mismatch");
    try {
      terminalState = await baselineUsefulState(page, route.path, timeoutMs);
      if (terminalState === "useful") usefulMs = await page.evaluate(() => performance.now());
      else readyReason = terminalState;
    } catch {
      terminalState = "missing";
      readyReason = "useful_timeout";
      const unavailable = await page.locator('main [role="alert"]').filter({ hasText: /Couldn't load the player pool|Unable to load|Failed to load|Sign.in required/i }).first().isVisible().catch(() => false);
      if (unavailable) { terminalState = "unavailable"; readyReason = "explicit_unavailable"; }
    }
    if (new URL(page.url()).origin !== new URL(origin).origin || new URL(page.url()).pathname !== route.path) return failedSample("route_mismatch");
    // Navigation Timing is only final once the load event has fired; the
    // readiness wait above usually outlives it, but not always.
    await page.waitForLoadState("load", { timeout: timeoutMs }).catch(() => {});
    if (new URL(page.url()).origin !== new URL(origin).origin || new URL(page.url()).pathname !== route.path) return failedSample("route_mismatch");
  } catch (err) {
    return failedSample("navigation_failed");
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
    navigationStatus,
    usefulMs,
    readyReason,
    terminalState,
    // A late check after the useful probe, not the first error paint.
    unavailableObservedMs: terminalState === "unavailable" ? await page.evaluate(() => performance.now()) : null,
  };
}

export function summarise(samples, expected = samples.length) {
  const keys = ["ttfbMs", "fcpMs", "usefulMs", "domContentLoadedMs", "loadMs", "encodedBytes", "decodedBytes", "requestCount", "domNodes"];
  const out = {};
  for (const k of keys) {
    const vals = samples.map((s) => s?.[k]).filter((v) => Number.isFinite(v) && v >= 0);
    out[k] = { p50: pct(vals, 50), p95: pct(vals, 95), n: vals.length };
  }
  // How many runs produced NO useful state. Reported rather than
  // averaged away: three good runs and two blank frames is not the same
  // page as five good runs, and a percentile over the survivors hides it.
  out.usefulMissing = samples.filter((s) => !Number.isFinite(s?.usefulMs) || s.usefulMs < 0 || s.terminalState !== "useful").length;
  out.errors = samples.filter((s) => s?.error).length;
  out.expected = expected;
  out.observed = samples.length;
  out.valid = expected > 0 && samples.length === expected && out.usefulMissing === 0 && out.errors === 0;
  out.unavailable = samples.filter(s => s?.terminalState === "unavailable").length;
  return out;
}

export function failedSample(reason) {
  if (!["navigation_status", "route_mismatch", "navigation_failed", "session_failed", "attempt_failed", "cleanup_failed", "production_auth_failed"].includes(reason)) reason = "attempt_failed";
  return { usefulMs: null, terminalState: "missing", readyReason: reason, error: reason };
}

/** No credential material leaves this in-memory configuration. */
export function productionAuth(env, requiredSeconds, nowSeconds = Date.now() / 1000) {
  if (env.PROD_ORIGIN !== "https://chaseupside.com" || env.E2E_TEST_SECRET || env.E2E_BASE_URL || env.E2E_PAGE_ORIGIN) throw Error("invalid_production_configuration");
  const expires = Number(env.PROD_SESSION_EXPIRES_EPOCH);
  if (!Number.isFinite(expires) || expires < nowSeconds + requiredSeconds) throw Error("session_expiry_insufficient");
  const file = env.PROD_SESSION_COOKIE_FILE;
  if (!file) throw Error("session_file_invalid");
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 1 || stat.size > 4096 || (process.platform !== "win32" && (stat.mode & 0o077))) throw Error("session_file_invalid");
  const value = fs.readFileSync(file, "utf8");
  if (!/^[A-Za-z0-9_\-]+$/.test(value)) throw Error("session_file_invalid");
  return { mode: "production-cookie", origin: env.PROD_ORIGIN, value, expires };
}

export async function authenticateProduction(ctx, auth) {
  if (Date.now() / 1000 >= auth.expires) return false;
  await ctx.addCookies([{ name: "jason_session", value: auth.value, url: auth.origin, httpOnly: true, secure: true, sameSite: "Lax" }]);
  const response = await ctx.request.get(`${auth.origin}/api/auth/status`, { timeout: 30000, maxRedirects: 0 });
  if (response.status() !== 200) return false;
  const body = await response.body();
  if (body.length > 8192) return false;
  const data = JSON.parse(body.toString("utf8"));
  return data.authenticated === true && data.authMethod === "guest_pass";
}

/** Every requested cold/warm attempt survives session, navigation and cleanup failure. */
export async function collectAttempt(browser, viewport, route, timeout, auth = {mode: "local-test", origin: PAGE_ORIGIN}) {
  let ctx;
  const result = { cold: failedSample("attempt_failed"), warm: failedSample("attempt_failed") };
  try {
    ctx = await browser.newContext({ baseURL: API, viewport: VIEWPORTS[viewport], isMobile: viewport === "mobile", hasTouch: viewport === "mobile" });
    let authenticated = false;
    if (auth.mode === "production-cookie") {
      authenticated = await authenticateProduction(ctx, auth);
    } else {
      const session = await ctx.request.post(`${API}/api/test/create-session`, {
        headers: { Authorization: `Bearer ${SECRET}` }, timeout: 60_000,
      });
      authenticated = session.ok();
    }
    if (!authenticated) {
      result.cold = failedSample(auth.mode === "production-cookie" ? "production_auth_failed" : "session_failed");
      result.warm = { ...result.cold };
    } else {
      const page = await ctx.newPage();
      result.cold = await measureOnce(page, route, timeout, auth.origin);
      result.warm = await measureOnce(page, route, timeout, auth.origin);
    }
  } catch {
    // Fixed errors already initialized; retain any completed cold observation.
  } finally {
    if (ctx) {
      try { await ctx.close(); } catch {
        result.cold.error = "cleanup_failed";
        result.warm.error = "cleanup_failed";
      }
    }
  }
  return result;
}

/** Observed sample gates, deliberately distinct from complete campaign acceptance. */
export function targetVerdicts(cold, warm, expected) {
  const c = summarise(cold, expected);
  const w = summarise(warm, expected);
  const complete = c.valid && w.valid;
  return {
    coldP95Within3000Ms: c.valid && c.usefulMs.p95 <= 3000,
    warmP95Within1000Ms: w.valid && w.usefulMs.p95 <= 1000,
    everyObservedUsefulWithin5000Ms: complete && [...cold, ...warm].every(s => s.usefulMs <= 5000),
    normalNavigationP95: null,
    normalNavigationReason: "not_measured",
  };
}

export async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (args.auth === "local-test" && !SECRET) {
    console.error("session_secret_missing");
    return 2;
  }
  const routes = args.routes ? ROUTES.filter(r => args.routes.includes(r.path)) : ROUTES;
  const viewports = args.viewport === "both" ? ["desktop", "mobile"] : [args.viewport];
  const auth = args.auth === "production-cookie"
    ? productionAuth(process.env, args.runs * routes.length * viewports.length * (6 * args.timeout / 1000 + 30) + 120)
    : { mode: "local-test", origin: PAGE_ORIGIN };
  const browser = await chromium.launch({
    executablePath: process.env.PW_CHROMIUM_PATH || undefined,
    args: ["--no-sandbox"],
  });
  const report = {
    measuredAt: new Date().toISOString(), runs: args.runs, routes: {},
    protocol: {
      cold: "fresh browser context per attempt",
      warm: "second document navigation in same context; HTTP cache warm, not SPA navigation",
      useful: "visible data-bearing probe; trade includes fixed a search",
      browserVersion: browser.version(), nodeVersion: process.version, authMode: auth.mode,
      verificationSourceSha: /^[a-f0-9]{40}$/.test(process.env.GITHUB_SHA || "") ? process.env.GITHUB_SHA : null,
      deployedRevision: null,
      profile: "unthrottled", viewports: VIEWPORTS,
      percentile: "nearest-rank", observationTimeoutMs: args.timeout,
      sampleLimitation: "bounded samples; five observations do not establish a robust tail percentile",
      notMeasured: ["normal SPA navigation", "prefetched navigation", "slowed profile", "field performance"],
    },
  };
  try {
    for (const vp of viewports) {
      for (const route of routes) {
        const cold = [], warm = [];
        for (let i = 0; i < args.runs; i++) {
          const attempt = await collectAttempt(browser, vp, route, args.timeout, auth);
          cold.push(attempt.cold);
          warm.push(attempt.warm);
        }
        const key = `${vp} ${route.path}`;
        report.routes[key] = {
          viewport: vp, path: route.path, readySelector: route.ready, readyMeans: route.note,
          cold: summarise(cold, args.runs), coldAttempts: cold,
          warm: summarise(warm, args.runs), warmAttempts: warm,
          observedTargets: targetVerdicts(cold, warm, args.runs),
        };
        const { cold: c, warm: w } = report.routes[key];
        console.log(`${key}: cold p95 ${c.usefulMs.p95 ?? "missing"}ms; warm p95 ${w.usefulMs.p95 ?? "missing"}ms; missing ${c.usefulMissing + w.usefulMissing}`);
      }
    }
  } finally {
    await browser.close();
  }
  report.collectionValid = Object.keys(report.routes).length > 0 && Object.values(report.routes).every(r => r.cold.valid && r.warm.valid);
  report.observedTargetsPass = report.collectionValid && Object.values(report.routes).every(({observedTargets: t}) =>
    t.coldP95Within3000Ms && t.warmP95Within1000Ms && t.everyObservedUsefulWithin5000Ms);
  report.campaignAcceptance = "not_established";
  if (args.json) fs.writeFileSync(args.json, JSON.stringify(report, null, 2));
  console.log(`collectionValid=${report.collectionValid}; observedTargetsPass=${report.observedTargetsPass}; campaignAcceptance=not_established`);
  return report.observedTargetsPass ? 0 : 1;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then(code => { process.exitCode = code; }).catch(() => {
    console.error("baseline_failed"); process.exitCode = 1;
  });
}
