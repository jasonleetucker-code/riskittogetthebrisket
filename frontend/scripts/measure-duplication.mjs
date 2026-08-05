#!/usr/bin/env node
/**
 * measure-duplication.mjs — reproduction harness for the ambient
 * SSR-streaming duplication race.
 *
 * WHAT THIS MEASURES
 * ------------------
 * Some loads leave React's streaming staging container (`<div id="S:1">`)
 * behind, so the page's markup ends up in the document twice.  The
 * duplicate has no client rects and never reaches the accessibility tree,
 * so it is invisible in a screenshot, in an a11y snapshot, and to a human
 * clicking around.  It is still duplicate DOM and duplicate element ids.
 *
 * `docs/performance-optimization.md` records it as a PRE-EXISTING,
 * app-wide race: 1/15 loads on /arbitrage and 1/45 on /waivers, measured
 * identically on `main` and on the round-6 branch.  Round 6's `dynamic()`
 * regression was a different, deterministic instance of the same shape —
 * that one is fixed; this one is not.
 *
 * WHY A DEDICATED HARNESS
 * -----------------------
 * Every metric in the performance ledger — CLS, LCP, INP, FPS, bundle
 * size — was UNCHANGED by a bug that rendered every page twice.  The only
 * thing that ever caught it was a Playwright strict-mode violation.  A
 * rate this low also cannot be established by hand: at a 1/45 base rate,
 * 15 loads cannot distinguish 2% from 0%.  Hence: many loads, a generic
 * oracle, and a printed rate.
 *
 * THE ORACLE
 * ----------
 * Deliberately route-agnostic, so adding a route needs no needle string:
 *
 *   staged   — any `div[id^="S:"]` left in the document.  This is the
 *              direct signature; React removes these on a clean swap.
 *   dupIds   — element ids present more than once.  This is the actual
 *              HARM (duplicate ids break getElementById, label/for,
 *              aria-labelledby and anchor links), so it is what the
 *              assertion should be written against, not a proxy.
 *   mainCount/h1Count — corroborating structural counts.  NOTE these are
 *              route-dependent: the shell renders `<main id="main">` and
 *              SOME pages render their own `<main>` too (/waivers does,
 *              /arbitrage does not).  So a baseline is captured per route
 *              rather than assumed to be a constant.
 *
 * Each load is sampled TWICE — once at domcontentloaded, once after a
 * settle delay — because "transient during streaming" and "left behind
 * permanently" are different defects with different fixes, and a single
 * sample cannot tell them apart.
 *
 * USAGE
 *   node frontend/scripts/measure-duplication.mjs [--loads 200] [--routes a,b]
 *
 * Requires both services up and a prod build (`next build && next start`)
 * — dev mode streams differently and will not reproduce faithfully.
 * `playwright` resolves from the REPO ROOT node_modules (it is a root
 * devDependency, not a frontend one); node's upward resolution handles
 * that from this directory.
 *
 * Exit codes: 0 clean, 1 duplication observed, 2 harness could not
 * measure (never conflate "measured zero" with "failed to measure" —
 * same posture as assertGateIsMeasuring() in check-bundle-sizes.mjs).
 */
import { chromium } from "playwright";

const PAGE_ORIGIN = process.env.E2E_PAGE_ORIGIN || "http://127.0.0.1:3000";
const API_ORIGIN = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";
const SECRET = process.env.E2E_TEST_SECRET || "";
// Escape hatch for sandboxes that ship a Chromium whose build number does
// not match the pinned @playwright/test.  Unset on a normal machine, where
// Playwright resolves its own bundled browser.
const CHROMIUM_PATH = process.env.PW_CHROMIUM_PATH || "";

// Routes WITH their own loading.jsx (an App Router loading.jsx implicitly
// wraps that segment's children in a <Suspense> boundary — the same shape
// as the dynamic() regression) versus routes WITHOUT one.  The split is
// the experiment: if only the first group stages, loading.jsx is the
// cause.  Both measured routes from the ledger are in the first group.
const DEFAULT_ROUTES = [
  { path: "/arbitrage", loadingJsx: true },
  { path: "/waivers", loadingJsx: true },
  { path: "/rankings", loadingJsx: true },
  { path: "/trade", loadingJsx: true },
  { path: "/bdvm", loadingJsx: false },
  { path: "/finder", loadingJsx: false },
  { path: "/trending", loadingJsx: false },
  { path: "/settings", loadingJsx: false },
];

