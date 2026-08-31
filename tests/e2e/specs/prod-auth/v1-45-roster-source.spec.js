/**
 * V1-45 evidence-only follow-up.
 *
 * The production render proof found a receiving team whose contract-side
 * `players.length` was 58 while the canonical roster-capacity response used
 * `sizeBefore=57`. This spec does not choose a verdict or change product
 * behaviour. It makes the two contract-side identity populations legible so
 * the already-set evidence rule can distinguish an empty display-name entry
 * from an unresolved real roster asset.
 */
const {
  test,
  expect,
  getJson,
  annotate,
  desktopOnly,
} = require("./helpers");

function nonblank(value) {
  return String(value ?? "").trim().length > 0;
}

test.describe("V1-45: roster source reconciliation", () => {
  test("contract publishes enough identity evidence to explain roster-capacity sizeBefore", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);

    const { status, body: contract } = await getJson(page, "/api/data?view=app");
    expect(status, "/api/data must serve the authenticated session").toBe(200);

    const teams = contract?.sleeper?.teams || [];
    expect(teams.length, "contract carries no Sleeper teams").toBeGreaterThan(0);

    const { body: leaguesBody } = await getJson(page, "/api/leagues");
    const leagueList = Array.isArray(leaguesBody)
      ? leaguesBody
      : leaguesBody?.leagues || [];
    const contractLeagueKey = contract?.meta?.leagueKey || contract?.leagueKey || null;
    const leagueEntry =
      leagueList.find((l) => l?.key === contractLeagueKey) || leagueList[0] || null;
    const rosterLimit = Number(leagueEntry?.rosterSettings?.rosterSize) || null;

    // Match the production trade-surface spec's receiving-team selection,
    // deliberately using raw `players.length`. We are explaining that exact
    // population rather than selecting a friendlier one after seeing data.
    const bySizeDesc = [...teams].sort(
      (a, b) => (b.players || []).length - (a.players || []).length,
    );
    const team =
      bySizeDesc.find(
        (t) => rosterLimit != null && (t.players || []).length >= rosterLimit,
      ) || bySizeDesc[0];

    const players = Array.isArray(team?.players) ? team.players : [];
    const playerIds = Array.isArray(team?.playerIds) ? team.playerIds : [];
    const blankNameIndexes = players
      .map((value, index) => ({ value, index }))
      .filter(({ value }) => !nonblank(value))
      .map(({ index }) => index);
    const blankIdIndexes = playerIds
      .map((value, index) => ({ value, index }))
      .filter(({ value }) => !nonblank(value))
      .map(({ index }) => index);
    const idsPresentAtBlankNameIndexes = blankNameIndexes.filter(
      (index) => index < playerIds.length && nonblank(playerIds[index]),
    );

    annotate(testInfo, "league", `${contractLeagueKey} rosterLimit=${rosterLimit}`);
    annotate(testInfo, "receiving-team", `${team?.name || "unknown"}`);
    annotate(
      testInfo,
      "roster-source",
      `players raw=${players.length} nonblank=${players.filter(nonblank).length} ` +
        `blankIndexes=[${blankNameIndexes.join(",")}]`,
    );
    annotate(
      testInfo,
      "roster-source",
      `playerIds raw=${playerIds.length} nonblank=${playerIds.filter(nonblank).length} ` +
        `blankIndexes=[${blankIdIndexes.join(",")}]`,
    );
    annotate(
      testInfo,
      "roster-source",
      `idsPresentAtBlankNameIndexes=[${idsPresentAtBlankNameIndexes.join(",")}]`,
    );

    // Evidence-only assertions: arrays and selected team must be real. Do not
    // assert which of the competing explanations is true; that would bake the
    // answer into the instrument before production supplies it.
    expect(team, "no receiving team resolved").toBeTruthy();
    expect(players.length, "selected team has no raw player population").toBeGreaterThan(0);
  });
});
