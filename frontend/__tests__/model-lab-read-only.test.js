/**
 * The Model Lab is READ-ONLY, structurally (IC-6; owner rule: nothing
 * self-promotes, evaluation is not activation).
 *
 * The component test proves the requests a rendered Lab makes are GETs of
 * `/api/model-lab`.  This proves it for code paths a render does not reach:
 * it walks the REAL transitive import graph of `/admin/model-lab`
 * (`scripts/route-import-graph.mjs`, the walker the no-player-data gate
 * uses) plus every Model Lab module — including `FamilyDetail`, which is
 * lazily imported — and fails on:
 *
 *   * any non-GET method literal (`method: "POST"` …, `.post(` helpers);
 *   * `sendBeacon`, `XMLHttpRequest`, `WebSocket` — other ways to write;
 *   * a `fetch(` in a Model Lab module that is not the one GET of the Lab;
 *   * a `fetch(` anywhere else in the graph (the shared primitives it
 *     renders with must not fetch on its behalf).
 *
 * Positive control at the bottom: the same scan DOES flag a module known
 * to POST, so a clean result here is not a scanner that sees nothing.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import { describe, expect, it } from "vitest";
import { findTransitivePlayerDataConsumers } from "../scripts/route-import-graph.mjs";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");
const PAGE = path.join(ROOT, "app", "admin", "model-lab", "page.jsx");
const LAB_DIR = path.join(ROOT, "components", "model-lab");
const LAB_LIB = path.join(ROOT, "lib", "model-lab.js");

/** Strip block and line comments (prose here names "POST" and "fetch"). */
function code(file) {
  return fs
    .readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

const WRITE_PATTERNS = [
  [/method\s*:\s*["'`](POST|PUT|PATCH|DELETE)["'`]/i, "non-GET method literal"],
  [/method\s*=\s*["'`](POST|PUT|PATCH|DELETE)["'`]/i, "non-GET method default"],
  [/\.(post|put|patch|delete)\s*\(/, "write helper call"],
  [/sendBeacon\s*\(/, "navigator.sendBeacon"],
  [/\bXMLHttpRequest\b/, "XMLHttpRequest"],
  [/\bnew\s+WebSocket\b/, "WebSocket"],
];

function writeFindings(file) {
  const src = code(file);
  return WRITE_PATTERNS.filter(([re]) => re.test(src)).map(([, what]) => what);
}

function labModules() {
  return fs
    .readdirSync(LAB_DIR)
    .filter((n) => /\.(jsx?|mjs)$/.test(n))
    .map((n) => path.join(LAB_DIR, n));
}

function modelLabGraph() {
  const files = new Set();
  for (const entry of [PAGE, ...labModules()]) {
    for (const f of findTransitivePlayerDataConsumers(entry).visitedFiles) files.add(f);
  }
  return files;
}

describe("Model Lab is read-only", () => {
  const graph = modelLabGraph();

  it("the walk actually covers the page, every Lab module and the lib", () => {
    expect(graph.has(PAGE)).toBe(true);
    for (const f of labModules()) expect(graph.has(f), f).toBe(true);
    expect(graph.has(LAB_LIB)).toBe(true);
    // ds primitives were walked too (not just the entry files).
    expect([...graph].some((f) => f.includes(`${path.sep}ds${path.sep}`))).toBe(true);
  });

  it("no module in the graph issues a write request", () => {
    const offenders = [];
    for (const f of graph) {
      const found = writeFindings(f);
      if (found.length) offenders.push(`${path.relative(ROOT, f)}: ${found.join(", ")}`);
    }
    expect(offenders).toEqual([]);
  });

  it("the only fetch is the hook's GET of /api/model-lab", () => {
    const fetchers = [...graph].filter((f) => /\bfetch\s*\(/.test(code(f)));
    expect(fetchers.map((f) => path.relative(ROOT, f).split(path.sep).join("/"))).toEqual([
      "components/model-lab/useModelLab.js",
    ]);
    const src = code(path.join(LAB_DIR, "useModelLab.js"));
    const calls = [...src.matchAll(/\bfetch\s*\(\s*([A-Za-z_$][\w$]*|["'`][^"'`]*["'`])\s*,\s*\{([\s\S]*?)\}\s*\)/g)];
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toBe("MODEL_LAB_PATH");
    expect(calls[0][2]).toMatch(/method\s*:\s*"GET"/);
    expect(src).toMatch(/export const MODEL_LAB_PATH = "\/api\/model-lab";/);
  });

  it("no Model Lab module renders a promote / apply / rollback control", () => {
    for (const f of [PAGE, LAB_LIB, ...labModules()]) {
      const src = code(f);
      // A <Button> or <button> whose text names a write action.
      expect(src, path.relative(ROOT, f)).not.toMatch(
        /<(Button|button)\b[^>]*>\s*(Promote|Apply|Roll ?back|Activate|Retire|Reject)\b/i,
      );
    }
  });
});

describe("positive control — the scan sees real writes", () => {
  it("flags a module known to POST", () => {
    const known = path.join(ROOT, "components", "admin", "GuestPassPanel.jsx");
    expect(writeFindings(known)).toContain("non-GET method literal");
  });

  it("flags the admin page's POST default", () => {
    expect(writeFindings(path.join(ROOT, "app", "admin", "page.jsx"))).toContain(
      "non-GET method default",
    );
  });
});
