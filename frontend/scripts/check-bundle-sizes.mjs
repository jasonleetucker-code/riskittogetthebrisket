#!/usr/bin/env node
/**
 * Bundle-size budget enforcement for Next.js builds.
 *
 * Run after ``next build`` from the frontend dir.  Parses
 * ``.next/app-build-manifest.json``, isolates each page's
 * page-specific JS chunks (the chunks under
 * ``static/chunks/app/<route>/page-*.js``), sums their on-disk
 * size, and fails non-zero if any page is over its configured
 * budget.
 *
 * Per-page budgets live in ``BUDGETS_KB`` below.  Adjust
 * deliberately — bumping a budget because "the page got
 * bigger" is what this script is meant to catch.  Set the
 * ``--strict`` flag to fail on missing pages too (default
 * behaviour is to skip pages we don't have a budget for).
 *
 * Why a custom script and not the next-bundle-analyzer plugin?
 * The plugin is a great visualisation tool but emits an HTML
 * report, not a CI-friendly fail signal.  We want a clean
 * exit code on bloat regression so PR validation blocks merge.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const ROOT = path.resolve(
  path.dirname(url.fileURLToPath(import.meta.url)),
  "..",
);
// Honor NEXT_DIST_DIR so the post-build check looks at the same
// dir Next just wrote to.  ``deploy/deploy.sh`` runs the production
// build with ``NEXT_DIST_DIR=.next.new`` to stage chunks beside
// the live ``.next/`` for an atomic swap; the previous hardcode of
// ``.next`` made this script look at the OLD live build (or fail
// outright if ``.next`` was missing), which silently broke every
// production deploy after the staging dir was introduced.
const DIST_DIR_NAME = process.env.NEXT_DIST_DIR || ".next";
const NEXT_DIR = path.isAbsolute(DIST_DIR_NAME)
  ? DIST_DIR_NAME
  : path.join(ROOT, DIST_DIR_NAME);
const MANIFEST = path.join(NEXT_DIR, "app-build-manifest.json");

// Per-page budgets in KB (raw on-disk size of the page-specific
// JS chunks, NOT gzipped).  Values are intentionally a little
// above the current footprint so a small safety margin exists
// before CI fails — but small enough that a bloat regression
// (e.g. an unintentional library import) trips the gate.
//
// Update deliberately and document in the PR.  ``next build``
// prints the page sizes; copy the value + ~5 KB headroom.
const BUDGETS_KB = {
  // Pin each budget to roughly current size + ~15% headroom.  Updated
  // 2026-04-26 against the live build.  When you intentionally add a
  // feature that pushes a page over budget, bump the value here in
  // the same PR and call it out — that's the audit trail.
  // R6 re-pin: splitting PlayerPopup/CommandPalette out of the root
  // layout and the 21 /league sections out of that page MOVED code from
  // the shared graph into the page chunks that actually use it. Real
  // first-load JS fell on every route — /league by 215 KB, /draft by 67,
  // /trade by 51, /rankings by 42 — while three page-specific slices
  // grew, because code that used to be everyone's is now attributed to
  // its owner. These bumps record that reattribution; they are not
  // headroom for new bloat. The `[first-load …]` column now printed
  // beside each line is the number to watch.
  "/page": 90, // landing
  "/rankings/page": 75, // dense table + filter bar + popups; 65→75 (R6 reattribution)
  "/trade/page": 92, // calculator + simulator + breakdown; bumped 75→82 for the BDVM fundamentals-check panel (CES trade eval); 82→92 (R6 reattribution)
  "/draft/page": 150, // depth chart + analysis charts; bumped 125→128 for ScreenshotFab + Toast in shared layout (PR #432); 128→150 (R6 reattribution)
  "/edge/page": 30,
  "/finder/page": 20,
  "/angle/page": 30,
  // Public hub bundles every section together; bumped 165→170 for
  // /league?tab=teamAssignment. Held at 170 through R5 phase A: the
  // Card→Panel migration cost 3.2 KB (Panel + its static `Icon`
  // dependency landing in a bundle that had zero ds usage), and 2.2 of
  // that was recovered by splitting the chevron into its own module
  // rather than by bumping this number. See glyph-chevron-down.jsx.
  // R6: TIGHTENED 170→50, the one budget that moves the other way. The
  // 21 sections are now dynamic imports, so the page slice fell 174→39
  // KB. Held close so a future `import XSection from "./sections/…"`
  // — the easy mistake, since it looks like every other import — trips
  // CI instead of quietly putting all 21 back on the page.
  "/league/page": 50,
  "/rosters/page": 30,
  "/trades/page": 20,
  // Added R4: /waivers was shipping unmeasured. Pinned at the R4
  // rebuild's measured size + headroom so the claim desk can't drift
  // unnoticed like it had been.
  "/waivers/page": 36,
  "/settings/page": 60,  // bumped 50→55 for guest-pass admin panel (token reveal, list table, revoke); 55→60 for the Sharp Tracker intel section in the shared PlayerPopup chunk (useLeague + intel fetch, PR #534)
  "/login/page": 15,
  "/more/page": 10,
};

function fmtKb(bytes) {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function pageChunks(manifest, pageKey) {
  const chunks = manifest.pages[pageKey] || [];
  // Page-specific = chunks emitted under ``app/<route>/`` only.  The
  // shared framework / common chunks are amortised across every
  // page and don't represent an incremental cost for this page.
  return chunks.filter((c) => c.startsWith("static/chunks/app/"));
}

/**
 * Every JS chunk the browser loads for a route: the root layout's chunk
 * set unioned with the page's own.  This is what a visitor actually
 * downloads and — the part that dominates on a slow CPU — parses.
 *
 * Reported, not budgeted, and the distinction is deliberate.  The
 * per-page budgets above police the incremental cost of a page, which is
 * the right gate for "did this feature bloat its own route".  But they
 * see only that slice, and the slice is the SMALL one: measured on this
 * repo the root layout is ~464 KB while page chunks run 42-147 KB, so
 * the budgets covered 9-24% of the real cost.  A 500 KB shared graph
 * could grow forever without tripping anything.
 *
 * That blind spot is not hypothetical.  Moving PlayerPopup and the
 * /league sections out of the shared graph cut real first-load JS on
 * every route (/league by 215 KB) while PUSHING TWO PAGES OVER their
 * page-specific budgets, because code stopped being shared and started
 * being attributed to the routes that actually use it.  Judged on the
 * old number alone, an unambiguous improvement looked like a regression.
 */
