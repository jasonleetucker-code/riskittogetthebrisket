/**
 * The /rankings methodology panel must not carry its own copy of the
 * board's constants.
 *
 * WHY THIS EXISTS
 * ===============
 * `board-sections.jsx` hardcoded
 *
 *     value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))
 *
 * which was wrong twice over. The constants 45 / 1.10 were the retired
 * rank-form pair (the backend's are 65.4 / 0.910), AND the live
 * pipeline does not use rank form at all — it uses the percentile-form
 * Hill with per-scope masters. Measured against the real board on the
 * pinned 2026-07-30 payload, the displayed formula was off by a MEDIAN
 * of 805 points across 740 ranked rows (p90 1060, max 1185).
 *
 * This is the SECOND instance of the same mirror. The first was
 * `frontend/lib/value-history.js`, fixed 2026-07-30 and now guarded by
 * `tests/api/test_rank_form_frontend_parity.py`. That fix corrected the
 * mirror it knew about; this copy sat one directory over and nothing
 * looked for it.
 *
 * So this test does not check that the numbers MATCH — it checks that
 * the file contains no such numbers at all. A parity test would have to
 * be updated on every curve promotion; an absence test cannot drift,
 * and the contract already publishes the live formula under
 * `methodology.formula`.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SOURCE = join(HERE, "..", "app", "rankings", "board-sections.jsx");

describe("methodology panel carries no mirrored curve constants", () => {
  const text = readFileSync(SOURCE, "utf8");

  // Strip comments: the explanation of the OLD formula legitimately
  // quotes it, and a naive scan would match that and never go green.
  const code = text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");

  it("does not re-implement the Hill curve in JSX", () => {
    expect(code).not.toMatch(/9998\s*\/\s*\(\s*1\s*\+/);
    expect(code).not.toMatch(/rank\s*-\s*1\s*\)\s*\/\s*45/);
  });

  it("does not hardcode the retired rank-form constants", () => {
    // 45 and 1.10 together are the retired pair; either alone is noise.
    const hasRetiredMidpoint = /\/\s*45\s*\)/.test(code);
    const hasRetiredSlope = /\^\s*1\.10|\*\*\s*1\.10/.test(code);
    expect(hasRetiredMidpoint && hasRetiredSlope).toBe(false);
  });

  it("does not hardcode the retired absolute confidence thresholds", () => {
    // The live board buckets on percentile spread (0.08 / 0.20); the
    // absolute 30 / 80 rule is a fallback the /api/data path never
    // takes, and 31.9% of bucketed rows contradicted it.
    expect(code).not.toMatch(/spread\s*&le;\s*30/);
    expect(code).not.toMatch(/spread\s*&le;\s*80/);
  });

  it("reads the formula from the contract instead", () => {
    expect(code).toMatch(/methodology\?\.formula/);
    expect(code).toMatch(/methodology\?\.confidenceBuckets/);
  });
});
