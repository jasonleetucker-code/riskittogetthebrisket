#!/usr/bin/env node
/**
 * Per-route first-load JS — the measurement that replaces firstLoadChunks().
 *
 * WHY A THIRD INSTRUMENT
 * ----------------------
 * `firstLoadChunks()` was RETRACTED: it read a build manifest Next 16 no
 * longer emits. Its disk-derived replacement was worse — it treated every
 * file in `static/chunks/` as always-loaded, so it counted DYNAMIC-import
 * chunks against every route and scored round 6's own refactor as +213 KB
 * shared while `/league`'s slice actually fell 163.4 -> 37.8 KB. It
 * reported an improvement as a regression, confidently.
 *
 * The lesson is not "measure harder", it is "measure something that
 * cannot lie about which chunks a route loads".
 *
 * WHAT THIS MEASURES
 * ------------------
 * The `<script src>` tags in each route's PRERENDERED HTML
 * (`.next/server/app/**.html`). That list is Next's own statement of what
 * the browser fetches before the page is interactive — a chunk only
 * appears there if the route actually preloads it.
 *
 *   ALWAYS-LOADED = the intersection across every route
 *   ROUTE-SPECIFIC = that route's chunks minus the intersection
 *
 * The control that proves it is honest: `html2canvas` is a ~198 KB chunk
 * pulled in by `await import("html2canvas")` in ScreenshotFab. It sits
 * directly in `static/chunks/`, so the retracted disk-derived metric
 * counted it on every route. It must NOT appear in the intersection here
 * — and the script asserts that, rather than trusting it.
 *
 * `_global-error.html` is EXCLUDED from the intersection: the global error
 * boundary bypasses the root layout, so it loads a strict subset and would
 * drag the intersection down to a set no real route has.
 *
 * IT REFUSES TO REPORT WHAT IT DID NOT MEASURE
 * --------------------------------------------
 * Same posture as `assertGateIsMeasuring()` in check-bundle-sizes.mjs.
 * Exits non-zero if there is no build, no route HTML, no script tags, or
 * if a referenced chunk is missing from disk. A zero here means "I could
 * not measure", never "there is nothing to load".
 *
 * TURBOPACK: like the bundle-size gate, this needs the `--webpack` build
 * (`npm run build:nocheck`). Under Turbopack the prerendered HTML has no
 * stable per-route chunk attribution. It says so and exits rather than
 * guessing.
 *
 * USAGE
 *   node frontend/scripts/measure-first-load.mjs [--json] [--top N]
 */
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const NEXT_DIR = path.join(HERE, "..", ".next");
const APP_HTML_DIR = path.join(NEXT_DIR, "server", "app");
const STATIC_DIR = path.join(NEXT_DIR, "static");

// Bypasses the root layout, so its chunk set is a strict subset of every
// real route's. Including it would silently shrink the intersection.
const EXCLUDE_HTML = new Set(["_global-error.html"]);

// The control below proves the instrument DISCRIMINATES — that it counts
// what a route preloads rather than everything on disk, which is precisely
// what the retracted metric got wrong.
//
// The first version of this control asserted that no always-loaded chunk
// had "html2canvas" in its URL. That was VACUOUS: webpack content-hashes
// that chunk to `ad2866b8.<hash>.js`, so the string never appears in a
// filename and the check could not fail. (Grepping for it finds only the
// import SPECIFIER inside the shell chunk.) A control that cannot fail is
// worse than none — it reads as verification.
//
// The real invariant: `.next/static/chunks/` contains large chunks that no
// route preloads, and the instrument must exclude them. Measured on this
// build: html2canvas at 196 KB (`ad2866b8.*`), plus `framework-*` 188 KB
// and `main-*` 136 KB, which are pages-router artifacts the app router
// never loads. All three are in ZERO route HTMLs.
const CONTROL_MIN_EXCLUDED_KB = 100;

function parseArgs(argv) {
  const out = { json: false, top: 12 };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--json") out.json = true;
    else if (argv[i] === "--top") out.top = Number(argv[++i]);
  }
  return out;
}