function firstLoadChunks(manifest, pageKey) {
  const layout = manifest.pages["/layout"] || [];
  const page = manifest.pages[pageKey] || [];
  return [...new Set([...layout, ...page])].filter((c) => c.endsWith(".js"));
}

function sumBytes(nextDir, chunks) {
  let total = 0;
  for (const chunk of chunks) {
    try {
      total += fs.statSync(path.join(nextDir, chunk)).size;
    } catch {
      // Listed in the manifest but absent on disk — should not happen on
      // a clean build; skip rather than fail spuriously.
    }
  }
  return total;
}

function main() {
  if (!fs.existsSync(MANIFEST)) {
    console.error(
      `[check-bundle-sizes] manifest not found at ${MANIFEST}.\n` +
        "Run ``npm run build`` first.",
    );
    process.exit(2);
  }
  const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf-8"));
  const failures = [];
  const lines = [];

  for (const [pageKey, budgetKb] of Object.entries(BUDGETS_KB)) {
    const chunks = pageChunks(manifest, pageKey);
    if (chunks.length === 0) {
      // Page may not exist (e.g. removed) — skip silently rather
      // than fail.  ``--strict`` flag below would change this.
      lines.push(`  ${pageKey.padEnd(22)} (no chunks — skipped)`);
      continue;
    }
    const totalBytes = sumBytes(NEXT_DIR, chunks);
    const firstLoadBytes = sumBytes(
      NEXT_DIR,
      firstLoadChunks(manifest, pageKey),
    );
    const totalKb = totalBytes / 1024;
    const overshoot = totalKb - budgetKb;
    const verdict =
      overshoot > 0
        ? `OVER  by ${overshoot.toFixed(1)} KB`
        : `ok    (${(-overshoot).toFixed(1)} KB headroom)`;
    lines.push(
      `  ${pageKey.padEnd(22)} ${fmtKb(totalBytes).padStart(10)} / ${budgetKb} KB budget   ${verdict}` +
        `   [first-load ${fmtKb(firstLoadBytes)}]`,
    );
    if (overshoot > 0) {
      failures.push({ pageKey, totalKb, budgetKb });
    }
  }

  const layoutBytes = sumBytes(
    NEXT_DIR,
    (manifest.pages["/layout"] || []).filter((c) => c.endsWith(".js")),
  );
  console.log("[check-bundle-sizes] per-page chunk sizes:");
  console.log(
    `  (root layout, loaded by EVERY route: ${fmtKb(layoutBytes)} — budgeted below is the page-specific slice only)`,
  );
  for (const line of lines) console.log(line);

  if (failures.length > 0) {
    console.error(
      `\n[check-bundle-sizes] ${failures.length} page(s) over budget:`,
    );
    for (const f of failures) {
      console.error(
        `  ${f.pageKey}: ${f.totalKb.toFixed(1)} KB > ${f.budgetKb} KB`,
      );
    }
    console.error(
      "\nIf the bloat is intentional, bump the budget in " +
        "``frontend/scripts/check-bundle-sizes.mjs::BUDGETS_KB`` " +
        "and document the why in your PR description.",
    );
    process.exit(1);
  }
  console.log("[check-bundle-sizes] all pages under budget ✓");
}

main();
