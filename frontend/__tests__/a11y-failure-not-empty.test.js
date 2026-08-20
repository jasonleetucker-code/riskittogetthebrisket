/**
 * A failure must not be rendered as an absence.
 *
 * `EmptyState` says "there is nothing here". A failed fetch says "we
 * could not find out". Rendering the second with the first is wrong in
 * three separate ways, and all three were live:
 *
 *   1. It tells a screen reader the wrong thing. EmptyState is a
 *      neutral, non-interrupting surface; a failure needs `role="alert"`.
 *      `ds/FailureState` picks the role from the KIND — `empty` stays
 *      `role="status"` precisely so a backend that simply has not
 *      scraped yet does not interrupt anyone.
 *   2. It offers no retry, because an empty list has nothing to retry.
 *   3. It prints the raw thrown string. Since contract failures now
 *      carry their response body, that is a JSON 503 payload rendered
 *      into the page — observed on `/rosters` in a control run:
 *      `Failed to load dynasty data: 503 {"ok":false,"error":"backend
 *      unreachable or stalled",...}`.
 *
 * The enabling defect was upstream of all of them: `useDynastyData`
 * classifies failures, but `AppShell`'s context forwarded only the
 * message string, so no `useApp()` consumer could tell a 503 from a 403
 * however well the hook had classified it. That is fixed, and this guard
 * stops the pattern coming back.
 *
 * Ratchet, in the style of `a11y-tab-roles.test.js` and
 * `a11y-clickable-keyboard.test.js`: new violations fail, and so do
 * stale allowances.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");

/**
 * Known sites rendering a failure through the empty primitive, measured
 * 2026-08-18. Most are `/league` — a public route of ~10.8k lines whose
 * sections each own their own fetch — and are a separate unit of work.
 *
 * `app/rosters/page.jsx` is deliberately ABSENT: it was the one this
 * guard was written for, and it now renders `ds/FailureState`.
 */
const BASELINE = {
  "app/admin/sharp-identities/page.jsx": 1,
  "app/trending/page.jsx": 1,
  "app/players/compare/page.jsx": 1,
  "app/tools/ros-data-health/page.jsx": 1,
  "app/bdvm/page.jsx": 2,
  "app/market/sharp-tracker/page.jsx": 1,
  "app/league/activity/page.jsx": 1,
  "app/league/sections/ros-team-strength.jsx": 1,
  "app/league/sections/ros-championship.jsx": 1,
  "app/league/sections/ros-trade-deadline.jsx": 1,
  "app/league/sections/draft-capital.jsx": 1,
  "app/league/sections/ros-power.jsx": 1,
  "app/league/LeagueClient.jsx": 2,
  "app/league/insider-trading/page.jsx": 1,
  "app/market/sharp-people/page.jsx": 1,
  "app/market/sharp-people/[personId]/page.jsx": 1,
};

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    if (e.name === "__tests__") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith(".jsx")) out.push(p);
  }
  return out;
}

/**
 * `<EmptyState ...>` occurrences whose TITLE names a failure.
 *
 * Matching on the title rather than anywhere in the props is the whole
 * precision of this guard, and it was tightened after a first pass
 * flagged `app/league/activity/page.jsx`:
 *
 *     <EmptyState
 *       title="No activity in this view"
 *       message={newsUnavailable && type === "all" ? "News is
 *         unavailable right now, and no trades ... match these filters."
 *         : "Try widening the scope..."} />
 *
 * That is CORRECT usage. The view genuinely is empty, and the body
 * honestly notes that one input was degraded. Flagging it would push
 * people toward exemptions, and toward hiding the degraded-input note to
 * get green — the opposite of what this file wants.
 *
 * The title is what the reader takes the state to BE, so the title is
 * what decides.
 */
