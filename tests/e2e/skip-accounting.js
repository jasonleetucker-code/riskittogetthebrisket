/**
 * Skip accounting for the Playwright suite -- pure functions, no I/O except
 * `loadBaseline`.
 *
 * Why this exists (STAB-8, owner directive 2026-11-19)
 * ----------------------------------------------------
 * The suite used to bound skips with ONE bare number (`MAX_EXPECTED_SKIPPED`,
 * 70).  Main sat at exactly 70 of 70, so any new deliberate skip turned the
 * whole E2E Safety Net red -- and a bare count cannot tell a deliberate skip
 * from a layer that silently stopped running.  Worse, 66 of those 70 were
 * not signal at all: project gating (`desktopOnly` / `mobileOnly` called
 * `test.skip()` on every project a test was not meant for).
 *
 * The accounting is now per test, against a reviewed baseline
 * (`skip-baseline.json`): spec file + test title + project + category +
 * reason.
 *
 *   unexpected  a test skipped that is NOT in the baseline -> FAILS the run,
 *               named in the error.  This is the real guard: a new skip must
 *               be reviewed and recorded, never absorbed by headroom.
 *   stale       a baseline entry whose test ran this time (or no longer
 *               exists) -> FAILS the run, so the list can only shrink.
 *               EXCEPT category `unsupported-environment`: whether the host
 *               can run the test (e.g. Tesseract is installed) legitimately
 *               differs between machines, so a stale entry there is reported
 *               but never fails.
 *
 * Project-only gating does not belong in this list at all.  Use a title tag
 * (`@desktop-only`, `@mobile-only`, `@a11y-desktop-only`) filtered by the
 * project's `grepInvert` in playwright.config.js, so the test simply does
 * not exist on that project.
 *
 * Staleness is judged only for what THIS run could have seen: a baseline
 * entry is checked only when its project ran and its spec file was collected
 * (a one-spec or one-project run does not mark everything else stale).
 */

const fs = require("node:fs");
const path = require("node:path");

const BASELINE_PATH = path.join(__dirname, "skip-baseline.json");

/**
 * `project-gating` is deliberately NOT a category: it is expressed with
 * grepInvert tags and must never be counted as a skip.
 */
const CATEGORIES = Object.freeze([
  "unsupported-environment", // the host cannot run it (missing binary, no network)
  "data-dependent", // skips when the seeded data lacks the precondition
  "missing-fixture", // a fixture/baseline the test needs is not committed
  "temporary-exclusion", // known-broken, with an owner and an exit condition
]);

/** Host capability can legitimately differ run to run; stale never fails. */
const HOST_DEPENDENT = Object.freeze(new Set(["unsupported-environment"]));

function entryId(file, project, title) {
  return `${file} | ${project} | ${title}`;
}

/** Playwright `TestCase` -> plain, comparable record. */
function describeTest(testCase) {
  // titlePath() = ["", projectName, fileName, ...describes, title]
  const tp = testCase.titlePath();
  return {
    project: tp[1] || "",
    file: tp[2] || "",
    title: tp.slice(3).join(" > "),
    skipped: typeof testCase.outcome === "function" && testCase.outcome() === "skipped",
  };
}

/** Structural validation of the baseline document.  Returns error strings. */
function validateBaseline(doc) {
  const errors = [];
  if (!doc || typeof doc !== "object" || !Array.isArray(doc.entries)) {
    return ["baseline must be an object with an `entries` array"];
  }
  const seen = new Set();
  doc.entries.forEach((e, i) => {
    const where = `entries[${i}]`;
    if (!e || typeof e !== "object") {
      errors.push(`${where} is not an object`);
      return;
    }
    for (const k of ["file", "title", "category", "reason"]) {
      if (typeof e[k] !== "string" || e[k].trim() === "") {
        errors.push(`${where}.${k} must be a non-empty string`);
      }
    }
    if (!Array.isArray(e.projects) || e.projects.length === 0 || e.projects.some((p) => typeof p !== "string" || !p)) {
      errors.push(`${where}.projects must be a non-empty array of project names`);
    }
    if (typeof e.category === "string" && !CATEGORIES.includes(e.category)) {
      errors.push(
        `${where}.category "${e.category}" is not one of ${CATEGORIES.join(", ")} ` +
          `(project-only gating is a @tag + grepInvert, never a baseline entry)`,
      );
    }
    for (const p of Array.isArray(e.projects) ? e.projects : []) {
      const id = entryId(e.file, p, e.title);
      if (seen.has(id)) errors.push(`${where} duplicates ${id}`);
      seen.add(id);
    }
  });
  return errors;
}

