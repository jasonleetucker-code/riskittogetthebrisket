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
 * Frame intervals delivered during a REAL scroll of the full board:
 * `requestAnimationFrame` timestamps sampled inside the page while CDP
 * `Input.synthesizeScrollGesture` drives the scroll from outside it.
 *
 * CPU throttling goes through CDP `Emulation.setCPUThrottlingRate`,
 * which is what makes a fast sandbox stand in for a real laptop. 1x on
 * this hardware is not a phone; the 4x and 6x rows are the honest ones.
 *
 * ⚠ THE FIRST VERSION OF THIS SCRIPT MEASURED ITSELF. Read this before
 * changing the driver back.
 *
 * It scrolled with an in-page loop:
 *
 *     for (let i = 0; i < steps; i++) {
 *       window.scrollBy(0, stepPx);
 *       await new Promise((r) => setTimeout(r, 16));   // <-- the bug
 *     }
 *
 * That is 30 discrete jumps paced by a timer, not a scroll. The frame
 * count it produced was `max(timer floor, layout+paint per step)` — i.e.
 * bounded ABOVE by the timer at ~60/s no matter how fast the page was,
 * and pushed below it by anything slow. Every absolute number it
 * reported was a property of the loop as much as of the board, and the
 * numbers it gave (trivial page 59.5, 65-row board 32.1, 964-row board
 * 28.6) are exactly what that artifact looks like: the control pinned at
 * the timer floor and both boards landing in one indistinguishable band.
 *
 * The relative comparison survived that — both boards were measured
 * identically, so "15x the rows costs ~11%" still held — but the
 * absolute framing ("the board is ~30 FPS against a >=50 target") did
 * not, and it was published before this was noticed.
 *
 * So: NO TIMER IN THE MEASUREMENT LOOP, and the page is not asked to
 * drive its own scroll. The gesture is synthesized by the browser at a
 * declared px/s, the page only records `rAF` timestamps, and the two
 * never gate each other.
 *
 * WHY INTERVALS AND NOT A MEAN
 * ----------------------------
 * Jank is long frames, not a low average. A scroll that delivers 55
 * frames in a second feels broken if four of them were 120 ms. So the
 * report leads with median FPS but also carries p95 frame time and the
 * count of frames over 32 ms (two missed vsyncs at 60 Hz), which is the
 * number that actually tracks what a user calls "chuggy".
 *
 * IT REFUSES TO REPORT A NUMBER IT DID NOT EARN
 * ---------------------------------------------
 * Same posture as assertGateIsMeasuring() in check-bundle-sizes.mjs and
 * the needle detector in measure-duplication.mjs. If the board never
 * rendered rows, if "Show all" never took effect, if the page never
 * actually scrolled, or if too few frames were sampled to say anything,
 * it exits non-zero and says which.
 *
 * THE CONTROL IS PRINTED, NOT ASSUMED
 * -----------------------------------
 * Every run first measures a trivial scrollable page at the same
 * throttle rates. That is this hardware's ceiling under this driver, and
 * it is what makes a board number readable: "28 FPS" means nothing until
 * you know whether the harness can produce 60 here at all. The old
 * script's real failure was that its control read 59.5 and nobody asked
 * why it was suspiciously close to the timer it was using.
 *
 * USAGE
 *   node frontend/scripts/measure-board-fps.mjs [--throttle 1,4,6]
 *                                               [--runs 3] [--json]
 *                                               [--no-hover] [--capped]
 *
 * `--no-hover` parks the cursor outside the table before scrolling. The
 * board has `tr:hover .sticky-name { background: ... }` on a sticky,
 * box-shadowed cell in every row (app/ds.css), so hover repaints are a
 * live suspect for scroll cost; running with and without discriminates
 * them from the sticky positioning itself.
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
  const out = { throttle: [1, 4, 6], runs: 3, json: false, hover: true, capped: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--throttle") out.throttle = argv[++i].split(",").map(Number);
    else if (argv[i] === "--runs") out.runs = Number(argv[++i]);
    else if (argv[i] === "--json") out.json = true;
    else if (argv[i] === "--no-hover") out.hover = false;
    else if (argv[i] === "--capped") out.capped = true;
  }
  return out;
}

// Gesture shape. `speed` is px/s handed to the browser's own gesture
// synthesizer, so the scroll is paced by the compositor rather than by
// anything this script does. 2400 px/s over 9000 px is ~3.75 s of
// continuous scrolling — long enough to sample a few hundred frames,
// fast enough to be a realistic flick rather than a crawl.
const SCROLL_DISTANCE_PX = 9000;
const SCROLL_SPEED_PX_S = 2400;
// Below this many frames there is no distribution to take percentiles
// of, so the script refuses. It is deliberately LOW.
//
// The first value here was 30, and it was wrong in an instructive way:
// at 4x throttle the board delivered 29 frames across the whole gesture
// — under 8 FPS — and the guard rejected the run. That is a guard firing
// on the FINDING. Refusing to report "the board is very slow" because
// the board was very slow is the same class of error as the earlier
// version's guard that rejected a windowed run for having fewer mounted
// rows, just pointing the other way.
//
// So: refuse only where the arithmetic genuinely breaks down, and flag
// thin samples in the output instead of suppressing them.
const MIN_FRAMES = 8;
// Below this the percentiles are directionally useful but coarse; the
// report says so rather than presenting them as equal to a dense run.
const THIN_SAMPLE_FRAMES = 30;