function violations(src) {
  const out = [];
  for (const m of src.matchAll(/<EmptyState\b((?:[^<>]|\{[^{}]*\})*?)\/?>/gs)) {
    const attrs = m[1] || "";
    // Backreference the opening quote instead of a "not any quote"
    // class. The class version truncated `title="Couldn't load data"` at
    // the apostrophe, capturing "Couldn" — so three real violations read
    // as clean. The stale-allowance assertion is what surfaced it, which
    // is the job that assertion exists to do.
    const title =
      /title=\{?(["'`])((?:(?!\1).)*)\1\}?/s.exec(attrs)?.[2] ??
      /title=\{([^}]*)\}/s.exec(attrs)?.[1] ??
      "";
    if (
      !/error|failed|failure|unavailable|couldn't load|could not load/i.test(
        title,
      )
    ) {
      continue;
    }
    out.push({ line: src.slice(0, m.index).split("\n").length });
  }
  return out;
}

function scanRepo() {
  const found = {};
  for (const dir of ["app", "components"]) {
    const abs = path.join(ROOT, dir);
    if (!fs.existsSync(abs)) continue;
    for (const file of walk(abs)) {
      const rel = path.relative(ROOT, file).split(path.sep).join("/");
      // FailureState composes EmptyState on purpose — it is the fix, and
      // its own presentation table names every kind.
      if (rel === "components/ds/FailureState.jsx") continue;
      const v = violations(fs.readFileSync(file, "utf8"));
      if (v.length) found[rel] = v;
    }
  }
  return found;
}

describe("a failure must not render as an absence", () => {
  const found = scanRepo();

  it("the matcher actually matches (and does not over-match)", () => {
    expect(
      violations(`<EmptyState title="Error" message={error} />`),
    ).toHaveLength(1);
    // An apostrophe inside the title must not end the capture early.
    expect(
      violations(`<EmptyState title="Couldn't load data" message={String(e)} />`),
    ).toHaveLength(1);
    expect(
      violations(`<EmptyState title="No players match these filters" />`),
    ).toHaveLength(0);
    // The tightening case: an empty view that honestly reports a degraded
    // input is EMPTY, not failed, and must not be flagged.
    expect(
      violations(
        `<EmptyState title="No activity in this view" message={x ? "News is unavailable right now" : "Try widening"} />`,
      ),
    ).toHaveLength(0);
  });

  it("introduces no new failure-rendered-as-empty sites", () => {
    const offenders = [];
    for (const [file, v] of Object.entries(found)) {
      const allowed = BASELINE[file] ?? 0;
      if (v.length > allowed) {
        offenders.push(`${file}: ${v.length} (allowed ${allowed}) — lines ${v.map((x) => x.line).join(", ")}`);
      }
    }
    expect(
      offenders,
      "Render failures with `ds/FailureState`, which picks role=alert vs " +
        "role=status from the failure KIND and offers retry only when the " +
        "failure is retryable:\n" + offenders.join("\n"),
    ).toEqual([]);
  });

  it("has no stale allowances", () => {
    const stale = [];
    for (const [file, allowed] of Object.entries(BASELINE)) {
      const actual = found[file]?.length ?? 0;
      if (actual < allowed) stale.push(`${file}: allows ${allowed}, found ${actual}`);
    }
    expect(stale, "Lower or remove these BASELINE entries:\n" + stale.join("\n")).toEqual([]);
  });

  it("the contract context carries the classified failure, not just a string", () => {
    // The enabling defect. Without these on the context, every useApp()
    // consumer is structurally unable to render a classified failure.
    const shell = fs.readFileSync(
      path.join(ROOT, "components", "AppShell.jsx"),
      "utf8",
    );
    expect(shell).toMatch(/const\s*\{[^}]*\bfailure\b[^}]*\}\s*=\s*useDynastyData\(\)/s);
    const ctxValue = shell.slice(shell.indexOf("<AppContext.Provider"));
    expect(ctxValue).toMatch(/\bfailure,/);
    expect(ctxValue).toMatch(/\bretry,/);
  });

  it("/rosters renders a classified failure", () => {
    const src = fs.readFileSync(
      path.join(ROOT, "app", "rosters", "page.jsx"),
      "utf8",
    );
    expect(src).toMatch(/<FailureState\b/);
    expect(found["app/rosters/page.jsx"] ?? []).toEqual([]);
  });
});
