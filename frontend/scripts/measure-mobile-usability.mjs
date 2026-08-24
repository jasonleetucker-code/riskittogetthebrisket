#!/usr/bin/env node
/**
 * measure-mobile-usability.mjs — V1-109 / W26-F015 / W26-F017.
 *
 * WHY THIS EXISTS
 * ---------------
 * The V1-109 row inherits four specific claims from the 2026-07 audit:
 *
 *   W26-F015  /trade's sticky verdict bar is clipped by a floating action
 *             button; /draft's teams panel refuses to stack at 390px.
 *   W26-F017  873 of 900 interactive targets on /rankings are under 44px
 *             at 390px, and type as small as 9.0px ships on three pages.
 *
 * Those were measured BEFORE #984 restyled the shell across every route
 * and before #1003 windowed the rankings board. Under this repo's own
 * rule — NO REPRODUCTION → NO REPAIR — they are claims, not findings,
 * until re-measured at the current head. This script re-measures them so
 * a repair is aimed at something that still exists, and so a claim that
 * has since been fixed is reported as fixed rather than silently
 * "repaired" a second time.
 *
 * WHAT IT REFUSES TO DO
 * ---------------------
 * Report a number it cannot stand behind. Every check either produces a
 * measurement or an explicit `unavailable` with a reason. A route that
 * fails to reach a useful state is NOT counted as "0 violations" — that
 * is the failure mode this codebase calls MISSING IS NEVER ZERO, and on
 * an a11y sweep it reads as a clean bill of health for a page that never
 * rendered.
 *
 * THE CONTROL
 * -----------
 * `--control` renders a synthetic page with three targets of KNOWN size
 * (30px, 44px, 48px) and one 9px span. If the instrument does not report
 * exactly one undersized target and one undersized font on it, the
 * instrument is broken and every other number in the run is void. The
 * repo has been burned once by an instrument measuring itself (#760's
 * setTimeout-paced FPS harness), so a self-check is not optional.
 *
 * WHAT COUNTS AS AN INTERACTIVE TARGET
 * ------------------------------------
 * Rendered, hit-testable controls only: a/button/input/select/textarea
 * plus anything with an interactive ARIA role or a tabindex. Excluded,
 * with reasons, because counting them produces a number nobody can act
 * on:
 *   - zero-area / display:none / visibility:hidden — not on screen;
 *   - elements inside `[aria-hidden="true"]` — not offered to anyone;
 *   - `<a>` with no href — not a control;
 *   - inputs of type hidden.
 * WCAG 2.5.5 asks for 44×44 CSS px. An element smaller than that is
 * still compliant if its parent hit area or padding reaches 44 — this
 * script measures the element's own border box and reports the shortfall
 * distribution, so the output is a triage list, not a verdict.
 *
 * USAGE
 *   node frontend/scripts/measure-mobile-usability.mjs \
 *     [--routes /rankings,/trade,/draft] [--viewport 390x844] \
 *     [--json out.json] [--control]
 *
 * Env: PAGE_ORIGIN (default http://127.0.0.1:3000)
 *      API_ORIGIN  (default http://127.0.0.1:8000)
 *      E2E_TEST_SECRET — required for private routes.
 *      PW_CHROMIUM_PATH — chromium binary override.
 */
import fs from "node:fs";
import { chromium } from "playwright";

const DEFAULT_ROUTES = ["/rankings", "/trade", "/draft"];
const MIN_TARGET_PX = 44; // WCAG 2.5.5 AAA / 2.5.8 AA is 24; 44 is the row's own bar.
const MIN_FONT_PX = 12; // the audit's "9.0px ships" claim is against this.

function parseArgs(argv) {
  const out = {
    routes: DEFAULT_ROUTES,
    viewport: { width: 390, height: 844 },
    json: null,
    control: false,
    timeout: 45_000,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--routes") out.routes = argv[++i].split(",").map((s) => s.trim());
    else if (a === "--viewport") {
      const [w, h] = argv[++i].split("x").map(Number);
      out.viewport = { width: w, height: h };
    } else if (a === "--json") out.json = argv[++i];
    else if (a === "--control") out.control = true;
    else if (a === "--timeout") out.timeout = Number(argv[++i]);
  }
  return out;
}

