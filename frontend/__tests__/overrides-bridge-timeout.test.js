/**
 * The overrides bridge must not report a slow backend as a broken one.
 *
 * WHY THIS EXISTS
 * ---------------
 * `frontend/app/api/rankings/overrides/route.js` aborts the backend
 * fetch on a timer and returns 503. The budget was 15s. Measured
 * 2026-08-06, a cold `view=delta` recompute takes **13.27s** on hardware
 * faster than a GitHub runner — 88% of the budget. Over the line, the
 * bridge synthesized a 503 that was byte-for-byte indistinguishable from
 * the backend's own, and `journey-settings-overrides.spec.js:92`
 * reported it as "expected 200, received 503".
 *
 * That is the rotating E2E flake, and it cost three investigations
 * because every one of them went looking in `server.py`.
 *
 * It is provably not there. `post_rankings_overrides` has exactly two
 * 503 branches:
 *   1. `not latest_data` — but `_prime_latest_payload` swaps the
 *      contract to empty for falsy data, so `has_data` would be false
 *      and CI's readiness gate would never have opened.
 *   2. scoring-profile mismatch — but both leagues in
 *      `config/leagues/registry.json` are `superflex_tep15_ppr1`, so the
 *      comparison can never be unequal.
 * Neither can fire in the environment that produced the failure.
 *
 * These tests pin the two halves of the fix: a budget set against the
 * measurement, and an error body that names which side gave up.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ROUTE = path.resolve(
  __dirname,
  "..",
  "app",
  "api",
  "rankings",
  "overrides",
  "route.js",
);
const source = fs.readFileSync(ROUTE, "utf8");

// The route is a Next server module (next/server import, module-scope
// env reads), so it is asserted structurally rather than imported —
// same posture as bridge-refuses-unstamped-snapshot.test.js.
describe("overrides bridge timeout budget", () => {
  it("is well clear of the measured 13.27s cold recompute", () => {
    const m = source.match(/OVERRIDES_TIMEOUT_MS\s*=\s*(\d+)/);
    expect(m, "the budget must be a named constant, not a literal").toBeTruthy();
    const budget = Number(m[1]);
    // 13.27s measured. Anything under ~27s leaves less than 2x headroom
    // on a runner slower than the machine that produced that number.
    expect(budget).toBeGreaterThanOrEqual(30000);
  });

  it("no longer carries the 15s budget that produced the flake", () => {
    expect(source).not.toMatch(/setTimeout\(\s*\(\)\s*=>\s*ctl\.abort\(\)\s*,\s*15000\s*\)/);
  });
});

describe("the synthesized 503 names its origin", () => {
  it("distinguishes a bridge timeout from an unreachable backend", () => {
    expect(source).toMatch(/bridge_timeout/);
    expect(source).toMatch(/backend_unreachable/);
  });

  it("stamps the origin and the elapsed time", () => {
    // Without these, the next person reading a failing run has the same
    // ambiguity that made this take three attempts.
    expect(source).toMatch(/origin:\s*["']next-bridge["']/);
    expect(source).toMatch(/elapsedMs/);
  });

  it("says explicitly that server.py did not produce it", () => {
    expect(source).toMatch(/not by server\.py/);
  });

  it("detects the abort by both the flag and AbortError", () => {
    // `ctl.abort()` surfaces as an AbortError, but a fetch that fails
    // for another reason after the timer fired would otherwise be
    // mislabelled. Both signals are checked.
    expect(source).toMatch(/aborted\s*\|\|\s*err\?\.name === ["']AbortError["']/);
  });
});