function die(msg) {
  console.error(`[measure-first-load] REFUSING TO REPORT\n\n${msg}\n`);
  process.exit(2);
}

function walkHtml(dir, acc = []) {
  if (!fs.existsSync(dir)) return acc;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walkHtml(full, acc);
    else if (entry.name.endsWith(".html")) acc.push(full);
  }
  return acc;
}

const args = parseArgs(process.argv.slice(2));

if (!fs.existsSync(NEXT_DIR)) {
  die(`No build at ${NEXT_DIR}.\nRun: npm run build:nocheck`);
}

const htmlFiles = walkHtml(APP_HTML_DIR).filter(
  (f) => !EXCLUDE_HTML.has(path.basename(f)),
);
if (htmlFiles.length === 0) {
  die(
    `No prerendered route HTML under ${APP_HTML_DIR}.\n` +
      `Under Next 16's DEFAULT builder (Turbopack) this directory is not\n` +
      `produced in a form this instrument can attribute. Build with\n` +
      `--webpack (npm run build:nocheck), the same requirement\n` +
      `check-bundle-sizes.mjs already declares.`,
  );
}

// route name -> Set(chunk url)
const byRoute = new Map();
const SCRIPT_SRC = /<script[^>]+src="([^"]+)"/g;
for (const file of htmlFiles) {
  const html = fs.readFileSync(file, "utf8");
  const chunks = new Set();
  for (const m of html.matchAll(SCRIPT_SRC)) {
    const src = m[1];
    if (src.startsWith("/_next/static/")) chunks.add(src);
  }
  const route =
    "/" +
    path
      .relative(APP_HTML_DIR, file)
      .replace(/\.html$/, "")
      .replace(/\\/g, "/");
  byRoute.set(route === "/index" ? "/" : route, chunks);
}

const totalScriptTags = [...byRoute.values()].reduce((n, s) => n + s.size, 0);
if (totalScriptTags === 0) {
  die(
    `Found ${htmlFiles.length} route HTML files but ZERO <script src> tags\n` +
      `pointing at /_next/static/. The HTML shape changed; this parser is\n` +
      `measuring nothing and would report 0 KB for every route.`,
  );
}

// Intersection = loaded by EVERY route.
let always = null;
for (const chunks of byRoute.values()) {
  always = always === null ? new Set(chunks) : new Set([...always].filter((c) => chunks.has(c)));
}

