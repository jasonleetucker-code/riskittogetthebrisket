/**
 * One <main> landmark per page.  AppShellWrapper renders the only
 * `<main id="main">`; every route renders inside it, so a page-level
 * <main> nests a second main landmark (axe "landmark-no-duplicate-main",
 * and Playwright strict-mode `locator("main")` failures in production
 * verification).  Pages use a <div> with the same classes instead.
 */
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const APP = join(__dirname, "..", "app");

// A JSX <main element: "<main" then whitespace or ">" at the start of a
// line (optionally after `return (`), so a comment that merely names the
// landmark does not count.
const JSX_MAIN = /^\s*(?:return\s*\(?\s*)?<main(?:\s|>)/gm;

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "api" || name === "node_modules") continue;
      walk(p, out);
    } else if (/\.(jsx|js|tsx)$/.test(name)) {
      out.push(p);
    }
  }
  return out;
}

describe("single main landmark", () => {
  it("only the app shell renders a <main> element", () => {
    const offenders = walk(APP)
      .filter((f) => !f.endsWith("AppShellWrapper.jsx"))
      .filter((f) => (readFileSync(f, "utf8").match(JSX_MAIN) || []).length > 0)
      .map((f) => relative(APP, f));
    expect(offenders).toEqual([]);
  });

  it('the shell renders exactly one <main id="main">', () => {
    const shell = readFileSync(join(APP, "AppShellWrapper.jsx"), "utf8");
    expect((shell.match(JSX_MAIN) || []).length).toBe(1);
    expect(shell).toMatch(/<main\s+id="main"/);
  });
});
