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
// The team step (trade-advisor-shell.jsx) is its OWN chunk since the
// flag-off byte-parity fix: LeagueClient loads it with next/dynamic
// `ssr: true`, so it is server-rendered while the advisor is served and
// never referenced by /league while the flag is off.  Its chunks are
// located from Next's react-loadable-manifest (exactly the files that
// import pulls in, dependencies included) AND by this marker; both must
// agree, and every file found either way is privacy-checked.
const SHELL_MARKER = "Which team is yours?";
const SHELL_IMPORT = "./sections/trade-advisor-shell.jsx";
const LOADABLE_MANIFEST = path.join(ROOT, ".next", "react-loadable-manifest.json");
// The /league page chunk(s): with the team step split out, they must carry
// no advisor code at all (flag off = main, byte for byte).
const LEAGUE_PAGE_CHUNK = /^app[\\/]league[\\/]page-[^\\/]+\.js$/;

const FORBIDDEN = [
  "/api/data",
  "/api/dynasty-data",
  "/api/trade/",
  "useDynastyData",
  'credentials:"include"',
  'credentials: "include"',
  "rankDerivedValue",
];

// Private MODULES that must never be bundled into a public advisor chunk
// (spec §4.6 item 6).  Located by a string literal each module carries that
// survives minification — module paths do not survive a production build.
const FORBIDDEN_MODULES = [
  ["lib/trade-logic.js (workspace storage key)", "next_trade_workspace_v1"],
  ["package-model code (geom_q078_v1)", "geom_q078_v1"],
  ["lib/fairness-bands.js", "fairness_bands_v1"],
  ["lib/dynasty-data.js (curve scopes)", "overall_offense"],
  ["lib/edge-helpers.js", "Consensus asset"],
  ["lib/trade-war-room.js / trade-war-room-copy.js", "Too close / depends"],
  ["frontend/__tests__/fixtures/trade-multi (private engine output)", "decisionRunIds"],
];

// Public copy rule (spec §4.4): the advisor never tells anyone to accept,
// decline, approve or deny a trade and gives no advice or personalization.
// Scanned over the STRING LITERALS of every advisor chunk (identifiers are
// minified and not copy).  The product name "Brisket Trade Advisor" is out
// of scope (spec §10).
const FORBIDDEN_WORDS =
  /\b(accept|decline|approve|deny|reject|should|recommend\w*|advice|favorable|unfavorable|win|lose|smash|fleece|your roster|your lineup)\b/i;
function stringLiterals(src) {
  const out = [];
  const re = /"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g;
  let m;
  while ((m = re.exec(src))) out.push(m[1] ?? m[2] ?? m[3] ?? "");
  return out;
}

// Gzipped total of the team step's own chunks (JS from the manifest).
// It used to count against the /league page budget (50 KB raw); split
// out, it gets its own.  Measured 8.7 KB gzip + ~15%.
const SHELL_BUDGET_GZIP_KB = 10;

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
const failures = [];

// Team step, two ways.  (a) the manifest: every JS file the
// `import("./sections/trade-advisor-shell.jsx")` loads.
let manifestShell = [];
if (!fs.existsSync(LOADABLE_MANIFEST)) {
  failures.push("no react-loadable-manifest.json — cannot locate the team step's chunks");
} else {
  const manifest = JSON.parse(fs.readFileSync(LOADABLE_MANIFEST, "utf8"));
  const entries = Object.entries(manifest).filter(([key]) => key.endsWith(`-> ${SHELL_IMPORT}`));
  if (entries.length === 0) failures.push(`react-loadable-manifest has no entry for ${SHELL_IMPORT}`);
  const rel = new Set(entries.flatMap(([, v]) => v.files || []).filter((f) => f.endsWith(".js")));
  manifestShell = files.filter((f) =>
    rel.has(path.relative(path.join(ROOT, ".next"), f.file).split(path.sep).join("/")),
  );
  if (rel.size !== manifestShell.length) failures.push("a team-step chunk named by the manifest is missing on disk");
}
// (b) the marker: any chunk carrying the team step's copy.
const markerShell = files.filter((f) => f.src.includes(SHELL_MARKER));
if (markerShell.length === 0) failures.push("could not locate the advisor team step in any chunk");
if (manifestShell.length && !manifestShell.some((f) => f.src.includes(SHELL_MARKER))) {
  failures.push("the manifest's team-step chunks do not contain the team step (marker absent)");
}
const shell = [...new Set([...manifestShell, ...markerShell])];

