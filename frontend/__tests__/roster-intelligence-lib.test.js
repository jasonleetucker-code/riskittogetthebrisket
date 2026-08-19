/**
 * `lib/roster-intelligence.js` — the materializer between
 * `GET /api/roster/intelligence` and the Team Strength surface.
 *
 * The fixture is not hand-written. `fixtures/roster-intelligence.json`
 * was produced by running `src/api/roster_intelligence.py` over the
 * tracked export archive (`exports/latest/dynasty_data_2026-08-19.json`)
 * and trimming the blocks this surface does not read. That matters:
 * the last frontend defect on this branch came from a fixture that
 * invented a field name, so the fixture and the code agreed with each
 * other while both disagreed with the server.
 *
 * Real numbers from that run, quoted below because they are what the
 * assertions are about:
 *
 *   total 79,994 · starters 60,431 · reserves 19,563 · rank 9 of 12
 *   unpricedCount 12 · unfilledStarterSlots ["K"] · isComplete false
 *   fullRosterValue null · league totals 55,520 … 146,487
 */
import { describe, it, expect } from "vitest";
import fixture from "./fixtures/roster-intelligence.json";
import {
  NOT_MEASURED,
  classifyRosterIntelligenceFailure,
  formatStrengthValue,
  ownerIdForTeamName,
  strengthCaveats,
  teamStrengthDetail,
  teamStrengthLadder,
} from "@/lib/roster-intelligence";

/** Deep clone so a mutation in one test cannot leak into another. */
const clone = (v) => JSON.parse(JSON.stringify(v));

describe("classifyRosterIntelligenceFailure", () => {
  it("returns null for a 2xx", () => {
    expect(classifyRosterIntelligenceFailure(200, fixture)).toBeNull();
  });

  it("tells the user-fixable refusals apart from a broken engine", () => {
    // These four are all HTTP 400/404/503 and would be one indistinct
    // "error" under a status-only classifier. Two of them the user can
    // act on.
    expect(classifyRosterIntelligenceFailure(400, { error: "team_required" }).kind).toBe(
      "team_required",
    );
    expect(classifyRosterIntelligenceFailure(404, { error: "team_not_found" }).kind).toBe(
      "team_not_found",
    );
    expect(classifyRosterIntelligenceFailure(400, { error: "unknown_league" }).kind).toBe(
      "league",
    );
    expect(classifyRosterIntelligenceFailure(503, { error: "data_not_ready" }).kind).toBe(
      "not_ready",
    );
  });

  it("classifies the bridge's own 503 separately from the backend's", () => {
    // The Next bridge route returns `roster_intelligence_unavailable`
    // when it cannot reach FastAPI at all. "The league has no data yet"
    // and "the service did not answer" are different facts.
    expect(
      classifyRosterIntelligenceFailure(503, { error: "roster_intelligence_unavailable" })
        .kind,
    ).toBe("unavailable");
  });

  it("carries the backend's own message through", () => {
    const f = classifyRosterIntelligenceFailure(503, {
      error: "data_not_ready",
      message: "No data loaded for league 'dynasty_new' yet.",
    });
    expect(f.message).toBe("No data loaded for league 'dynasty_new' yet.");
  });

  it("falls back to the status, never to a blank", () => {
    expect(classifyRosterIntelligenceFailure(500, null)).toEqual({
      kind: "error",
      message: "HTTP 500",
    });
  });
});