/**
 * Needles — the LIKE-FOR-LIKE half of the oracle.
 *
 * The structural probe below (ids / <main> / <h1>) found zero defects in
 * 1,200 loads.  That is not yet a contradiction of the ledger's 1/15 and
 * 1/45, because the ledger's detector was different: a Playwright
 * strict-mode violation, i.e. a LOCATOR resolving to 2 elements.  A
 * duplicate carrying no id and adding no landmark would slip past the
 * structural probe, so retiring a measured number on it alone would be
 * the retracted-firstLoadChunks mistake in a new costume.
 *
 * These are therefore the specs' OWN locators, not hand-rolled text
 * matches — `getByLabel(/Include rookies/i, {exact:false})` is copied
 * from waivers-smoke.spec.js:38 via NAME.waiverRookieToggle
 * (helpers/journey.js:24).  `.count() > 1` is precisely the condition
 * that makes strict mode throw.
 *
 * Note "Include rookies" also appears in an EmptyState `description`
 * (waivers/page.jsx:510) as well as the toggle label (:727), which is
 * why the count is compared against the route's own modal baseline
 * rather than a hardcoded 1 — same self-calibrating rule the <main>
 * count uses, and the reason a naive text match was rejected here.
 */
const ROUTE_NEEDLES = {
  "/waivers": [{ kind: "label", value: /Include rookies/i }],
  "/arbitrage": [{ kind: "text", value: "Pick a team and scan" }],
};

async function countNeedles(page, routePath) {
  const out = {};
  // Universal: a full-page duplicate doubles the <h1>, on every route.
  out.h1Role = await page.getByRole("heading", { level: 1 }).count();
  for (const nd of ROUTE_NEEDLES[routePath] || []) {
    const loc =
      nd.kind === "label"
        ? page.getByLabel(nd.value, { exact: false })
        : page.getByText(nd.value, { exact: false });
    out[String(nd.value)] = await loc.count();
  }
  return out;
}

function parseArgs(argv) {
  const out = { loads: 200, routes: null, settleMs: 750 };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--loads") out.loads = Number(argv[++i]);
    else if (argv[i] === "--routes") out.routes = argv[++i].split(",");
    else if (argv[i] === "--settle-ms") out.settleMs = Number(argv[++i]);
  }
  if (!Number.isFinite(out.loads) || out.loads < 1) {
    console.error("--loads must be a positive integer");
    process.exit(2);
  }
  return out;
}

// Runs in the page.  Kept dependency-free and defensive: it must never
// throw, because a throw here would be indistinguishable from a clean
// sample in the aggregate.
const PROBE = () => {
  const ids = Object.create(null);
  let dupIds = [];
  for (const el of document.querySelectorAll("[id]")) {
    const id = el.id;
    if (!id) continue;
    ids[id] = (ids[id] || 0) + 1;
  }
  for (const [id, n] of Object.entries(ids)) if (n > 1) dupIds.push(`${id}×${n}`);
  const staged = Array.from(document.querySelectorAll('div[id^="S:"]')).map((d) => d.id);
  return {
    staged,
    dupIds,
    mainCount: document.querySelectorAll("main").length,
    h1Count: document.querySelectorAll("h1").length,
    url: location.pathname,
  };
};

async function mintSession(context) {
  if (!SECRET) return false;
  const res = await context.request.post(`${API_ORIGIN}/api/test/create-session`, {
    headers: { Authorization: `Bearer ${SECRET}` },
  });
  return res.ok();
}

function mode(values) {
  const counts = new Map();
  for (const v of values) counts.set(v, (counts.get(v) || 0) + 1);
  let best = null;
  let bestN = -1;
  for (const [v, n] of counts) if (n > bestN) ((best = v), (bestN = n));
  return best;
}

/**
 * `phase` is load-bearing.  At domcontentloaded a `div[id^="S:"]` is
 * React streaming NORMALLY — the staging container is how streamed
 * content arrives, and it is removed on the swap.  Measured here at 26.7%
 * of loads with zero survivors after settle, so treating its mere
 * presence as the defect (the obvious reading of the ledger's "#S:1
 * present" row) would report a healthy app as 27% broken.
 *
 * The defect is a staging container that PERSISTS, or structure that is
 * duplicated once the page has settled.  So DCL samples are recorded as
 * context only, and the pass/fail verdict comes from the settled ones.
 */
