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
 *     carried the `jason_session` cookie 154 times plus full private response
 *     bodies (run 37690745794, artifact 11517431856).
 *
 * Owner directive 2026-10-08: no private data in public artifacts; sanitized
 * evidence only. So this reporter publishes, per test:
 *
 *   - project, spec file, the fixed test title, status, duration — every
 *     test's PASS/FAIL stays visible, so the run remains a gate;
 *   - ONLY the annotations `prod-auth-annotation-allowlist.js` allows for that
 *     spec file, and only when the value is exactly of the declared kind
 *     (status, boolean, count, HTTP status, enum state, fixed code string);
 *   - `withheldCount`: how many annotations were NOT published — "nothing to
 *     say" and "not allowed to say it" must not read the same;
 *   - for a failure, an `errorClass` enum (assertion / timeout / error) — never
 *     the message, because custom assertion messages interpolate team ids,
 *     player names and values.
 *
 * The session cookie value (and any `jason_session=` text) is scrubbed from
 * everything as a backstop; an annotation that contained it is withheld.
 *
 * Writes `tests/e2e/prod-auth-results.json` (the evidence artifact the
 * workflow uploads) and prints one line per test plus a summary.
 */
const fs = require("node:fs");
const path = require("node:path");
const { isPublishable } = require("./prod-auth-annotation-allowlist.js");

const OUTPUT_FILE = path.join(__dirname, "prod-auth-results.json");
const MAX_TITLE_CHARS = 300;

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
  const scrub = (value, max) => {
    let text = String(value ?? "");
    if (secret && secret.length >= 8) text = text.split(secret).join("[REDACTED]");
    // Any cookie header or jason_session=… that slipped into a string.
    text = text.replace(/jason_session=[^;\s"']+/gi, "jason_session=[REDACTED]");
    return text.length > max ? `${text.slice(0, max)}…` : text;
  };
  const containsSecret = (value) => {
    const text = String(value ?? "");
    return (secret && secret.length >= 8 && text.includes(secret)) || /jason_session\s*=/i.test(text);
  };
  return { scrub, containsSecret };
}

/** A fixed class for a failure — never its text. */
function errorClass(result) {
  if (result.status === "timedOut") return "timeout";
  const err = result.errors?.[0] || result.error;
  const message = String(err?.message || "");
  if (/\bexpect\(|\bto(Be|Equal|Have|Contain|Match|BeVisible)/.test(message)) return "assertion";
  if (/timeout|timed out/i.test(message)) return "timeout";
  return "error";
}

class ProdAuthSafeReporter {
  constructor() {
    const { scrub, containsSecret } = makeScrub(readSecret());
    this.scrub = scrub;
    this.containsSecret = containsSecret;
    this.results = [];
    this.startedAt = new Date().toISOString();
  }

  printsToStdio() {
    return true;
  }

  sanitizeAnnotations(file, test, result) {
    const seen = new Set();
    const published = [];
    let withheld = 0;
    for (const a of [...(test.annotations || []), ...((result && result.annotations) || [])]) {
      // The two lists overlap (Playwright mirrors test annotations onto the
      // result); count each (type, description) once.
      const key = JSON.stringify([a && a.type, a && a.description]);
      if (seen.has(key)) continue;
      seen.add(key);
      const type = a && a.type;
      const description = a && a.description;
      if (
        isPublishable(file, type, description) &&
        !this.containsSecret(type) &&
        !this.containsSecret(description)
      ) {
        published.push({ type, description });
      } else {
        withheld += 1;
      }
    }
    return { published, withheld };
  }

  onTestEnd(test, result) {
    const project = test.parent?.project()?.name || "";
    const file = path.basename(test.location?.file || "");
    const { published, withheld } = this.sanitizeAnnotations(file, test, result);
    const entry = {
      project,
      file,
      title: this.scrub(test.title, MAX_TITLE_CHARS),
      status: result.status,
      durationMs: result.duration,
      annotations: published,
      withheldCount: withheld,
    };
    if (result.status !== "passed" && result.status !== "skipped") {
      entry.errorClass = errorClass(result);
    }
    this.results.push(entry);
    const tag = { passed: "ok", skipped: "skip", failed: "FAIL", timedOut: "TIMEOUT", interrupted: "INTERRUPTED" }[
      result.status
    ];
    process.stdout.write(
      `${tag || result.status} [${project}] ${file} › ${entry.title} (${result.duration}ms)` +
        (entry.errorClass ? ` [${entry.errorClass}]` : "") +
        "\n",
    );
  }

  onEnd(result) {
    const counts = {};
    let withheld = 0;
    for (const r of this.results) {
      counts[r.status] = (counts[r.status] || 0) + 1;
      withheld += r.withheldCount;
    }
    const report = {
      schema: "prod-auth-safe-report/v2",
      sanitized: true,
      annotationPolicy: "allowlist (tests/e2e/prod-auth-annotation-allowlist.js); everything else withheld",
      startedAt: this.startedAt,
      finishedAt: new Date().toISOString(),
      status: result.status,
      counts,
      annotationsWithheld: withheld,
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
module.exports.errorClass = errorClass;
