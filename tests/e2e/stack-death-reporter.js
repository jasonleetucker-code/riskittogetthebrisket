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

class StackDeathReporter {
  constructor() {
    this.enabled = !process.env.E2E_NO_STACK_GUARD;
    this.tripped = false;
    this.completed = 0;
  }

  onTestEnd(test, result) {
    this.completed += 1;
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
}

module.exports = StackDeathReporter;
