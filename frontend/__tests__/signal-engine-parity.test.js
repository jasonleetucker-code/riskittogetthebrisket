/**
 * Frontend half of the Buy/Sell/Hold engine parity test (debt item D3).
 *
 * Twin of `tests/api/test_signal_engine_parity.py`. Both halves assert
 * against ONE fixture, `tests/fixtures/signal_parity_cases.json` — see
 * that Python file's module docstring for the full rationale. The
 * short version:
 *
 *   - `frontend/lib/signal-engine.js::evaluate` is what the user SEES
 *     (BuySellHold.jsx / TopSignalsRail.jsx render its verdicts).
 *   - `src/api/terminal.py::_evaluate_signal` is what gets EMAILED
 *     (server.py feeds the terminal `signals` block into
 *     src/api/signal_alerts.py).
 *
 * Nothing checked that the two agreed until this pair of files. A
 * divergence means "you were emailed a SELL the Signals panel does not
 * show", so it is a correctness bug, not a cosmetic one.
 *
 * NEITHER half may hardcode expectations of its own. The fixture is the
 * single source of truth; if the engines disagree, exactly one suite
 * goes red against a shared, human-authored statement of intent.
 *
 * ASSERTED: `signal`, `tag`, and the ORDERED list of firing rule tags.
 * NOT ASSERTED: reason prose (the two engines word four rules
 * differently and round MAD differently — Python `f"{mad:.1f}"` is
 * round-half-even, JS `.toFixed(1)` rounds half away from zero), the
 * `fired[]` entry shape (JS carries `id`, Python carries `priority`),
 * and the context BUILDERS (`buildContext` eats a buildRows row,
 * `_build_signal_context` eats a contract row — they cannot share a
 * fixture and are known to diverge). This pins the RULE TABLE.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { evaluate, SIGNALS, SIGNAL_META } from "@/lib/signal-engine";

const REPO_ROOT = path.resolve(__dirname, "../..");
const FIXTURE_PATH = path.join(
  REPO_ROOT,
  "tests",
  "fixtures",
  "signal_parity_cases.json",
);
const ENGINE_PATH = path.join(REPO_ROOT, "frontend", "lib", "signal-engine.js");

const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));

/**
 * Scrape (priority, signal, tag) out of the RULES array in the engine
 * source. Static, not introspective — RULES is module-private by
 * design. This exists so that adding an 11th rule to one engine and
 * not the other fails a test instead of silently drifting.
 */
function declaredRulesFromEngineSource() {
  const src = fs.readFileSync(ENGINE_PATH, "utf8");
  const start = src.indexOf("const RULES = [");
  const end = src.indexOf("\n];", start);
  if (start < 0 || end < 0) throw new Error("could not locate RULES array");
  const body = src.slice(start, end);

  const out = [];
  const idRe = /id:\s*"([^"]+)"/g;
  const starts = [];
  let m;
  while ((m = idRe.exec(body)) !== null) starts.push(m.index);
  for (let i = 0; i < starts.length; i++) {
    const chunk = body.slice(starts[i], starts[i + 1] ?? body.length);
    const signal = /signal:\s*SIGNALS\.([A-Z_]+)/.exec(chunk);
    const priority = /priority:\s*(\d+)/.exec(chunk);
    const tag = /tag:\s*"([a-z0-9_]+)"/.exec(chunk);
    if (!signal || !priority || !tag) continue;
    out.push({
      priority: Number(priority[1]),
      signal: signal[1],
      tag: tag[1],
    });
  }
  return out;
}

const key = (r) => `${r.priority}|${r.signal}|${r.tag}`;