/** Runs IN the page. Returns raw measurements, no verdicts. */
const PROBE = (minTarget, minFont) => {
  const vw = window.innerWidth;
  const isHidden = (el) => {
    if (el.closest('[aria-hidden="true"]')) return true;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) return true;
    const r = el.getBoundingClientRect();
    return r.width === 0 || r.height === 0;
  };

  const SEL =
    'a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"]),' +
    '[role="button"],[role="link"],[role="tab"],[role="checkbox"],[role="switch"],[role="menuitem"]';

  const targets = [];
  for (const el of document.querySelectorAll(SEL)) {
    if (el.tagName === "INPUT" && el.type === "hidden") continue;
    if (isHidden(el)) continue;
    const r = el.getBoundingClientRect();
    targets.push({
      tag: el.tagName.toLowerCase(),
      w: Math.round(r.width * 10) / 10,
      h: Math.round(r.height * 10) / 10,
      label: (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40),
    });
  }

  // Font sizes over elements that actually render text.
  const fonts = new Map();
  for (const el of document.querySelectorAll("body *")) {
    if (isHidden(el)) continue;
    const hasOwnText = Array.from(el.childNodes).some(
      (n) => n.nodeType === 3 && n.textContent.trim().length > 0,
    );
    if (!hasOwnText) continue;
    const px = Math.round(parseFloat(getComputedStyle(el).fontSize) * 10) / 10;
    if (!Number.isFinite(px)) continue;
    const key = String(px);
    if (!fonts.has(key)) fonts.set(key, { px, count: 0, sample: "" });
    const rec = fonts.get(key);
    rec.count += 1;
    if (!rec.sample) rec.sample = el.textContent.trim().slice(0, 40);
  }

  // Horizontal overflow: the page body must never scroll sideways.
  const docW = document.documentElement.scrollWidth;

  // Elements wider than the viewport — the "refuses to stack" signature.
  const overflowing = [];
  for (const el of document.querySelectorAll("body *")) {
    if (isHidden(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width > vw + 1 && r.height > 40) {
      overflowing.push({
        tag: el.tagName.toLowerCase(),
        cls: String(el.className || "").slice(0, 60),
        w: Math.round(r.width),
      });
    }
  }

  // Fixed/sticky elements and their overlaps — the "clipped by the FAB"
  // signature.  Two fixed elements that intersect means one is covering
  // the other; which one loses depends on z-index, so both are reported.
  const pinned = [];
  for (const el of document.querySelectorAll("body *")) {
    if (isHidden(el)) continue;
    const pos = getComputedStyle(el).position;
    if (pos !== "fixed" && pos !== "sticky") continue;
    const r = el.getBoundingClientRect();
    pinned.push({
      tag: el.tagName.toLowerCase(),
      cls: String(el.className || "").slice(0, 60),
      pos,
      z: getComputedStyle(el).zIndex,
      rect: {
        x: Math.round(r.x),
        y: Math.round(r.y),
        w: Math.round(r.width),
        h: Math.round(r.height),
      },
    });
  }
  const overlaps = [];
  for (let i = 0; i < pinned.length; i++) {
    for (let j = i + 1; j < pinned.length; j++) {
      const a = pinned[i].rect;
      const b = pinned[j].rect;
      const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (ox > 0 && oy > 0) {
        overlaps.push({
          a: `${pinned[i].tag}.${pinned[i].cls}`,
          b: `${pinned[j].tag}.${pinned[j].cls}`,
          overlapPx: { x: ox, y: oy },
          area: ox * oy,
        });
      }
    }
  }

  return {
    viewportWidth: vw,
    documentScrollWidth: docW,
    horizontalOverflowPx: Math.max(0, docW - vw),
    targets: {
      total: targets.length,
      under: targets.filter((t) => t.w < minTarget || t.h < minTarget).length,
      worst: targets
        .filter((t) => t.w < minTarget || t.h < minTarget)
        .sort((x, y) => Math.min(x.w, x.h) - Math.min(y.w, y.h))
        .slice(0, 10),
    },
    fonts: {
      distinctSizes: Array.from(fonts.values()).sort((a, b) => a.px - b.px),
      smallestPx: Math.min(...Array.from(fonts.values()).map((f) => f.px)),
      underCount: Array.from(fonts.values())
        .filter((f) => f.px < minFont)
        .reduce((n, f) => n + f.count, 0),
    },
    wideElements: overflowing.slice(0, 10),
    pinnedCount: pinned.length,
    pinnedOverlaps: overlaps.sort((a, b) => b.area - a.area).slice(0, 5),
  };
};

/** A page of KNOWN geometry — if this misreads, nothing else counts. */
const CONTROL_HTML = `<!doctype html><meta name=viewport content="width=device-width">
<style>body{margin:0;font-size:16px}button{display:block;border:0;padding:0}</style>
<button style="width:30px;height:30px">a</button>
<button style="width:44px;height:44px">b</button>
<button style="width:48px;height:48px">c</button>
<span style="font-size:9px">tiny</span><p>normal</p>`;

async function measureRoute(page, url, timeout) {
  const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout });
  const status = resp ? resp.status() : null;
  // Let the shell settle: the probe reads laid-out geometry, so measuring
  // mid-stream reports a page that does not exist for any user.
  await page.waitForLoadState("networkidle", { timeout }).catch(() => {});
  await page.waitForTimeout(1200);
  const hasMain = await page.locator("main").count();
  const h1 = (await page.locator("h1").first().textContent().catch(() => "")) || "";
  const data = await page.evaluate(
    ([t, f]) => PROBE_IMPL(t, f),
    [MIN_TARGET_PX, MIN_FONT_PX],
  );
  return { status, hasMain: hasMain > 0, h1: h1.trim().slice(0, 60), ...data };
}

