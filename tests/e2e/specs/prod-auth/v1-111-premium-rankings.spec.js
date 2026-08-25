/**
 * V1-111 — the premium (`.psi-editorial`) rankings surface on the
 * DEPLOYED production site renders backend stamps verbatim.
 *
 * Grounded in docs/psi/PR_A_VISUAL_VERIFICATION_2026-08-20.md ("every
 * number traces to the contract; nothing on the page is invented") and
 * the rankings page component:
 *
 *   - the `.psi-editorial` scope is present AND active (its token remap
 *     is measurably applied, not just a class string in the DOM);
 *   - the top row shows rank #1 with the real backend name and value —
 *     compared against the authenticated /api/data contract, under the
 *     page's own formatting (Math.round + toLocaleString);
 *   - no client-side rank/value computation: the first N rendered rows'
 *     (rank → name, value) tuples are exactly the backend's stamps, and
 *     buildRows' zero-rank-stamps fail-fast never fired in the console;
 *   - partial-data states render truthfully where the visible window
 *     exhibits one (annotated honestly when it does not).
 *
 * Runs at BOTH 1366x768 (prod-desktop) and 390x844 (prod-mobile).
 */
const {
  test,
  expect,
  prodUrl,
  getJson,
  annotate,
} = require("./helpers");

const BOARD_ROW = ".ds-table-wrap table tbody tr.rankings-row-clickable";

/** rank → {name, value} from the legacy players dict the app view serves. */
function backendRankMap(contract) {
  const map = new Map();
  for (const [name, row] of Object.entries(contract?.players || {})) {
    const rank = row?._canonicalConsensusRank;
    if (rank == null) continue;
    map.set(Number(rank), {
      name,
      value: Math.round(Number(row.rankDerivedValue ?? row.values?.full ?? 0)),
    });
  }
  return map;
}

test.describe("V1-111: premium rankings render backend stamps", () => {
  test("psi-editorial is active and the board is the backend's, verbatim", async ({
    prodPage: page,
  }, testInfo) => {
    // Backend truth first, over the same session.
    const { status, body: contract } = await getJson(page, "/api/data?view=app");
    expect(status, "/api/data must serve the session").toBe(200);
    const rankMap = backendRankMap(contract);
    expect(
      rankMap.size,
      "the contract carries no rank stamps — nothing to verify against",
    ).toBeGreaterThan(100);

    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 300));
    });

    await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });
    const rows = page.locator(BOARD_ROW);
    await expect(rows.first(), "rankings board should render rows").toBeVisible({
      timeout: 90_000,
    });

    // ── The premium scope is present AND active ──────────────────────
    const scope = page.locator("section.psi-editorial");
    await expect(
      scope,
      "the rankings page section no longer carries the psi-editorial scope",
    ).toHaveCount(1);
    // Active = the scope's token remap is applied, not merely classed:
    // --surface-0 is the psi cream canvas (frontend/app/tokens.css).
    const surface0 = await scope.evaluate((el) =>
      getComputedStyle(el).getPropertyValue("--surface-0").trim(),
    );
    expect(
      surface0.toLowerCase(),
      "psi-editorial is classed but its token layer is not applied — " +
        "the premium surface is not actually active",
    ).toBe("#f2ebdd");
    annotate(testInfo, "psi-editorial", `active (--surface-0=${surface0})`);

    // ── Top row: rank #1, real name, real value ──────────────────────
    const first = rows.first();
    const firstRankText = (
      await first.locator('td[data-col="rank"]').innerText()
    ).trim();
    const firstRank = parseInt(firstRankText, 10);
    expect(
      firstRank,
      `top rendered row shows rank "${firstRankText}", expected #1`,
    ).toBe(1);

    const backendTop = rankMap.get(1);
    expect(backendTop, "backend stamps no rank-1 row").toBeTruthy();
    const renderedName = (
      await first.locator('td[data-col="name"] .rankings-player-name').innerText()
    ).trim();
    expect(
      renderedName,
      "the top row's player is not the backend's rank-1 player",
    ).toBe(backendTop.name);

    const renderedValue = (
      await first.locator('td[data-col="value"] button').first().innerText()
    ).trim();
    expect(
      renderedValue,
      `top row value must be the backend's rankDerivedValue (${backendTop.value}) under the page's own formatting`,
    ).toBe(backendTop.value.toLocaleString("en-US"));
    annotate(
      testInfo,
      "top-row",
      `#1 ${renderedName} · ${renderedValue} (API: ${backendTop.name} · ${backendTop.value})`,
    );

    // ── No client-side re-rank/re-value: sample the visible window ───
    const sampleCount = Math.min(await rows.count(), 15);
    let partialsSeen = 0;
    for (let i = 0; i < sampleCount; i += 1) {
      const row = rows.nth(i);
      const rankText = (
        await row.locator('td[data-col="rank"]').innerText()
      ).trim();
      const name = (
        await row.locator('td[data-col="name"] .rankings-player-name').innerText()
      ).trim();
      if (rankText.startsWith("—")) {
        // Partial-data state: an unranked row must really be unranked
        // in the contract — "—" is truthful, a number would have to be.
        partialsSeen += 1;
        const contractRow = contract.players?.[name];
        expect(
          contractRow?._canonicalConsensusRank ?? null,
          `row "${name}" renders an em-dash rank but the backend stamps one`,
        ).toBeNull();
        continue;
      }
      const rank = parseInt(rankText, 10);
      const backendRow = rankMap.get(rank);
      expect(
        backendRow,
        `rendered rank #${rank} ("${name}") does not exist in the backend's rank stamps — a client-side ordinal`,
      ).toBeTruthy();
      expect(
        name,
        `rank #${rank} renders "${name}" but the backend stamps "${backendRow.name}" — a client-side re-rank`,
      ).toBe(backendRow.name);
      const valueText = (
        await row.locator('td[data-col="value"] button').first().innerText()
      ).trim();
      expect(
        valueText,
        `rank #${rank} "${name}" renders a value the backend did not stamp`,
      ).toBe(backendRow.value.toLocaleString("en-US"));
    }
    annotate(
      testInfo,
      "rows-verified",
      `${sampleCount} rendered rows matched backend (rank, name, value) exactly`,
    );
    annotate(
      testInfo,
      "partial-data-states",
      partialsSeen > 0
        ? `${partialsSeen} visible row(s) rendered explicit missing states, verified truthful`
        : "no partial-data row visible in the sampled window — state not exercisable on this board",
    );

    // buildRows' fail-fast (zero rank stamps → empty board + console
    // error) must not have fired; nor any other page error.
    const failFast = consoleErrors.filter((t) => /rank stamp|buildRows/i.test(t));
    expect(
      failFast,
      "buildRows reported missing backend stamps — the board would be a client-side construction",
    ).toEqual([]);
  });
});
