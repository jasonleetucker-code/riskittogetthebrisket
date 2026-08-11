// A test may not import a symbol its module does not export.
//
// Vitest transforms with esbuild, which does NOT perform the live-binding
// check real ESM does: a named import of a missing export silently
// resolves to `undefined` instead of throwing. That turns a deleted
// export into a quiet `undefined` inside the test file, and any
// assertion written against it becomes vacuous.
//
// That is not hypothetical. `draft-logic.test.js` imported
// DEFAULT_INITIAL_SLOTS, PHASE_LATE_BOOST and slotsByTeamFromPicks,
// all removed by the Perfect Draft rebuild. One test then asserted
//
//     expect(ws.teams[0].initialSlots).toBe(DEFAULT_INITIAL_SLOTS)
//
// which was `expect(undefined).toBe(undefined)` — green, named
// "backfills initialSlots to DEFAULT_INITIAL_SLOTS when missing", and
// verifying nothing at all. The same file contained a sibling test
// pinning those exports as REMOVED, so the file asserted both that the
// symbols were gone and that a value equalled one of them.
//
// REPAIR_PROTOCOL names this file for a related reason: it once held a
// test pinning a draft bug as the contract. A vacuous assertion is the
// same failure wearing green.
//
// Scope: `@/`-aliased named imports whose target module resolves inside
// the repo and does not re-export with `export *` (which this static
// check cannot follow). Default imports, namespace imports and
// node_modules are out of scope.

import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const TESTS_DIR = fileURLToPath(new URL(".", import.meta.url));
const FRONTEND_DIR = dirname(TESTS_DIR);

function testFiles(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) testFiles(full, acc);
    else if (/\.test\.jsx?$/.test(entry.name)) acc.push(full);
  }
  return acc;
}

/** Named exports of a module, or null when the file cannot be read. */
function namedExports(modulePath) {
  let src;
  try {
    src = readFileSync(modulePath, "utf8");
  } catch {
    return null;
  }
  const names = new Set(
    [
      ...src.matchAll(
        /export\s+(?:async\s+)?(?:const|function|class|let|var)\s+([A-Za-z0-9_$]+)/g,
      ),
    ].map((m) => m[1]),
  );
  for (const m of src.matchAll(/export\s*\{([^}]+)\}/g)) {
    for (const token of m[1].split(",")) {
      const name = token.split(/\s+as\s+/).pop().trim();
      if (name) names.add(name);
    }
  }
  // `export *` re-exports cannot be resolved statically here.
  if (/export\s+\*/.test(src)) return "OPAQUE";
  return names;
}

function resolveAlias(specifier) {
  for (const suffix of [".js", ".jsx", "/index.js", "/index.jsx"]) {
    const candidate = join(FRONTEND_DIR, specifier + suffix);
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

describe("test files import only symbols their modules export", () => {
  it("finds no phantom named import anywhere under __tests__", () => {
    const phantom = [];

    for (const file of testFiles(TESTS_DIR)) {
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(
        /import\s*\{([^}]+)\}\s*from\s*["']@\/([^"']+)["']/g,
      )) {
        const target = resolveAlias(m[2]);
        if (!target) continue;
        const exported = namedExports(target);
        if (!exported || exported === "OPAQUE") continue;

        const imported = m[1]
          .split(",")
          .map((t) => t.trim().split(/\s+as\s+/)[0].trim())
          .filter(Boolean);
        for (const name of imported) {
          if (!exported.has(name)) {
            phantom.push(
              `${file.slice(FRONTEND_DIR.length + 1)} imports { ${name} } from "@/${m[2]}", which does not export it`,
            );
          }
        }
      }
    }

    expect(phantom).toEqual([]);
  });
});