function loadBaseline(file = BASELINE_PATH) {
  const doc = JSON.parse(fs.readFileSync(file, "utf8"));
  const errors = validateBaseline(doc);
  if (errors.length) {
    throw new Error(`skip baseline ${file} is invalid:\n  - ${errors.join("\n  - ")}`);
  }
  return doc;
}

/**
 * @param {{file:string,project:string,title:string,skipped:boolean}[]} collected
 *        every test the run COLLECTED (after grep/grepInvert), skipped or not
 * @param {{entries:object[]}} baseline
 */
function evaluateSkips(collected, baseline) {
  const byId = new Map();
  const projectsRun = new Set();
  const filesRun = new Set();
  for (const t of collected) {
    byId.set(entryId(t.file, t.project, t.title), t);
    projectsRun.add(t.project);
    filesRun.add(`${t.project} | ${t.file}`);
  }

  const baselineIds = new Map();
  for (const e of baseline.entries) {
    for (const p of e.projects) baselineIds.set(entryId(e.file, p, e.title), { entry: e, project: p });
  }

  const skipped = collected.filter((t) => t.skipped);
  const unexpected = skipped.filter((t) => !baselineIds.has(entryId(t.file, t.project, t.title)));

  const stale = [];
  const hostDependentStale = [];
  for (const [id, { entry, project }] of baselineIds) {
    if (!projectsRun.has(project)) continue; // this run never targeted that project
    if (!filesRun.has(`${project} | ${entry.file}`)) continue; // that spec was not part of this run
    const seen = byId.get(id);
    let why = null;
    if (!seen) why = "no such test exists any more (renamed, tagged out or deleted)";
    else if (!seen.skipped) why = "the test ran this time";
    if (!why) continue;
    const row = { file: entry.file, project, title: entry.title, category: entry.category, why };
    (HOST_DEPENDENT.has(entry.category) ? hostDependentStale : stale).push(row);
  }
  return { skippedCount: skipped.length, unexpected, stale, hostDependentStale };
}

/** Human-readable failure/diagnostic text.  Empty string when all is well. */
function formatReport(result, { baselinePath = "tests/e2e/skip-baseline.json" } = {}) {
  const lines = [];
  if (result.unexpected.length) {
    lines.push(`UNEXPECTED SKIPS (${result.unexpected.length}) -- not in ${baselinePath}:`);
    for (const t of result.unexpected) lines.push(`  - [${t.project}] ${t.file} :: ${t.title}`);
    lines.push(
      "",
      "A skipped test is lost coverage.  Either make the test run, express",
      "project-only gating with a @desktop-only / @mobile-only title tag",
      "(filtered by grepInvert, never skipped), or -- if the skip is truly",
      "intended -- add a reviewed entry with a category and a reason.",
    );
  }
  if (result.stale.length) {
    if (lines.length) lines.push("");
    lines.push(`STALE BASELINE ENTRIES (${result.stale.length}) -- remove them from ${baselinePath}:`);
    for (const s of result.stale) lines.push(`  - [${s.project}] ${s.file} :: ${s.title}  (${s.why})`);
  }
  if (result.hostDependentStale.length) {
    if (lines.length) lines.push("");
    lines.push(
      `note: ${result.hostDependentStale.length} unsupported-environment baseline entr` +
        `${result.hostDependentStale.length === 1 ? "y" : "ies"} did not skip on this host ` +
        `(expected when the host has the capability; not a failure):`,
    );
    for (const s of result.hostDependentStale) lines.push(`  - [${s.project}] ${s.file} :: ${s.title}`);
  }
  return lines.join("\n");
}

module.exports = {
  BASELINE_PATH,
  CATEGORIES,
  describeTest,
  entryId,
  evaluateSkips,
  formatReport,
  loadBaseline,
  validateBaseline,
};
