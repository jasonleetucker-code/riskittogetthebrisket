/**
 * V1-45 — the Trade Calculator consumes the canonical
 * `finalRosterSimulation` block truthfully, verified on the DEPLOYED
 * production site.
 *
 * Implements §4 steps 2-3 of
 * docs/trade/V1_45_TRADE_CALCULATOR_L4_EVIDENCE_RECIPE.md against the
 * merged render (frontend/app/trade/trade-sections.jsx SimulationPanel,
 * PR #1120): build a trade through the deployed UI whose receiving
 * roster sits at the league's roster cap, capture the page's OWN
 * POST /api/trade/simulate, and assert the rendered Final-roster
 * section matches the response's stamps field-for-field on what is
 * rendered.
 *
 * Honesty rules, per the task brief:
 *   - only states the live league actually produces are asserted;
 *     `states-observed` annotations record which branch ran;
 *   - the spec replicates the component's formatters exactly
 *     (helpers.js::fmtSigned / strengthText) so "matches" means
 *     character-for-character, not approximately;
 *   - nothing here computes trade math — every expectation is a
 *     restatement of a backend-stamped number.
 *
 * Read-only over the site: /api/trade/simulate is a pure computation
 * endpoint (it mutates no league state) and is the one POST made.
 */
const {
  test,
  expect,
  prodUrl,
  getJson,
  annotate,
  fmtSigned,
  strengthText,
  desktopOnly,
} = require("./helpers");

/** Board display names (the trade search pool), lowercased → exact. */
function boardNames(contract) {
  const names = new Map();
  for (const key of Object.keys(contract?.players || {})) {
    names.set(key.toLowerCase(), key);
  }
  if (Array.isArray(contract?.playersArray)) {
    for (const p of contract.playersArray) {
      if (p?.displayName) names.set(p.displayName.toLowerCase(), p.displayName);
    }
  }
  return names;
}

const PICK_TOKEN = /\d{4}/;

