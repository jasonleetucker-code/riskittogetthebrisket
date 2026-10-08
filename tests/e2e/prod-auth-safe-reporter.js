/**
 * The ONLY reporter the production-auth suite runs (security S3).
 *
 * This repository is PUBLIC, and so are its Actions logs and uploaded
 * artifacts. The prod-auth specs run against PRODUCTION with a real session
 * cookie, so everything a reporter prints or writes is published. The
 * built-in reporters are unsafe here:
 *
 *   - `list` / `line` / `dot` print the full assertion error — `Received:`
 *     values (private board/roster data), call logs and code snippets — into
 *     the public job log;
 *   - `json` records the same plus stdout/stderr and attachment paths;
 *   - `html` embeds traces, screenshots and videos. A failed run's trace.zip
 *     carried the `jason_session` cookie 154 times plus full private
 *     response bodies (run 37690745794, artifact 11517431856).
 *
 * So this reporter emits a deliberately small, SANITIZED record:
 *   per test: project, file, title, status, duration, the spec's own
 *   annotations (authored as evidence — specs must not put private values in
 *   them), and for a failure ONLY the first line of the error message
 *   (the assertion's own description), truncated.
 * Every string is also scrubbed of the session cookie value, if it can be
 * read, as defense in depth.
 *
 * Writes `tests/e2e/prod-auth-results.json` (the evidence artifact the
 * workflow uploads) and prints one line per test plus a summary.
 */
const fs = require("node:fs");
const path = require("node:path");

const OUTPUT_FILE = path.join(__dirname, "prod-auth-results.json");
const MAX_ERROR_CHARS = 300;
const MAX_ANNOTATION_CHARS = 600;

function readSecret() {
  const file = process.env.PROD_SESSION_COOKIE_FILE;
  if (!file) return "";
  try {
    return fs.readFileSync(file, "utf-8").trim();
  } catch {
    return "";
  }
}

function makeScrub(secret) {
  return (value, max) => {
    let text = String(value ?? "");
    if (secret && secret.length >= 8) text = text.split(secret).join("[REDACTED]");
    // Any cookie header or jason_session=… that slipped into a message.
    text = text.replace(/jason_session=[^;\s"']+/gi, "jason_session=[REDACTED]");
    return text.length > max ? `${text.slice(0, max)}…` : text;
  };
}

/** First line of an error message only — the assertion's own description. */
function firstLine(message) {
  const plain = String(message || "")
    // Strip ANSI colour codes Playwright embeds in assertion output.
    .replace(/\u001b\[[0-9;]*m/g, "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .find(Boolean);
  return plain || "";
}

class ProdAuthSafeReporter {
  constructor() {
    this.scrub = makeScrub(readSecret());
    this.results = [];
    this.startedAt = new Date().toISOString();
  }

  printsToStdio() {
    return true;
  }

  onTestEnd(test, result) {
    const project = test.parent?.project()?.name || "";
    const file = path.basename(test.location?.file || "");
    const entry = {
      project,
      file,
      title: this.scrub(test.title, 300),
      status: result.status,
      durationMs: result.duration,
      annotations: [...test.annotations, ...(result.annotations || [])]
        // The two lists overlap (Playwright mirrors test annotations onto the
        // result); keep each (type, description) once.
        .filter(
          (a, i, all) =>
            all.findIndex((b) => b.type === a.type && b.description === a.description) === i,
        )
        .map((a) => ({
          type: this.scrub(a.type, 120),
          description: this.scrub(a.description, MAX_ANNOTATION_CHARS),
        })),
    };
    if (result.status !== "passed" && result.status !== "skipped") {
      const err = result.errors?.[0] || result.error;
      entry.error = this.scrub(firstLine(err?.message), MAX_ERROR_CHARS);
    }
    this.results.push(entry);
    const tag = { passed: "ok", skipped: "skip", failed: "FAIL", timedOut: "TIMEOUT", interrupted: "INTERRUPTED" }[
      result.status
    ];
    process.stdout.write(
      `${tag || result.status} [${project}] ${file} › ${entry.title} (${result.duration}ms)` +
        (entry.error ? `\n    ${entry.error}` : "") +
        "\n",
    );
  }

  onEnd(result) {
    const counts = {};
    for (const r of this.results) counts[r.status] = (counts[r.status] || 0) + 1;
    const report = {
      schema: "prod-auth-safe-report/v1",
      sanitized: true,
      startedAt: this.startedAt,
      finishedAt: new Date().toISOString(),
      status: result.status,
      counts,
      tests: this.results,
    };
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(report, null, 1));
    process.stdout.write(
      `\n${Object.entries(counts)
        .map(([k, v]) => `${v} ${k}`)
        .join(", ")} — run ${result.status}\n`,
    );
  }
}

module.exports = ProdAuthSafeReporter;