// Flag off = main: the /league page chunk carries no advisor code.
for (const f of files.filter((x) => LEAGUE_PAGE_CHUNK.test(path.relative(CHUNKS, x.file)))) {
  for (const m of [SHELL_MARKER, ...LAZY_MARKERS]) {
    if (f.src.includes(m))
      failures.push(`${path.relative(ROOT, f.file)} (the /league page chunk) contains advisor code (${m})`);
  }
}

const foundMarkers = LAZY_MARKERS.filter((m) => lazy.some((f) => f.src.includes(m)));
if (foundMarkers.length !== LAZY_MARKERS.length) {
  failures.push(
    `could not locate every lazy advisor module (missing: ${LAZY_MARKERS.filter((m) => !foundMarkers.includes(m)).join(", ")}) — ` +
      "either a module moved into the page chunk or a marker string changed",
  );
}
if (shell.length === 0) failures.push("could not locate the advisor team step in any chunk");

// Chunks shared with the rest of the app (React, the ds primitives) carry
// framework strings that are not advisor copy; the word scan reads only
// chunks that are advisor-owned (they carry an advisor marker).
const ADVISOR_OWNED = (f) => [SHELL_MARKER, ...LAZY_MARKERS].some((m) => f.src.includes(m));
for (const f of [...lazy, ...shell]) {
  for (const marker of FORBIDDEN) {
    if (f.src.includes(marker)) failures.push(`${path.relative(ROOT, f.file)} contains ${marker}`);
  }
  for (const [name, marker] of FORBIDDEN_MODULES) {
    if (f.src.includes(marker)) failures.push(`${path.relative(ROOT, f.file)} bundles ${name}`);
  }
  if (ADVISOR_OWNED(f)) {
    const words = new Set();
    for (const lit of stringLiterals(f.src)) {
      if (lit.includes("Brisket Trade Advisor")) continue;
      const hit = lit.match(FORBIDDEN_WORDS);
      if (hit) words.add(`${hit[0]} (in "${lit.slice(0, 60)}")`);
    }
    for (const w of words) failures.push(`${path.relative(ROOT, f.file)} public copy uses a forbidden word: ${w}`);
  }
  if (fs.existsSync(`${f.file}.map`)) failures.push(`${path.relative(ROOT, f.file)} ships a source map`);
}

const shellKb = manifestShell.reduce((sum, f) => sum + zlib.gzipSync(f.src).length, 0) / 1024;
if (shellKb > SHELL_BUDGET_GZIP_KB) {
  failures.push(`advisor team step ${shellKb.toFixed(1)} KB gzip exceeds the ${SHELL_BUDGET_GZIP_KB} KB budget`);
}
const gzipKb = lazy.reduce((sum, f) => sum + zlib.gzipSync(f.src).length, 0) / 1024;
console.log(
  `[advisor-bundle] lazy advisor chunks: ${lazy.length} (${gzipKb.toFixed(1)} KB gzip, budget ${LAZY_BUDGET_GZIP_KB} KB); ` +
    `team-step chunk(s): ${shell.map((f) => path.relative(CHUNKS, f.file)).join(", ") || "none"} ` +
    `(${shellKb.toFixed(1)} KB gzip, budget ${SHELL_BUDGET_GZIP_KB} KB)`,
);
if (gzipKb > LAZY_BUDGET_GZIP_KB) {
  failures.push(`advisor lazy chunks ${gzipKb.toFixed(1)} KB gzip exceed the ${LAZY_BUDGET_GZIP_KB} KB budget`);
}

if (failures.length) {
  for (const msg of failures) console.error(`[advisor-bundle] FAIL ${msg}`);
  process.exit(1);
}
console.log("[advisor-bundle] PASS");
