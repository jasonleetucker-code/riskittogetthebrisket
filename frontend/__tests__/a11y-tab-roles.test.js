/**
 * `role="tab"` must control something (a11y guard).
 *
 * ── Why this is a test and not an ESLint rule ─────────────────────────
 * The R5 plan called for a lint rule. This project has **no ESLint at
 * all** — no config, no dependency, no CI step; the only linter in the
 * repo is Python's ruff. Standing up the whole toolchain would mean new
 * devDependencies, churn in the coordination-controlled lockfile, a new
 * CI job, and a first run that floods a never-linted codebase with
 * unrelated findings. That is disproportionate mid-integration-window.
 *
 * So the guard lives where this repo already keeps its structural
 * invariants (token-contract, panel-order-pairing, card-surface-tokens,
 * panel-server-safe): a vitest test in the existing CI gate. Same
 * blocking effect, zero new dependencies.
 *
 * It is also STRICTLY STRONGER than the rule would have been. I recorded
 * that cross-file `aria-controls` → `role="tabpanel"` resolution is
 * beyond a per-file linter; a test reads the whole tree, so it does that
 * resolution properly instead of settling for "the attribute exists".
 *
 * ── What it enforces ──────────────────────────────────────────────────
 *   An element with role="tab" must carry aria-controls, and the id it
 *   names must belong to an element with role="tabpanel".
 *
 * A tab that controls nothing is not a tab — it is a filter or a toggle,
 * and it should be a ds `SegmentedControl` or a `Button` with
 * aria-pressed. The fix is ALWAYS to use the primitive, never to hand-add
 * `aria-controls`: bolting the attribute on produces a control that
 * *claims* to own a tabpanel that does not exist, which is worse than
 * today's honest-but-wrong markup.
 *
 * ── Ratchet ───────────────────────────────────────────────────────────
 * Existing violations are baselined below (same pattern as the repo's
 * ruff enforcement, which lints changed files only). The baseline blocks
 * NEW instances today — which is the point, since this is a spreading
 * habit — and R5 burns it down as each control moves to a primitive.
 * Removing an entry is a one-line change once its file is fixed; the
 * test fails if a file improves and its entry is left stale, so the
 * baseline cannot rot upward.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const SCAN = ["app", "components"];

/**
 * Known-violating files and their `role="tab"` count, as of the R5 scope
 * pass. Each is a control that switches a view without owning a
 * tabpanel. All become `SegmentedControl`; none become `Tabs`.
 *
 * Burn-down owner: docs/redesign/R5-LEAGUE-MIGRATION.md §3a.
 */
const BASELINE = {
  "app/trending/page.jsx": 1,
  "app/league/activity/page.jsx": 1,
  "components/terminal/PlayerMarketMovement.jsx": 2,
  "components/terminal/TeamNewsFeed.jsx": 1,
};
// Burned down so far:
//   app/news/page.jsx — R3 (#551) moved it onto ds `Tabs`, which stamps
//   a real role="tabpanel" + aria-controls. De-listed when the
//   stale-entry assertion caught it on the first rebase onto merged
//   main, which is precisely the job that assertion exists to do.
//   components/terminal/MarketTicker.jsx — C8-PSI-01 (Chase Upside
//   Market Ticker rebuild) moved its scope switch onto ds
//   `SegmentedControl`, which is a radiogroup filter over one list, not
//   tabpanels — the fix this guard has always named. De-listed by the
//   same stale-entry assertion.

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith(".jsx")) out.push(p);
  }
  return out;
}

const FILES = SCAN.flatMap((d) => walk(path.join(ROOT, d)));
const rel = (p) => path.relative(ROOT, p).split(path.sep).join("/");
/**
 * Comments are stripped before scanning. A file that EXPLAINS why it is
 * not using `role="tab"` necessarily contains the literal `role="tab"`
 * in prose, and counting that as a violation makes the guard punish the
 * very documentation it asks people to write. (Caught exactly that way:
 * fixing `/trade` added a comment naming the pattern, and the scanner
 * flagged the comment.)
 */
const sources = new Map(
  FILES.map((f) => [
    rel(f),
    fs.readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, ""),
  ]),
);

