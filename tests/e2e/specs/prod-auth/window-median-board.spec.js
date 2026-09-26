/**
 * #1434 window median — production board evidence (owner approval 2026-09-26).
 *
 * The board is private, so its values are read here through the
 * authenticated V1 session. Deploy ships the committed raw export, so the
 * production board is reproducible offline for the deployed SHA; this run
 * publishes the served values of the rows the window median moved most (and
 * a stable offense control) plus the scrape timestamp, which the release
 * receipt compares against local builds of the SAME raw payload under the
 * new and the retired estimator.
 *
 * It also asserts scale integrity on the served board: every ranked row has
 * a finite value inside the canonical 1–9999 scale, and no row is priced 0.
 */
const { test, expect, getJson, annotate } = require("./helpers");

const SENTINELS = [
  "Kyle Hamilton",
  "Kerby Joseph",
  "Jaycee Horn",
  "Omar Speights",
  "Marlon Humphrey",
  "Frankie Luvu",
  "Daiyan Henley",
  "Josh Allen",
  "Ja'Marr Chase",
];

test.describe("#1434 window median — production board", () => {
  test("serves an intact board and publishes the sentinel movers", async ({ prodPage: page }, testInfo) => {
    test.setTimeout(180_000);
    const { status, body } = await getJson(page, "/api/data", { timeoutMs: 120_000 });
    expect(status, "/api/data must serve the session").toBe(200);
    const rows = body.playersArray || [];
    expect(rows.length).toBeGreaterThan(500);
    const ranked = rows.filter((r) => typeof r.canonicalConsensusRank === "number");
    expect(ranked.length).toBeGreaterThan(300);
    for (const r of ranked) {
      expect(Number.isFinite(r.rankDerivedValue), `${r.displayName} value`).toBe(true);
      expect(r.rankDerivedValue).toBeGreaterThanOrEqual(1);
      expect(r.rankDerivedValue).toBeLessThanOrEqual(9999);
    }
    const byName = new Map(rows.map((r) => [r.displayName || r.canonicalName, r]));
    const seen = SENTINELS.map((n) => {
      const r = byName.get(n);
      return r
        ? `${n}=${r.rankDerivedValue}@${r.canonicalConsensusRank ?? "-"}(${r.sourceCount ?? "?"}src)`
        : `${n}=absent`;
    });
    annotate(
      testInfo,
      "window-median-board",
      `scrape=${body.scrapeTimestamp || body.meta?.scrapeTimestamp || "?"} ` +
        `generated=${body.meta?.generatedAt || body.generatedAt || "?"} rows=${rows.length} ranked=${ranked.length} ` +
        seen.join(" "),
    );
  });
});
