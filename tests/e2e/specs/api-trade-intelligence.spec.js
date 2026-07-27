/**
 * Trade & valuation engine contracts (API layer).
 *
 * Why an API-layer spec rather than more page journeys: these two
 * endpoints carry the product's actual arithmetic — pick valuation and
 * roster-aware trade construction — and neither had ANY e2e coverage.
 * `/api/draft-capital` appeared in no spec; `/api/trade/suggestions`
 * appeared in no spec (only `/api/trade/finder` did).  Driving them
 * directly also keeps the assertions immune to the `/api/auth/status`
 * proxy race that makes page-level authed specs load-sensitive in this
 * topology (docs/e2e-assertion-audit.md §3.1).
 *
 * Every number below is cross-checked against another number from the
 * same payload, or against the committed contract — no magic constants
 * that would need editing when the snapshot refreshes.
 */
const { test, expect } = require("../helpers/auth-fixture");
const { desktopOnly, contractFixture } = require("../helpers/journey");

test.describe("api: draft capital valuation", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("GET /api/draft-capital prices a complete, internally consistent pick board", async ({
    authedPage: page,
  }) => {
    const res = await page.request.get("/api/draft-capital");
    expect(res.status(), await res.text().catch(() => "")).toBe(200);
    const body = await res.json();

    const picks = body.picks || [];
    expect(Array.isArray(picks)).toBeTruthy();
    expect(picks.length, "draft-capital returned no picks").toBeGreaterThan(0);

    // Completeness: the board must be exactly numTeams x draftRounds.
    // A short board means the pick generator dropped rounds or teams —
    // the kind of silent gap that makes every downstream pick value
    // wrong without erroring.
    expect(typeof body.numTeams).toBe("number");
    expect(typeof body.draftRounds).toBe("number");
    expect(
      picks.length,
      `expected numTeams(${body.numTeams}) x draftRounds(${body.draftRounds}) picks`,
    ).toBe(body.numTeams * body.draftRounds);

    // Every pick is owned and priced.
    for (const p of picks) {
      expect(String(p.currentOwner || ""), `pick ${p.pick} has no owner`).not.toBe("");
      expect(
        Number.isFinite(Number(p.dollarValue)),
        `pick ${p.pick} has a non-numeric dollarValue: ${p.dollarValue}`,
      ).toBeTruthy();
      expect(Number(p.dollarValue)).toBeGreaterThanOrEqual(0);
    }

    // Valuation monotonicity: early rounds are worth more than late
    // ones.  This is the core property of the pick curve, and it holds
    // regardless of which players are in the class, so it survives the
    // nightly snapshot refresh.
    const meanByRound = new Map();
    for (const p of picks) {
      const r = Number(p.round);
      if (!meanByRound.has(r)) meanByRound.set(r, []);
      meanByRound.get(r).push(Number(p.dollarValue));
    }
    const rounds = [...meanByRound.keys()].sort((a, b) => a - b);
    expect(rounds.length).toBeGreaterThan(1);
    const means = rounds.map(
      (r) => meanByRound.get(r).reduce((a, b) => a + b, 0) / meanByRound.get(r).length,
    );
    expect(
      means[0],
      `round ${rounds[0]} mean (${means[0].toFixed(1)}) should exceed round ` +
        `${rounds[rounds.length - 1]} mean (${means[means.length - 1].toFixed(1)})`,
    ).toBeGreaterThan(means[means.length - 1]);

    // Traded picks must actually have changed hands.  `isTraded` that
    // never disagrees with ownership is a flag that means nothing.
    const traded = picks.filter((p) => p.isTraded);
    if (traded.length) {
      for (const p of traded) {
        expect(
          p.currentOwner,
          `pick ${p.pick} is flagged traded but owner never changed`,
        ).not.toBe(p.originalOwner);
      }
    }

    expect(body).toHaveProperty("leagueKey");
  });
});

test.describe("api: roster-aware trade suggestions", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("POST /api/trade/suggestions builds real trades and honours the top-150 board gate", async ({
    authedPage: page,
  }) => {
    // Real rosters from the live contract — never hardcoded names.
    const { teams } = await contractFixture(page);
    expect(teams.length, "need Sleeper rosters to exercise the engine").toBeGreaterThan(1);

    const me = teams[0];
    const myRoster = (me.players || []).filter(Boolean);
    expect(
      myRoster.length,
      `team "${me.name}" has an empty roster in the contract`,
    ).toBeGreaterThan(0);

    const leagueRosters = teams
      .slice(1)
      .map((t) => ({ team: t.name, roster: (t.players || []).filter(Boolean) }));

    const res = await page.request.post("/api/trade/suggestions", {
      data: { roster: myRoster, league_rosters: leagueRosters },
    });
    expect(res.status(), await res.text().catch(() => "")).toBe(200);
    const body = await res.json();

    // Roster analysis must reflect the roster we sent.
    const ra = body.rosterAnalysis || {};
    expect(ra.rosterSize, "engine matched none of the roster").toBeGreaterThan(0);
    expect(typeof ra.starterCounts).toBe("object");

    // The documented quality gate (CLAUDE.md: BOARD_TOP_N_FILTER=150).
    expect(body.metadata?.boardTopNFilter).toBe(150);

    const buckets = ["sellHigh", "buyLow", "consolidation", "positionalUpgrades"];
    for (const b of buckets) {
      expect(Array.isArray(body[b]), `${b} must be an array`).toBeTruthy();
    }

    // Without this the per-suggestion loop below never executes and a
    // test named "builds real trades" passes on an engine that returns
    // none — the exact trap finding A8 caught in journey-trade.
    expect(
      body.totalSuggestions,
      "engine returned zero suggestions for a real roster with 11 opponent rosters",
    ).toBeGreaterThan(0);

    const all = buckets.flatMap((b) => body[b] || []);
    expect(all.length).toBe(body.totalSuggestions);

    const myRosterSet = new Set(myRoster.map((n) => String(n).toLowerCase()));
    for (const s of all) {
      expect(Array.isArray(s.give)).toBeTruthy();
      expect(Array.isArray(s.receive)).toBeTruthy();
      expect(s.give.length).toBeGreaterThan(0);
      expect(s.receive.length).toBeGreaterThan(0);

      for (const asset of [...s.give, ...s.receive]) {
        expect(String(asset.name || "").length).toBeGreaterThan(0);
        expect(Number.isFinite(Number(asset.displayValue))).toBeTruthy();
        expect(Number(asset.displayValue)).toBeGreaterThan(0);
        // The gate the engine advertises must be the gate it applied.
        expect(
          Number(asset.boardRank),
          `${asset.name} ranks ${asset.boardRank}, past the advertised top-150 gate`,
        ).toBeLessThanOrEqual(150);
      }

      // Correctness: you can only trade away players you own.
      for (const asset of s.give) {
        expect(
          myRosterSet.has(String(asset.name).toLowerCase()),
          `suggestion offers "${asset.name}", who is not on the submitted roster`,
        ).toBeTruthy();
      }
    }
  });
});