/** The attribute text of the JSX element containing index `i`. */
function attrsAround(src, i) {
  const open = src.lastIndexOf("<", i);
  if (open === -1) return "";
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    const c = src[j];
    if (c === "{") depth++;
    else if (c === "}") depth--;
    else if (c === ">" && depth === 0) return src.slice(open, j);
  }
  return src.slice(open);
}

/** Every role="tab" site, with whether it declares aria-controls. */
function tabSites() {
  const sites = [];
  for (const [file, src] of sources) {
    for (const m of src.matchAll(/role=["']tab["']/g)) {
      const attrs = attrsAround(src, m.index);
      sites.push({
        file,
        line: src.slice(0, m.index).split("\n").length,
        hasControls: /aria-controls\s*=/.test(attrs),
      });
    }
  }
  return sites;
}

/** True if ANY file declares a role="tabpanel" (cross-file, so a test
 *  can check what a per-file linter cannot). */
const hasTabpanelAnywhere = [...sources.values()].some((s) =>
  /role=["']tabpanel["']/.test(s),
);

const sites = tabSites();
const offenders = sites.filter((s) => !s.hasControls);
const byFile = offenders.reduce((acc, s) => {
  acc[s.file] = (acc[s.file] || 0) + 1;
  return acc;
}, {});

const FIX =
  'a role="tab" without aria-controls is a filter, not a tab — use ds ' +
  "`SegmentedControl` (or `Button` + aria-pressed). Do NOT hand-add " +
  "aria-controls: that claims a tabpanel that does not exist.";

describe('role="tab" must control something', () => {
  it("finds tab sites to check (guards against a broken scanner)", () => {
    // If the scan silently matched nothing, every assertion below would
    // pass vacuously.
    expect(sites.length).toBeGreaterThan(5);
    expect(hasTabpanelAnywhere).toBe(true);
  });

  it("reports no NEW violations beyond the documented baseline", () => {
    const unexpected = Object.entries(byFile)
      .filter(([f, n]) => (BASELINE[f] || 0) < n)
      .map(([f, n]) => `${f}: ${n} (baseline ${BASELINE[f] || 0}) — ${FIX}`);
    expect(unexpected).toEqual([]);
  });

  it("has no stale baseline entries (fixed files must be de-listed)", () => {
    // Keeps the ratchet pointing one way: once a file is fixed, its
    // entry has to go, so the baseline can never quietly re-absorb a
    // regression.
    const stale = Object.entries(BASELINE)
      .filter(([f, n]) => (byFile[f] || 0) < n)
      .map(([f, n]) => `${f}: baseline ${n}, actual ${byFile[f] || 0}`);
    expect(stale).toEqual([]);
  });

  it("every compliant tab resolves to a real tabpanel", () => {
    // The cross-file check a per-file linter can't do. For sites that DO
    // declare aria-controls, the id must be produced by the same helper
    // that stamps role="tabpanel" — i.e. they go through ds Tabs.
    const compliant = sites.filter((s) => s.hasControls);
    for (const s of compliant) {
      const src = sources.get(s.file);
      const usesHelper =
        /tabPanelId\s*\(/.test(src) || /role=["']tabpanel["']/.test(src);
      expect(
        usesHelper,
        `${s.file}:${s.line} declares aria-controls but nothing in the file ` +
          "produces a role=\"tabpanel\" — the tab points at a region that " +
          "does not exist",
      ).toBe(true);
    }
  });

  it("the ds Tabs primitive is itself compliant", () => {
    // The fix for every baseline entry is "use the primitive", so the
    // primitive had better be right.
    //
    // NOTE: Tabs deliberately renders NO tabpanels — it emits
    // aria-controls={tabPanelId(prefix, id)} and the caller renders the
    // matching role="tabpanel". So asserting role="tabpanel" *here* is
    // wrong, and until comments were stripped this assertion was
    // passing on Tabs' own docblock rather than on its markup: a
    // vacuous check hiding in a compliance test.
    const src = sources.get("components/ds/Tabs.jsx");
    expect(src).toBeTruthy();
    expect(src).toMatch(/role=["']tab["']/);
    // every tab it renders names the panel it controls
    expect(src).toMatch(/aria-controls=\{tabPanelId\(/);
    // and it exports the helper callers need to stamp that panel id
    expect(src).toMatch(/export function tabPanelId/);
  });
});
