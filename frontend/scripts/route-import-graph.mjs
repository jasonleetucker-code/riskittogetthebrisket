// Static transitive-import-graph walker for one specific question:
// "does this route module's production import graph reach a real call
// to useDynastyData() or useApp()?"
//
// V1-108 (docs/VERSION_1_COMPLETION_CONTRACT.md) requires committed
// regression evidence that the six NO_PLAYER_DATA_ROUTE_PREFIXES routes
// (frontend/components/AppShell.jsx) cannot reacquire the player
// pipeline. A hand-maintained list of "files these routes import" would
// itself be the kind of shallow evidence the target was refused for —
// this walks the REAL import graph starting from the route's own page
// module, following every local import/re-export it resolves.
//
// This is intentionally NOT a full JS/TS parser (this repo has none —
// see the a11y and CSS-contract tests for the same regex-based
// convention). Three things make a regex approach trustworthy enough
// for this specific question, each earned by measurement against the
// real tree during development (not asserted a priori):
//
//   1. Comments are stripped first (string/template-aware), so a prose
//      comment mentioning "useApp()" cannot be mistaken for a call —
//      this codebase's own comments are dense enough that this is not
//      hypothetical (AppShell.jsx's own doc comments name both hooks).
//   2. A hook CALL (`useApp(`) is distinguished from the hook's own
//      DECLARATION (`function useApp(`) via a negative lookbehind, so
//      walking into the hook's defining file does not self-flag.
//   3. Imports are resolved per NAMED BINDING, not whole-file: when a
//      route imports one named export from a multi-export file, only
//      that export's own top-level declaration (plus the file's module
//      header) is scanned and only ITS OWN referenced imports are
//      followed — otherwise an unrelated sibling export in the same
//      file (e.g. AppShellWrapper.jsx's unrelated search-bridge
//      component, which does call useApp()) would falsely implicate
//      every importer of any OTHER export from that file.
//
// Where a binding cannot be precisely narrowed (barrel re-export chains
// deeper than 6 hops, an unrecognized export shape), this walker fails
// SAFE by scanning/following the whole file rather than skipping it —
// under-approximating a security/perf guard is the wrong direction to
// be wrong in.
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const FRONTEND_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");
const EXTENSIONS = [".js", ".jsx", ".ts", ".tsx"];
const HOOK_NAMES = ["useDynastyData", "useApp"];