test.describe("V1-45: /trade renders finalRosterSimulation from the page's own simulate call", () => {
  test("SimulationPanel matches POST /api/trade/simulate field-for-field", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    test.setTimeout(300_000); // real UI drive over the network

    // ── Pick an at-cap receiving team + real players, from the API ──
    const { status: dataStatus, body: contract } = await getJson(
      page,
      "/api/data?view=app",
    );
    expect(dataStatus, "/api/data must serve the authenticated session").toBe(
      200,
    );
    const teams = contract?.sleeper?.teams || [];
    expect(teams.length, "contract carries no Sleeper teams").toBeGreaterThan(
      0,
    );

    const { body: leaguesBody } = await getJson(page, "/api/leagues");
    const leagueList = Array.isArray(leaguesBody)
      ? leaguesBody
      : leaguesBody?.leagues || [];
    const contractLeagueKey =
      contract?.meta?.leagueKey || contract?.leagueKey || null;
    const leagueEntry =
      leagueList.find((l) => l?.key === contractLeagueKey) ||
      leagueList[0] ||
      null;
    const rosterLimit = Number(leagueEntry?.rosterSettings?.rosterSize) || null;
    annotate(testInfo, "league", `${contractLeagueKey} rosterLimit=${rosterLimit}`);

    const board = boardNames(contract);
    // My team: prefer a roster AT the cap (so the +1-player trade forces
    // a release), else the largest roster — annotated either way, and
    // the assertions below follow what the backend actually stamps
    // rather than assuming the forced-release branch.
    const bySizeDesc = [...teams].sort(
      (a, b) => (b.players || []).length - (a.players || []).length,
    );
    const myTeam =
      bySizeDesc.find(
        (t) => rosterLimit != null && (t.players || []).length >= rosterLimit,
      ) || bySizeDesc[0];
    const myTeamIdx = teams.indexOf(myTeam);
    const atCap =
      rosterLimit != null && (myTeam.players || []).length >= rosterLimit;
    annotate(
      testInfo,
      "receiving-team",
      `${myTeam.name} (${(myTeam.players || []).length} players, atCap=${atCap})`,
    );

    // Side A (my side, giving): ONE player whose Sleeper spelling is an
    // EXACT board row name — that exact match is what the page's
    // "which side is mine" scorer keys on (trade/page.jsx
    // teamRosterNames → rowByName.has), so it guarantees side A is
    // treated as the sending side.
    const myRosterSet = new Set(myTeam.players || []);
    const giveName = (myTeam.players || []).find(
      (p) => p && !PICK_TOKEN.test(p) && board.get(p.toLowerCase()) === p,
    );
    expect(
      giveName,
      "no player on the chosen roster resolves to an identically-spelled board row — cannot drive the UI deterministically",
    ).toBeTruthy();

    // Side B (their side, my team receives): TWO players from another
    // roster, on the board, not on my roster. Net +1 player to an
    // at-cap roster → the forced-release path.
    const donor = teams.find(
      (t) =>
        t !== myTeam &&
        (t.players || []).filter(
          (p) =>
            p &&
            !PICK_TOKEN.test(p) &&
            board.get(p.toLowerCase()) === p &&
            !myRosterSet.has(p),
        ).length >= 2,
    );
    expect(donor, "no donor roster with two board-resolvable players").toBeTruthy();
    const receiveNames = (donor.players || [])
      .filter(
        (p) =>
          p &&
          !PICK_TOKEN.test(p) &&
          board.get(p.toLowerCase()) === p &&
          !myRosterSet.has(p) &&
          p !== giveName,
      )
      .slice(0, 2);
    annotate(
      testInfo,
      "trade",
      `give [${giveName}] · receive [${receiveNames.join(", ")}] from ${donor.name}`,
    );

    // ── Drive the deployed UI ────────────────────────────────────────
    await page.goto(prodUrl("/trade"), { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ }),
    ).toBeVisible({ timeout: 60_000 });
    await page.waitForFunction(
      () => !document.body.innerText.includes("Loading player pool..."),
      null,
      { timeout: 90_000 },
    );

    // Select my team (the SuggestionsDesk selector is what feeds
    // `selectedTeam`, which both gates the Simulate button and names
    // the team in the request).
    await page.selectOption("#suggest-team", String(myTeamIdx));
    await expect(
      page.getByText(/^Loaded \d+ players/),
      "team selection should load the roster",
    ).toBeVisible({ timeout: 30_000 });

    // Add assets through the page's own search-and-pick flow.
    async function addToSide(sideLabel, name) {
      const input = page.getByLabel(
        `Search to add a player to Side ${sideLabel}`,
      );
      await input.click();
      await input.fill(name);
      const result = page
        .locator(".trade-side-search-result")
        .filter({
          has: page.locator(".trade-side-search-result-name", {
            hasText: new RegExp(
              `^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`,
            ),
          }),
        })
        .first();
      await expect(
        result,
        `search should surface "${name}" verbatim`,
      ).toBeVisible({ timeout: 15_000 });
      await result.click();
      await expect(
        page.getByRole("button", {
          name: `Remove ${name} from Side ${sideLabel}`,
        }),
        `"${name}" should land on Side ${sideLabel}`,
      ).toBeVisible({ timeout: 15_000 });
    }

    await addToSide("A", giveName);
    for (const name of receiveNames) await addToSide("B", name);

    // ── (a) capture the page's OWN simulate round-trip ───────────────
    const responsePromise = page.waitForResponse(
      (res) =>
        res.url().includes("/api/trade/simulate") &&
        !res.url().includes("simulate-mc") &&
        res.request().method() === "POST",
      { timeout: 60_000 },
    );
    const simulateBtn = page.getByRole("button", { name: /^Simulate impact$/ });
    await expect(simulateBtn).toBeEnabled({ timeout: 15_000 });
    await simulateBtn.click();

    const simResponse = await responsePromise;
    const requestBody = simResponse.request().postDataJSON() || {};
    expect(
      requestBody.teamName,
      "the page's simulate request must name the selected team",
    ).toBe(myTeam.name);
    expect(requestBody.playersOut).toContain(giveName);
    for (const name of receiveNames) {
      expect(requestBody.playersIn).toContain(name);
    }
    expect(
      simResponse.status(),
      `simulate answered ${simResponse.status()}`,
    ).toBe(200);
    const sim = await simResponse.json();

    // ── (b) rendered Final-roster section === response stamps ────────
    const frs = sim.finalRosterSimulation;
    expect(
      frs,
      "response carries no finalRosterSimulation — the V1-45 render " +
        "(PR #1120) has nothing to consume; is the deployed SHA behind?",
    ).toBeTruthy();
    const rc = sim.rosterCapacity;
    annotate(
      testInfo,
      "response-shape",
      `finalRosterSimulation keys: ${Object.keys(frs).join(",")} · ` +
        `rosterCapacity.requiresDrops=${rc ? rc.requiresDrops : "absent"}`,
    );

    const panel = page
      .locator(".ds-panel")
      .filter({
        has: page.getByRole("heading", { level: 2, name: /^Impact on / }),
      })
      .first();
    await expect(panel).toBeVisible({ timeout: 30_000 });

    // Roster-capacity banner — the forced-release COUNT, rendered vs
    // stamped (rc.forcedDrops), when the backend says drops are forced.
    //
    // Scoped to the "Roster capacity" alert region specifically, not the
    // whole panel: a forced-drop player can ALSO appear in the Final-roster
    // section's own "Displaced: <name> (<pos>) — ..." line further down
    // the same panel (a real production case, e.g. Budda Baker), and a
    // panel-wide text search hits both — a Playwright strict-mode
    // violation on a locator that was never meant to be unique panel-wide.
    if (rc && rc.requiresDrops === true) {
      const capacityBanner = panel
        .locator('[role="alert"], [role="status"]')
        .filter({ has: page.getByText("Roster capacity", { exact: true }) })
        .first();
      const nDrops = (rc.forcedDrops || []).length;
      await expect(
        capacityBanner.getByText(
          new RegExp(`Forces ${nDrops} release${nDrops === 1 ? "" : "s"}`),
        ),
        `rendered forced-release count must equal rosterCapacity.forcedDrops.length (${nDrops})`,
      ).toBeVisible();
      for (const d of rc.forcedDrops || []) {
        await expect(
          capacityBanner.getByText(new RegExp(`${d.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} \\(${d.position}\\)`)),
          `forced drop "${d.name}" must be named in the capacity banner`,
        ).toBeVisible();
      }
      annotate(testInfo, "states-observed", `rosterCapacity forces ${nDrops} release(s)`);
    } else {
      annotate(
        testInfo,
        "states-observed",
        `rosterCapacity.requiresDrops=${rc ? rc.requiresDrops : "absent"} — no forced-release banner expected`,
      );
    }

    // The Final-roster section itself, branch by what the backend stamped.
    const stat = (label) =>
      panel
        .locator("div.ds-stat")
        .filter({
          has: page.locator(".ds-stat__label", {
            hasText: new RegExp(`^${label}$`),
          }),
        })
        .locator(".ds-stat__value");

    if (frs.available === true) {
      annotate(testInfo, "states-observed", "finalRosterSimulation: populated");

      await expect(
        panel.getByText(/^Final roster$/),
        "populated state must render the Final roster section",
      ).toBeVisible();

      // Strength tiles — the BACKEND's numbers under the component's
      // exact formatting (strengthText / fmtSigned replicas).
      await expect(stat("Strength before")).toHaveText(
        strengthText(frs.strengthBefore?.total),
      );
      await expect(stat("Strength after")).toHaveText(
        strengthText(frs.strengthAfter?.total),
      );
      const expectedDelta = Number.isFinite(Number(frs.strengthDelta))
        ? fmtSigned(frs.strengthDelta)
        : "—";
      await expect(
        stat("Strength change"),
        `Strength change must render the backend's strengthDelta (${frs.strengthDelta}) verbatim`,
      ).toHaveText(expectedDelta);

      // Promotions / displacements — count parity plus every stamped
      // name present, as rendered.
      const promoted = panel.locator("li", { hasText: /^Promoted:/ });
      await expect(promoted).toHaveCount((frs.promotions || []).length);
      for (const m of frs.promotions || []) {
        await expect(
          promoted.filter({ hasText: m.name }),
          `promotion "${m.name}" missing from the rendered list`,
        ).toHaveCount(1);
      }
      const displaced = panel.locator("li", { hasText: /^Displaced:/ });
      await expect(displaced).toHaveCount((frs.displacements || []).length);
      for (const m of frs.displacements || []) {
        await expect(
          displaced.filter({ hasText: m.name }),
          `displacement "${m.name}" missing from the rendered list`,
        ).toHaveCount(1);
      }

      // Needs — both directions, rendered iff stamped non-empty.
      const needsClosed = panel.locator("li", { hasText: /^Needs closed:/ });
      if ((frs.needsFixed || []).length > 0) {
        await expect(needsClosed).toHaveText(
          `Needs closed: ${frs.needsFixed.join(", ")}`,
        );
      } else {
        await expect(needsClosed).toHaveCount(0);
      }
      const needsOpened = panel.locator("li", { hasText: /^Needs opened:/ });
      if ((frs.needsCreated || []).length > 0) {
        await expect(needsOpened).toHaveText(
          `Needs opened: ${frs.needsCreated.join(", ")}`,
        );
      } else {
        await expect(needsOpened).toHaveCount(0);
      }

      // Cleanup line — the forced-release count INSIDE the final-roster
      // section, which must agree with the stamp it renders.
      const nCleanup = (frs.cleanupApplied || []).length;
      if (nCleanup > 0) {
        await expect(
          panel.getByText(
            new RegExp(
              `Solved after ${nCleanup} required release${nCleanup === 1 ? "" : "s"}`,
            ),
          ),
          `cleanup line must carry cleanupApplied.length (${nCleanup})`,
        ).toBeVisible();
      }
      if (frs.cleanupIsUpperBound) {
        await expect(
          panel.getByText(/worst case, so this final\s+roster is one of a range/),
        ).toBeVisible();
      }

      // Distinguishability: the populated section must NOT carry the
      // refusal copy.
      await expect(panel.getByText(/Not simulated/)).toHaveCount(0);
    } else if (frs.unavailableReason === "capacity_uncertain") {
      annotate(
        testInfo,
        "states-observed",
        "finalRosterSimulation: capacity_uncertain",
      );
      // The capacity_uncertain copy is its own sentence — "taxi
      // occupancy" wording — distinct from both the populated section
      // and the generic error refusal.
      await expect(
        panel.getByText(
          /Not simulated — taxi occupancy is unknown, so the forced-drop set is a range/,
        ),
      ).toBeVisible();
      // The refusal banner reuses the "Final roster" title, so absence
      // of the POPULATED section is asserted on its tiles, not the title.
      await expect(stat("Strength change")).toHaveCount(0);
    } else {
      const reason = frs.unavailableReason || frs.unavailable || "unreported";
      annotate(
        testInfo,
        "states-observed",
        `finalRosterSimulation: unavailable (${reason})`,
      );
      await expect(
        panel.getByText(new RegExp(`Not simulated — .*${reason}`)),
        "the refusal must be rendered with its own reason, not collapsed",
      ).toBeVisible();
      await expect(stat("Strength change")).toHaveCount(0);
      // ...and it must not read like the capacity_uncertain state.
      if (reason !== "capacity_uncertain") {
        await expect(panel.getByText(/taxi occupancy is unknown/)).toHaveCount(
          0,
        );
      }
    }
  });
});
