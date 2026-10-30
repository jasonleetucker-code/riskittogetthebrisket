/**
 * lib/roster-construction.js — the display-only helpers for /roster-construction.
 *
 * Pins: the request URL (no team = the gate probe), failure classification
 * (the gate vs a stated failure), the stale-response guard, every formatter
 * returning null (never "0") for a missing number, each rank travelling with
 * its own denominator, the lineup-basis label, the diagnosis state vocabulary
 * (NO ACTION is first-class, not-evaluated is not a pass), and that the bridge
 * and gate-hook endpoint literals match the lib's.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  ROSTER_CONSTRUCTION_ENDPOINT,
  buildRosterConstructionUrl,
  classifyRosterConstructionFailure,
  diagnosisState,
  evidenceRows,
  fmtCountOf,
  fmtPercentile,
  fmtPoints,
  fmtRank,
  fmtRatio,
  fmtShare,
  fmtSpells,
  fmtValue,
  fmtWeeks,
  humanizeCode,
  isStaleRosterConstructionPayload,
  lineupBasisText,
  mismatchRows,
  exclusionText,
  marginalUnavailableText,
  overallVerdictText,
  playerNameIndex,
  rulesEvaluated,
  rulesNotEvaluated,
  scenarioText,
  sortPositions,
} from "@/lib/roster-construction";
import { ROSTER_CONSTRUCTION_GATE_ENDPOINT } from "@/components/roster-construction/useRosterConstructionGate";

const load = (name) =>
  JSON.parse(
    fs.readFileSync(
      path.resolve(__dirname, `fixtures/roster-construction/${name}.json`),
      "utf-8",
    ),
  );
const fixture = load("golden-best-ball-v1");
const managed = load("golden-managed-v1");

describe("request", () => {
  it("builds the URL and omits what was not chosen", () => {
    expect(buildRosterConstructionUrl({ leagueKey: "dynasty_main" })).toBe(
      "/api/roster-construction?leagueKey=dynasty_main",
    );
    expect(
      buildRosterConstructionUrl({ leagueKey: "a b", rosterId: 4, season: "2025" }),
    ).toBe("/api/roster-construction?leagueKey=a%20b&season=2025&rosterId=4");
    expect(buildRosterConstructionUrl({})).toBe(ROSTER_CONSTRUCTION_ENDPOINT);
  });

  it("keeps the gate hook, the lib and the bridge on one endpoint", () => {
    expect(ROSTER_CONSTRUCTION_GATE_ENDPOINT).toBe(ROSTER_CONSTRUCTION_ENDPOINT);
    const bridge = fs.readFileSync(
      path.resolve(__dirname, "../app/api/roster-construction/route.js"),
      "utf-8",
    );
    expect(bridge).toContain("/api/roster-construction");
    // The bridge never echoes an exception message.
    expect(bridge).not.toMatch(/err\??\.message/);
  });
});

describe("failures", () => {
  it("reads the flag-off and missing-route answers as the closed gate", () => {
    expect(
      classifyRosterConstructionFailure(503, {
        error: "feature_disabled",
        flag: "roster_construction",
      }),
    ).toMatchObject({ kind: "disabled", flag: "roster_construction" });
    expect(classifyRosterConstructionFailure(404, {})).toMatchObject({
      kind: "disabled",
      code: "route_not_registered",
    });
  });

  it("names every other failure instead of hiding it", () => {
    expect(classifyRosterConstructionFailure(401, null).kind).toBe("auth");
    const notReady = classifyRosterConstructionFailure(503, {
      error: "data_not_ready",
      reason: "league_snapshot_mismatch",
    });
    expect(notReady.kind).toBe("unavailable");
    expect(notReady.message).toContain("not ready");
    expect(notReady.message).toContain("different league");
    expect(classifyRosterConstructionFailure(404, { error: "unknown_team" })).toMatchObject({
      kind: "degraded",
      message: expect.stringContaining("not in this league"),
    });
    expect(classifyRosterConstructionFailure(500, {}).message).toBe("Unavailable.");
  });
});

describe("stale-response guard", () => {
  it("rejects another league or team and accepts a match", () => {
    const p = { leagueKey: "dynasty_main", team: { rosterId: 4 } };
    expect(isStaleRosterConstructionPayload(p, { leagueKey: "dynasty_main", rosterId: "4" })).toBe(false);
    expect(isStaleRosterConstructionPayload(p, { leagueKey: "dynasty_new", rosterId: "4" })).toBe(true);
    expect(isStaleRosterConstructionPayload(p, { leagueKey: "dynasty_main", rosterId: "5" })).toBe(true);
    expect(isStaleRosterConstructionPayload(null, {})).toBe(true);
  });
});

describe("formatters never turn missing into 0", () => {
  it("returns null for absent and non-finite input", () => {
    for (const f of [fmtPoints, fmtValue, fmtShare, fmtRatio, fmtPercentile]) {
      expect(f(null)).toBeNull();
      expect(f(undefined)).toBeNull();
      expect(f("")).toBeNull();
      expect(f(Number.NaN)).toBeNull();
    }
    expect(fmtRank(null, 10)).toBeNull();
    expect(fmtCountOf({ value: null, of: 6 })).toBeNull();
    expect(fmtCountOf(null)).toBeNull();
    expect(fmtSpells([])).toBeNull();
    expect(fmtWeeks(null)).toBeNull();
  });

  it("renders a real zero as a zero", () => {
    expect(fmtPoints(0)).toBe("0.0");
    expect(fmtValue(0)).toBe("0");
    expect(fmtPercentile(0)).toBe("0th");
    expect(fmtCountOf({ value: 0, of: 6 })).toBe("0 of 6");
  });

  it("formats with units and ordinals", () => {
    expect(fmtPoints(212.44)).toBe("212.4");
    expect(fmtValue(9120.4)).toBe("9,120");
    expect(fmtShare(0.61)).toBe("61%");
    expect(fmtRatio(0.3)).toBe("0.30");
    expect(fmtPercentile(0.909)).toBe("91st");
    expect(fmtPercentile(0.667)).toBe("67th");
    expect(fmtPercentile(0.222)).toBe("22nd");
    expect(fmtPercentile(0.13)).toBe("13th");
    expect(fmtPercentile(1)).toBe("100th");
  });

  it("keeps each rank beside its own denominator", () => {
    expect(fmtRank(10, 10)).toBe("10 of 10");
    expect(fmtRank(2, 12)).toBe("2 of 12");
    expect(fmtRank(3, null)).toBe("3");
  });

  it("formats ownership spells and weeks", () => {
    expect(fmtSpells([{ fromWeek: 1, toWeek: 5 }, { fromWeek: 9, toWeek: 17 }])).toBe("Wk 1–5, 9–17");
    expect(fmtSpells([{ fromWeek: 3, toWeek: 3 }])).toBe("Wk 3");
    expect(fmtWeeks([6, 11])).toBe("Wk 6, 11");
  });
});

describe("labelled concepts", () => {
  it("labels best ball, manual leagues and an unknown mode distinctly", () => {
    expect(lineupBasisText({ rules: { lineupMode: "best_ball" } })).toMatchObject({
      label: "Best ball",
      hypothetical: false,
    });
    // The backend's own stamps (top level, also in rules).
    expect(lineupBasisText(fixture)).toMatchObject({ label: "Best ball", hypothetical: false });
    expect(lineupBasisText(managed)).toMatchObject({
      label: "Hypothetical optimal",
      hypothetical: true,
    });
    expect(fixture.lineupBasis).toBe("host_best_ball_optimal");
    expect(managed.lineupBasis).toBe("hypothetical_optimal");
    expect(managed.rules.lineupBasis).toBe("hypothetical_optimal");
    const manual = lineupBasisText({ rules: { lineupMode: "managed" } });
    expect(manual).toMatchObject({ label: "Hypothetical optimal", hypothetical: true });
    expect(manual.detail).toContain("not the lineups that were submitted");
    expect(lineupBasisText({ lineupBasis: "hypothetical_optimal" }).hypothetical).toBe(true);
    expect(lineupBasisText({})).toMatchObject({ label: "Unknown", hypothetical: false });
  });

  it("states the hypothetical scenario's assumptions", () => {
    expect(scenarioText("end_roster_plus_player")).toContain("ex-post");
    expect(scenarioText("end_roster_plus_player")).toContain("no roster-cap");
    expect(scenarioText(null)).toBeNull();
    expect(scenarioText("some_new_scenario")).toBe("Some new scenario");
  });
});

describe("diagnoses", () => {
  it("keeps NO ACTION, review, not-triggered and not-evaluated apart", () => {
    expect(diagnosisState({ status: "fired", verdict: "NO_ACTION" })).toEqual({ label: "No action", tone: "neutral" });
    expect(diagnosisState({ status: "fired", verdict: "REVIEW" }).label).toBe("Review");
    expect(diagnosisState({ status: "not_fired", verdict: "NO_ACTION" }).label).toBe("Not triggered");
    expect(diagnosisState({ status: "not_evaluated" }).label).toBe("Not evaluated");
    expect(diagnosisState(null).label).toBe("Unknown");
  });

  it("states NO ACTION as a valid overall result", () => {
    expect(overallVerdictText({ verdict: "NO_ACTION" }).note).toContain("valid result");
    expect(overallVerdictText({ verdict: "REVIEW" }).note).toContain("not a transaction");
    expect(overallVerdictText(null).label).toBe("Unknown");
  });

  it("shows every evidence key, rank pairs with denominators and names for ids", () => {
    const names = playerNameIndex([{ playerId: "1234", name: "Gavin Strand" }]);
    const rows = evidenceRows(
      { valueRank: [2, 12], holders: ["1234"], posture: "PUSH", flag: true, none: null },
      names,
    );
    const by = Object.fromEntries(rows.map((r) => [r.key, r.text]));
    expect(by.valueRank).toBe("2 of 12");
    expect(by.holders).toBe("Gavin Strand");
    expect(by.posture).toBe("PUSH");
    expect(by.flag).toBe("yes");
    expect(by.none).toBe("—");
    expect(evidenceRows(null)).toEqual([]);
  });
});

describe("golden fixtures", () => {
  it("orders positions canonically", () => {
    const shuffled = [...fixture.positions].reverse();
    expect(sortPositions(shuffled).map((p) => p.position)).toEqual([
      "QB", "RB", "WR", "TE", "K", "DL", "LB", "DB",
    ]);
  });

  it("pairs production and value without computing a gap", () => {
    const rows = mismatchRows(fixture.positions, fixture.diagnoses);
    const te = rows.find((r) => r.position === "TE");
    expect(te.production.rank).toBe(6);
    expect(te.production.of).toBe(6);
    expect(te.value.rank).toBe(1);
    expect(te.value.of).toBe(6);
    expect(te.diagnosis.rule).toBe("RC-D1");
    expect(te.diagnosis.verdict).toBe("NO_ACTION");
    expect(te).not.toHaveProperty("gap");
    // RC-D1 evaluated every position but fired only for TE.
    expect(rows.find((r) => r.position === "QB").diagnosis.status).toBe("not_fired");
  });

  it("reads the overall block's string reasons and derives the evaluated rules", () => {
    expect(rulesNotEvaluated(fixture.overall)).toEqual([
      { rule: "RC-D5", reason: "requires_forward_projection" },
      { rule: "RC-D7", reason: "trade_desk_dependency" },
    ]);
    expect(rulesEvaluated(fixture.overall, fixture.diagnoses)).toEqual([
      "RC-D1", "RC-D2", "RC-D3", "RC-D4", "RC-D6",
    ]);
    expect(rulesNotEvaluated({ rulesNotEvaluated: [{ rule: "X", reason: "y" }] })).toEqual([
      { rule: "X", reason: "y" },
    ]);
  });

  it("renders object evidence with player names and {value, of} counts", () => {
    const d1 = fixture.diagnoses.find((d) => d.rule === "RC-D1" && d.status === "fired");
    const rows = Object.fromEntries(
      evidenceRows(d1.evidence, playerNameIndex(fixture.players)).map((r) => [r.key, r.text]),
    );
    expect(rows.productionRank).toBe("6 of 6");
    expect(rows.valueRank).toBe("1 of 6");
    expect(rows.explainedBy).toBe("injured; developmental");
    expect(rows.holders).toContain("t1-te9 (");
    expect(rows.holders).toContain("starts 0 of 8");
  });

  it("carries a manual league's submitted points apart from the hypothetical optimum", () => {
    const qb = managed.positions.find((p) => p.position === "QB").production;
    expect(qb.points).toBe(267.48);
    expect(qb.observedSubmittedPoints).toBe(246.69);
    expect(fmtPoints(qb.observedSubmittedPoints)).toBe("246.7");
    // Best ball has no observed submitted lineup: absent, not 0.
    const bb = fixture.positions.find((p) => p.position === "QB").production;
    expect(bb.observedSubmittedPoints).toBeNull();
    expect(fmtPoints(bb.observedSubmittedPoints)).toBeNull();
    expect(managed.team.observedSubmittedWeeks).toBe(8);
  });

  it("states why a managed league's lineup marginal is unknown", () => {
    const p = managed.players[0];
    expect(p.marginalPoints.value).toBeNull();
    expect(marginalUnavailableText(p.marginalPoints)).toContain("best-ball leagues");
    expect(marginalUnavailableText(p.marginalPoints)).toContain("8 weeks");
    expect(marginalUnavailableText({})).toBeNull();
  });

  it("formats exclusions of every shape", () => {
    expect(exclusionText(3)).toBe("Week 3");
    expect(exclusionText({ rosterId: 7, week: 3, reason: "host_score_mismatch" })).toBe(
      "Roster 7, week 3: host score mismatch",
    );
    expect(exclusionText({ week: 18, reason: "not_final" })).toBe("week 18: not final");
  });

  it("humanizes codes", () => {
    expect(humanizeCode("requires_forward_projection")).toBe("Requires forward projection");
    expect(humanizeCode(null)).toBe("");
  });
});