// Installed in the page BEFORE the gesture. Records rAF timestamps and
// nothing else — no scrolling, no timers, no work that could itself
// become the thing being measured.
const START_SAMPLER = () => {
  window.__fpsProbe = {
    ts: [],
    running: true,
    startY: window.scrollY,
    maxScroll: document.documentElement.scrollHeight - window.innerHeight,
  };
  const tick = (now) => {
    const p = window.__fpsProbe;
    if (!p || !p.running) return;
    p.ts.push(now);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
};

// Stops the sampler and reduces the timestamps. Returns an `error` key
// rather than a number whenever the run cannot support one.
const STOP_SAMPLER = (minFrames) => {
  const p = window.__fpsProbe;
  if (!p) return { error: "sampler was never installed" };
  p.running = false;
  const moved = window.scrollY - p.startY;
  if (p.maxScroll < 200) {
    return { error: `page is not scrollable (max ${Math.round(p.maxScroll)}px)` };
  }
  if (Math.abs(moved) < 200) {
    return { error: `scroll did not move (delta ${Math.round(moved)}px)` };
  }
  const ts = p.ts;
  if (ts.length < minFrames) {
    return { error: `only ${ts.length} frames sampled (need ${minFrames})` };
  }
  const deltas = [];
  for (let i = 1; i < ts.length; i += 1) deltas.push(ts[i] - ts[i - 1]);
  const sorted = [...deltas].sort((a, b) => a - b);
  const pct = (q) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))];
  const span = ts[ts.length - 1] - ts[0];
  return {
    frames: ts.length,
    elapsedMs: span,
    // Frames-per-second over the sampled window. With no timer pacing
    // the loop this is bounded only by the display refresh rate.
    fps: ((ts.length - 1) / span) * 1000,
    medianFrameMs: pct(0.5),
    p95FrameMs: pct(0.95),
    // Two missed vsyncs at 60 Hz. This is the jank number.
    longFrames: deltas.filter((d) => d > 32).length,
    // NOTE: `thinSample` is stamped by the CALLER, in Node. This
    // function is serialized into the page, so it can only see its own
    // arguments — a module-scope constant referenced here is a
    // ReferenceError at runtime, not a build error.
    moved: Math.round(moved),
    maxScroll: Math.round(p.maxScroll),
  };
};

/**
 * One measurement: install sampler, let the BROWSER scroll, collect.
 *
 * The gesture is issued over CDP and awaited there, so the page's main
 * thread is never asked to pace it. That is the whole difference from
 * the retracted version — see the header.
 */
async function measureScroll(page, cdp, { x, y }) {
  await page.evaluate(START_SAMPLER);
  await cdp.send("Input.synthesizeScrollGesture", {
    x,
    y,
    // Negative yDistance scrolls the content DOWN (the gesture models
    // finger/wheel movement, not content movement). The `moved` guard in
    // STOP_SAMPLER catches it if that convention ever flips.
    yDistance: -SCROLL_DISTANCE_PX,
    speed: SCROLL_SPEED_PX_S,
    gestureSourceType: "mouse",
  });
  const r = await page.evaluate(STOP_SAMPLER, MIN_FRAMES);
  if (r.error) return r;
  // Stamped here rather than in the page — see STOP_SAMPLER's note.
  return { ...r, thinSample: r.frames < THIN_SAMPLE_FRAMES };
}

/**
 * The instrument's ceiling on this hardware, under this driver.
 *
 * A trivial document of the same scroll height with none of the board's
 * DOM. Without it a board number is unreadable: "28 FPS" could be the
 * board or could be the harness, and the retracted version could not
 * tell those apart — its control read 59.5 because that was its timer.
 */
async function measureControl(page, cdp, rates, runs) {
  await page.goto("about:blank");
  await page.setContent(
    `<style>body{margin:0}div{height:40px;border-bottom:1px solid #ccc}</style>` +
      `<body>${'<div>row</div>'.repeat(600)}</body>`,
  );
  const out = [];
  for (const rate of rates) {
    const samples = [];
    for (let i = 0; i < runs; i += 1) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(200);
      await cdp.send("Emulation.setCPUThrottlingRate", { rate });
      const r = await measureScroll(page, cdp, { x: 400, y: 400 });
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
      if (r.error) {
        return { error: `control failed at ${rate}x: ${r.error}` };
      }
      samples.push(r);
    }
    samples.sort((a, b) => a.fps - b.fps);
    out.push({ rate, ...samples[Math.floor(samples.length / 2)] });
  }
  return { rows: out };
}

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

