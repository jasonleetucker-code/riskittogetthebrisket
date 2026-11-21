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
// The ONE skip-accounting engine (STAB-8).  Reused as-is -- the prod-auth
// suite differs only in its baseline file and its inert/floor rules below.
const skipAccounting = require("./skip-accounting.js");

const PROD_AUTH_BASELINE_PATH = path.join(__dirname, "prod-auth-skip-baseline.json");

/**
 * Minimum number of PASSED tests a credentialed run must produce.
 *
 * Skip accounting says every skip is a reviewed one; it cannot say the suite
 * still RUNS.  A run whose collection quietly shrank (a grep that matches
 * nothing, a config edit, an import that throws at load) would otherwise read
 * "0 failed" green.  Declared, not derived: on 2026-11-20 the suite collected
 * 134 (project, test) pairs of which, after project gating became title tags,
 * 108 are collected and run (63 prod-desktop + 45 prod-mobile).  100 leaves
 * room for a handful of removals; a change that drops more must edit this
 * number on purpose, in review.  `PROD_AUTH_MIN_PASSED` overrides it (e.g. a
 * deliberate single-spec rerun) but never below 1: zero passed is never a run.
 */
const DEFAULT_MIN_PASSED = 100;

function minPassedFloor(env = process.env) {
  const raw = Number.parseInt(String(env.PROD_AUTH_MIN_PASSED ?? ""), 10);
  return Number.isFinite(raw) && raw >= 1 ? raw : DEFAULT_MIN_PASSED;
}

/** Same definition helpers.js::isConfigured uses: BOTH variables set. */
function credentialsConfigured(env = process.env) {
  return Boolean(env.PROD_ORIGIN && env.PROD_SESSION_COOKIE_FILE);
}

/**
 * Pure verdict for a finished run.  Never reads or returns a value, only test
 * identities (spec file, project, fixed title -- already published) and counts.
 *
 *  inert      credentials not configured: every spec skips by design (a local
 *             run).  Reported loudly, never a failure -- and never a pass the
 *             caller may mistake for evidence (`inert: true` in the report).
 *  listOnly   `--list` collects without running; nothing to account.
 *  otherwise  an unexpected skip, a stale baseline entry, or fewer than the
 *             floor passed (always >= 1) FAILS the run.
 */
function evaluateRun({ configured, listOnly, passed, runStatus, collected, baseline, minPassed }) {
  if (listOnly) return { inert: false, listOnly: true, failed: false, problems: [], skipReport: null };
  if (!configured) return { inert: true, listOnly: false, failed: false, problems: [], skipReport: null };
  const problems = [];
  const skipReport = skipAccounting.evaluateSkips(collected, baseline);
  if (skipReport.unexpected.length) problems.push(`${skipReport.unexpected.length} unexpected skip(s)`);
  if (skipReport.stale.length) problems.push(`${skipReport.stale.length} stale skip-baseline entr(ies)`);
  // Only when nothing else already failed the run: real failures are the
  // story, and a red run needs no floor to be red.
  if (runStatus === "passed" || runStatus === undefined) {
    if (passed < 1) problems.push("zero tests passed");
    else if (passed < minPassed) problems.push(`only ${passed} tests passed (floor ${minPassed})`);
  }
  return { inert: false, listOnly: false, failed: problems.length > 0, problems, skipReport };
}

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

