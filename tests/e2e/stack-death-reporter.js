/**
 * Stop the run — loudly — when the stack dies mid-flight.
 *
 * Why this exists
 * ---------------
 * The Next.js frontend has been observed getting SIGKILLed partway
 * through a full run: bare `[WebServer] Killed`, no Node stack trace,
 * no heap-OOM message.  Characterised while building this suite as
 * intermittent (1 of 4 managed runs), NOT the suite's own concurrency
 * (identical worker count in the clean and killed runs), and NOT
 * memory (RSS ~180 MB against 8.7 GB free, nothing in dmesg).  The
 * root cause is still unexplained and correlates with process
 * ownership rather than load.
 *
 * The root cause is not what makes this dangerous, though.  Once the
 * frontend is gone, EVERY remaining page test fails with
 * ERR_CONNECTION_REFUSED — roughly fifteen of them in the run that
 * prompted this — and that reads exactly like a catastrophic product
 * regression.  One such run reported "40 failed" when the real answer
 * was "the stack died at test 99 of 178".  A suite that invents
 * fifteen fake failures is worse than one that stops and says the
 * stack died, because the fake failures cost a human an investigation.
 *
 * So: when a test fails with a connection-level error, confirm whether
 * the stack is actually reachable, and if it isn't, abort immediately
 * with a diagnosis instead of letting the rest of the run manufacture
 * evidence.
 *
 * Deliberate design notes
 * -----------------------
 * - Only connection-level failures trigger a probe.  A normal
 *   assertion failure never does, so this cannot mask real failures.
 * - The probe is the arbiter, not the error text.  If the stack
 *   answers, this stays silent and the failure stands on its own —
 *   a genuine ERR_CONNECTION_REFUSED against some *other* origin is
 *   still reported as a test failure.
 * - Exiting loses the HTML report index.  That is an accepted trade:
 *   per-test artifacts (screenshots, traces, videos) are already
 *   written to test-results/ as each test finishes, and stopping in
 *   seconds beats twelve more minutes of noise.  Set
 *   E2E_NO_STACK_GUARD=1 to disable if you ever need the full run.
 *
 * ⚠ DO NOT PASS `--reporter` ON THE COMMAND LINE.
 * The CLI flag REPLACES the whole `reporter` array from
 * playwright.config.js, so `--reporter=line` silently unloads this
 * file and every guard in it.  Nothing warns you: the run looks
 * normal and the guards simply never execute.
 *
 * This is not hypothetical — it is how the guard was first "verified".
 * Local runs used `--reporter=line`, the module was never loaded, and
 * "the guard stayed silent on a healthy run" was indistinguishable
 * from "the guard never ran at all".  Proven by a module-level probe
 * that printed nothing with the flag and printed immediately without
 * it.  The suite's own entry points (`npm run e2e`, e2e.yml) do not
 * pass it, so CI is guarded; keep it that way.
 */

// Connection-level signatures — the stack is unreachable, as distinct
// from the app misbehaving.
const CONNECTION_ERROR = /ERR_CONNECTION_REFUSED|ERR_EMPTY_RESPONSE|ECONNREFUSED|ECONNRESET|socket hang up/i;

function originsToProbe() {
  const api = (process.env.E2E_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const page = (
    process.env.E2E_PAGE_ORIGIN ||
    (process.env.E2E_BASE_URL ? "" : "http://127.0.0.1:3000")
  ).replace(/\/+$/, "");
  const out = [{ name: "backend", url: `${api}/api/status` }];
  if (page) out.push({ name: "frontend", url: `${page}/login` });
  return out;
}

// Confirmation attempts before declaring an origin dead.  One failed
// probe is NOT proof: a momentary blip under load — exactly what
// happens while a browser suite is hammering the box — would otherwise
// abort a perfectly good run.  This is the same mistake the auth hook
// used to make by treating a single timeout as an authoritative
// answer, and it bit this reporter in testing: a transient failure
// against a demonstrably-alive backend printed the abort banner.
//
// Dying is permanent, so requiring the failure to persist costs a
// couple of seconds in the real case and eliminates the false one.
const CONFIRM_ATTEMPTS = 3;
const CONFIRM_GAP_MS = 750;

async function isAlive(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(10_000) });
    // Any HTTP answer means the process is alive and serving; a 5xx is
    // the app's problem, not a dead stack.
    return res.status > 0;
  } catch {
    return false;
  }
}

