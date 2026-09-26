/**
 * Live Median Race — production acceptance (owner directive 2026-09-26).
 *
 * On the deployed /game-day, desktop and phone (prod-desktop / prod-mobile):
 *   - the board is present and lists every roster of the selected league once;
 *   - its order is the API's `medianRace.teams` order (the backend's rank);
 *   - the selected row's beat-median figure equals the hero's for that team;
 *   - the projected median and its 80% range render when a forecast exists;
 *   - a row tap switches Game Day to that team via ?team=;
 *   - no sideways page scroll.
 * Whatever state production is in (pregame / live / final / pending /
 * withheld) is annotated with the projected median, current median, bubble
 * and whether movement was present, so the run is its own evidence.
 */
const { test, expect, prodUrl, getJson, annotate } = require("./helpers");

function pct(v) {
  return typeof v === "number" ? `${v.toFixed(1)}%` : null;
}

async function resolveTeam(page) {
  const { status, body } = await getJson(page, "/api/data?view=app");
  expect(status, "/api/data must serve the session").toBe(200);
  const teams = ((body && body.sleeper && body.sleeper.teams) || []).filter((t) => t && t.ownerId);
  expect(teams.length).toBeGreaterThan(0);
  return String(teams[0].ownerId);
}

async function noPageOverflow(page) {
  const s = await page.evaluate(() => ({
    d: document.documentElement.scrollWidth,
    v: document.documentElement.clientWidth,
  }));
  expect(s.d, "the page must not scroll sideways").toBeLessThanOrEqual(s.v + 1);
}

test.describe("Live Median Race (production)", () => {
  test("the whole league, API order, hero agreement, row switch", async ({ prodPage: page }, testInfo) => {
    test.setTimeout(300_000);
    const team = await resolveTeam(page);
    const { status, body } = await getJson(page, `/api/matchup/intel?team=${encodeURIComponent(team)}`, {
      timeoutMs: 90_000,
    });
    expect(status).toBe(200);
    const race = body.medianRace;
    expect(race, "the payload carries the league median race").toBeTruthy();
    const ids = race.teams.map((t) => t.rosterId);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(ids)).toEqual(new Set((body.leagueTeams || []).map((t) => t.rosterId)));
    const selected = race.teams.find((t) => t.rosterId === race.selectedRosterId);
    expect(selected.beatMedianPct).toBe(body.team.outcome ? body.team.outcome.beatMedianPct : null);
    annotate(
      testInfo,
      "median-race",
      [
        `league=${body.leagueKey} week=${body.week} mode=${body.mode} state=${race.state}`,
        `current=${race.currentMedian}(${race.currentMedianState})`,
        `projected=${race.projectedMedianMean} [${race.projectedMedianP10}-${race.projectedMedianP90}]`,
        `final=${race.finalMedian}`,
        `bubble=${(race.bubble || []).join(",")}`,
        `movement=${race.movement ? race.movement.comparedToGenerationId : "none"}`,
        `top=${race.teams.slice(0, 3).map((t) => `${t.rosterId}:${t.beatMedianPct}`).join(" ")}`,
      ].join(" "),
    );

    await page.goto(prodUrl(`/game-day?team=${encodeURIComponent(team)}`), { waitUntil: "domcontentloaded" });
    const section = page.locator('section[aria-labelledby="median-race-title"]');
    await expect(section).toBeVisible({ timeout: 90_000 });
    if (race.state !== "not_applicable") {
      const order = await section.locator("li[data-roster-id]").evaluateAll((els) =>
        els.map((e) => e.getAttribute("data-roster-id")),
      );
      // The page may have polled a newer generation; compare to what IT shows
      // against a fresh read if the first read differs.
      if (JSON.stringify(order) !== JSON.stringify(ids)) {
        const again = await getJson(page, `/api/matchup/intel?team=${encodeURIComponent(team)}`, {
          timeoutMs: 90_000,
        });
        expect(order).toEqual(again.body.medianRace.teams.map((t) => t.rosterId));
      } else {
        expect(order).toEqual(ids);
      }
      const sel = section.locator('[aria-current="true"]');
      await expect(sel).toHaveCount(1);
      if (pct(selected.beatMedianPct)) {
        await expect(sel.getByText(pct(selected.beatMedianPct), { exact: false }).first()).toBeVisible();
      }
    }
    if (race.state === "forecast") {
      await expect(section.getByText("Projected final")).toBeVisible();
    }
    await noPageOverflow(page);

    // Row tap switches the team.
    const other = race.teams.find((t) => t.ownerId && t.ownerId !== team);
    if (other && race.state !== "not_applicable") {
      await section.locator(`li[data-roster-id="${other.rosterId}"] button`).click();
      await expect(page).toHaveURL(new RegExp(`team=${encodeURIComponent(other.ownerId)}`));
      await expect(section.locator(`li[data-roster-id="${other.rosterId}"] [aria-current="true"]`)).toHaveCount(
        1,
        { timeout: 90_000 },
      );
      await expect(page.getByRole("combobox", { name: "Viewing team" })).toHaveValue(other.ownerId);
      await noPageOverflow(page);
    }
    const shot = testInfo.outputPath("median-race.png");
    await section.screenshot({ path: shot });
    await testInfo.attach("median-race", { path: shot, contentType: "image/png" });
  });
});
