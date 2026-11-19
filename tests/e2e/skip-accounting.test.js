// Run with: node --test tests/e2e/skip-accounting.test.js
// Pure-function tests for skip-accounting.js plus invariants on the committed
// baseline.  No Playwright, no stack.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  BASELINE_PATH,
  CATEGORIES,
  describeTest,
  evaluateSkips,
  formatReport,
  loadBaseline,
  validateBaseline,
} = require("./skip-accounting.js");

const OCR = "trade-screenshot-import.spec.js";
const T1 = "real OCR: a committed screenshot lands on the right sides";

function baselineOf(...entries) {
  return { entries };
}
function entry(over = {}) {
  return {
    file: OCR,
    title: T1,
    projects: ["desktop-1366"],
    category: "data-dependent",
    reason: "because",
    ...over,
  };
}
function t(file, project, title, skipped) {
  return { file, project, title, skipped };
}

test("a skip that is in the baseline is accepted", () => {
  const r = evaluateSkips([t(OCR, "desktop-1366", T1, true)], baselineOf(entry()));
  assert.equal(r.skippedCount, 1);
  assert.deepEqual(r.unexpected, []);
  assert.deepEqual(r.stale, []);
});

test("a NEW skip not in the baseline is unexpected and named, whatever the total", () => {
  const r = evaluateSkips(
    [t(OCR, "desktop-1366", T1, true), t("a.spec.js", "desktop-1366", "g > brand new skip", true)],
    baselineOf(entry()),
  );
  assert.equal(r.unexpected.length, 1);
  assert.equal(r.unexpected[0].title, "g > brand new skip");
  const text = formatReport(r);
  assert.match(text, /UNEXPECTED SKIPS \(1\)/);
  assert.match(text, /\[desktop-1366\] a\.spec\.js :: g > brand new skip/);
});

test("the same test skipping on a project the baseline does not list is unexpected", () => {
  const r = evaluateSkips([t(OCR, "mobile-390", T1, true)], baselineOf(entry()));
  assert.equal(r.unexpected.length, 1);
});

test("an entry that no longer skips is stale (the list can only shrink)", () => {
  const r = evaluateSkips([t(OCR, "desktop-1366", T1, false)], baselineOf(entry()));
  assert.deepEqual(r.unexpected, []);
  assert.equal(r.stale.length, 1);
  assert.match(r.stale[0].why, /ran this time/);
  assert.match(formatReport(r), /STALE BASELINE ENTRIES \(1\)/);
});

test("an entry whose test was renamed or removed is stale too", () => {
  const r = evaluateSkips([t(OCR, "desktop-1366", "some other test", false)], baselineOf(entry()));
  assert.equal(r.stale.length, 1);
  assert.match(r.stale[0].why, /no such test/);
});

test("unsupported-environment entries that did not skip are reported but never fail", () => {
  const r = evaluateSkips(
    [t(OCR, "desktop-1366", T1, false)],
    baselineOf(entry({ category: "unsupported-environment" })),
  );
  assert.deepEqual(r.stale, []);
  assert.equal(r.hostDependentStale.length, 1);
  assert.match(formatReport(r), /did not skip on this host/);
});

test("a run that did not target a project or spec does not mark its entries stale", () => {
  const b = baselineOf(
    entry({ projects: ["desktop-1366", "mobile-390"] }),
    entry({ file: "other.spec.js", title: "x" }),
  );
  // Only desktop-1366 ran, and only the OCR spec was collected.
  const r = evaluateSkips([t(OCR, "desktop-1366", T1, true)], b);
  assert.deepEqual(r.stale, []);
  assert.deepEqual(r.unexpected, []);
});

test("no skips and an empty baseline is a clean report", () => {
  const r = evaluateSkips([t("a.spec.js", "desktop-1366", "x", false)], baselineOf());
  assert.equal(formatReport(r), "");
});

test("describeTest reads Playwright's titlePath and outcome()", () => {
  const fake = {
    titlePath: () => ["", "mobile-390", "a.spec.js", "describe", "test title"],
    outcome: () => "skipped",
  };
  assert.deepEqual(describeTest(fake), {
    project: "mobile-390",
    file: "a.spec.js",
    title: "describe > test title",
    skipped: true,
  });
});

test("validateBaseline rejects project-only gating, missing reasons, bad shapes and duplicates", () => {
  assert.deepEqual(validateBaseline(baselineOf(entry())), []);
  assert.match(validateBaseline(baselineOf(entry({ category: "project-gating" })))[0], /not one of/);
  assert.match(validateBaseline(baselineOf(entry({ reason: " " })))[0], /reason/);
  assert.match(validateBaseline(baselineOf(entry({ projects: [] })))[0], /projects/);
  assert.match(validateBaseline(baselineOf(entry(), entry()))[0], /duplicates/);
  assert.equal(validateBaseline(null).length, 1);
});

test("the committed baseline is valid, small and fully described", () => {
  const doc = loadBaseline(BASELINE_PATH);
  assert.ok(doc.entries.length > 0);
  // Coarse growth guard: the baseline is a list that shrinks.  Raising this
  // is a review decision, not a number to nudge to make CI green.
  assert.ok(doc.entries.length <= 10, `baseline has ${doc.entries.length} entries`);
  for (const e of doc.entries) {
    assert.ok(CATEGORIES.includes(e.category));
    assert.ok(e.reason.length >= 20, `${e.title}: reason too thin`);
  }
});

test("every baseline spec file exists and still contains its test title", () => {
  const doc = loadBaseline(BASELINE_PATH);
  for (const e of doc.entries) {
    const file = path.join(__dirname, "specs", e.file);
    assert.ok(fs.existsSync(file), `${e.file} does not exist`);
    const leaf = e.title.split(" > ").pop();
    assert.ok(fs.readFileSync(file, "utf8").includes(leaf), `${e.file} no longer contains "${leaf}"`);
  }
});