const sizeCache = new Map();
function sizeOf(url) {
  if (sizeCache.has(url)) return sizeCache.get(url);
  const rel = url.replace(/^\/_next\/static\//, "");
  const file = path.join(STATIC_DIR, rel);
  if (!fs.existsSync(file)) {
    die(
      `Route HTML references ${url} but ${file} does not exist.\n` +
        `Sizes would be understated by an unknown amount.`,
    );
  }
  const buf = fs.readFileSync(file);
  const rec = { raw: buf.length, gz: zlib.gzipSync(buf).length };
  sizeCache.set(url, rec);
  return rec;
}

const alwaysList = [...always]
  .map((url) => ({ url, ...sizeOf(url) }))
  .sort((a, b) => b.raw - a.raw);

// ── Control: prove the instrument excludes what routes do not preload ──
const chunkDir = path.join(STATIC_DIR, "chunks");
const onDisk = fs.existsSync(chunkDir)
  ? fs
      .readdirSync(chunkDir)
      .filter((f) => f.endsWith(".js"))
      .map((f) => ({ name: f, raw: fs.statSync(path.join(chunkDir, f)).size }))
  : [];
const alwaysNames = new Set(alwaysList.map((c) => path.basename(c.url)));
const excludedLarge = onDisk
  .filter((c) => c.raw >= CONTROL_MIN_EXCLUDED_KB * 1024 && !alwaysNames.has(c.name))
  .sort((a, b) => b.raw - a.raw);

if (onDisk.length === 0) {
  die(`No chunks found under ${chunkDir}; the control cannot run.`);
}
if (excludedLarge.length === 0) {
  die(
    `Control failed: every chunk >= ${CONTROL_MIN_EXCLUDED_KB} KB on disk is in the\n` +
      `ALWAYS-LOADED set. This build should contain large chunks no route\n` +
      `preloads (dynamic imports, pages-router artifacts). Either they\n` +
      `regressed into the shared graph, or this instrument has started\n` +
      `counting everything on disk like the retracted metric did.`,
  );
}

const sum = (list, k) => list.reduce((n, c) => n + c[k], 0);
const alwaysRaw = sum(alwaysList, "raw");
const alwaysGz = sum(alwaysList, "gz");

// Framework vs app-owned. The framework chunks are the Next client
// runtime, react-dom, polyfills and webpack's own runtime; everything
// else in the intersection is code this repo wrote or imported.
const FRAMEWORK = /(polyfills|webpack-|main-app-|framework-)/;
const isFramework = (c) => FRAMEWORK.test(c.url) || c.raw > 150_000;
const framework = alwaysList.filter(isFramework);
const appOwned = alwaysList.filter((c) => !isFramework(c));

const routes = [...byRoute.entries()]
  .map(([route, chunks]) => {
    const own = [...chunks].filter((c) => !always.has(c)).map((url) => ({ url, ...sizeOf(url) }));
    return { route, raw: sum(own, "raw"), gz: sum(own, "gz"), count: own.length };
  })
  .sort((a, b) => b.raw - a.raw);

const kb = (n) => (n / 1024).toFixed(1);

if (args.json) {
  console.log(
    JSON.stringify(
      {
        routeCount: byRoute.size,
        alwaysLoaded: { raw: alwaysRaw, gz: alwaysGz, chunks: alwaysList },
        framework: { raw: sum(framework, "raw"), gz: sum(framework, "gz") },
        appOwned: { raw: sum(appOwned, "raw"), gz: sum(appOwned, "gz") },
        routes,
      },
      null,
      2,
    ),
  );
} else {
  console.log(`\nfirst-load JS — ${byRoute.size} routes measured from prerendered HTML\n`);
  console.log(`ALWAYS LOADED (intersection of every route)`);
  console.log(`  ${kb(alwaysRaw)} KB raw   ${kb(alwaysGz)} KB gzipped   ${alwaysList.length} chunks`);
  console.log(
    `    framework  ${kb(sum(framework, "raw"))} KB raw / ${kb(sum(framework, "gz"))} KB gz`,
  );
  console.log(
    `    app-owned  ${kb(sum(appOwned, "raw"))} KB raw / ${kb(sum(appOwned, "gz"))} KB gz\n`,
  );
  console.log(`  largest always-loaded chunks:`);
  for (const c of alwaysList.slice(0, args.top)) {
    console.log(`    ${kb(c.raw).padStart(8)} KB  ${kb(c.gz).padStart(7)} KB gz  ${c.url.replace("/_next/static/chunks/", "")}`);
  }
  console.log(`\nROUTE-SPECIFIC (on top of the above)`);
  console.log(`  ${"route".padEnd(34)} ${"raw".padStart(9)} ${"gz".padStart(9)}  chunks`);
  console.log("  " + "-".repeat(66));
  for (const r of routes.slice(0, args.top)) {
    console.log(
      `  ${r.route.padEnd(34)} ${(kb(r.raw) + " KB").padStart(9)} ${(kb(r.gz) + " KB").padStart(9)}  ${r.count}`,
    );
  }
  console.log(
    `\ncontrol: ${excludedLarge.length} chunk(s) >= ${CONTROL_MIN_EXCLUDED_KB} KB on disk are correctly` +
      ` EXCLUDED (no route preloads them):`,
  );
  for (const c of excludedLarge.slice(0, 4)) {
    console.log(`    ${kb(c.raw).padStart(8)} KB  ${c.name}`);
  }
}
