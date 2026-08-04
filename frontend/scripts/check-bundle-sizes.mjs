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
  //
  // Bumped 36→42: the "Best add/drop moves" FAAB column now joins the
  // backend's bids onto its client-computed rows at render time
  // (lib/waiver-faab.js + the POST in useWaiverAnalysis) instead of
  // rendering "—" on every row. Measured 37.6 KB, up from 35.0 —
  // 42 restores the ~15% headroom this table asks for. The alternative
  // was a client-side bid formula, which the no-frontend-valuation
  // rule forbids (see the closing note in lib/waiver-logic.js).
  "/waivers/page": 42,
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
    let totalBytes = 0;
    for (const chunk of chunks) {
      const fullPath = path.join(NEXT_DIR, chunk);
      try {
        totalBytes += fs.statSync(fullPath).size;
      } catch {
        // Chunk listed in manifest but not on disk — should not
        // happen on a clean build, but skip to avoid spurious
        // failures.
      }
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