// Control FIRST, on a blank page, before the app is ever loaded — so the
// ceiling is measured on a process the board has not yet touched.
const control = await measureControl(page, cdp, args.throttle, args.runs);
if (control.error) {
  console.error(`REFUSING TO REPORT: ${control.error}`);
  console.error("The harness could not measure a trivial page, so any board");
  console.error("number it produced would be unattributable.");
  await browser.close();
  process.exit(2);
}

await page.goto(`${PAGE_ORIGIN}/rankings`, { waitUntil: "domcontentloaded" });

const rowSel = ".ds-table-wrap table tbody tr.rankings-row-clickable";
await page.locator(rowSel).first().waitFor({ timeout: 90_000 });

// Defeat the row cap — that is the whole point of the measurement. The
// board renders "Show all" only when there are more rows than the cap.
//
// `--capped` skips it, which is how the row-count question is answered:
// measure the SAME page at the default cap and at full size and compare.
// Without a paired capped run, a low full-board number cannot be
// attributed to row count rather than to the board's fixed per-frame
// cost, and attributing it wrongly is what sends someone off to build a
// virtualizer that does not help.
const showAll = page.getByRole("button", { name: /Show all/i });
const cappedCount = await page.locator(rowSel).count();
if (!args.capped && (await showAll.count())) {
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
if (!args.capped && boardCount <= cappedCount) {
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

// The gesture is aimed at the middle of the viewport, which is over the
// table. With --no-hover the pointer is parked in the left margin first,
// so `tr:hover .sticky-name` never fires. Discriminating hover repaints
// from the sticky positioning itself is a one-flag experiment; do that
// before editing any CSS.
const gestureAt = args.hover ? { x: 683, y: 500 } : { x: 8, y: 500 };
if (!args.hover) {
  await page.mouse.move(8, 500);
}

const results = [];
for (const rate of args.throttle) {
  const samples = [];
  for (let run = 0; run < args.runs; run += 1) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate });
    const r = await measureScroll(page, cdp, gestureAt);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    if (r.error) {
      console.error(`REFUSING TO REPORT at ${rate}x: ${r.error}`);
      await browser.close();
      process.exit(2);
    }
    samples.push(r);
  }
  samples.sort((a, b) => a.fps - b.fps);
  results.push({ rate, ...samples[Math.floor(samples.length / 2)], samples });
}

// Row NODE count — the other half of the story. Windowing should cut
// mounted DOM sharply even where FPS is already acceptable.
const domNodes = await page.evaluate(() => document.querySelectorAll("*").length);
const mountedRows = await page.locator(rowSel).count();

await browser.close();

const controlByRate = new Map(control.rows.map((r) => [r.rate, r]));

if (args.json) {
  console.log(
    JSON.stringify(
      { fullCount, mountedRows, domNodes, hover: args.hover, control: control.rows, results },
      null,
      2,
    ),
  );
} else {
  console.log(`\nrankings board scroll FPS — ${fullCount} rows after "Show all"`);
  console.log(
    `mounted rows: ${mountedRows}   total DOM nodes: ${domNodes}   ` +
      `hover: ${args.hover ? "cursor over table" : "cursor parked outside"}`,
  );
  console.log(
    `driver: CDP synthesizeScrollGesture, ${SCROLL_DISTANCE_PX}px @ ` +
      `${SCROLL_SPEED_PX_S}px/s — no timer in the loop\n`,
  );
  console.log("CPU     board FPS   p95 frame   >32ms   | control FPS   headroom");
  console.log("-".repeat(72));
  for (const r of results) {
    const c = controlByRate.get(r.rate);
    const ratio = c ? `${((r.fps / c.fps) * 100).toFixed(0)}% of ceiling` : "—";
    console.log(
      `${String(r.rate + "x").padEnd(8)}${r.fps.toFixed(1).padEnd(12)}` +
        `${(r.p95FrameMs.toFixed(1) + "ms").padEnd(12)}${String(r.longFrames).padEnd(8)}| ` +
        `${(c ? c.fps.toFixed(1) : "—").padEnd(14)}${ratio}` +
        // A thin sample is a real result (the page was too slow to
        // deliver many frames), just a coarse one. Marked, not hidden.
        (r.thinSample ? `   [thin: ${r.frames} frames]` : ""),
    );
  }
  const target = { 1: 50, 4: 30 };
  console.log("");
  for (const r of results) {
    if (target[r.rate] == null) continue;
    const ok = r.fps >= target[r.rate];
    const c = controlByRate.get(r.rate);
    // A target the CONTROL cannot hit is a statement about the harness
    // or the hardware, not about the board. Say so rather than reporting
    // "BELOW" and letting a reader blame the page.
    const capped = c && c.fps < target[r.rate];
    console.log(
      `${r.rate}x: ${r.fps.toFixed(1)} vs target >=${target[r.rate]} — ` +
        (capped
          ? `INCONCLUSIVE (control only reached ${c.fps.toFixed(1)} here)`
          : ok
            ? "MEETS"
            : "BELOW"),
    );
  }
}
