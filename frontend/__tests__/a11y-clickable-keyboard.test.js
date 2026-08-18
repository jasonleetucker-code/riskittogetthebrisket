/**
 * A click handler on a non-interactive element must be reachable from a
 * keyboard (WCAG 2.1.1, Keyboard).
 *
 * ── Why this is a test, not a lint rule ───────────────────────────────
 * Same reason as `a11y-tab-roles.test.js`: this repo has no ESLint at
 * all, and standing up the toolchain to catch one rule class would mean
 * new devDependencies, lockfile churn in a coordination-controlled file,
 * a new CI job, and a first run that floods a never-linted codebase.
 * The guard lives where this repo already keeps its structural
 * invariants — a vitest test in the existing gate. Same blocking effect,
 * zero new dependencies.
 *
 * ── Why axe does not cover this ───────────────────────────────────────
 * The axe ratchet added in this branch (`tests/e2e/specs/a11y-axe.spec.js`)
 * reports **zero** WCAG A/AA violations across ten routes, and every one
 * of the elements below is still unreachable by keyboard. axe has no
 * rule for "a span with onClick and no key handler" — a bare clickable
 * div is not machine-distinguishable from a decorative one, so the
 * checker leaves it to a manual review that had never happened here.
 * Reporting green while a core action cannot be performed without a
 * mouse is exactly the gap this file closes.
 *
 * ── What it enforces ──────────────────────────────────────────────────
 * An element from the non-interactive set carrying `onClick` must ALSO
 * carry `tabIndex` and a key handler. The real fix is almost always to
 * use a `<button>` instead, which gets focus, Enter/Space activation and
 * the right AT role for free — `tabIndex` + `onKeyDown` is the fallback
 * for cases where the element must stay a row or a cell.
 *
 * Native interactive elements (button, a[href], input, select, textarea,
 * summary) are exempt: they already do this.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");

// Elements with no native activation behaviour. `label` is here because
// its click target is the labelled control, not the label itself.
const NON_INTERACTIVE =
  "(span|div|li|td|tr|p|section|article|h[1-6]|img|label|ul|ol|nav|figure)";

/**
 * Known violations by file, measured 2026-08-18. Every entry is a
 * control a keyboard user cannot operate. This is a RATCHET: new
 * violations fail, and so do stale allowances, so burning one down
 * forces the entry to be removed rather than left to rot.
 *
 * Burn-down note: `app/draft/page.jsx` is not listed because it was the
 * severe case and is fixed in the same commit — five of its six were the
 * player NAME on the next-best-target boards, i.e. *drafting a player*
 * was mouse-only from five separate panels.
 *
 * The remaining 24 are mostly `/league` (a public route, ~10.8k lines)
 * and are a separate, larger unit of work.
 */
const BASELINE = {
  "app/league/sections/awards.jsx": 6,
  "app/league/sections/history.jsx": 3,
  "components/ScreenshotFab.jsx": 2,
  "app/league/shared.jsx": 2,
  "app/league/sections/rivalries.jsx": 2,
  "components/InsiderLeads.jsx": 1,
  "components/terminal/MoversPanel.jsx": 1,
  "components/ds/Dialog.jsx": 1,
  "app/league/sections/ros-team-strength.jsx": 1,
  "app/league/sections/draft.jsx": 1,
  "app/league/sections/franchise.jsx": 1,
  "app/league/sections/activity.jsx": 1,
  "app/league/sections/ros-power.jsx": 1,
  "app/league/insider-trading/page.jsx": 1,
};

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    if (e.name === "__tests__") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith(".jsx") || e.name.endsWith(".js")) out.push(p);
  }
  return out;
}

/**
 * Opening tags of non-interactive elements that carry onClick without
 * both a tabIndex and a key handler.
 *
 * The attribute matcher allows one level of brace nesting, which is what
 * JSX props like `onClick={() => f(x)}` and template class names need;
 * without it the scan silently stops at the first `}` and under-reports.
 */
function violations(src) {
  const re = new RegExp(`<${NON_INTERACTIVE}\\b((?:[^<>]|\\{[^{}]*\\})*?)>`, "gs");
  const out = [];
  for (const m of src.matchAll(re)) {
    const attrs = m[2] || "";
    if (!attrs.includes("onClick")) continue;
    const hasKey = ["onKeyDown", "onKeyUp", "onKeyPress"].some((k) =>
      attrs.includes(k),
    );
    if (attrs.includes("tabIndex") && hasKey) continue;
    out.push({ tag: m[1], line: src.slice(0, m.index).split("\n").length });
  }
  return out;
}

function scanRepo() {
  const found = {};
  for (const dir of ["app", "components", "lib"]) {
    const abs = path.join(ROOT, dir);
    if (!fs.existsSync(abs)) continue;
    for (const file of walk(abs)) {
      const rel = path.relative(ROOT, file).split(path.sep).join("/");
      const v = violations(fs.readFileSync(file, "utf8"));
      if (v.length) found[rel] = v;
    }
  }
  return found;
}

describe("a11y: a click handler must be reachable from a keyboard", () => {
  const found = scanRepo();

  // Self-guard. A regex that silently matched nothing would make every
  // assertion below pass against an empty scan — the failure mode this
  // whole file exists to prevent, one level up.
  it("actually parses JSX and finds click handlers at all", () => {
    const src = fs.readFileSync(
      path.join(ROOT, "app", "draft", "page.jsx"),
      "utf8",
    );
    expect(src.length).toBeGreaterThan(1000);
    // A synthetic positive: the matcher must flag this shape.
    expect(violations(`<span onClick={() => f(1)}>x</span>`)).toHaveLength(1);
    // ...and must NOT flag a properly keyboard-enabled one.
    expect(
      violations(
        `<span role="button" tabIndex={0} onClick={f} onKeyDown={f}>x</span>`,
      ),
    ).toHaveLength(0);
    // ...nor a real button.
    expect(violations(`<button onClick={f}>x</button>`)).toHaveLength(0);
  });

  it("introduces no new keyboard-unreachable click targets", () => {
    const offenders = [];
    for (const [file, v] of Object.entries(found)) {
      const allowed = BASELINE[file] ?? 0;
      if (v.length > allowed) {
        offenders.push(
          `${file}: ${v.length} (allowed ${allowed}) — lines ${v
            .map((x) => x.line)
            .join(", ")}`,
        );
      }
    }
    expect(
      offenders,
      "A click handler on a non-interactive element is invisible to a keyboard " +
        "user. Use a <button> (focus + Enter/Space + role for free), or add " +
        "tabIndex AND a key handler if it must stay a row/cell.\n" +
        offenders.join("\n"),
    ).toEqual([]);
  });

  it("has no stale allowances", () => {
    // A baseline entry that is no longer needed must be deleted, or the
    // ratchet quietly stops ratcheting.
    const stale = [];
    for (const [file, allowed] of Object.entries(BASELINE)) {
      const actual = found[file]?.length ?? 0;
      if (actual < allowed) {
        stale.push(`${file}: allows ${allowed}, found ${actual}`);
      }
    }
    expect(
      stale,
      "These files improved — lower or remove their BASELINE entry:\n" +
        stale.join("\n"),
    ).toEqual([]);
  });

  it("the draft board's own actions are keyboard-reachable", () => {
    // Named explicitly rather than left to the aggregate: drafting a
    // player is the page's whole purpose, and it was mouse-only from
    // five separate panels plus the main board row.
    expect(found["app/draft/page.jsx"] ?? []).toEqual([]);
  });
});