describe("signal-engine parity fixture integrity", () => {
  it("loads a non-trivial shared fixture", () => {
    expect(Array.isArray(FIXTURE.cases)).toBe(true);
    expect(FIXTURE.cases.length).toBeGreaterThanOrEqual(40);
    // 10 until 2026-07-30, when `low_conf_unstable` was retired — see
    // the retirement note in frontend/lib/signal-engine.js.
    expect(FIXTURE.rules).toHaveLength(9);
  });

  it("has unique case ids", () => {
    const ids = FIXTURE.cases.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("declares only signals this engine knows", () => {
    for (const rule of FIXTURE.rules) {
      expect(SIGNALS[rule.signal]).toBe(rule.signal);
      expect(SIGNAL_META[rule.signal]).toBeTruthy();
    }
    expect(SIGNALS[FIXTURE.defaultVerdict.signal]).toBe(
      FIXTURE.defaultVerdict.signal,
    );
  });
});

describe("signal-engine rule table matches the shared fixture", () => {
  it("frontend RULES == fixture rule declaration", () => {
    const declared = FIXTURE.rules.map(key).sort();
    const actual = declaredRulesFromEngineSource().map(key).sort();
    expect(
      actual,
      "frontend/lib/signal-engine.js RULES no longer matches the rule " +
        "table in tests/fixtures/signal_parity_cases.json. If you added " +
        "or changed a rule, mirror it in src/api/terminal.py::" +
        "_evaluate_signal AND add fixture cases for it (threshold, " +
        "either side of the threshold, and every input null) — " +
        "otherwise the two engines are free to drift.",
    ).toEqual(declared);
  });
});

describe("signal-engine parity — every shared fixture case", () => {
  for (const c of FIXTURE.cases) {
    it(`${c.id}: ${c.why}`, () => {
      const verdict = evaluate(c.ctx);
      expect(verdict.signal).toBe(c.expected.signal);
      expect(verdict.tag).toBe(c.expected.tag);
      expect(verdict.fired.map((f) => f.tag)).toEqual(c.expected.firedTags);
    });
  }

  it("every verdict carries non-empty reason prose", () => {
    // Prose is not compared across engines, but it must exist — a
    // reason() that throws would be swallowed by `evaluate`'s
    // per-rule try/catch only in `test`, not in `reason`.
    for (const c of FIXTURE.cases) {
      const verdict = evaluate(c.ctx);
      expect(String(verdict.reason || "").trim(), c.id).not.toBe("");
      for (const entry of verdict.fired) {
        expect(String(entry.reason || "").trim(), `${c.id}/${entry.tag}`).not.toBe(
          "",
        );
      }
    }
  });
});

describe("signal-engine null-trend regression", () => {
  /**
   * The one real divergence this parity pair found.
   *
   * `sell.sustained_downtrend` and `strong.elite_stable` both gate on
   * trend30. This engine used `(c.trend30 ?? 0)`, which makes "no 30d
   * coverage" satisfy both `<= 0` and `>= 0` — so a player with NO
   * rank history came back SELL from one rule and STRONG_HOLD from the
   * other, while the Python engine returned HOLD for both.
   *
   * Python's `is not None` reading is the correct one: null means
   * unmeasured, not flat, and SELL is in signal_alerts.ACTIONABLE_
   * SIGNALS so it reaches users by email. The JS rules were changed to
   * match rather than the reverse.
   *
   * Blast radius of that change is provably zero in production:
   * `computeWindowTrend` returns null only when `points` is empty, so
   * through `buildContext` trend30 === null implies trend7 === null
   * (which already failed sustained_downtrend's first clause) and
   * volatility === null (which already failed elite_stable's
   * volatility clause). The fix is reachable only at the exported
   * `evaluate()` boundary — which is exactly what this test drives.
   */
  for (const id of ["r3_trend30_null_no_history", "r8_trend30_null_no_history"]) {
    it(`${id}: null trend30 is not read as flat`, () => {
      const c = FIXTURE.cases.find((x) => x.id === id);
      expect(c, `fixture case ${id} missing`).toBeTruthy();
      expect(c.ctx.trend30).toBeNull();
      expect(c.expected.signal).toBe("HOLD");
      const verdict = evaluate(c.ctx);
      expect(verdict.signal).toBe(SIGNALS.HOLD);
      expect(verdict.fired).toEqual([]);
    });
  }
});
