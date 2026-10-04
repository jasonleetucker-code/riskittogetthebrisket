"use strict";

// An opt-in summary of the existing deterministic Playwright assertions.
// Keep raw errors, DOM snapshots, URLs, cookies, and attachment paths in the
// ordinary failure artifacts; this summary can be shared without them.
const fs = require("node:fs");
const path = require("node:path");

const MAX_FINDINGS = 500;
const OUTPUT = path.join(
  __dirname,
  "playwright-report",
  "journey-evidence.json",
);

function targetOrigin(value) {
  try {
    return value ? new URL(value).origin : null;
  } catch {
    return null;
  }
}

function specPath(file) {
  const relative = path.relative(__dirname, file || "").replaceAll("\\", "/");
  return relative.startsWith("specs/") && !relative.includes("../")
    ? relative
    : null;
}

function summarize(test) {
  const results = test.results || [];
  const outcome = test.outcome();
  const failedSteps = (steps) =>
    steps.reduce(
      (count, step) =>
        count + Number(Boolean(step.error)) + failedSteps(step.steps || []),
      0,
    );
  return {
    spec: specPath(test.location?.file),
    project: test.parent?.project()?.name || null,
    title: String(test.title || "").slice(0, 180),
    outcome:
      outcome === "expected"
        ? "passed"
        : outcome === "unexpected"
          ? "failed"
          : outcome,
    attempts: results.length,
    duration_ms: results.reduce(
      (sum, result) => sum + Math.max(0, result.duration || 0),
      0,
    ),
    failed_steps: results.reduce(
      (sum, result) => sum + failedSteps(result.steps || []),
      0,
    ),
    error_count: results.reduce(
      (sum, result) => sum + (result.errors || []).length,
      0,
    ),
    has_trace: results.some((result) =>
      (result.attachments || []).some((item) => item.name === "trace"),
    ),
    has_screenshot: results.some((result) =>
      (result.attachments || []).some(
        (item) => item.contentType === "image/png",
      ),
    ),
  };
}

class StructuredJourneyReporter {
  constructor(options = {}) {
    this.findings = new Map();
    this.outputFile = options.outputFile || OUTPUT;
  }

  onTestEnd(test) {
    // Playwright calls this again for a retry; keep one final finding per test.
    this.findings.set(test.id, summarize(test));
  }

  async onEnd(result) {
    const all = [...this.findings.values()].sort((a, b) =>
      `${a.spec}:${a.project}:${a.title}`.localeCompare(
        `${b.spec}:${b.project}:${b.title}`,
      ),
    );
    const counts = {
      passed: 0,
      failed: 0,
      flaky: 0,
      skipped: 0,
      interrupted: 0,
      unexpected: 0,
    };
    for (const finding of all) {
      if (Object.hasOwn(counts, finding.outcome)) counts[finding.outcome] += 1;
      else counts.unexpected += 1;
    }
    const evidence = {
      schema_version: 1,
      generated_at: new Date().toISOString(),
      source_commit: /^[0-9a-f]{40}$/.test(process.env.GITHUB_SHA || "")
        ? process.env.GITHUB_SHA
        : null,
      target_origin: targetOrigin(process.env.E2E_BASE_URL),
      run_status: result.status,
      counts,
      total_tests: all.length,
      truncated: all.length > MAX_FINDINGS,
      findings: all.slice(0, MAX_FINDINGS),
    };
    fs.mkdirSync(path.dirname(this.outputFile), { recursive: true });
    const temporary = `${this.outputFile}.tmp`;
    fs.writeFileSync(temporary, `${JSON.stringify(evidence, null, 2)}\n`, {
      mode: 0o600,
    });
    fs.renameSync(temporary, this.outputFile);
  }
}

module.exports = StructuredJourneyReporter;
module.exports.summarize = summarize;
module.exports.targetOrigin = targetOrigin;
