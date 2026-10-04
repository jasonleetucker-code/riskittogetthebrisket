"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const Reporter = require("./structured-journey-reporter");

test("writes bounded structured findings without raw failure or attachment data", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "journey-evidence-"));
  const outputFile = path.join(directory, "report.json");
  const reporter = new Reporter({ outputFile });
  const originalBase = process.env.E2E_BASE_URL;
  const originalSha = process.env.GITHUB_SHA;
  process.env.E2E_BASE_URL =
    "https://user:secret@chaseupside.com/league?token=secret";
  process.env.GITHUB_SHA = "a".repeat(40);
  try {
    const browserTest = {
      id: "one",
      title: "deep link opens the right tab",
      location: {
        file: path.join(__dirname, "specs", "public-league.spec.js"),
      },
      parent: { project: () => ({ name: "mobile-chromium" }) },
      outcome: () => "flaky",
      results: [
        {
          duration: 20,
          errors: [{ message: "private content: secret" }],
          steps: [
            {
              error: null,
              steps: [{ error: { message: "secret" }, steps: [] }],
            },
          ],
          attachments: [{ path: "C:/private/trace.zip", name: "trace" }],
        },
        { duration: 10, errors: [], steps: [], attachments: [] },
      ],
    };
    reporter.onTestEnd(browserTest);
    await reporter.onEnd({ status: "passed" });
    const report = JSON.parse(fs.readFileSync(outputFile, "utf8"));
    assert.equal(report.source_commit, "a".repeat(40));
    assert.equal(report.target_origin, "https://chaseupside.com");
    assert.deepEqual(report.counts, {
      passed: 0,
      failed: 0,
      flaky: 1,
      skipped: 0,
      interrupted: 0,
      unexpected: 0,
    });
    assert.deepEqual(report.findings, [
      {
        spec: "specs/public-league.spec.js",
        project: "mobile-chromium",
        title: "deep link opens the right tab",
        outcome: "flaky",
        attempts: 2,
        duration_ms: 30,
        failed_steps: 1,
        error_count: 1,
        has_trace: true,
        has_screenshot: false,
      },
    ]);
    const raw = fs.readFileSync(outputFile, "utf8");
    assert.equal(raw.includes("secret"), false);
    assert.equal(raw.includes("C:/private"), false);
  } finally {
    if (originalBase === undefined) delete process.env.E2E_BASE_URL;
    else process.env.E2E_BASE_URL = originalBase;
    if (originalSha === undefined) delete process.env.GITHUB_SHA;
    else process.env.GITHUB_SHA = originalSha;
    fs.unlinkSync(outputFile);
    fs.rmdirSync(directory);
  }
});

test("normalizes Playwright expected and unexpected outcomes", () => {
  const fixture = {
    id: "one",
    title: "a test",
    location: { file: path.join(__dirname, "specs", "public-league.spec.js") },
    parent: { project: () => ({ name: "desktop-1366" }) },
    results: [{ duration: 1, errors: [], steps: [], attachments: [] }],
  };
  assert.equal(
    Reporter.summarize({ ...fixture, outcome: () => "expected" }).outcome,
    "passed",
  );
  assert.equal(
    Reporter.summarize({ ...fixture, outcome: () => "unexpected" }).outcome,
    "failed",
  );
});

test("caps findings while preserving all outcome counts", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "journey-evidence-"));
  const outputFile = path.join(directory, "report.json");
  try {
    const reporter = new Reporter({ outputFile });
    for (let index = 0; index < 501; index += 1) {
      reporter.onTestEnd({
        id: String(index),
        title: `case ${index}`,
        location: {
          file: path.join(__dirname, "specs", "public-league.spec.js"),
        },
        parent: { project: () => ({ name: "desktop-1366" }) },
        outcome: () => (index === 500 ? "unexpected" : "expected"),
        results: [{ duration: 1, errors: [], steps: [], attachments: [] }],
      });
    }
    await reporter.onEnd({ status: "failed" });
    const report = JSON.parse(fs.readFileSync(outputFile, "utf8"));
    assert.equal(report.total_tests, 501);
    assert.equal(report.findings.length, 500);
    assert.equal(report.truncated, true);
    assert.equal(report.counts.passed, 500);
    assert.equal(report.counts.failed, 1);
  } finally {
    fs.unlinkSync(outputFile);
    fs.rmdirSync(directory);
  }
});
