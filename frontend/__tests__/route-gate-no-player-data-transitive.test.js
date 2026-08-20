/**
 * V1-108 committed regression evidence: the six NO_PLAYER_DATA routes
 * (frontend/components/AppShell.jsx) must not be able to reacquire the
 * player pipeline (useDynastyData / useApp) through ANY chain of
 * production imports, not just their own page.jsx source.
 *
 * V1-108 was previously refused for exactly the gap this file closes:
 * the route-gating logic (isNoPlayerDataRoute) was measured working in
 * the browser, but nothing durable proved the SIX ROUTES' actual import
 * graphs stay clear of the two hooks as the codebase changes around
 * them. `app-shell-route-gates.test.js` pins the STRING-MATCHING gate
 * (does "/admin/x" match the "/admin" prefix?) — a real, separate
 * concern, but it says nothing about what admin/page.jsx's own imports
 * actually pull in.
 *
 * This test walks the REAL transitive import graph from each route's
 * own page module (frontend/scripts/route-import-graph.mjs) — no
 * hand-maintained "these are the files this route touches" list.
 */
import { describe, expect, it } from "vitest";
import path from "node:path";
import url from "node:url";
import {
  findTransitivePlayerDataConsumers,
  findPageModulesUnder,
} from "../scripts/route-import-graph.mjs";
import { __routeGates } from "@/components/AppShell";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");

function describeConsumers(consumers) {
  return consumers
    .map((c) => `${c.hook}() reachable via ${path.relative(FRONTEND_ROOT, c.file)}`)
    .join("\n  ");
}

// Route prefix -> app directory. Mirrors how Next.js itself maps a
// route prefix to a directory; not duplicated route-by-route logic.
function appDirForPrefix(prefix) {
  return path.join(FRONTEND_ROOT, "app", prefix.replace(/^\//, ""));
}

describe("no-player-data routes cannot transitively reacquire useDynastyData/useApp", () => {
  const prefixes = __routeGates.NO_PLAYER_DATA_ROUTE_PREFIXES;

  it("the gate list itself is non-empty (a vacuous list would pass every assertion below)", () => {
    expect(prefixes.length).toBeGreaterThan(0);
  });

  for (const prefix of prefixes) {
    describe(prefix, () => {
      const dir = appDirForPrefix(prefix);
      const pageFiles = findPageModulesUnder(dir);

      it("has at least one real page.jsx under it (a route with none would pass vacuously)", () => {
        expect(pageFiles.length, `no page.jsx found under ${dir}`).toBeGreaterThan(0);
      });

      it.each(pageFiles.length ? pageFiles : ["<none found>"])(
        "%s reaches no useDynastyData()/useApp() call in its transitive import graph",
        (pageFile) => {
          if (pageFile === "<none found>") return; // covered by the assertion above
          const { visitedFiles, consumers } = findTransitivePlayerDataConsumers(pageFile);
          // A graph of 1 (just the entry file, nothing resolved) means the
          // walker never actually traversed anything real — that would be
          // this test lying about coverage, not a clean route.
          expect(
            visitedFiles.size,
            `${path.relative(FRONTEND_ROOT, pageFile)}: import graph walk only reached ` +
              `${visitedFiles.size} file(s) — the walker is not resolving this route's imports`,
          ).toBeGreaterThan(1);
          expect(
            consumers,
            `${path.relative(FRONTEND_ROOT, pageFile)} transitively reaches a player-data ` +
              `consumer it must not have:\n  ${describeConsumers(consumers)}`,
          ).toEqual([]);
        },
      );
    });
  }
});

// Positive control (requirement: the scanner must demonstrably detect a
// REAL transitive consumer, not just report "clean" because it never
// looks at anything). These two routes are the deliberate exclusions —
// audited and pinned in app-shell-route-gates.test.js as staying ON the
// player pipeline because they really consume it. If the scanner ever
// stopped detecting them, every "no consumers found" result above would
// be meaningless.
describe("positive control — the scanner detects real consumers on the two deliberate exclusions", () => {
  it("/settings calls useDynastyData() directly", () => {
    const file = path.join(FRONTEND_ROOT, "app", "settings", "page.jsx");
    const { consumers } = findTransitivePlayerDataConsumers(file);
    expect(consumers.some((c) => c.hook === "useDynastyData")).toBe(true);
  });

  it("/tools/trade-coverage reaches useApp() — directly, and transitively via useTeam()", () => {
    const file = path.join(FRONTEND_ROOT, "app", "tools", "trade-coverage", "page.jsx");
    const { consumers } = findTransitivePlayerDataConsumers(file);
    const appConsumers = consumers.filter((c) => c.hook === "useApp");
    expect(appConsumers.length).toBeGreaterThan(0);
    // At least one hit must come from a file OTHER than the route's own
    // page.jsx — proving this is genuinely a TRANSITIVE-graph detection,
    // not just "does the entry file itself mention the hook".
    expect(appConsumers.some((c) => c.file !== file)).toBe(true);
  });
});