async function findDeadOrigin() {
  for (const origin of originsToProbe()) {
    let dead = true;
    for (let i = 0; i < CONFIRM_ATTEMPTS; i += 1) {
      if (await isAlive(origin.url)) {
        dead = false;
        break;
      }
      if (i < CONFIRM_ATTEMPTS - 1) {
        await new Promise((r) => setTimeout(r, CONFIRM_GAP_MS));
      }
    }
    if (dead) return origin;
  }
  return null;
}

// ── Coverage floor ─────────────────────────────────────────────────────
// A suite that skips everything reports green.  That is the same
// never-fires class as a workflow that cannot start: absence of
// failure read as evidence of success.
//
// Measured baseline, chromium desktop + mobile, read from the summary
// line of run 30945387957 (aa6f415f2, 2026-08-04, dispatched on main):
//
//     49 skipped
//     139 passed (1.9m)
//
// The comment this replaces claimed "~149 passed / 29 skipped" and said
// the ceiling existed because "well above ~29 means a whole layer
// stopped running".  Skips had drifted 29 -> 49 against a ceiling of 60
// and nothing fired, so the guard's STATED tolerance and its REAL
// tolerance had come apart — the ORCHESTRATION.md 6.15 shape, inside
// the file written to prevent it.  Re-derive both numbers from a named
// green run before changing them, and cite the run.
//
// The floor still sits under the baseline so ordinary drift doesn't
// trip it, but a run where a whole layer silently stopped executing —
// an env var lost, a fixture skipping, a project filter typo — lands
// far below it.
//
// Deliberately a FAILURE, not a warning: a warning in a green run is
// something nobody reads.
//
// Parsed, not coerced, and that matters as of the same change that
// wrote this: `Number("3O")` is NaN, and BOTH `passed < NaN` and
// `skipped > NaN` are false — one typo in a workflow's `env:` block
// would disable this entire guard while the banner it prints claims the
// opposite.  That hole was unreachable while nothing set these vars;
// prod-e2e-smoke.yml now sets them by hand in YAML, so it is reachable.
// Empty string is treated as unset rather than 0, because
// `E2E_MAX_SKIPPED: ""` reads as "I set the ceiling to zero" and would
// otherwise silently land on the default of 60.
function coverageBound(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw.trim() === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n)) {
    throw new Error(
      `${name}="${raw}" is not a number.  Refusing to run: an unparseable ` +
        `coverage bound disables the floor silently and the run reports green.`,
    );
  }
  return n;
}

// 120, raised from 100 against the measured 139.  At 100 a run could
// lose 39 of the suite's tests and still clear the floor — more than a
// quarter of it — which is a lot of silence for a guard whose banner
// says "this green is not trustworthy".  120 keeps 19 tests of headroom
// for ordinary drift.  The skip ceiling stays at 60 against a measured
// 49: project gating moves in steps of 2-4 whenever a describe block
// gains desktopOnly/mobileOnly, and a bound that needs adjusting every
// quarter stops being believed.
const MIN_EXPECTED_PASSED = coverageBound("E2E_MIN_PASSED", 120);
const MAX_EXPECTED_SKIPPED = coverageBound("E2E_MAX_SKIPPED", 60);

class StackDeathReporter {
  constructor() {
    this.enabled = !process.env.E2E_NO_STACK_GUARD;
    this.tripped = false;
    this.completed = 0;
    this.counts = { passed: 0, skipped: 0, failed: 0 };
    this.rootSuite = null;
  }

  /**
   * Held only so onEnd can ask Playwright which tests ended up flaky,
   * using Playwright's own predicate (`TestCase.outcome()`) rather than
   * a hand-rolled retry count.  `result.retry > 0 && status === "passed"`
   * is close but not the same: outcome() also weighs `expectedStatus`,
   * and a test whose first attempt fails and whose retry hits a dynamic
   * `test.skip()` scores "unexpected", not "flaky".  One predicate, and
   * it is the same word the HTML report's badge uses.
   */
  onBegin(_config, suite) {
    this.rootSuite = suite || null;
  }