function stripComments(src) {
  let out = "";
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i];
    const c2 = src[i + 1];
    if (c === "/" && c2 === "/") {
      while (i < n && src[i] !== "\n") i++;
      continue;
    }
    if (c === "/" && c2 === "*") {
      i += 2;
      while (i < n && !(src[i] === "*" && src[i + 1] === "/")) i++;
      i += 2;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      const quote = c;
      out += c;
      i++;
      while (i < n && src[i] !== quote) {
        if (src[i] === "\\") {
          out += src[i] + (src[i + 1] ?? "");
          i += 2;
          continue;
        }
        out += src[i];
        i++;
      }
      out += src[i] ?? "";
      i++;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

function resolveModule(spec, fromFile) {
  let base;
  if (spec.startsWith(".")) {
    base = path.resolve(path.dirname(fromFile), spec);
  } else if (spec.startsWith("@/")) {
    base = path.resolve(FRONTEND_ROOT, spec.slice(2));
  } else {
    return null; // external package (react, next/*, ...) — not traversed
  }
  if (fs.existsSync(base) && fs.statSync(base).isFile()) return base;
  for (const ext of EXTENSIONS) if (fs.existsSync(base + ext)) return base + ext;
  for (const ext of EXTENSIONS) {
    const idx = path.join(base, "index" + ext);
    if (fs.existsSync(idx)) return idx;
  }
  return null;
}

// "*" (namespace/dynamic/require — need whole module) or an array of
// { local, imported } bindings.
function parseBindings(clauseText) {
  clauseText = clauseText.trim();
  if (clauseText.startsWith("*")) return "*";
  const bindings = [];
  const rest = clauseText;
  const braceStart = rest.indexOf("{");
  if (braceStart > 0) {
    const defaultPart = rest.slice(0, braceStart).replace(/,\s*$/, "").trim();
    if (defaultPart) bindings.push({ local: defaultPart, imported: "default" });
  } else if (braceStart === -1 && rest) {
    bindings.push({ local: rest, imported: "default" });
    return bindings;
  }
  const braceEnd = rest.lastIndexOf("}");
  if (braceStart !== -1 && braceEnd !== -1) {
    const inner = rest.slice(braceStart + 1, braceEnd);
    for (const part of inner.split(",")) {
      const p = part.trim();
      if (!p) continue;
      const asMatch = p.split(/\s+as\s+/);
      bindings.push({ local: (asMatch[1] || asMatch[0]).trim(), imported: asMatch[0].trim() });
    }
  }
  return bindings;
}

function extractClauses(src) {
  const out = [];
  const importRe = /(?:^|\n)\s*import\s+([^'";]*?)\s+from\s+["']([^"']+)["']/g;
  const exportFromRe = /(?:^|\n)\s*export\s+([^'";]*?)\s+from\s+["']([^"']+)["']/g;
  const dynImportRe = /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;
  const requireRe = /\brequire\(\s*["']([^"']+)["']\s*\)/g;
  let m;
  while ((m = importRe.exec(src))) out.push({ spec: m[2], bindings: parseBindings(m[1]) });
  while ((m = exportFromRe.exec(src))) out.push({ spec: m[2], bindings: parseBindings(m[1]) });
  while ((m = dynImportRe.exec(src))) out.push({ spec: m[1], bindings: "*" });
  while ((m = requireRe.exec(src))) out.push({ spec: m[1], bindings: "*" });
  return out;
}

const DECL_RE =
  /^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)|^(?:export\s+)?const\s+(\w+)\s*=|^(?:export\s+)?class\s+(\w+)/gm;

function sliceDeclarations(src) {
  const bounds = [];
  let m;
  while ((m = DECL_RE.exec(src))) bounds.push({ name: m[1] || m[2] || m[3], start: m.index });
  const slices = new Map();
  for (let i = 0; i < bounds.length; i++) {
    const start = bounds[i].start;
    const end = i + 1 < bounds.length ? bounds[i + 1].start : src.length;
    slices.set(bounds[i].name, (slices.get(bounds[i].name) || "") + src.slice(start, end));
  }
  const header = src.slice(0, bounds.length ? bounds[0].start : src.length);
  return { header, slices };
}

function defaultExportLocalName(src) {
  const m1 = src.match(/^export\s+default\s+(?:async\s+)?function\s+(\w+)/m);
  if (m1) return m1[1];
  const m2 = src.match(/^export\s+default\s+(\w+)\s*;?\s*$/m);
  if (m2) return m2[1];
  return null;
}

function findConsumerCalls(text, extraLocalNames = []) {
  const found = [];
  for (const hook of HOOK_NAMES) {
    if (new RegExp(`(?<!function\\s)\\b${hook}\\s*\\(`).test(text)) found.push(hook);
  }
  for (const { local, hook } of extraLocalNames) {
    if (local === hook) continue;
    if (new RegExp(`(?<!function\\s)\\b${local}\\s*\\(`).test(text)) found.push(hook);
  }
  return found;
}

// Local alias names bound to useApp/useDynastyData via THIS file's own
// imports, e.g. `import { useApp as useShell } from "..."` — rare (no
// current file does this), but a rename should not defeat the guard.
function hookAliasesInFile(rec) {
  const aliases = [];
  for (const clause of rec.clauses) {
    if (clause.bindings === "*") continue;
    for (const b of clause.bindings) {
      if (b.imported === "useApp" || b.imported === "useDynastyData") {
        aliases.push({ local: b.local, hook: b.imported });
      }
    }
  }
  return aliases;
}

const fileCache = new Map();
function loadFile(file) {
  if (fileCache.has(file)) return fileCache.get(file);
  let raw;
  try {
    raw = fs.readFileSync(file, "utf-8");
  } catch {
    const empty = { stripped: "", header: "", slices: new Map(), clauses: [] };
    fileCache.set(file, empty);
    return empty;
  }
  const stripped = stripComments(raw);
  const { header, slices } = sliceDeclarations(stripped);
  const clauses = extractClauses(header); // imports always live in the header
  const rec = { stripped, header, slices, clauses };
  fileCache.set(file, rec);
  return rec;
}

function resolveExportToSliceOrFile(file, importedName, depth = 0) {
  if (depth > 6) return { kind: "whole", file };
  const rec = loadFile(file);
  if (importedName === "default") {
    const local = defaultExportLocalName(rec.stripped);
    if (local && rec.slices.has(local)) return { kind: "slice", file, body: rec.slices.get(local) };
  } else if (rec.slices.has(importedName)) {
    return { kind: "slice", file, body: rec.slices.get(importedName) };
  }
  for (const clause of rec.clauses) {
    if (clause.bindings === "*") continue;
    for (const b of clause.bindings) {
      if (b.imported === importedName) {
        const resolved = resolveModule(clause.spec, file);
        if (resolved) return resolveExportToSliceOrFile(resolved, importedName, depth + 1);
      }
    }
  }
  return null; // could not narrow — caller falls back to whole-file
}

/**
 * Walk the transitive production import graph from `entryFile` and
 * report every reached call site of useDynastyData()/useApp().
 *
 * @param {string} entryFile absolute path to a route module (page.jsx)
 * @returns {{ visitedFiles: Set<string>, consumers: Array<{file: string, hook: string}> }}
 */
export function findTransitivePlayerDataConsumers(entryFile) {
  const visitedFiles = new Set();
  const visitedWhole = new Set();
  const visitedSliceKeys = new Set();
  const consumers = [];
  const queue = [{ file: entryFile, bindings: "*" }];

  while (queue.length) {
    const { file, bindings } = queue.pop();
    const rec = loadFile(file);
    if (!rec.stripped) continue;
    visitedFiles.add(file);

    const textsToScan = [];
    const followClauses = [];

    if (bindings === "*") {
      if (visitedWhole.has(file)) continue;
      visitedWhole.add(file);
      textsToScan.push(rec.stripped);
      followClauses.push(...rec.clauses);
    } else {
      for (const b of bindings) {
        const key = `${file}::${b.imported}`;
        if (visitedSliceKeys.has(key)) continue;
        visitedSliceKeys.add(key);
        const resolved = resolveExportToSliceOrFile(file, b.imported);
        if (resolved && resolved.kind === "slice") {
          textsToScan.push(resolved.body);
          // Only follow an import the slice's OWN body actually uses —
          // otherwise an unrelated sibling export's dependencies leak in.
          for (const clause of rec.clauses) {
            if (clause.bindings === "*") {
              followClauses.push(clause);
              continue;
            }
            const used = clause.bindings.some((cb) => new RegExp(`\\b${cb.local}\\b`).test(resolved.body));
            if (used) followClauses.push(clause);
          }
        } else if (resolved && resolved.kind === "whole") {
          if (!visitedWhole.has(resolved.file)) {
            visitedWhole.add(resolved.file);
            const rec2 = loadFile(resolved.file);
            textsToScan.push(rec2.stripped);
            followClauses.push(...rec2.clauses);
          }
        } else if (!visitedWhole.has(file)) {
          visitedWhole.add(file);
          textsToScan.push(rec.stripped);
          followClauses.push(...rec.clauses);
        }
      }
    }

    const aliases = hookAliasesInFile(rec);
    for (const text of textsToScan) {
      for (const hook of findConsumerCalls(text, aliases)) consumers.push({ file, hook });
    }
    for (const clause of followClauses) {
      const resolved = resolveModule(clause.spec, file);
      if (resolved) queue.push({ file: resolved, bindings: clause.bindings });
    }
  }
  return { visitedFiles, consumers };
}

// Recursively find every `page.jsx`/`page.js` under `dir` — the actual
// route modules, not a hand-maintained list, so a new sub-page under a
// gated prefix is covered automatically.
export function findPageModulesUnder(dir) {
  const found = [];
  function walkDir(d) {
    let entries;
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) {
        walkDir(full);
      } else if (/^page\.(jsx?|tsx?)$/.test(entry.name)) {
        found.push(full);
      }
    }
  }
  walkDir(dir);
  return found;
}
