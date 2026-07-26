/**
 * ds `Panel` must stay renderable from a React Server Component.
 *
 * WHY THIS TEST EXISTS
 * The contract lived only in a docblock in `app/league/shared-server.jsx`
 * ("no hooks ... so they can be rendered either from a React Server
 * Component or a Client Component"), so nothing caught it when the R3
 * `collapsible` addition put useState + useId into Panel without a
 * client directive.
 *
 * That is a quiet failure by construction:
 *   - Panel carries no client directive, so it adopts its importer's
 *     environment.
 *   - Every consumer today is already a client component, so it works.
 *   - `next build` still compiles: bundling succeeds, and the error
 *     would only appear when a Server Component actually renders it.
 *   - The seven /league RSCs that import shared-server.jsx are dynamic
 *     and data-backed, so they do not render in a data-less CI build.
 *
 * Seven Server Components import `shared-server.jsx` and four render its
 * `Card`, which is slated to become a `Panel`. The next hook added to
 * Panel should fail here, loudly, rather than wait for the first server
 * consumer to crash in production.
 *
 * WHAT THE RULE ACTUALLY IS — the subtlety this test got wrong first
 * time. It is NOT "nothing in Panel's import graph may be a client
 * component". A Server Component may freely render a client child; that
 * child is just a boundary. `Icon` is a client component and Panel
 * renders it perfectly happily.
 *
 * The real rule is about which modules end up executing *as server
 * modules*: a dependency with a client directive is a boundary and stops
 * the traversal; a dependency without one inherits the server
 * environment and therefore has to be hook-free, exactly like Panel.
 *
 * Asserted structurally rather than by rendering: reproducing an RSC
 * environment in vitest would test our mock of React's boundary rules,
 * not React's.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const DS = path.resolve(__dirname, "../../../components/ds");
const CLIENT_DIRECTIVE = /^\s*["']use client["']\s*;?\s*$/m;
const HOOKS =
  /\buse(State|Effect|LayoutEffect|Reducer|Context|Ref|Id|Memo|Callback|Transition|DeferredValue|SyncExternalStore|ImperativeHandle|OptimisticState|FormStatus)\s*\(/;

/** Source with comments stripped — prose about "use client" is not a
 *  directive, and this file's own docblocks discuss both at length. */
const read = (f) =>
  fs.readFileSync(path.join(DS, f), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Modules that execute as SERVER modules when an RSC renders a Panel:
 *  Panel plus its non-client dependencies, transitively. A dependency
 *  carrying the client directive is a boundary, not a member. */
function serverModules(entry = "Panel.jsx", seen = new Set()) {
  if (seen.has(entry)) return seen;
  seen.add(entry);
  for (const m of read(entry).matchAll(/from\s+"\.\/([\w-]+)"/g)) {
    const file = `${m[1]}.jsx`;
    if (!fs.existsSync(path.join(DS, file))) continue;
    if (CLIENT_DIRECTIVE.test(read(file))) continue; // boundary — fine
    serverModules(file, seen);
  }
  return seen;
}

const graph = [...serverModules()];

describe("ds Panel is server-safe", () => {
  it("has Panel itself in the server graph", () => {
    expect(graph).toContain("Panel.jsx");
  });

  it("keeps that graph small", () => {
    // If this grows, the surface that must stay hook-free grew too —
    // worth a look rather than a silent pass.
    expect(graph.length).toBeLessThanOrEqual(4);
  });

  it.each(graph.map((f) => [f]))("%s calls no React hook", (file) => {
    expect(
      read(file),
      `${file} calls a hook, so an RSC rendering <Panel> would crash`,
    ).not.toMatch(HOOKS);
  });

  it.each(graph.map((f) => [f]))("%s imports no hook from react", (file) => {
    const imports = read(file).match(/import\s+[^;]*?from\s+"react"/s)?.[0] ?? "";
    expect(imports).not.toMatch(/\buse[A-Z]/);
  });

  it("does not paper over it by making Panel a client component", () => {
    // A client directive on Panel would make the hook assertions pass
    // while pushing client JS onto seven currently-server /league
    // routes — on the page with the tightest bundle headroom in the app
    // (167.8 of 170 KB). The fix is to keep state out, not to move the
    // boundary.
    expect(read("Panel.jsx")).not.toMatch(CLIENT_DIRECTIVE);
  });

  it("keeps the stateful variant behind its own client boundary", () => {
    const wrapper = read("CollapsiblePanel.jsx");
    expect(wrapper).toMatch(CLIENT_DIRECTIVE);
    expect(wrapper).toMatch(/useState\s*\(/);
    // …and it composes Panel rather than forking its markup.
    expect(wrapper).toMatch(/from\s+"\.\/Panel"/);
  });
});