  onTestEnd(test, result) {
    this.completed += 1;
    if (result.status === "passed") this.counts.passed += 1;
    else if (result.status === "skipped") this.counts.skipped += 1;
    else this.counts.failed += 1;
    if (!this.enabled || this.tripped) return;
    if (result.status !== "failed" && result.status !== "timedOut") return;

    const text = [
      result.error && result.error.message,
      ...(result.errors || []).map((e) => e && e.message),
    ]
      .filter(Boolean)
      .join("\n");
    if (!CONNECTION_ERROR.test(text)) return;

    // Confirm before accusing.  Reporters can't await, so this runs
    // detached; the run is exited from inside once a probe comes back
    // negative.
    findDeadOrigin()
      .then((dead) => {
        if (!dead || this.tripped) return;
        this.tripped = true;
        const line = "═".repeat(72);
        process.stderr.write(
          `\n${line}\n` +
            `E2E RUN ABORTED — THE STACK DIED MID-RUN\n` +
            `${line}\n` +
            `The ${dead.name} stopped answering at ${dead.url} after ` +
            `${this.completed} test(s).\n` +
            `Failed here: ${test.titlePath().slice(1).join(" › ")}\n\n` +
            `Every remaining page test would fail with a connection error, ` +
            `which\nlooks like a mass product regression and is not one.  ` +
            `Results from this\nrun are INVALID past this point — do not ` +
            `read the failure count.\n\n` +
            `The frontend has been seen getting SIGKILLed mid-run ` +
            `(intermittent,\nnot load-correlated, root cause open).  Re-run ` +
            `the suite; if it recurs\nimmediately, check whether something ` +
            `is reaping long-lived processes.\n` +
            `Per-test artifacts up to this point are in ` +
            `tests/e2e/test-results/.\n` +
            `Set E2E_NO_STACK_GUARD=1 to run through a dead stack anyway.\n` +
            `${line}\n\n`,
        );
        process.exit(1);
      })
      .catch(() => {
        /* probe itself failed — stay silent rather than guess */
      });
  }

  /**
   * Name the flaky tests.  DIAGNOSTIC ONLY — read this before moving it.
   *
   * The run is already red by the time this executes.  `failOnFlakyTests`
   * in playwright.config.js is what fails it: failureTracker.result()
   * consults it and is computed BEFORE onEnd is called.  This block
   * deliberately returns no status, and must not start.
   *
   * DO NOT move the flaky predicate into this file.  A `--reporter=…` on
   * the command line REPLACES the config's reporter array and unloads
   * this module whole — see the header above; that is how the
   * stack-death guard was once "verified" while never running, and it is
   * how every prod-e2e-smoke run before 2026-08-05 executed with no
   * guards at all.  A config key survives that flag; this printout does
   * not.  Two mechanisms on purpose: one that cannot be unloaded, and
   * one that explains.
   *
   * What this adds over Playwright's own "N flaky" line is WHY the run
   * is red and what to check first.
   */
  _reportFlaky() {
    if (process.env.E2E_ALLOW_FLAKY) return;
    if (!this.rootSuite || typeof this.rootSuite.allTests !== "function") return;
    const flaky = this.rootSuite
      .allTests()
      .filter((t) => typeof t.outcome === "function" && t.outcome() === "flaky");
    if (flaky.length === 0) return;

    const line = "═".repeat(72);
    const names = flaky
      .map((t) => `  • ${t.titlePath().slice(1).filter(Boolean).join(" › ")}`)
      .join("\n");
    process.stderr.write(
      `\n${line}\n` +
        `E2E FLAKY — THIS GREEN WAS EARNED ON A RETRY\n` +
        `${line}\n` +
        `${flaky.length} test(s) failed once and passed on retry:\n\n` +
        `${names}\n\n` +
        `Playwright's own status for that is "passed", exit 0.  Without\n` +
        `failOnFlakyTests in playwright.config.js, e2e.yml's close step\n` +
        `would retire the open e2e-failures issue on this run — and it\n` +
        `iterates .[], so it drains every open one.\n\n` +
        `TWO COMMON CAUSES, and they want opposite responses.\n\n` +
        `1. A READINESS race — the spec sampled the page before it was\n` +
        `   done.  Routes with a loading.jsx are streamed, so around the\n` +
        `   swap a selector can match twice; and a control can exist\n` +
        `   while still measuring as not-visible, so a one-shot\n` +
        `   isVisible() picks the wrong branch (measured 4/15 on a phone\n` +
        `   viewport — that was #732).  Neither is a product defect.\n` +
        `   Fix the WAIT: awaitStreamSettled() in helpers/journey.js for\n` +
        `   the streaming case, locator.or() for "which control is\n` +
        `   live".  Never the assertion.\n\n` +
        `2. A PERSISTENT duplicate — the page's markup really does\n` +
        `   exist twice, and still does after streaming completes.  THAT\n` +
        `   is a product defect (#709 shipped one: every route rendered\n` +
        `   twice, invisible in a screenshot, in the a11y tree, and to a\n` +
        `   human clicking around).  Fix the app.\n\n` +
        `Tell them apart by whether it survives awaitStreamSettled().\n` +
        `NOTE the earlier story here — "React leaves its <div id=\\"S:1\\">\n` +
        `staging copy behind" — was WRONG on both the mechanism and the\n` +
        `rate (see #747); it sent one investigation down a dead end.\n\n` +
        `DO NOT "fix" either by adding .first() to the locator.  The two\n` +
        `sites that can see case 2 — journey-trade.spec.js (/arbitrage)\n` +
        `and waivers-smoke.spec.js (/waivers) — are the ONLY detectors\n` +
        `this repo has for duplicated markup, and .first() restores the\n` +
        `silence while looking like a fix.\n\n` +
        `Traces for the failed attempt are in tests/e2e/test-results/\n` +
        `(trace: "on-first-retry").  Read those before re-running.\n` +
        `E2E_ALLOW_FLAKY=1 accepts a retried green locally; a workflow\n` +
        `that sets it fails tests/e2e/test_e2e_harness_guards.py.\n` +
        `${line}\n\n`,
    );
  }