describe("teamStrengthDetail", () => {
  it("reads the canonical total verbatim", () => {
    expect(teamStrengthDetail(fixture).total).toBe(79994);
  });

  it("is a materializer: change the backend number, the output changes", () => {
    // The point of the assertion is that nothing here derives the total
    // from the position rows, the starter/reserve split, or anything
    // else. Move ONLY `total` and only `total` moves.
    const moved = clone(fixture);
    moved.team.strength.total = 12345.678;
    const out = teamStrengthDetail(moved);
    expect(out.total).toBe(12345.678);
    expect(out.starterValue).toBe(60431);
    expect(out.reserveValue).toBe(19563);
  });

  it("does not clamp an aggregate above 9999", () => {
    // Inventory row 7.5: player values are a 1-9999 scale, aggregates
    // are NOT capped. Every real team on this board is far above it.
    expect(teamStrengthDetail(fixture).total).toBeGreaterThan(9999);
    const huge = clone(fixture);
    huge.team.strength.total = 250000;
    expect(teamStrengthDetail(huge).total).toBe(250000);
  });

  it("keeps the portfolio a separate field from the strength total", () => {
    // `fullRosterValue` is null on the live endpoint today. Null must
    // stay null: an absent portfolio is not a portfolio worth nothing,
    // and it is certainly not the strength total.
    const out = teamStrengthDetail(fixture);
    expect(out.fullRosterValue).toBeNull();
    expect(out.fullRosterValue).not.toBe(out.total);

    const withPortfolio = clone(fixture);
    withPortfolio.team.strength.fullRosterValue = 131000;
    const out2 = teamStrengthDetail(withPortfolio);
    expect(out2.fullRosterValue).toBe(131000);
    expect(out2.total).toBe(79994);
  });

  it("reports an unavailable strength as unavailable, not as zero", () => {
    const refused = clone(fixture);
    refused.team.strength = {
      available: false,
      unavailableReason: "no_starter_slots",
      total: 0,
      unpricedIds: [],
      unpricedCount: 0,
      byPosition: [],
      positionOrder: [],
      unfilledStarterSlots: [],
      unfilledReserveSlots: [],
      isComplete: false,
      leagueRank: null,
      leaguePercentile: null,
      fullRosterValue: null,
      starterValue: 0,
      reserveValue: 0,
    };
    const out = teamStrengthDetail(refused);
    expect(out.available).toBe(false);
    expect(out.unavailableReason).toBe("no_starter_slots");
    expect(out.rankLabel).toBe(NOT_MEASURED);
  });

  it("renders a null rank as not-measured", () => {
    const unranked = clone(fixture);
    unranked.team.strength.leagueRank = null;
    const out = teamStrengthDetail(unranked);
    expect(out.rank).toBeNull();
    expect(out.rankLabel).toBe(NOT_MEASURED);
    expect(out.rankLabel).not.toContain("0");
  });

  it("takes the position groups and their order from the backend", () => {
    // No local group list. A league running a group the frontend has
    // never heard of still gets a row, and FLEX never becomes one — a
    // FLEX-seated RB is summed under RB by the backend's own grouping.
    const out = teamStrengthDetail(fixture);
    expect(out.positions.map((p) => p.position)).toEqual([
      "QB",
      "RB",
      "WR",
      "TE",
      "DL",
      "LB",
      "DB",
    ]);
    expect(out.positions.map((p) => p.position)).not.toContain("FLEX");

    const exotic = clone(fixture);
    exotic.team.strength.positionOrder = ["QB", "PK"];
    exotic.team.strength.byPosition = [
      { position: "QB", value: 1, count: 1, starterValue: 1, starterCount: 1, reserveValue: 0, reserveCount: 0, leagueRank: 1 },
      { position: "PK", value: 2, count: 1, starterValue: 2, starterCount: 1, reserveValue: 0, reserveCount: 0, leagueRank: null },
    ];
    const out2 = teamStrengthDetail(exotic);
    expect(out2.positions.map((p) => p.position)).toEqual(["QB", "PK"]);
    expect(out2.positions[1].rankLabel).toBe(NOT_MEASURED);
  });

  it("returns null when there is no team at all", () => {
    expect(teamStrengthDetail({ leagueContext: [] })).toBeNull();
    expect(teamStrengthDetail(null)).toBeNull();
  });
});

