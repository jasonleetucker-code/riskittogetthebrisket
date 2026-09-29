/**
 * League MVP team-success gate — production acceptance (owner decision
 * 2026-09-26). Public League Hub, desktop + phone.
 *
 * From the live /api/public/league/awards payload:
 *   - the League MVP race publishes a verified eligibility block, and no
 *     player the gate keeps out appears in its standings;
 *   - OPOY / DPOY carry no eligibility block (not gated), and when their
 *     leader sits on a team the gate excludes, they still rank him first;
 * then on the rendered Awards tab: the MVP card states the rule, the
 * OPOY / DPOY cards do not, standings still expand, and nothing scrolls
 * sideways.
 */
const { test, expect, ORIGIN, prodUrl, getJson, annotate } = require("./helpers");

function configured() {
  return Boolean(String(ORIGIN || "").trim());
}

test.describe("League MVP team-success gate (production)", () => {
  test("MVP is gated, OPOY / DPOY are not, and the page says so", async ({ page }, testInfo) => {
    test.skip(!configured(), "PROD_ORIGIN is not configured");
    test.setTimeout(240_000);
    const { status, body } = await getJson(page, "/api/public/league/awards", { timeoutMs: 90_000 });
    expect(status).toBe(200);
    const races = new Map((body.data.awardRaces || []).map((r) => [r.key, r]));
    const mvp = races.get("league_mvp");
    expect(mvp, "a live League MVP race (or its explicit awaiting state)").toBeTruthy();
    const elig = mvp.eligibility;
    expect(elig, "the race publishes its eligibility rule").toBeTruthy();
    expect(elig.rule).toBe("playoff_field_and_record_500_or_better");
    // Owner correction 2026-09-29: ".500 or better". The retired
    // "not above .500" reason must never be published again.
    for (const o of elig.outsideTheRace || []) {
      expect(o.reason).not.toBe("team_record_not_above_500");
    }

    const outsideIds = new Set((elig.outsideTheRace || []).map((o) => o.playerId));
    for (const s of mvp.standings || []) {
      expect(outsideIds.has(s.value.playerId), `${s.value.playerName} is outside the race`).toBe(false);
    }
    for (const key of ["off_mvp", "def_mvp"]) {
      const r = races.get(key);
      if (!r) continue;
      expect(r.eligibility, `${key} must not carry the MVP gate`).toBeUndefined();
      const lead = (r.leaders || [])[0];
      if (lead && outsideIds.has(lead.value.playerId)) {
        // The best performer is on a team the gate excludes, and still leads.
        expect((r.standings || [])[0].value.playerId).toBe(lead.value.playerId);
      }
    }
    annotate(
      testInfo,
      "league-mvp-gate",
      `verified=${elig.verified} basis=${elig.basis} field=${elig.playoffTeams} ` +
        `mvpLead=${(mvp.leaders || [])[0]?.value?.playerName || mvp.awaitingReason} ` +
        `outside=${(elig.outsideTheRace || []).map((o) => `${o.playerName}:${o.reason}`).join("|")} ` +
        `opoyLead=${races.get("off_mvp")?.leaders?.[0]?.value?.playerName} ` +
        `dpoyLead=${races.get("def_mvp")?.leaders?.[0]?.value?.playerName}`,
    );

    await page.goto(prodUrl("/league?tab=awards"), { waitUntil: "domcontentloaded", timeout: 60_000 });
    const mvpCard = page.locator('article[data-award-key="league_mvp"]');
    await expect(mvpCard).toBeVisible({ timeout: 60_000 });
    if (elig.verified) {
      await expect(mvpCard.locator("[data-mvp-eligibility]")).toContainText(".500-or-better record");
    }
    for (const key of ["off_mvp", "def_mvp"]) {
      const c = page.locator(`article[data-award-key="${key}"]`);
      if ((await c.count()) === 0) continue;
      await expect(c.locator("[data-mvp-eligibility]")).toHaveCount(0);
      await expect(c.locator("[data-mvp-outside]")).toHaveCount(0);
    }
    if ((mvp.standings || []).length) {
      const btn = mvpCard.getByRole("button", { name: /Expand standings/ });
      await btn.click();
      await expect(mvpCard.locator("[data-award-standings] ol > li")).toHaveCount(mvp.standings.length);
    }
    const s = await page.evaluate(() => ({
      d: document.documentElement.scrollWidth,
      v: document.documentElement.clientWidth,
    }));
    expect(s.d, "no sideways page scroll").toBeLessThanOrEqual(s.v + 1);
    const shot = testInfo.outputPath("league-mvp-gate.png");
    await mvpCard.screenshot({ path: shot });
    await testInfo.attach("league-mvp-gate", { path: shot, contentType: "image/png" });
  });
});
