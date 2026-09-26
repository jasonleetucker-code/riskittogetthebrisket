/**
 * Game Day team switcher — production acceptance (owner directive
 * 2026-09-25, #1335).  Its own file so it never collides with the W1-16
 * spec's evidence.
 *
 * Team A is a real roster from the deployed contract (the same resolution
 * `w1-16-game-day.spec.js` uses — the guest session has no team of its own).
 * Team B is A's scheduled opponent and Team C a third roster, both taken
 * from the endpoint's own `leagueTeams` for the selected league, so the spec
 * can only walk rosters production says are in that league.
 *
 * Asserted on the live page, on desktop AND phone (390 px):
 *   - the picker lists the league's rosters and switching changes the URL,
 *     the payload identity (`data-game-day-team`) and the hero's teams;
 *   - B's page shows B's side: when A's and B's answers came from the same
 *     generation with numeric chances, B's win chance is A's opponent's;
 *   - a quick B -> C switch ends on C, and nothing of B is left under C;
 *   - the league never changes; the page never scrolls sideways.
 *
 * Truthful about the day: the state, probability state and generation of
 * every answer are annotated, including a PENDING (computing) one.
 */
const { test, expect, prodUrl, getJson, annotate } = require("./helpers");

async function intel(page, team) {
  const { status, body } = await getJson(
    page,
    `/api/matchup/intel?team=${encodeURIComponent(team)}`,
    { timeoutMs: 90_000 },
  );
  expect(status, `/api/matchup/intel?team=${team}`).toBe(200);
  return body;
}

async function resolveTeam(page) {
  const { status, body } = await getJson(page, "/api/data?view=app");
  expect(status, "/api/data must serve the session").toBe(200);
  const teams = (body && body.sleeper && body.sleeper.teams) || [];
  const withOwner = teams.filter((t) => t && t.ownerId);
  expect(withOwner.length, "contract carries no Sleeper team with an ownerId").toBeGreaterThan(0);
  return String(withOwner[0].ownerId);
}

async function shows(page, team, displayName) {
  await expect(page.locator(`[data-game-day-team="${team}"]`)).toHaveCount(1, { timeout: 90_000 });
  await expect(page.getByRole("table", { name: /matchup:/ }).locator("caption")).toContainText(
    displayName,
  );
}

async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, "the page must not scroll sideways").toBeLessThanOrEqual(sizes.viewport + 1);
}

function describeAnswer(body) {
  return [
    body.leagueKey,
    `w${body.week}`,
    body.mode,
    body.probabilityState || "-",
    (body.freshness && body.freshness.state) || "-",
    (body.freshness && body.freshness.generationId) || "no-generation",
  ].join(" ");
}

test.describe("Game Day team switcher (production)", () => {
  test("Team A -> B -> C within the selected league", async ({ prodPage: page }, testInfo) => {
    const a = await resolveTeam(page);
    const answerA = await intel(page, a);
    const league = answerA.leagueKey;
    const teams = answerA.leagueTeams || [];
    expect(teams.length, "the payload must list the league's rosters").toBeGreaterThan(2);
    const owners = teams.filter((t) => t.ownerId).map((t) => t.ownerId);
    expect(owners).toContain(a);
    const b = (answerA.opponent && answerA.opponent.ownerId) || owners.find((o) => o !== a);
    const c = owners.find((o) => o !== a && o !== b);
    annotate(testInfo, "team-switch-league", league);
    annotate(testInfo, "team-switch-A", `${a} ${describeAnswer(answerA)}`);

    await page.goto(prodUrl(`/game-day?team=${encodeURIComponent(a)}`), {
      waitUntil: "domcontentloaded",
    });
    await shows(page, a, answerA.team.displayName);
    const picker = page.getByRole("combobox", { name: "Viewing team" });
    await expect(picker).toHaveValue(a);
    const optionValues = await picker.locator("option").evaluateAll((os) =>
      os.map((o) => o.value).filter((v) => v && !v.startsWith("roster:")),
    );
    expect(new Set(optionValues)).toEqual(new Set(owners));
    await noPageOverflow(page);

    // A -> B (A's opponent: the perspective must reverse).
    await picker.selectOption(b);
    await expect(page).toHaveURL(new RegExp(`team=${encodeURIComponent(b)}`));
    const answerB = await intel(page, b);
    annotate(testInfo, "team-switch-B", `${b} ${describeAnswer(answerB)}`);
    expect(answerB.leagueKey).toBe(league);
    expect(answerB.team.ownerId).toBe(b);
    await shows(page, b, answerB.team.displayName);
    const sameGeneration =
      answerA.freshness &&
      answerB.freshness &&
      answerA.freshness.generationId &&
      answerA.freshness.generationId === answerB.freshness.generationId;
    const winA = answerA.opponent && answerA.opponent.outcome && answerA.opponent.outcome.winMatchupPct;
    const winB = answerB.team.outcome && answerB.team.outcome.winMatchupPct;
    if (sameGeneration && answerA.opponent.ownerId === b && typeof winA === "number") {
      expect(winB, "B's own win chance is A's opponent's win chance").toBe(winA);
      annotate(testInfo, "team-switch-reversal", `verified ${winB}%`);
    } else {
      annotate(testInfo, "team-switch-reversal", "not comparable (different generation or no numeric chance)");
    }
    await noPageOverflow(page);

    // B -> C, then check nothing of B remains under C.
    await picker.selectOption(c);
    await expect(page).toHaveURL(new RegExp(`team=${encodeURIComponent(c)}`));
    const answerC = await intel(page, c);
    annotate(testInfo, "team-switch-C", `${c} ${describeAnswer(answerC)}`);
    expect(answerC.leagueKey).toBe(league);
    await shows(page, c, answerC.team.displayName);
    await expect(page.locator(`[data-game-day-team="${b}"]`)).toHaveCount(0);
    await expect(picker).toHaveValue(c);
    if (answerC.probabilityState === "PENDING") {
      await expect(page.getByText(/Computing/).first()).toBeVisible();
    }
    // The league the page asked about never changed.
    expect(new URL(page.url()).searchParams.get("leagueKey") || league).toBe(league);
    await noPageOverflow(page);

    const file = testInfo.outputPath("team-switch-C.png");
    await page.screenshot({ path: file, fullPage: false });
    await testInfo.attach("team-switch-C", { path: file, contentType: "image/png" });
  });
});