describe("strengthCaveats", () => {
  it("says an unfilled starting slot makes the total partial", () => {
    // Real board: this league starts a K and the roster has none.
    const caveats = strengthCaveats(teamStrengthDetail(fixture));
    expect(caveats.join(" ")).toContain("K");
    expect(caveats.join(" ")).toContain("unmeasured rather than low");
  });

  it("says unpriced players are excluded rather than counted as zero", () => {
    const caveats = strengthCaveats(teamStrengthDetail(fixture));
    expect(caveats.join(" ")).toContain("12 rostered players");
    expect(caveats.join(" ")).toContain("rather than counted as zero");
  });

  it("is empty for a complete roster", () => {
    const complete = clone(fixture);
    complete.team.strength.unfilledStarterSlots = [];
    complete.team.strength.unfilledReserveSlots = [];
    complete.team.strength.unpricedCount = 0;
    complete.team.strength.isComplete = true;
    expect(strengthCaveats(teamStrengthDetail(complete))).toEqual([]);
  });
});

describe("teamStrengthLadder", () => {
  it("preserves the backend's order rather than re-sorting", () => {
    // `_league_context_order` already put ranked teams first, best
    // first, and unranked last on an explicit `inf`. Re-sorting here
    // would be a second opinion about the ladder.
    const rows = teamStrengthLadder(fixture);
    expect(rows.map((r) => r.rank)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(rows[0].strengthTotal).toBe(146487);
    expect(rows[rows.length - 1].strengthTotal).toBe(55520);
  });

  it("does not move an unranked team to the top", () => {
    // The failure mode this guards is `(a.rank ?? 0) - (b.rank ?? 0)`,
    // which reads an ABSENT rank as the best possible one. We keep the
    // server's order, so an unranked team stays where it put it.
    const withUnranked = clone(fixture);
    withUnranked.leagueContext.push({
      ownerId: "unreadable",
      teamName: "Unreadable",
      strengthTotal: null,
      strengthRank: null,
      youngCoreIndex: null,
      valueWeightedCoreAge: null,
    });
    const rows = teamStrengthLadder(withUnranked);
    expect(rows[0].teamName).toBe("Jason");
    const last = rows[rows.length - 1];
    expect(last.teamName).toBe("Unreadable");
    expect(last.measured).toBe(false);
    expect(last.rankLabel).toBe(NOT_MEASURED);
    expect(last.strengthTotal).toBeNull();
  });

  it("marks the caller's own team", () => {
    const me = fixture.leagueContext[3];
    const rows = teamStrengthLadder(fixture, { myOwnerId: me.ownerId });
    expect(rows.filter((r) => r.isMe).map((r) => r.teamName)).toEqual([me.teamName]);
  });

  it("marks nobody when no ownerId is supplied", () => {
    // An empty ownerId must not match a team whose ownerId is also
    // empty-ish; "I don't know who you are" is not "you are that team".
    expect(teamStrengthLadder(fixture).some((r) => r.isMe)).toBe(false);
  });

  it("is empty rather than throwing on a payload with no context", () => {
    expect(teamStrengthLadder({})).toEqual([]);
    expect(teamStrengthLadder(null)).toEqual([]);
  });
});

describe("ownerIdForTeamName", () => {
  const teams = [
    { name: "Jason", ownerId: "468418790212759552" },
    { name: "Roy", ownerId: "472206636534984704" },
  ];

  it("resolves the settings team NAME to the endpoint's ownerId", () => {
    expect(ownerIdForTeamName(teams, "Roy")).toBe("472206636534984704");
  });

  it("returns empty for an unknown name so the endpoint uses the session team", () => {
    expect(ownerIdForTeamName(teams, "Nobody")).toBe("");
    expect(ownerIdForTeamName(teams, "")).toBe("");
    expect(ownerIdForTeamName(null, "Roy")).toBe("");
  });
});

describe("formatStrengthValue", () => {
  it("renders an em-dash for an absent value, never a zero", () => {
    expect(formatStrengthValue(null)).toBe("—");
    expect(formatStrengthValue(undefined)).toBe("—");
    expect(formatStrengthValue(0)).toBe("0");
  });

  it("does not clamp", () => {
    expect(formatStrengthValue(146487)).toBe("146,487");
  });
});
