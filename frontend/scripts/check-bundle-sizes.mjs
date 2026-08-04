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
// Where the app-router page chunks live.  Derived from DISK, not from
// ``app-build-manifest.json``, because that manifest is gone.
//
// Next 16 does not emit it at all — under either builder.  Worse, no
// Next 16 manifest maps an app-router page key to its chunks:
// ``build-manifest.json``'s ``pages`` holds only the legacy pages-router
// ``/_app``, and ``app-path-routes-manifest.json`` maps page keys to
// ROUTE paths, not chunk files.  Reading any of those would hand this
// script an object whose ``pages[pageKey]`` is undefined, every page
// would log "no chunks — skipped", and the gate would PASS while
// measuring nothing.  That silent-pass is the failure mode this
// rewrite exists to prevent; see assertGateIsMeasuring() below.
//
// The on-disk layout, by contrast, is identical across Next 15 and
// Next 16 --webpack, and maps 1:1 from the page key (verified against
// real builds of both on 2026-08-04):
//
//     /page           -> static/chunks/app/page-<hash>.js
//     /rankings/page  -> static/chunks/app/rankings/page-<hash>.js
//
// Under Next 16's DEFAULT builder (Turbopack) there is no such layout —
// chunks are flat and content-hashed (``static/chunks/1de9myc15dqxx.js``)
// with nothing tying a file to a route. Per-page attribution is simply
// not available there, so this script refuses loudly rather than
// reporting a pass it cannot justify.
const APP_CHUNK_DIR = path.join(NEXT_DIR, "static", "chunks", "app");

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
  "/page": 90, // landing
  "/rankings/page": 65, // dense table + filter bar + popups
  "/trade/page": 82, // calculator + simulator + breakdown; bumped 75→82 for the BDVM fundamentals-check panel (CES trade eval)
  "/draft/page": 128, // depth chart + analysis charts; bumped 125→128 for ScreenshotFab + Toast in shared layout (PR #432)
  "/edge/page": 30,
  "/finder/page": 20,
  "/angle/page": 30,
  // Public hub bundles every section together; bumped 165→170 for
  // /league?tab=teamAssignment. Held at 170 through R5 phase A: the
  // Card→Panel migration cost 3.2 KB (Panel + its static `Icon`
  // dependency landing in a bundle that had zero ds usage), and 2.2 of
  // that was recovered by splitting the chevron into its own module
  // rather than by bumping this number. See glyph-chevron-down.jsx.
  "/league/page": 170,
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

// Page key -> that page's own chunk files, resolved on disk.
//
// ``/rankings/page`` becomes ``<app>/rankings/page-*.js``: the key
// minus its leading slash, with a hash suffix.  Only chunks under
// ``static/chunks/app/`` count — shared framework/common chunks are
// amortised across every page and are not an incremental cost here.
// That is the same set the old manifest filter produced; verified
// against a real Next 15 build where every page key mapped to exactly
// the file this derives.
function pageChunks(pageKey) {
  const rel = pageKey.replace(/^\//, "");
  const dir = path.join(APP_CHUNK_DIR, path.dirname(rel));
  const base = path.basename(rel);
  let entries;
  try {
    entries = fs.readdirSync(dir);
  } catch {
    return [];
  }
  // ``page-<hash>.js`` — anchored so ``/page`` cannot also swallow
  // ``page-legacy-*.js`` or a sibling route sharing the prefix.
  const re = new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}-[^/]+\\.js$`);
  return entries.filter((e) => re.test(e)).map((e) => path.join(dir, e));
}

// Refuse to report success when the gate could not actually measure.
//
// Every earlier version of this script degraded silently when its
// assumption about Next's output broke: a missing page logged
// "no chunks — skipped" and the run still exited 0.  That is fine for
// ONE removed route and catastrophic when the layout changes wholesale,
// which is exactly what Next 16 + Turbopack does.  If nothing resolved,
// something structural is wrong and a green tick would be a lie.
function assertGateIsMeasuring(resolvedCount) {
  if (resolvedCount > 0) return;
  console.error(
    "[check-bundle-sizes] resolved chunks for ZERO of the " +
      `${Object.keys(BUDGETS_KB).length} budgeted pages under ${APP_CHUNK_DIR}.\n` +
      "\n" +
      "Refusing to pass: this gate cannot measure anything, and exiting 0\n" +
      "would report a budget check that never ran.\n" +
      "\n" +
      "Most likely cause: the build used Turbopack, which emits a flat,\n" +
      "content-hashed chunk layout with no per-route attribution. Next 16\n" +
      "makes Turbopack the default builder. Build with ``next build\n" +
      "--webpack`` to restore the per-route layout this gate reads, or\n" +
      "replace this script with a Turbopack-native measurement.",
  );
  process.exit(2);
}

function main() {
  if (!fs.existsSync(NEXT_DIR)) {
    console.error(
      `[check-bundle-sizes] build output not found at ${NEXT_DIR}.\n` +
        "Run ``npm run build`` first.",
    );
    process.exit(2);
  }
  if (!fs.existsSync(APP_CHUNK_DIR)) {
    console.error(
      `[check-bundle-sizes] no app-router chunk dir at ${APP_CHUNK_DIR}.\n` +
        "\n" +
        "Under Next 16 the default builder is Turbopack, which emits a flat,\n" +
        "content-hashed chunk layout and no per-route attribution — this gate\n" +
        "cannot measure it. Build with ``next build --webpack``, or replace\n" +
        "this script with a Turbopack-native measurement.",
    );
    process.exit(2);
  }
  const failures = [];
  const lines = [];
  let resolvedCount = 0;

  for (const [pageKey, budgetKb] of Object.entries(BUDGETS_KB)) {
    const chunks = pageChunks(pageKey);
    if (chunks.length === 0) {
      // Page may not exist (e.g. removed) — skip silently rather
      // than fail.  ``--strict`` flag below would change this.
      lines.push(`  ${pageKey.padEnd(22)} (no chunks — skipped)`);
      continue;
    }
    resolvedCount += 1;
    let totalBytes = 0;
    for (const fullPath of chunks) {
      // Paths come from readdir, so a stat failure here means the file
      // vanished mid-run rather than a stale manifest entry.
      totalBytes += fs.statSync(fullPath).size;
    }
    const totalKb = totalBytes / 1024;
    const overshoot = totalKb - budgetKb;
    const verdict =
      overshoot > 0
        ? `OVER  by ${overshoot.toFixed(1)} KB`
        : `ok    (${(-overshoot).toFixed(1)} KB headroom)`;
    lines.push(
      `  ${pageKey.padEnd(22)} ${fmtKb(totalBytes).padStart(10)} / ${budgetKb} KB budget   ${verdict}`,
    );
    if (overshoot > 0) {
      failures.push({ pageKey, totalKb, budgetKb });
    }
  }

  console.log("[check-bundle-sizes] per-page chunk sizes:");
  for (const line of lines) console.log(line);
  assertGateIsMeasuring(resolvedCount);

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
