// Brisket Trade Advisor — public bundle privacy + lazy-chunk budget gate
// (design §8.5, §13 item 13).  Run after `next build`.
//
// check-bundle-sizes.mjs gates PAGE chunks only; the advisor's builder,
// picker, sheet and result are lazy chunks it never sees.  This script finds
// those chunks by content — each advisor module carries a stable marker
// string — and asserts two things:
//
//   1. privacy: no advisor chunk reaches the private data path.  Markers are
//      DATA-PATH strings (`/api/data`, `/api/dynasty-data`, `/api/trade/`,
//      `useDynastyData`, credentialed fetches), not formula names — shared
//      chunks already carry those through AppShell, and a formula name in a
//      chunk is not a request.
//   2. budget: the advisor's lazy chunks stay within a declared total
//      (measured + ~15%, the convention check-bundle-sizes.mjs uses).
//
// Also asserts production browser source maps are not emitted for these
// chunks.  Exit 0 pass, 1 fail, 2 no build output.

import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import zlib from "node:zlib";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");
const CHUNKS = path.join(ROOT, ".next", "static", "chunks");

// One stable marker per lazy advisor module (strings that survive
// minification: user-facing copy and test ids).
const LAZY_MARKERS = [
  "Build your trade", // trade-advisor.jsx (builder)
  "advisor-asset-list", // _advisor-asset-picker.jsx
  "advisor-asset-sheet", // _advisor-asset-sheet.jsx
  "advisor-result", // _advisor-result.jsx
];
// The team step lives in the /league page chunk (static by design).
const SHELL_MARKER = "Which team are you evaluating for?";

const FORBIDDEN = [
  "/api/data",
  "/api/dynasty-data",
  "/api/trade/",
  "useDynastyData",
  'credentials:"include"',
  "credentials: \"include\"",
  "rankDerivedValue",
];

// Gzipped total of the advisor's LAZY chunks.  Measured 2026-10-20 on
// claude/advisor-hub-frontend; see docs/ui/UI_PARALLEL_LEDGER.md.
const LAZY_BUDGET_GZIP_KB = 11; // measured 9.1 KB + ~15%

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith(".js")) out.push(p);
  }
  return out;
}

if (!fs.existsSync(CHUNKS)) {
  console.error(`[advisor-bundle] no build output at ${CHUNKS} — run \`next build\` first`);
  process.exit(2);
}

const files = walk(CHUNKS).map((file) => ({ file, src: fs.readFileSync(file, "utf8") }));
const lazy = files.filter((f) => LAZY_MARKERS.some((m) => f.src.includes(m)) && !f.src.includes(SHELL_MARKER));
const shell = files.filter((f) => f.src.includes(SHELL_MARKER));
const failures = [];

const foundMarkers = LAZY_MARKERS.filter((m) => lazy.some((f) => f.src.includes(m)));
if (foundMarkers.length !== LAZY_MARKERS.length) {
  failures.push(
    `could not locate every lazy advisor module (missing: ${LAZY_MARKERS.filter((m) => !foundMarkers.includes(m)).join(", ")}) — ` +
      "either a module moved into the page chunk or a marker string changed",
  );
}
if (shell.length === 0) failures.push("could not locate the advisor team step in any chunk");

for (const f of [...lazy, ...shell]) {
  for (const marker of FORBIDDEN) {
    if (f.src.includes(marker)) failures.push(`${path.relative(ROOT, f.file)} contains ${marker}`);
  }
  if (fs.existsSync(`${f.file}.map`)) failures.push(`${path.relative(ROOT, f.file)} ships a source map`);
}

const gzipKb = lazy.reduce((sum, f) => sum + zlib.gzipSync(f.src).length, 0) / 1024;
console.log(
  `[advisor-bundle] lazy advisor chunks: ${lazy.length} (${gzipKb.toFixed(1)} KB gzip, budget ${LAZY_BUDGET_GZIP_KB} KB); ` +
    `team-step chunk(s): ${shell.map((f) => path.relative(CHUNKS, f.file)).join(", ") || "none"}`,
);
if (gzipKb > LAZY_BUDGET_GZIP_KB) {
  failures.push(`advisor lazy chunks ${gzipKb.toFixed(1)} KB gzip exceed the ${LAZY_BUDGET_GZIP_KB} KB budget`);
}

if (failures.length) {
  for (const msg of failures) console.error(`[advisor-bundle] FAIL ${msg}`);
  process.exit(1);
}
console.log("[advisor-bundle] PASS");