function summarize(samples, phase) {
  const mainMode = mode(samples.map((s) => s.mainCount));
  const h1Mode = mode(samples.map((s) => s.h1Count));
  // Per-needle modal baseline, for the same reason mainCount has one: the
  // clean count is a property of the route, not a constant.
  const needleKeys = [...new Set(samples.flatMap((s) => Object.keys(s.needles || {})))];
  const needleMode = {};
  for (const k of needleKeys) {
    needleMode[k] = mode(samples.map((s) => (s.needles || {})[k]).filter((v) => v !== undefined));
  }
  const needleExceeded = (s) =>
    needleKeys.filter((k) => (s.needles || {})[k] > needleMode[k]);
  const isDirty = (s) =>
    s.dupIds.length > 0 ||
    s.mainCount > mainMode ||
    s.h1Count > h1Mode ||
    needleExceeded(s).length > 0 ||
    (phase === "settle" && s.staged.length > 0);
  const dirty = samples.filter(isDirty);
  return {
    n: samples.length,
    dirty: dirty.length,
    rate: samples.length ? dirty.length / samples.length : 0,
    stagedSeen: samples.filter((s) => s.staged.length > 0).length,
    mainMode,
    h1Mode,
    mains: [...new Set(samples.map((s) => s.mainCount))].sort(),
    needleMode,
    needlesExceeded: dirty.length ? needleExceeded(dirty[0]) : [],
    exampleDupIds: dirty.length ? dirty[0].dupIds.slice(0, 5) : [],
    exampleStaged: dirty.length ? dirty[0].staged.slice(0, 3) : [],
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const routes = args.routes
    ? args.routes.map((p) => ({ path: p, loadingJsx: null }))
    : DEFAULT_ROUTES;

  const browser = await chromium.launch(
    CHROMIUM_PATH ? { executablePath: CHROMIUM_PATH } : {},
  );
  const context = await browser.newContext();
  const authed = await mintSession(context);
  if (!authed) {
    console.error(
      "FATAL: could not mint a session via /api/test/create-session.\n" +
        "Set E2E_TEST_SECRET (and E2E_TEST_MODE=1 + E2E_TEST_USERNAME on the\n" +
        "server) — without it every private route redirects to /login and\n" +
        "this harness would report a clean zero for pages it never loaded.",
    );
    await browser.close();
    process.exit(2);
  }

  const results = [];
  let measuredAnything = false;

  for (const route of routes) {
    const atDcl = [];
    const atSettle = [];
    let redirected = 0;

    for (let i = 0; i < args.loads; i += 1) {
      const page = await context.newPage();
      try {
        await page.goto(`${PAGE_ORIGIN}${route.path}`, {
          waitUntil: "domcontentloaded",
        });
        const a = await page.evaluate(PROBE);
        if (a.url.startsWith("/login")) {
          redirected += 1;
          continue;
        }
        atDcl.push(a);
        await page.waitForTimeout(args.settleMs);
        const settled = await page.evaluate(PROBE);
        settled.needles = await countNeedles(page, route.path);
        atSettle.push(settled);
        measuredAnything = true;
      } catch {
        // A single failed load is noise; a route that never loads shows
        // up as n=0 below and is reported, not silently skipped.
      } finally {
        await page.close();
      }
    }

    if (redirected > 0) {
      console.error(
        `FATAL: ${route.path} redirected to /login on ${redirected} loads — session not honoured.`,
      );
      await browser.close();
      process.exit(2);
    }

    results.push({
      route: route.path,
      loadingJsx: route.loadingJsx,
      dcl: summarize(atDcl, "dcl"),
      settle: summarize(atSettle, "settle"),
    });
  }

  await browser.close();

  if (!measuredAnything) {
    console.error("FATAL: harness measured zero loads. Are both services up on a PROD build?");
    process.exit(2);
  }

  console.log(`\nSSR duplication — ${args.loads} loads/route, settle ${args.settleMs}ms`);
  console.log(
    "`streaming` = staging container seen mid-load (NORMAL). `DEFECT` = persists/duplicates after settle.\n",
  );
  console.log(
    "route                loading.jsx  streaming@DCL    DEFECT@settle    <main>  example",
  );
  console.log("-".repeat(100));
  for (const r of results) {
    const streaming = `${r.dcl.stagedSeen}/${r.dcl.n} (${((r.dcl.stagedSeen / (r.dcl.n || 1)) * 100).toFixed(1)}%)`;
    const st = `${r.settle.dirty}/${r.settle.n} (${(r.settle.rate * 100).toFixed(1)}%)`;
    const ex = r.settle.exampleStaged[0] || r.settle.exampleDupIds[0] || "";
    console.log(
      `${r.route.padEnd(20)} ${String(r.loadingJsx).padEnd(12)} ${streaming.padEnd(16)} ${st.padEnd(16)} ${String(r.settle.mainMode).padEnd(7)} ${ex}`,
    );
  }

  // Verdict is the SETTLED state only — see summarize()'s note.
  const anyDirty = results.some((r) => r.settle.dirty > 0);
  console.log(`\n${anyDirty ? "DUPLICATION OBSERVED" : "clean"}\n`);
  console.log(JSON.stringify(results, null, 2));
  process.exit(anyDirty ? 1 : 0);
}

main().catch((err) => {
  console.error("FATAL: harness crashed:", err);
  process.exit(2);
});