const args = parseArgs(process.argv.slice(2));
const PAGE_ORIGIN = process.env.PAGE_ORIGIN || "http://127.0.0.1:3000";
const API_ORIGIN = process.env.API_ORIGIN || "http://127.0.0.1:8000";

const browser = await chromium.launch({
  executablePath: process.env.PW_CHROMIUM_PATH || undefined,
  args: ["--no-sandbox"],
});
const context = await browser.newContext({
  viewport: args.viewport,
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
});
// Install the probe as a page function so both the control and the real
// routes run byte-identical measurement code.
await context.addInitScript(`window.PROBE_IMPL = ${PROBE.toString()};`);

const report = {
  measuredAt: new Date().toISOString(),
  viewport: `${args.viewport.width}x${args.viewport.height}`,
  minTargetPx: MIN_TARGET_PX,
  minFontPx: MIN_FONT_PX,
  control: null,
  routes: {},
};

// ── control ────────────────────────────────────────────────────────────
{
  const page = await context.newPage();
  await page.setContent(CONTROL_HTML);
  const c = await page.evaluate(
    ([t, f]) => PROBE_IMPL(t, f),
    [MIN_TARGET_PX, MIN_FONT_PX],
  );
  const ok = c.targets.total === 3 && c.targets.under === 1 && c.fonts.smallestPx === 9;
  report.control = {
    ok,
    targetsSeen: c.targets.total,
    undersizedSeen: c.targets.under,
    smallestFontPx: c.fonts.smallestPx,
    expected: { targetsSeen: 3, undersizedSeen: 1, smallestFontPx: 9 },
  };
  await page.close();
  if (!ok) {
    console.error("CONTROL FAILED — the instrument is misreading known geometry.");
    console.error(JSON.stringify(report.control, null, 2));
    await browser.close();
    process.exit(2);
  }
  console.log(`control ok — 3 targets, 1 undersized, smallest font 9px`);
}
if (args.control) {
  await browser.close();
  console.log("control-only run; no routes measured.");
  process.exit(0);
}

// ── session ────────────────────────────────────────────────────────────
const secret = process.env.E2E_TEST_SECRET;
if (secret) {
  const page = await context.newPage();
  // The secret travels as `Authorization: Bearer`, not in the body —
  // the endpoint 404s (deliberately, not 401) on anything else, which
  // reads exactly like the route not existing.
  const res = await page.request.post(`${API_ORIGIN}/api/test/create-session`, {
    headers: { Authorization: `Bearer ${secret}` },
  });
  if (!res.ok()) {
    console.error(`session mint failed: ${res.status()} — private routes will not render.`);
    await browser.close();
    process.exit(2);
  }
  const cookies = await page.context().cookies();
  // Re-point the API-origin cookie at the page origin so Next serves authed.
  await context.addCookies(
    cookies.map((c) => ({ ...c, url: undefined, domain: "127.0.0.1", path: "/" })),
  );
  await page.close();
  console.log("session minted");
} else {
  console.error("E2E_TEST_SECRET unset — refusing to report on private routes.");
  await browser.close();
  process.exit(2);
}

// ── routes ─────────────────────────────────────────────────────────────
for (const route of args.routes) {
  const page = await context.newPage();
  try {
    const r = await measureRoute(page, `${PAGE_ORIGIN}${route}`, args.timeout);
    // A route that never reached a useful state must not read as clean.
    if (!r.hasMain || r.targets.total === 0) {
      report.routes[route] = {
        unavailable: true,
        reason: !r.hasMain
          ? "no <main> landmark — page did not render"
          : "zero interactive targets — page rendered empty",
        status: r.status,
      };
      console.log(`${route.padEnd(12)} UNAVAILABLE (${report.routes[route].reason})`);
    } else {
      report.routes[route] = r;
      console.log(
        `${route.padEnd(12)} targets ${r.targets.under}/${r.targets.total} under ${MIN_TARGET_PX}px · ` +
          `smallest font ${r.fonts.smallestPx}px · h-overflow ${r.horizontalOverflowPx}px · ` +
          `pinned ${r.pinnedCount} (${r.pinnedOverlaps.length} overlapping) · ` +
          `wide-elements ${r.wideElements.length}`,
      );
    }
  } catch (err) {
    report.routes[route] = { unavailable: true, reason: String(err).slice(0, 200) };
    console.log(`${route.padEnd(12)} UNAVAILABLE (${String(err).slice(0, 80)})`);
  } finally {
    await page.close();
  }
}

await browser.close();
if (args.json) {
  fs.writeFileSync(args.json, JSON.stringify(report, null, 2));
  console.log(`wrote ${args.json}`);
}
