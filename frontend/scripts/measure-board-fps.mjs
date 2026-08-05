#!/usr/bin/env node
/**
 * Scroll-FPS harness for the rankings board.
 *
 * WHY THIS EXISTS
 * ---------------
 * docs/performance-optimization.md sets a target of >=50 FPS at 1x CPU
 * and >=30 at 4x for the board past its row cap ("Show more" / "Show
 * all"), and records 39.5 / 8.8 against it. Those numbers came from a
 * manual session. Windowing the table is a large, shared-component
 * change, so the claim that it helped needs an instrument anyone can
 * re-run rather than a number someone remembers taking.
 *
 * WHAT IT MEASURES
 * ----------------
 * Frames delivered during a programmatic scroll of the FULL board, via a
 * requestAnimationFrame counter inside the page. Not paint timings, not
 * a synthetic benchmark — the thing a user feels when they drag the
 * scrollbar down a 632-row table.
 *
 * CPU throttling goes through CDP `Emulation.setCPUThrottlingRate`,
 * which is what makes a fast sandbox stand in for a real laptop. 1x on
 * this hardware is not a phone; the 4x and 6x rows are the honest ones.
 *
 * IT REFUSES TO REPORT A NUMBER IT DID NOT EARN
 * ---------------------------------------------
 * Same posture as assertGateIsMeasuring() in check-bundle-sizes.mjs and
 * the needle detector in measure-duplication.mjs. If the board never
 * rendered rows, if "Show all" never took effect, or if the page never
 * actually scrolled, it exits non-zero and says which — because "60 FPS"
 * measured on a page that rendered nothing is worse than no measurement.
 *
 * USAGE
 *   node frontend/scripts/measure-board-fps.mjs [--throttle 1,4,6]
 *                                               [--runs 3] [--json]
 *
 * Requires the stack up (backend :8000, Next :3000 on a PRODUCTION
 * build — `next dev` numbers are meaningless here) and E2E_TEST_SECRET
 * matching the backend's, since the board needs a signed-in session.
 */
import { chromium } from "playwright";

const API = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";
const PAGE_ORIGIN = process.env.E2E_PAGE_ORIGIN || "http://127.0.0.1:3000";
const SECRET = process.env.E2E_TEST_SECRET || "";

function parseArgs(argv) {
  const out = { throttle: [1, 4, 6], runs: 3, json: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--throttle") out.throttle = argv[++i].split(",").map(Number);
    else if (argv[i] === "--runs") out.runs = Number(argv[++i]);
    else if (argv[i] === "--json") out.json = true;
  }
  return out;
}