  /**
   * Enforce the coverage floor.  Returning a status from onEnd is
   * Playwright's supported way for a reporter to change the run's
   * outcome, so a suite that executed almost nothing exits non-zero
   * instead of reporting a green it did not earn.
   *
   * Skipped when the guard is disabled, when the run already failed
   * (the real failures are the story), or when the stack-death guard
   * tripped (that run was already declared invalid).
   */
  onEnd(result) {
    if (this.tripped) return undefined;
    // Diagnostic first, and OUTSIDE the `enabled` gate.  It has to print
    // on a run that failOnFlakyTests has already turned red — and the
    // coverage-floor branch below returns early on exactly those runs.
    // E2E_NO_STACK_GUARD does not silence it either: that switch is
    // documented as "run through a dead stack anyway", and this block
    // changes no status, so silencing it would open a fresh gap between
    // a switch's stated purpose and its actual reach.
    this._reportFlaky();
    if (!this.enabled) return undefined;
    if (result && result.status === "failed") return undefined;

    const { passed, skipped } = this.counts;
    const tooFewRan = passed < MIN_EXPECTED_PASSED;
    const tooManySkipped = skipped > MAX_EXPECTED_SKIPPED;
    if (!tooFewRan && !tooManySkipped) return undefined;

    const line = "═".repeat(72);
    process.stderr.write(
      `\n${line}\n` +
        `E2E COVERAGE FLOOR NOT MET — THIS GREEN IS NOT TRUSTWORTHY\n` +
        `${line}\n` +
        `passed=${passed} (floor ${MIN_EXPECTED_PASSED})  ` +
        `skipped=${skipped} (ceiling ${MAX_EXPECTED_SKIPPED})\n\n` +
        (tooFewRan
          ? `Too few tests actually executed.  A suite that skips its way\n` +
            `to zero failures reports the same green as one that passed.\n`
          : "") +
        (tooManySkipped
          ? `Too many tests skipped.  Expected ~29 from deliberate project\n` +
            `gating; well above that means a whole layer stopped running.\n`
          : "") +
        `\nUsual causes: E2E_TEST_SECRET missing or not matching the\n` +
        `server (every signed-in spec skips), a project filter that\n` +
        `matches nothing, or a fixture skipping on absent data.\n` +
        `Adjust the floor via E2E_MIN_PASSED / E2E_MAX_SKIPPED only when\n` +
        `the suite's real size has changed.\n${line}\n\n`,
    );
    return { status: "failed" };
  }
}

module.exports = StackDeathReporter;
