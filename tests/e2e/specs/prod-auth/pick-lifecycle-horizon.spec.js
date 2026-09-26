/**
 * #1442 pick lifecycle — production assertion (owner request 2026-09-26).
 *
 * The deployed board must carry exactly the classes the owner decided:
 * the completed 2026 rookie class RETIRED (draft complete, rookies rostered
 * — evidence-derived by `src/identity/pick_lifecycle.py`), the supported
 * future-pick horizon 2027–2029 present, and NO 2030 (retiring 2026 does not
 * advance the horizon).
 *
 * Two layers, both asserted:
 *   1. consistency with the lifecycle OWNER — every year the contract's own
 *      `pickClassLifecycle.retiredYears` names has zero pick rows;
 *   2. the owner's expected state today — 2026 is in `retiredYears`, each of
 *      2027/2028/2029 has pick rows, 2030 has none.
 * If 2026 ever reverts to UNKNOWN in production (for example a league's
 * draft evidence stops resolving), layer 2 fails on purpose: a completed
 * class back on the board is exactly the regression this row watches for.
 *
 * Read-only: `GET /api/data?view=array` (the full contract minus the
 * legacy `players` dict), the same data every board surface reads.
 */
const { test, expect, getJson, annotate, desktopOnly } = require("./helpers");

const PICK_YEAR = /^(20\d{2})\b/;

test.describe("#1442 pick lifecycle on production", () => {
  test("2026 retired, 2027-2029 present, no 2030", async ({ prodPage: page }, testInfo) => {
    desktopOnly(test, testInfo); // one read of one contract; the phone adds nothing
    const { status, body } = await getJson(page, "/api/data?view=array", { timeoutMs: 90_000 });
    expect(status, "/api/data?view=array must serve the session").toBe(200);

    const lifecycle = body && body.pickClassLifecycle;
    expect(lifecycle, "the contract must stamp pickClassLifecycle").toBeTruthy();
    const retired = (lifecycle.retiredYears || []).map(Number);

    const byYear = new Map();
    for (const row of body.playersArray || []) {
      if (!row || row.assetClass !== "pick") continue;
      const m = PICK_YEAR.exec(String(row.canonicalName || row.displayName || ""));
      if (!m) continue;
      const y = Number(m[1]);
      byYear.set(y, (byYear.get(y) || 0) + 1);
    }
    const census = [...byYear.entries()].sort((a, b) => a[0] - b[0]).map(([y, n]) => `${y}:${n}`);
    annotate(testInfo, "pick-census", census.join(" "));
    annotate(testInfo, "retired-years", JSON.stringify(retired));
    annotate(
      testInfo,
      "class-2026-status",
      JSON.stringify((lifecycle.classes || {})["2026"] || null),
    );

    // 1. Consistent with the owner: a retired class has no rows.
    for (const y of retired) {
      expect(byYear.get(y) || 0, `retired class ${y} must have no pick rows`).toBe(0);
    }
    // 2. The owner's expected state today.
    expect(retired, "the completed 2026 class must be retired on production").toContain(2026);
    expect(byYear.get(2026) || 0, "no 2026 pick rows").toBe(0);
    for (const y of [2027, 2028, 2029]) {
      expect(byYear.get(y) || 0, `${y} picks must be on the board`).toBeGreaterThan(0);
    }
    expect(byYear.get(2030) || 0, "retiring 2026 must not add 2030").toBe(0);
  });
});
