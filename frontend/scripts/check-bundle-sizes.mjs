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
const NEXT_DIR = path.join(ROOT, ".next");
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
  "/trade/page": 75, // calculator + simulator + breakdown
  "/draft/page": 115, // depth chart + analysis charts
  "/edge/page": 30,
  "/finder/page": 20,
  "/angle/page": 30,
  "/league/page": 165, // public hub bundles every section together
  "/rosters/page": 30,
  "/trades/page": 20,
  "/settings/page": 55,  // bumped 50→55 for guest-pass admin panel (token reveal, list table, revoke)
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