// Scrolls the document top-to-bottom in fixed steps while a rAF loop
// counts delivered frames. Returns null rather than a number when the
// page did not actually move, so "it scrolled smoothly" can never be
// reported for a page that never scrolled.
const SCROLL_AND_COUNT = async ({ steps, stepPx, settleMs }) => {
  const startTop = window.scrollY;
  const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
  if (maxScroll < stepPx) return { error: `page is not scrollable (max ${maxScroll}px)` };

  let frames = 0;
  let running = true;
  const tick = () => {
    if (!running) return;
    frames += 1;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  const t0 = performance.now();
  for (let i = 0; i < steps; i += 1) {
    window.scrollBy(0, stepPx);
    // One frame of settle per step, so the scroll is paced like a drag
    // rather than a single jump the browser can collapse.
    await new Promise((r) => setTimeout(r, settleMs));
  }
  const elapsed = performance.now() - t0;
  running = false;

  const moved = window.scrollY - startTop;
  if (moved < stepPx) return { error: `scroll did not move (delta ${moved}px)` };
  return { frames, elapsedMs: elapsed, fps: (frames / elapsed) * 1000, moved, maxScroll };
};

const args = parseArgs(process.argv.slice(2));

if (!SECRET) {
  console.error("E2E_TEST_SECRET is unset — the board needs a signed-in session.");
  process.exit(2);
}

const browser = await chromium.launch({
  executablePath: process.env.PW_CHROMIUM_PATH || undefined,
  args: ["--no-sandbox"],
});
const ctx = await browser.newContext({ baseURL: API, viewport: { width: 1366, height: 900 } });

// Secret goes in an Authorization: Bearer header — server.py reads it
// from there and 404s otherwise, which looks exactly like a missing route.
const session = await ctx.request.post(`${API}/api/test/create-session`, {
  headers: { Authorization: `Bearer ${SECRET}` },
  timeout: 60_000,
});
if (!session.ok()) {
  console.error(`could not mint session: ${session.status()}`);
  await browser.close();
  process.exit(2);
}

const page = await ctx.newPage();
const cdp = await ctx.newCDPSession(page);

await page.goto(`${PAGE_ORIGIN}/rankings`, { waitUntil: "domcontentloaded" });

const rowSel = ".ds-table-wrap table tbody tr.rankings-row-clickable";
await page.locator(rowSel).first().waitFor({ timeout: 90_000 });

// Defeat the row cap — that is the whole point of the measurement. The
// board renders "Show all" only when there are more rows than the cap.
const showAll = page.getByRole("button", { name: /Show all/i });
const cappedCount = await page.locator(rowSel).count();
if (await showAll.count()) {
  await showAll.first().click();
  // "Show all" is a non-urgent transition (page.jsx), so the row count
  // grows a beat later; poll rather than assuming it is synchronous.
  await page
    .waitForFunction(
      ([sel, before]) => document.querySelectorAll(sel).length > before,
      [rowSel, cappedCount],
      { timeout: 90_000 },
    )
    .catch(() => {});
}
const mountedAfter = await page.locator(rowSel).count();

// The BOARD size, which is not the mounted count once the table is
// windowed — that is the whole point of windowing. `aria-rowcount` on
// <tbody> carries the full row count when a window is active; without a
// window the two are the same number.
//
// Getting this wrong is a trap worth naming: the first version compared
// mounted counts and refused a windowed run ("65 -> 60") as if "Show
// all" had failed, when in fact it had worked and the window was doing
// its job. A guard that fires on success is as bad as one that never
// fires.
const boardCount = await page.evaluate(() => {
  const tb = document.querySelector(".ds-table-wrap table tbody");
  const declared = Number(tb?.getAttribute("aria-rowcount") || 0);
  return declared > 0
    ? declared
    : document.querySelectorAll(".ds-table-wrap table tbody tr.rankings-row-clickable").length;
});

if (mountedAfter <= 0) {
  console.error("REFUSING TO REPORT: the board mounted zero rows.");
  await browser.close();
  process.exit(2);
}
if (boardCount <= cappedCount) {
  console.error(
    `REFUSING TO REPORT: "Show all" did not grow the board ` +
      `(${cappedCount} -> ${boardCount}). This would measure the capped ` +
      `board and call it the full one.`,
  );
  await browser.close();
  process.exit(2);
}
// The >=50-row E2E assertions must stay true under windowing, so check
// it here too rather than finding out from a red suite later.
if (mountedAfter < 50) {
  console.error(
    `REFUSING TO REPORT: only ${mountedAfter} rows mounted. ` +
      `journey.js (minRows 50) and mobile-smoke both require >= 50.`,
  );
  await browser.close();
  process.exit(2);
}
const fullCount = boardCount;

const results = [];
for (const rate of args.throttle) {
  const samples = [];
  for (let run = 0; run < args.runs; run += 1) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate });
    const r = await page.evaluate(SCROLL_AND_COUNT, {
      steps: 30,
      stepPx: 400,
      settleMs: 16,
    });
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    if (r.error) {
      console.error(`REFUSING TO REPORT at ${rate}x: ${r.error}`);
      await browser.close();
      process.exit(2);
    }
    samples.push(r.fps);
  }
  samples.sort((a, b) => a - b);
  results.push({ rate, median: samples[Math.floor(samples.length / 2)], samples });
}

// Row NODE count — the other half of the story. Windowing should cut
// mounted DOM sharply even where FPS is already acceptable.
const domNodes = await page.evaluate(() => document.querySelectorAll("*").length);
const mountedRows = await page.locator(rowSel).count();

await browser.close();

if (args.json) {
  console.log(JSON.stringify({ fullCount, mountedRows, domNodes, results }, null, 2));
} else {
  console.log(`\nrankings board scroll FPS — ${fullCount} rows after "Show all"`);
  console.log(`mounted rows: ${mountedRows}   total DOM nodes: ${domNodes}\n`);
  console.log("CPU throttle   median FPS   samples");
  console.log("-".repeat(52));
  for (const r of results) {
    console.log(
      `${String(r.rate + "x").padEnd(14)} ${r.median.toFixed(1).padEnd(12)} ` +
        r.samples.map((s) => s.toFixed(1)).join(", "),
    );
  }
  const target = { 1: 50, 4: 30 };
  console.log("");
  for (const r of results) {
    if (target[r.rate] == null) continue;
    const ok = r.median >= target[r.rate];
    console.log(
      `${r.rate}x: ${r.median.toFixed(1)} vs target >=${target[r.rate]} — ${ok ? "MEETS" : "BELOW"}`,
    );
  }
}