// ANSI SGR escapes (colour / dim).  Playwright colours its VALUE-matcher
// hints — "\u001b[2mexpect(\u001b[22m…).\u001b[22mtoBe" — so the `\b` anchors
// below never matched them and every failed toBe / toEqual / toContain was
// published as "error", indistinguishable from a thrown TypeError (V1 run
// 39221318435: pick-lifecycle-horizon, the train2 Droppable test and W1-28).
const ANSI_ESCAPE = /\u001b\[[0-9;]*m/g;

/** A fixed class for a failure — never its text. */
function errorClass(result) {
  if (result.status === "timedOut") return "timeout";
  const err = result.errors?.[0] || result.error;
  // Classified only: the stripped text is read here and never published.
  const message = String(err?.message || "").replace(ANSI_ESCAPE, "");
  if (/\bexpect\(|\bto(Be|Equal|Have|Contain|Match|BeVisible)/.test(message)) return "assertion";
  if (/timeout|timed out/i.test(message)) return "timeout";
  return "error";
}

/**
 * The closed vocabulary of `failureSignal` values.  `errorClass` alone cannot
 * tell "the UI never showed up" from "the value was wrong": both are
 * "assertion".  Duration cannot either -- a web-first assertion (toHaveText,
 * toBeVisible, ...) RETRIES a wrong value to the same deadline and prints the
 * same `Timeout: Nms`.  What separates them is the Received line:
 * `<element(s) not found>` (or no Received line at all) means the target never
 * appeared -> `expect_timeout`; a Received VALUE means the page answered
 * wrongly -> no timeout signal.  The signal is read from the same stripped
 * message `errorClass` reads and is one of THESE strings, so the cause family is
 * published without a character of its text.  Mirrored by
 * scripts/v1_failure_classifier.py::FAILURE_SIGNALS (parity test:
 * tests/ops/test_v1_failure_classifier.py).
 */
const SIGNAL_NAMES = [
  "out_of_memory",
  "browser_launch_failed",
  "browser_closed",
  "network_error",
  "navigation_timeout",
  "api_request_timeout",
  "http_401_403",
  "http_5xx",
  "expect_timeout",
  "strict_mode_violation",
  "none",
];

// Order matters: the first match wins, most specific infrastructure first.
const SIGNAL_PATTERNS = [
  ["out_of_memory", /out of memory|\bENOMEM\b|JavaScript heap|ERR_INSUFFICIENT_RESOURCES|Aw, Snap/i],
  ["browser_launch_failed", /browserType\.launch|Executable doesn't exist|Failed to launch|Looks like Playwright/i],
  ["browser_closed", /Target (?:page, context or browser has been )?closed|Target crashed|Page crashed|browser has been closed/i],
  ["network_error", /net::ERR_|\bECONNRESET\b|\bECONNREFUSED\b|\bENOTFOUND\b|\bETIMEDOUT\b|\bEAI_AGAIN\b|socket hang up/i],
  ["navigation_timeout", /page\.goto: Timeout|waiting until "(?:domcontentloaded|load|networkidle|commit)"/i],
  ["api_request_timeout", /apiRequestContext\.\w+: Timeout|request\.(?:get|post|put|fetch): Timeout/i],
  // HTTP families ONLY in a status context -- never "any received number":
  // `expect(count).toBe(600)` / Received 512 is a count, not a 5xx.  Accepted:
  // HTTP/status wording next to the code, a status reason phrase, or a Received
  // code against an Expected 2xx / "< 400".  A guest-refusal spec that reads
  // "Expected: 403 / Received: 200" matches none of these.
  [
    "http_401_403",
    new RegExp(
      [
        String.raw`\b(?:HTTP|status(?:Code)?)\b[^\n\d]{0,16}\b(?:401|403)\b`,
        String.raw`\b(?:401 Unauthorized|403 Forbidden)\b`,
        String.raw`Expected:\s*(?:2\d\d|<\s*400)\s*\n\s*Received:\s*\[?\s*(?:401|403)\b`,
      ].join("|"),
      "i",
    ),
  ],
  [
    "http_5xx",
    new RegExp(
      [
        String.raw`\b(?:HTTP|status(?:Code)?)\b[^\n\d]{0,16}\b5\d\d\b`,
        String.raw`\b50[0-4] (?:Bad Gateway|Service Unavailable|Gateway Time-?out|Internal Server Error)\b`,
        String.raw`Expected:\s*(?:2\d\d|<\s*400)\s*\n\s*Received:\s*\[?\s*5\d\d\b`,
      ].join("|"),
      "i",
    ),
  ],
  // A web-first assertion that ran to its deadline WITHOUT finding its target.
  ["expect_timeout", expectTargetNeverAppeared],
  ["strict_mode_violation", /strict mode violation/i],
];

function expectTargetNeverAppeared(message) {
  const ranToDeadline =
    (/\bexpect\(/.test(message) && /Timeout:\s*\d+ms/.test(message)) ||
    /Timeout \d+ms exceeded while waiting for expect/i.test(message);
  if (!ranToDeadline) return false;
  if (/element\(s\) not found/i.test(message)) return true;
  // A Received VALUE means the target existed and answered wrongly.
  return !/^\s*Received(?: string| value| array| object)?:/im.test(message);
}

/** A closed-vocabulary signal for a failure — never its text. */
function failureSignal(result) {
  const err = result.errors?.[0] || result.error;
  const message = String(err?.message || "").replace(ANSI_ESCAPE, "");
  for (const [name, pattern] of SIGNAL_PATTERNS) {
    const hit = typeof pattern === "function" ? pattern(message) : pattern.test(message);
    if (hit) return name;
  }
  return "none";
}

class ProdAuthSafeReporter {
  constructor() {
    const { scrub, containsSecret } = makeScrub(readSecret());
    this.scrub = scrub;
    this.containsSecret = containsSecret;
    this.results = [];
    this.rootSuite = null;
    this.startedAt = new Date().toISOString();
  }

  onBegin(_config, suite) {
    this.rootSuite = suite || null;
  }

  printsToStdio() {
    return true;
  }

  isoOrNull(value) {
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
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
      // When the test began (UTC ISO).  Lets a restart observed by the
      // workflow be attributed ONLY to tests it actually overlapped, instead
      // of to every failure in a run that happened to contain one.
      startedAt: this.isoOrNull(result.startTime),
      annotations: published,
      withheldCount: withheld,
    };
    if (result.status !== "passed" && result.status !== "skipped") {
      entry.errorClass = errorClass(result);
      entry.failureSignal = failureSignal(result);
    }
    this.results.push(entry);
    const tag = { passed: "ok", skipped: "skip", failed: "FAIL", timedOut: "TIMEOUT", interrupted: "INTERRUPTED" }[
      result.status
    ];
    process.stdout.write(
      `${tag || result.status} [${project}] ${file} › ${entry.title} (${result.duration}ms)` +
        (entry.errorClass ? ` [${entry.errorClass}]` : "") +
        (entry.failureSignal && entry.failureSignal !== "none" ? ` signal=${entry.failureSignal}` : "") +
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
    const passedCount = counts.passed || 0;
    const verdict = this.verdict(result, passedCount);
    const report = {
      schema: "prod-auth-safe-report/v2",
      sanitized: true,
      annotationPolicy: "allowlist (tests/e2e/prod-auth-annotation-allowlist.js); everything else withheld",
      startedAt: this.startedAt,
      finishedAt: new Date().toISOString(),
      status: result.status,
      counts,
      // Counts and booleans only.  `inert` = credentials were not configured,
      // so this run proved nothing about production.
      integrity: {
        inert: verdict.inert,
        failed: verdict.failed,
        minPassed: minPassedFloor(),
        unexpectedSkips: verdict.skipReport ? verdict.skipReport.unexpected.length : 0,
        staleBaselineEntries: verdict.skipReport ? verdict.skipReport.stale.length : 0,
      },
      annotationsWithheld: withheld,
      tests: this.results,
    };
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(report, null, 1));
    process.stdout.write(
      `\n${Object.entries(counts)
        .map(([k, v]) => `${v} ${k}`)
        .join(", ")} — run ${result.status}\n`,
    );
    return this.announce(verdict, result);
  }

  /** Collected-test records for the skip accounting.  Titles only. */
  collectedRecords() {
    if (!this.rootSuite || typeof this.rootSuite.allTests !== "function") return null;
    return this.rootSuite.allTests().map(skipAccounting.describeTest);
  }

  verdict(result, passed) {
    const listOnly = process.argv.includes("--list");
    const configured = credentialsConfigured();
    let collected = [];
    let baseline = { entries: [] };
    if (configured && !listOnly) {
      try {
        collected = this.collectedRecords();
        if (!collected) throw new Error("the run's collected suite is not available to the reporter");
        baseline = skipAccounting.loadBaseline(PROD_AUTH_BASELINE_PATH);
      } catch (err) {
        // An unreadable baseline or suite must never read as "no skips".
        return {
          inert: false,
          listOnly: false,
          failed: true,
          problems: [`skip accounting could not run: ${this.scrub(err && err.message, 300)}`],
          skipReport: null,
        };
      }
    }
    return evaluateRun({
      configured,
      listOnly,
      passed,
      runStatus: result.status,
      collected,
      baseline,
      minPassed: minPassedFloor(),
    });
  }

  announce(verdict, result) {
    const line = "═".repeat(72);
    if (verdict.inert) {
      process.stdout.write(
        `\n${line}\nPROD-AUTH SUITE INERT: PROD_ORIGIN / PROD_SESSION_COOKIE_FILE not both set.\n` +
          `Specs skip by design without credentials; this run proves NOTHING about production.\n${line}\n`,
      );
      return undefined;
    }
    if (verdict.listOnly) return undefined;
    if (verdict.skipReport) {
      const text = skipAccounting.formatReport(verdict.skipReport, {
        baselinePath: "tests/e2e/prod-auth-skip-baseline.json",
      });
      if (text) process.stdout.write(`\n${line}\nPROD-AUTH SKIP ACCOUNTING\n${line}\n${text}\n${line}\n`);
    }
    if (!verdict.failed) return undefined;
    process.stdout.write(
      `\n${line}\nPROD-AUTH RUN INVALID -- THIS GREEN IS NOT TRUSTWORTHY: ${verdict.problems.join("; ")}\n${line}\n`,
    );
    // Playwright's supported way for a reporter to change the run outcome.
    return result.status === "passed" ? { status: "failed" } : undefined;
  }
}

module.exports = ProdAuthSafeReporter;
module.exports.errorClass = errorClass;
module.exports.evaluateRun = evaluateRun;
module.exports.minPassedFloor = minPassedFloor;
module.exports.credentialsConfigured = credentialsConfigured;
module.exports.DEFAULT_MIN_PASSED = DEFAULT_MIN_PASSED;
module.exports.PROD_AUTH_BASELINE_PATH = PROD_AUTH_BASELINE_PATH;
module.exports.failureSignal = failureSignal;
module.exports.SIGNAL_NAMES = SIGNAL_NAMES;
