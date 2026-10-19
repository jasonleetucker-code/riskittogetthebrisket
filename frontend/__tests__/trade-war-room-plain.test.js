/**
 * The Trade War Room's plain-English formatters (owner directive 2026-10-19,
 * "Trade Calculator Clarity", Part 1).
 *
 * The rule under test: plain English changes the WORDS, never the NUMBERS.
 * Every sentence is checked against the raw payload field it formats, with
 * the rounding rules `lib/trade-war-room.js` declares (trade value to the
 * nearest whole point; points per week to one decimal, magnitude half away
 * from zero; percentages to the nearest whole percent).
 *
 * AJ_BROWN is a ROUTE-MOCK shaped payload (`fixtures/trade-war-room-mock/`)
 * carrying the values the owner observed on the live War Room (A.J. Brown in,
 * Justin Herbert out).  Nothing here asserts those numbers as expected
 * production output: every expectation is derived from the payload fields.
 * The other fixtures are REAL analyze output (`fixtures/trade-war-room/`).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  availabilityNote,
  formatPctPoint,
  formatPpg,
  formatSignedPpg,
  formatSignedValue,
  formatValue,
  roundTenth,
  unavailableText,
  UNAVAILABLE_WORDS,
  valueSummaryFromSideTotals,
  warRoomValueSummaryFor,
} from "@/lib/trade-war-room";
import { TRADE_VALUE_MODE, adjustedSideTotals, tradeEvaluationState } from "@/lib/trade-logic";
import {
  analysisErrorCode,
  analysisErrorText,
  argumentLine,
  assumptionLines,
  comparableReasonText,
  confidenceLimits,
  confidenceStatementText,
  confidenceSummary,
  decisionReasonSentences,
  decisionReasons,
  fitSentence,
  hasInternalIdentifier,
  incomingLineupSentences,
  lineupPointsSentence,
  listJoin,
  missingEvidenceText,
  packageModelLabel,
  plainLimit,
  projectionBasisText,
  reasonSentence,
  recordReasonText,
  rosterFit,
  rosterNoteLines,
  rosterSpotsLine,
  simulationExplanation,
  strategySentence,
  tradeValueSummary,
  uncertaintyLine,
  versionLabel,
  weeklyImpact,
} from "@/lib/trade-war-room-copy";

import AJ_BROWN from "./fixtures/trade-war-room-mock/aj-brown-herbert.json";
import CONSOLIDATION from "./fixtures/trade-war-room/consolidation.json";
import FORCED from "./fixtures/trade-war-room/forced-cut.json";
import PARTIAL from "./fixtures/trade-war-room/partial-coverage.json";
import ASSET_ONLY from "./fixtures/trade-war-room/asset-only.json";
import PARTIAL_LONG_TERM from "./fixtures/trade-war-room/partial-long-term.json";
import ROSTER_UNMEASURED from "./fixtures/trade-war-room/roster-unmeasured.json";
import ROSTER_ERROR from "./fixtures/trade-war-room/roster-error.json";
import STRATEGY_CUT_NO from "./fixtures/trade-war-room/strategy-cut-no.json";
import SUPERFLEX from "./fixtures/trade-war-room/superflex-holes.json";
import KTC_ROLLBACK from "./fixtures/trade-war-room/ktc-rollback.json";
import OUTGOING_NOT_HELD from "./fixtures/trade-war-room/outgoing-not-held.json";
import OVER_LIMIT from "./fixtures/trade-war-room/over-limit.json";

const market = (f) => f.analysis.lenses.market.detail;
const roster = (f) => f.analysis.lenses.roster;
const feas = (f) => f.analysis.lenses.feasibility;

describe("rounding rules — one rule, every display", () => {
  it("points per week: magnitude to one decimal, half away from zero, sign separate", () => {
    expect(roundTenth(5.65)).toBe(5.7);
    expect(roundTenth(-5.65)).toBe(5.7);
    expect(roundTenth(5.649)).toBe(5.6);
    expect(roundTenth(0.04)).toBe(0);
    expect(roundTenth(null)).toBeNull();
    expect(formatSignedPpg(-5.65)).toBe("−5.7");
    expect(formatSignedPpg(5.65)).toBe("+5.7");
    expect(formatSignedPpg(0.04)).toBe("±0.0");
    expect(formatPpg(-0.04)).toBe("0.0");
    expect(formatPpg(-1.25)).toBe("−1.3");
    expect(formatPpg(undefined)).toBeNull();
  });

  it("the sentence and the signed figure always carry the same digits", () => {
    for (let i = -2000; i <= 2000; i += 7) {
      const v = i / 100 + 0.005;
      const signed = formatSignedPpg(v);
      const sentence = lineupPointsSentence(v);
      const digits = signed.replace(/^[+−±]/, "");
      if (digits === "0.0") expect(sentence).toMatch(/about the same/);
      else expect(sentence).toContain(`about ${digits} ${v > 0 ? "more" : "fewer"} points`);
    }
  });

  it("trade value: nearest whole point; the gap clause matches the signed difference", () => {
    for (const gap of [-1194, -1194.5, -0.4, 0, 0.6, 1440, 12345.5]) {
      const s = tradeValueSummary({ receivingValue: 1000 + gap, sendingValue: 1000 });
      expect(s.difference).toBe(formatSignedValue(gap));
      const digits = s.difference.replace(/^[+−±]/, "");
      if (digits === "0") expect(s.sentence).toMatch(/the two sides are even/);
      else expect(s.sentence).toContain(`${digits} more than you`);
    }
  });
});

describe("tradeValueSummary — the market lens, in words", () => {
  it("AJ_BROWN: receive / send / difference straight from the payload, no VA", () => {
    const d = market(AJ_BROWN);
    expect(d.receivingValue - d.sendingValue).toBe(d.rawGap); // payload is self-consistent
    const s = tradeValueSummary(d);
    expect(s.receive).toBe(formatValue(d.receivingValue));
    expect(s.send).toBe(formatValue(d.sendingValue));
    expect(s.difference).toBe(formatSignedValue(d.vaAdjustedGap));
    expect(s.vaChanges).toBe(false);
    expect(s.sentence).toBe(
      `You receive ${formatValue(d.receivingValue)} and send ${formatValue(d.sendingValue)}, ` +
        `so you give ${formatValue(-d.vaAdjustedGap)} more than you get.`,
    );
    // The fixture's observed shape, as a sanity check on the derivation only.
    expect(s.sentence).toBe(
      "You receive 4,654 and send 5,848, so you give 1,194 more than you get.",
    );
  });

  it("CONSOLIDATION: the official gap is the VA-adjusted one; raw is named beside it", () => {
    const d = market(CONSOLIDATION);
    const s = tradeValueSummary(d);
    expect(s.vaChanges).toBe(true);
    expect(s.difference).toBe(formatSignedValue(d.vaAdjustedGap));
    expect(s.sentence).toBe(
      `You receive ${formatValue(d.receivingValue)} and send ${formatValue(d.sendingValue)}. ` +
        `After Value Adjustment, you get ${formatValue(d.vaAdjustedGap)} more than you give ` +
        `(${formatSignedValue(d.rawGap)} before it).`,
    );
  });

  it("missing totals are missing, never 0", () => {
    expect(tradeValueSummary(null)).toBeNull();
    expect(tradeValueSummary({ receivingValue: 10 })).toBeNull();
  });
});

describe("valueSummaryFromSideTotals — the calculator's totals for the selected side", () => {
  const totals = [
    { raw: 5848, adjustment: 0, adjusted: 5848 },
    { raw: 4654, adjustment: 0, adjusted: 4654 },
  ];
  it("the side the team GIVES is mySide", () => {
    expect(valueSummaryFromSideTotals(totals, 0)).toEqual({
      receivingValue: 4654,
      sendingValue: 5848,
      receivingValueAdjustment: 0,
      sendingValueAdjustment: 0,
      rawGap: -1194,
      vaAdjustedGap: -1194,
    });
    expect(valueSummaryFromSideTotals(totals, 1).vaAdjustedGap).toBe(1194);
  });
  it("carries the adjustment on whichever side received it", () => {
    const va = [
      { raw: 6000, adjustment: 0, adjusted: 6000 },
      { raw: 7000, adjustment: 440, adjusted: 7440 },
    ];
    const s = valueSummaryFromSideTotals(va, 0);
    expect(s.vaAdjustedGap).toBe(1440);
    expect(s.rawGap).toBe(1000);
    expect(tradeValueSummary(s).sentence).toContain("After Value Adjustment, you get 1,440 more");
  });
  it("refuses an unknown side or a non-number total (never 0)", () => {
    expect(valueSummaryFromSideTotals(totals, null)).toBeNull();
    expect(valueSummaryFromSideTotals([totals[0]], 0)).toBeNull();
    expect(valueSummaryFromSideTotals([totals[0], { raw: null }], 0)).toBeNull();
  });
});

describe("weeklyImpact — Impact on your team", () => {
  it("AJ_BROWN: 'about 5.7 fewer points per week' is the payload's ppg, rounded once", () => {
    const lens = roster(AJ_BROWN);
    const w = weeklyImpact(lens);
    expect(w.sentence).toBe(
      `Your projected lineup scores about ${roundTenth(lens.detail.ppg).toFixed(1)} fewer points per week.`,
    );
    expect(w.sentence).toBe("Your projected lineup scores about 5.7 fewer points per week.");
    expect(formatSignedPpg(lens.detail.ppg)).toBe("−5.7");
    expect(w.partial).toBe(false);
  });
  it("a forced cut says whether the cut changes the number", () => {
    const w = weeklyImpact(roster(FORCED));
    expect(w.note).toBe("The required cut does not change this.");
    const changed = structuredClone(roster(FORCED));
    changed.detail.ppgBeforeCleanup = 14.04;
    expect(weeklyImpact(changed).note).toBe("Before the required cut it would be about 14.0 more.");
  });
  it("partial coverage is shown, labelled, and never presented as complete", () => {
    const w = weeklyImpact(roster(PARTIAL));
    expect(w.partial).toBe(true);
    expect(w.sentence).toContain(`about ${roundTenth(roster(PARTIAL).detail.ppg).toFixed(1)} more`);
    expect(w.note).toMatch(/does not count toward the recommendation/);
    expect(w.note).toMatch(/\(a traded player has none\)/);
    // The count comes from the lens: never singular for three.
    const three = structuredClone(roster(PARTIAL));
    three.detail.coverage.tradedUnprojectedPlayerIds = ["a", "b", "c"];
    expect(weeklyImpact(three).note).toMatch(/\(3 traded players have none\)/);
  });
  it("an excluded or unavailable lens is words, not a number", () => {
    expect(weeklyImpact(roster(ASSET_ONLY))).toEqual({
      unavailable: "Not included in Asset-Only analysis",
    });
    expect(
      weeklyImpact({
        available: false,
        unavailableReason: "projection_basis_no_projection_snapshot",
      }),
    ).toEqual({ unavailable: "No league-scored projection snapshot yet" });
    // `roster_capacity.py`: "projection_basis_{reason or 'unavailable'}".
    expect(
      weeklyImpact({ available: false, unavailableReason: "projection_basis_unavailable" }),
    ).toEqual({ unavailable: "League-scored projections are not available" });
    expect(weeklyImpact({ available: true, detail: { ppg: null } }).unavailable).toBeTruthy();
  });
});

describe("rosterFit / fitSentence — Does it fit your roster?", () => {
  it("AJ_BROWN: a full roster that swaps one for one fits with no cut", () => {
    const f = rosterFit(feas(AJ_BROWN));
    expect(f.sentence).toBe("The trade fits. No player cut needed.");
    const d = feas(AJ_BROWN).detail;
    expect(f.spots).toBe(
      `Roster spots: ${d.sizeBefore} now, ${d.sizeAfter} after, limit ${d.rosterLimit}. Draft picks don't use roster spots.`,
    );
  });
  it("a forced cut names the backend's forced drops", () => {
    expect(rosterFit(feas(FORCED)).sentence).toBe(
      "The trade does not fit as built. You would need to cut Ghost Player.",
    );
  });
  it("every capacity state has words", () => {
    expect(fitSentence("fits_cleanly")).toBe("The trade fits. No player cut needed.");
    expect(fitSentence("uses_final_spot", [], { openSpotsBefore: 1 })).toMatch(
      /filling your last open/,
    );
    expect(fitSentence("uses_final_spot", [], { openSpotsBefore: 0 })).toBe(
      "The trade fits. No player cut needed.",
    );
    expect(fitSentence("cut_required", [])).toMatch(/A player would need to be cut/);
    // The count, when no named cut exists (an exhausted cut ladder).
    expect(fitSentence("cut_required", [], { cutsNeeded: 2 })).toBe(
      "The trade does not fit as built. 2 players would need to be cut.",
    );
    expect(fitSentence("cut_required", [], { cutsNeeded: 1 })).toMatch(/A player would need/);
    expect(fitSentence("cut_required", ["A", "B"], { tied: true })).toMatch(
      /cut A and B \(a close call between candidates\)/,
    );
    expect(fitSentence("resolves_overage")).toMatch(/back under the limit/);
    expect(fitSentence("reduces_overage")).toMatch(/reduces the overage/);
    expect(fitSentence("worsens_overage", ["X"])).toMatch(/adds to it\. You would need to cut X/);
    expect(fitSentence("overage_unchanged")).toMatch(/leaves that unchanged/);
    expect(fitSentence("mystery")).toBeNull();
  });
  it("a cut name that ends in its own period ends the sentence once", () => {
    expect(fitSentence("cut_required", ["Marvin Harrison Jr."])).toBe(
      "The trade does not fit as built. You would need to cut Marvin Harrison Jr.",
    );
    expect(fitSentence("cut_required", ["A.J. Brown", "Marvin Harrison Jr."])).toBe(
      "The trade does not fit as built. You would need to cut A.J. Brown and Marvin Harrison Jr.",
    );
    expect(fitSentence("worsens_overage", ["Odell Beckham Jr."])).toMatch(/Beckham Jr\.$/);
    expect(fitSentence("cut_required", ["Marvin Harrison Jr."], { tied: true })).toBe(
      "The trade does not fit as built. You would need to cut Marvin Harrison Jr. (a close call between candidates).",
    );
    // ...through the at-a-glance row and the Why list too.
    const lens = structuredClone(feas(FORCED));
    lens.detail.forcedDrops = [{ name: "Marvin Harrison Jr." }];
    expect(rosterFit(lens).sentence).not.toMatch(/\.\.$/);
    expect(
      reasonSentence({
        component: "feasibility",
        stance: "against",
        kind: "contextual",
        text: "Roster full — cut required: likely Marvin Harrison Jr.",
        evidence: { state: "cut_required", forcedDrops: ["Marvin Harrison Jr."] },
      }),
    ).toBe("The trade does not fit as built. You would need to cut Marvin Harrison Jr.");
  });
  it("an unknown limit or taxi uncertainty is said, not assumed", () => {
    expect(
      rosterFit({ available: false, unavailableReason: "uncertain", detail: {} }).unavailable,
    ).toMatch(/taxi squad/);
    expect(rosterFit(feas(ASSET_ONLY)).unavailable).toBe("Not included in Asset-Only analysis");
    expect(rosterSpotsLine({ rosterLimit: null })).toBeNull();
  });
});

/** Internal identifiers a person should never see: camelCase keys or ALL-CAPS codes. */
// Stricter than `hasInternalIdentifier` on purpose (no name exemptions): the
// fixtures carry no such names, so any match here is a real leak.
const INTERNAL = /[a-z][A-Z]|\b[A-Z]{3,}\b|[A-Za-z0-9]_[A-Za-z0-9]/;

/**
 * Confidence statements exactly as `src/trade/trade_decision.py::_confidence`
 * writes them: "<Level> confidence — limited by <axis>: <why>; <axis>: <why>",
 * with every reason string the backend can produce for a non-HIGH axis.
 */
const BACKEND_WHYS = {
  coverage: [
    "asset-only: roster and fit not considered",
    "no current-season roster effect to measure",
    "strategy defaulted: posture has no evidence",
    // the coverage axis may also carry the analysis' first uncertainty line
    // ...every line `analyze_trade.py::_uncertainty` can emit:
    "No league-scored projection for 1 traded player(s) — the roster lens abstains rather than count them as zero",
    "Roster impact not available (season_unresolved)",
    "Several cut candidates cost about the same; the likely cut is not certain",
    "Taxi occupancy is unknown, so the forced-cut count is a range",
    "Roster impact is shown before cleanup because the cut set is uncertain",
    "Low-confidence canonical value for A.J. Brown, Ghost Rookie",
    "Sources disagree on Justin Herbert",
    "Not on the board, so not priced: Mystery Man",
    "On the board but unpriced — unknown, not worth 0, so left out of the package math: RB Unpriced",
    "Counted as sent, but not taken off this roster because no specific owned pick was chosen: 2027 Round 1",
    "Not held by this team, so not counted as sent: 2027 1st (held by Rival)",
  ],
  margin: [
    "a near tie",
    "package gap SLIGHT EDGE",
    "package gap UNFAIR",
    "roster effect modest",
    "roster effect None",
    "deciding margin",
  ],
  agreement: ["value and roster disagree; your strategy decided"],
  assetEvidence: [
    "a traded asset has low or no confidence stamp",
    "sources disagree on a traded asset",
  ],
  precision: ["roster estimate moderately precise", "roster estimate imprecise"],
};
const statementOf = (level, pairs) =>
  `${level.charAt(0) + level.slice(1).toLowerCase()} confidence — limited by ` +
  pairs.map(([axis, why]) => `${axis}: ${why}`).join("; ");

describe("confidenceSummary — plain English, no internal identifiers", () => {
  it("every backend reason, alone and paired, reads without internal names or all-caps codes", () => {
    const pairs = Object.entries(BACKEND_WHYS).flatMap(([axis, whys]) =>
      whys.map((w) => [axis, w]),
    );
    for (const level of ["MEDIUM", "LOW"]) {
      for (const pair of pairs) {
        const c = { level, bottleneck: [pair[0]], statement: statementOf(level, [pair]) };
        const s = confidenceSummary(c);
        expect(s.level).toBe(level === "MEDIUM" ? "Medium confidence" : "Low confidence");
        expect(s.detail).toMatch(/^Limited because /);
        expect(s.detail).not.toMatch(INTERNAL);
        expect(s.detail).not.toMatch(/stamp|posture|lens/i);
      }
      // two axes, the second reason containing "; " (the backend's agreement why)
      const two = [
        ["assetEvidence", "a traded asset has low or no confidence stamp"],
        ["agreement", "value and roster disagree; your strategy decided"],
      ];
      const s = confidenceSummary({
        level,
        bottleneck: two.map((x) => x[0]),
        statement: statementOf(level, two),
      });
      expect(s.limits).toEqual([
        "a traded player's value rests on thin or missing evidence",
        "trade value and your lineup point different ways, so your strategy decided",
      ]);
    }
  });

  it("maps each known reason to its own plain clause", () => {
    expect(plainLimit("margin", "package gap SLIGHT EDGE")).toBe("the trade-value gap is small");
    expect(plainLimit("margin", "a near tie")).toBe("the trade is close to even");
    expect(plainLimit("precision", "roster estimate imprecise")).toBe(
      "the lineup simulation is imprecise",
    );
    expect(plainLimit("coverage", "asset-only: roster and fit not considered")).toMatch(
      /Asset-only analysis leaves out your roster and lineup/,
    );
  });

  it("maps every uncertainty line the analysis can emit to accurate plain wording", () => {
    const cases = [
      [
        "No league-scored projection for 1 traded player(s) — the roster lens abstains rather than count them as zero",
        "a traded player has no league-scored projection, so the lineup effect is left out rather than counted as zero",
      ],
      [
        "No league-scored projection for 2 traded player(s) — the roster lens abstains rather than count them as zero",
        "2 traded players have no league-scored projection, so the lineup effect is left out rather than counted as zero",
      ],
      [
        "Roster impact not available (season_unresolved)",
        "the impact on your lineup is not available (no current-season projection applies)",
      ],
      [
        "Several cut candidates cost about the same; the likely cut is not certain",
        "several cut candidates cost about the same, so the likely cut is not certain",
      ],
      [
        "Taxi occupancy is unknown, so the forced-cut count is a range",
        "who is on your taxi squad is unknown, so the number of forced cuts is a range",
      ],
      [
        "Roster impact is shown before cleanup because the cut set is uncertain",
        "the lineup impact is shown before any cut because which players would be cut is uncertain",
      ],
      [
        "Low-confidence canonical value for A.J. Brown, Ghost Rookie",
        "the values of A.J. Brown and Ghost Rookie rest on thin evidence",
      ],
      [
        // A name suffix keeps its period.
        "Low-confidence canonical value for Marvin Harrison Jr.",
        "the value of Marvin Harrison Jr. rests on thin evidence",
      ],
      ["Sources disagree on Justin Herbert", "the ranking sources disagree about Justin Herbert"],
      [
        "Sources disagree on Justin Herbert, DJ Moore, C.J. Stroud",
        "the ranking sources disagree about Justin Herbert, DJ Moore and C.J. Stroud",
      ],
      [
        "Not on the board, so not priced: Mystery Man",
        "Mystery Man is not on the board and has no value (unknown, not zero)",
      ],
      [
        "Not on the board, so not priced: Mystery Man, Ghost Rookie",
        "Mystery Man and Ghost Rookie are not on the board and have no value (unknown, not zero)",
      ],
      [
        "On the board but unpriced — unknown, not worth 0, so left out of the package math: RB Unpriced",
        "RB Unpriced has no value on the board (unknown, not zero) and is left out of the totals",
      ],
      [
        "On the board but unpriced — unknown, not worth 0, so left out of the package math: RB Unpriced, 2029 Round 4",
        "RB Unpriced and 2029 Round 4 have no value on the board (unknown, not zero) and are left out of the totals",
      ],
      [
        "Counted as sent, but not taken off this roster because no specific owned pick was chosen: 2027 Round 1",
        "2027 Round 1 is counted as sent but not taken off your roster, because no specific owned pick was chosen",
      ],
      [
        "Counted as sent, but not taken off this roster because no specific owned pick was chosen: 2027 Round 1, 2028 Round 2",
        "2027 Round 1 and 2028 Round 2 are counted as sent but not taken off your roster, because no specific owned picks were chosen",
      ],
      [
        "Not held by this team, so not counted as sent: 2027 1st (held by Rival)",
        "2027 1st (held by Rival) is not held by your team and is not counted as sent",
      ],
      [
        "Not held by this team, so not counted as sent: 2027 1st (held by Rival), 2028 2nd",
        "2027 1st (held by Rival) and 2028 2nd are not held by your team and are not counted as sent",
      ],
      [
        // An unknown reason code is left out, never shown or doubled.
        "Roster impact not available (some_new_reason)",
        "the impact on your lineup is not available",
      ],
      [
        "Roster impact not available (impact_missing)",
        "the impact on your lineup is not available (the lineup estimate came back without a number)",
      ],
    ];
    for (const [line, plain] of cases) expect(plainLimit("coverage", line)).toBe(plain);
    // ...and none of them reads "could not be measured": they were measured.
    for (const [line] of cases) {
      expect(plainLimit("coverage", line)).not.toMatch(/could not be measured/);
      expect(plainLimit("coverage", line)).not.toMatch(/unavailable \(/i);
      expect(hasInternalIdentifier(plainLimit("coverage", line))).toBe(false);
      expect(plainLimit("coverage", line)).not.toMatch(/\b(it|they) (has|have|is|are)\b/);
    }
    // The error reason the simulator writes when the roster simulation raises.
    expect(plainLimit("coverage", "Roster impact not available (error:KeyError)")).toBe(
      "the impact on your lineup is not available (could not be computed right now)",
    );
    // "not computed" only repeats "not available": left out.
    expect(plainLimit("coverage", "Roster impact not available (not_computed)")).toBe(
      "the impact on your lineup is not available",
    );
  });

  it("an unknown plain line is the backend's clause; one with an identifier is not", () => {
    // Inside "Limited because …": a leading ordinary word is lowercased, end
    // punctuation dropped -- but a leading name keeps its capitals.
    expect(plainLimit("coverage", "A brand-new caveat nobody mapped yet")).toBe(
      "a brand-new caveat nobody mapped yet",
    );
    expect(plainLimit("coverage", "Is the cut certain?")).toBe("is the cut certain");
    expect(plainLimit("coverage", "Justin Herbert has a new caveat.")).toBe(
      "Justin Herbert has a new caveat",
    );
    expect(plainLimit("coverage", "DJ Moore has a new caveat")).toBe("DJ Moore has a new caveat");
    expect(plainLimit("coverage", "Thin market for Marvin Harrison Jr.")).toBe(
      "thin market for Marvin Harrison Jr.",
    );
    expect(plainLimit("coverage", "Roster status pending (league_bundle_not_warm)")).toBe(
      "part of the analysis is uncertain (see Arguments, objections and uncertainty)",
    );
    expect(plainLimit("coverage", "rosterLens abstained")).toMatch(
      /part of the analysis is uncertain/,
    );
    expect(plainLimit("newAxis", "WHATEVER")).toMatch(/part of the evidence is weaker/);
    const s = confidenceSummary({
      level: "LOW",
      bottleneck: ["agreement"],
      statement: "Low — odd",
    });
    expect(s.detail).toBe("Limited because the evidence points different ways.");
  });

  it("the real fixture: plain level and limits; the verbatim statement stays for the methodology", () => {
    const c = CONSOLIDATION.analysis.decision.confidence;
    const s = confidenceSummary(c);
    expect(s.level).toBe("Medium confidence");
    expect(s.detail).toBe(
      "Limited because a traded player's value rests on thin or missing evidence and the lineup simulation is only moderately precise.",
    );
    expect(s.statement).toBe(c.statement);
  });

  it("HIGH says nothing more, except the execution gate; NOT ENOUGH EVIDENCE gives no level", () => {
    expect(
      confidenceSummary({
        level: "HIGH",
        bottleneck: [],
        statement: "High confidence — every axis is high.",
      }).detail,
    ).toBeNull();
    expect(
      confidenceSummary({
        level: "HIGH",
        bottleneck: [],
        statement: "High confidence — the trade cannot be executed as built.",
      }).detail,
    ).toBe("The trade cannot be made as built: no legal roster cleanup exists.");
    const nee = confidenceSummary(PARTIAL.analysis.decision.confidence);
    expect(nee.level).toBeNull();
    expect(nee.detail).toBe("No confidence level is given: important information is missing.");
  });
});

describe("hasInternalIdentifier — codes, never real names", () => {
  it("real player names are not identifiers", () => {
    for (const name of [
      "Henry To'oTo'o",
      "Kenneth Walker III",
      "Ray-Ray McCloud III",
      "D'Andre Swift",
      "JuJu Smith-Schuster",
      "DK Metcalf",
      "C.J. Stroud",
      "Amon-Ra St. Brown",
      "Marvin Harrison Jr.",
      "Odell Beckham Jr.",
      "Michael Pittman Jr.",
      "Ja'Marr Chase",
      "Wan'Dale Robinson",
      "DeVonta Smith",
      "Tee Higgins, A.J. Brown and T.J. Hockenson",
    ]) {
      expect(hasInternalIdentifier(name)).toBe(false);
      expect(hasInternalIdentifier(`the ranking sources disagree about ${name}`)).toBe(false);
    }
  });

  it("codes are identifiers: snake_case, camelCase keys, all-caps labels", () => {
    for (const code of [
      "not_computed",
      "(roster_capacity_unavailable)",
      "assetEvidence: thin",
      "rosterLens abstained",
      "package gap LOPSIDED",
      "contender (PUSH)",
      "MEDIUM",
      "Roster impact not available (error:KeyError)",
      "error:ValueError",
      "(error:HTTPError)",
      "the 'valueAdjustment' key",
      "band 'LOPSIDED'",
      "band \u2018LOPSIDED\u2019",
      'band "LOPSIDED"',
    ]) {
      expect(hasInternalIdentifier(code)).toBe(true);
    }
    // ...but a plain quoted word, an ordinary colon and a clock time are not.
    for (const plain of [
      "the 'value' gap",
      "limited by this: thin",
      "kickoff at 1:00",
      "O'Neil's",
    ]) {
      expect(hasInternalIdentifier(plain)).toBe(false);
    }
  });
});

describe("confidence clauses — one clause per fact", () => {
  // `trade_decision.py::_confidence`: assetEvidence says "sources disagree on a
  // traded asset" (sourceDisagreementAssets) while the coverage axis, otherwise
  // HIGH, carries the analysis' first uncertainty line naming the same asset.
  it("source disagreement said twice collapses to the named clause", () => {
    const pairs = [
      ["coverage", "Sources disagree on Justin Herbert"],
      ["assetEvidence", "sources disagree on a traded asset"],
    ];
    const s = confidenceSummary({
      level: "MEDIUM",
      bottleneck: pairs.map((x) => x[0]),
      statement: statementOf("MEDIUM", pairs),
    });
    expect(s.limits).toEqual(["the ranking sources disagree about Justin Herbert"]);
    expect(s.detail).toBe("Limited because the ranking sources disagree about Justin Herbert.");
  });

  it("thin evidence said twice collapses to the named clause, wherever it appears", () => {
    const pairs = [
      ["coverage", "Low-confidence canonical value for DJ Moore"],
      ["assetEvidence", "a traded asset has low or no confidence stamp"],
      ["precision", "roster estimate imprecise"],
    ];
    const s = confidenceSummary({
      level: "MEDIUM",
      bottleneck: pairs.map((x) => x[0]),
      statement: statementOf("MEDIUM", pairs),
    });
    expect(s.limits).toEqual([
      "the value of DJ Moore rests on thin evidence",
      "the lineup simulation is imprecise",
    ]);
    // Order-independent: a generic clause first is replaced in place by the named one.
    expect(
      confidenceSummary({
        level: "LOW",
        bottleneck: ["assetEvidence", "coverage"],
        statement: statementOf("LOW", [
          ["assetEvidence", "sources disagree on a traded asset"],
          ["coverage", "Sources disagree on Justin Herbert"],
        ]),
      }).limits,
    ).toEqual(["the ranking sources disagree about Justin Herbert"]);
  });

  it("different facts stay separate", () => {
    const pairs = [
      ["coverage", "Sources disagree on Justin Herbert"],
      ["assetEvidence", "a traded asset has low or no confidence stamp"],
    ];
    expect(
      confidenceSummary({
        level: "MEDIUM",
        bottleneck: pairs.map((x) => x[0]),
        statement: statementOf("MEDIUM", pairs),
      }).limits,
    ).toHaveLength(2);
  });
});

describe("partial projection coverage — the confidence line reads the roster lens", () => {
  // REAL analyze output (`partial-long-term`): long-term strategy, incoming
  // player unprojected.  The roster lens abstains (partial_projection_coverage),
  // `_roster_benefit` says not_applicable, and `_confidence` writes "no
  // current-season roster effect to measure" -- while the Impact row shows
  // the partial estimate.  The two must not contradict each other.
  const a = PARTIAL_LONG_TERM.analysis;
  const lens = a.lenses.roster;

  it("is real output in exactly that state", () => {
    expect(lens.unavailableReason).toBe("partial_projection_coverage");
    expect(a.decision.headline).not.toBe("NOT_ENOUGH_EVIDENCE");
    expect(a.decision.confidence.statement).toMatch(/no current-season roster effect to measure/);
  });

  it("says the lineup effect is left out because a traded player has no projection", () => {
    const n = lens.detail.coverage.tradedUnprojectedPlayerIds.length;
    expect(n).toBe(1);
    const s = confidenceSummary(a.decision.confidence, { rosterLens: lens });
    expect(s.limits[0]).toBe(
      "a traded player has no league-scored projection, so the lineup effect is left out rather than counted as zero",
    );
    expect(s.detail).toBe(
      "Limited because a traded player has no league-scored projection, so the lineup effect is left out rather than counted as zero, and a traded player's value rests on thin or missing evidence.",
    );
    expect(s.detail).not.toMatch(/no current-season lineup effect|could not be measured/);
    // ...and the Impact row it sits beside shows the labelled partial estimate.
    const impact = weeklyImpact(lens);
    expect(impact.partial).toBe(true);
    expect(impact.sentence).toBe(lineupPointsSentence(lens.detail.ppg));
  });

  it("counts the players; the offseason reasons keep 'nothing to measure'", () => {
    const why = "no current-season roster effect to measure";
    const two = {
      unavailableReason: "partial_projection_coverage",
      detail: { coverage: { state: "partial", tradedUnprojectedPlayerIds: ["a", "b"] } },
    };
    expect(plainLimit("coverage", why, { rosterLens: two })).toMatch(
      /^2 traded players have no league-scored projection/,
    );
    expect(
      plainLimit("coverage", why, {
        rosterLens: { unavailableReason: "partial_projection_coverage" },
      }),
    ).toMatch(/^some traded players have no league-scored projection/);
    expect(
      plainLimit("coverage", why, {
        rosterLens: { unavailableReason: "no_remaining_fantasy_weeks" },
      }),
    ).toBe("no fantasy weeks remain this season, so there is no lineup effect to measure");
    expect(plainLimit("coverage", why)).toBe("there is no current-season lineup effect to measure");
  });
});

describe("missingEvidenceText — what is missing, without reason codes", () => {
  // REAL analyze output (`roster-unmeasured`: the capacity check raised, so
  // the simulator wrote rosterCapacity {"unavailable": "KeyError"} and
  // rosterUtility "roster_capacity_unavailable"): both reason-code gaps
  // `trade_decision.py::_evidence_gaps` writes.
  const d = ROSTER_UNMEASURED.analysis.decision;

  it("words the real roster gaps from their evidence reason", () => {
    expect(ROSTER_UNMEASURED.rosterCapacity.unavailable).toBe("KeyError"); // the simulator's shape
    expect(d.missingEvidence.map((g) => g.text)).toEqual([
      "The roster effect could not be measured (roster_capacity_unavailable).",
      "Whether the trade fits your roster is unknown (KeyError).",
    ]); // the leak, as emitted
    expect(d.missingEvidence.map(missingEvidenceText)).toEqual([
      "The effect on your lineup could not be measured (your roster limit could not be checked).",
      "Whether the trade fits your roster is unknown (could not be computed right now).",
    ]);
    // The evidence gate's reason carries the first gap's text and evidence, no code.
    expect(d.primaryReason.code).toBeUndefined();
    expect(reasonSentence(d.primaryReason)).toBe(
      "The effect on your lineup could not be measured (your roster limit could not be checked).",
    );
    // "(not computed)" would only repeat "could not be measured": left out.
    expect(
      missingEvidenceText({
        code: "roster_unknown",
        text: "The roster effect could not be measured (not_computed).",
        evidence: { reason: "not_computed" },
      }),
    ).toBe("The effect on your lineup could not be measured.");
  });

  it("the simulator's error:<Exception> reason reads in words (real output)", () => {
    const e = ROSTER_ERROR.analysis.decision;
    expect(e.missingEvidence[0].evidence.reason).toBe("error:KeyError");
    expect(missingEvidenceText(e.missingEvidence[0])).toBe(
      "The effect on your lineup could not be measured (could not be computed right now).",
    );
    expect(reasonSentence(e.primaryReason)).toBe(
      "The effect on your lineup could not be measured (could not be computed right now).",
    );
    expect(uncertaintyLine(ROSTER_ERROR.analysis.uncertainty[0])).toBe(
      "The impact on your lineup is not available (could not be computed right now).",
    );
  });

  it("every feasibility reason the backend can put in a gap reads plainly", () => {
    for (const [reason, words] of [
      ["unknown_limit", "this league's roster limit is unknown"],
      ["roster_settings_missing", "this league's roster settings are missing"],
      ["roster_capacity_unavailable", "your roster limit could not be checked"],
    ]) {
      const gap = {
        code: "roster_limit_unknown",
        text: `Whether the trade fits your roster is unknown (${reason}).`,
        evidence: { reason },
      };
      expect(missingEvidenceText(gap)).toBe(
        `Whether the trade fits your roster is unknown (${words}).`,
      );
    }
    // A reason with no words is left out -- never shown raw.
    expect(
      missingEvidenceText({
        code: "roster_unknown",
        text: "The roster effect could not be measured (brand_new_reason).",
        evidence: { reason: "brand_new_reason" },
      }),
    ).toBe("The effect on your lineup could not be measured.");
  });

  it("plain gaps stay verbatim; names are names; an identifier falls back", () => {
    expect(
      missingEvidenceText({
        code: "forced_drop_unpriced",
        text: "1 forced cut(s) have no value, so the cost of the cut is unknown.",
        evidence: { count: 1 },
      }),
    ).toBe("1 forced cut(s) have no value, so the cost of the cut is unknown.");
    // A team display name is a name, even one a code detector would flag.
    expect(
      missingEvidenceText({
        code: "unheld_assets",
        text: "Your team does not hold: 2027 Round 1 (held by team_rocket)",
        evidence: {},
      }),
    ).toBe("Your team does not hold: 2027 Round 1 (held by team_rocket).");
    expect(missingEvidenceText({ code: "new_gap", text: "Something about rosterLens" })).toBe(
      "Some information the recommendation needs is missing.",
    );
    expect(missingEvidenceText({ code: "new_gap", text: "" })).toBe(
      "Some information the recommendation needs is missing.",
    );
    // A bare one-word code is not a sentence.
    expect(missingEvidenceText({ code: "new_gap", text: "blocked" })).toBe(
      "Some information the recommendation needs is missing.",
    );
    expect(missingEvidenceText({ code: "new_gap", text: "Value check: error:ValueError" })).toBe(
      "Some information the recommendation needs is missing.",
    );
    expect(missingEvidenceText(null)).toBeNull();
  });

  it("the uncertainty list: every known line in plain words, one period each", () => {
    const [line] = ROSTER_UNMEASURED.analysis.uncertainty;
    expect(line).toBe("Roster impact not available (roster_capacity_unavailable)");
    expect(uncertaintyLine(line)).toBe(
      "The impact on your lineup is not available (your roster limit could not be checked).",
    );
    expect(uncertaintyLine("Roster impact not available (not_computed)")).toBe(
      "The impact on your lineup is not available.",
    );
    // "the roster lens abstains" is not for people.
    expect(uncertaintyLine(PARTIAL.analysis.uncertainty[0])).toBe(
      "A traded player has no league-scored projection, so the lineup effect is left out rather than counted as zero.",
    );
    expect(uncertaintyLine("Sources disagree on Justin Herbert")).toBe(
      "The ranking sources disagree about Justin Herbert.",
    );
    expect(uncertaintyLine("Sources disagree on Marvin Harrison Jr.")).toBe(
      "The ranking sources disagree about Marvin Harrison Jr.",
    );
    // Unrecognised: verbatim when plain, a generic sentence when it is a code.
    expect(uncertaintyLine("A brand-new caveat")).toBe("A brand-new caveat.");
    expect(uncertaintyLine("cache_miss")).toBe("Part of the analysis could not be checked.");
    expect(uncertaintyLine("KeyError")).toBe("Part of the analysis could not be checked.");
    expect(uncertaintyLine("")).toBeNull();
  });

  it("argument lines word an all-caps injury designation and end in one period", () => {
    // `analyze_trade.py::_availability_reason`: "listed <DESIGNATION> this week".
    expect(
      argumentLine("WR Buf Star is unavailable for all 3 remaining weeks (listed OUT this week)"),
    ).toBe("WR Buf Star is unavailable for all 3 remaining weeks (listed as out this week).");
    expect(
      argumentLine("X is unavailable for all 2 remaining weeks (listed QUESTIONABLE this week)"),
    ).toBe("X is unavailable for all 2 remaining weeks (listed as questionable this week).");
    expect(argumentLine("X is unavailable for all 2 remaining weeks (listed IR this week)")).toBe(
      "X is unavailable for all 2 remaining weeks (on injured reserve this week).",
    );
    expect(argumentLine("Roster full — 1 cut required: likely Marvin Harrison Jr.")).toBe(
      "Roster full — 1 cut required: likely Marvin Harrison Jr.",
    );
    for (const code of [
      "OUT",
      "QUESTIONABLE",
      "DOUBTFUL",
      "IR",
      "PUP",
      "NA",
      "SUS",
      "DNR",
      "COV",
    ]) {
      const out = argumentLine(
        `X is unavailable for all 2 remaining weeks (listed ${code} this week)`,
      );
      expect(out).not.toMatch(/\b[A-Z]{2,}\b/);
    }
    expect(argumentLine("")).toBeNull();
  });
});

describe("reason list and confidence edge cases", () => {
  const main = {
    component: "objectiveValue",
    stance: "for",
    kind: "independent",
    text: "+1,440 package value",
    evidence: { band: { level: "slight" } },
  };
  const counter = {
    component: "rosterBenefit",
    stance: "against",
    kind: "independent",
    text: "-3.0 points",
    evidence: { magnitude: "modest" },
  };

  it("a main reason with nothing plain to say drops the list; a counter is never alone", () => {
    const silentMain = { component: "mystery", stance: "for", text: "rosterLens_gate" };
    expect(
      decisionReasonSentences({
        headline: "YES",
        primaryReason: silentMain,
        mainCounterargument: counter,
        reasons: [silentMain, counter],
      }),
    ).toEqual([]);
    const ok = decisionReasonSentences({
      headline: "YES",
      primaryReason: main,
      mainCounterargument: counter,
      reasons: [main, counter],
    });
    expect(ok.map((r) => r.role)).toEqual(["main", "counter"]);
    expect(ok.every((r) => typeof r.sentence === "string" && r.sentence)).toBe(true);
  });

  it("an unknown one-word feasibility state is a code, never shown", () => {
    for (const [text, state] of [
      ["blocked", "blocked"],
      ["uncertain", undefined],
    ]) {
      expect(
        reasonSentence({
          component: "feasibility",
          stance: "against",
          kind: "contextual",
          text,
          evidence: { state, forcedDrops: [] },
        }),
      ).toBe("Fitting it on your roster counts against it.");
    }
  });

  it("a named low-confidence clause leaves no unrated asset out", () => {
    const pairs = [
      ["coverage", "Low-confidence canonical value for DJ Moore"],
      ["assetEvidence", "a traded asset has low or no confidence stamp"],
    ];
    const c = {
      level: "MEDIUM",
      bottleneck: ["coverage", "assetEvidence"],
      statement: statementOf("MEDIUM", pairs),
    };
    const lens = (low, unstamped) => ({
      detail: {
        lowConfidenceAssets: low.map((name) => ({ name, confidenceBucket: "low" })),
        unstampedAssets: unstamped,
      },
    });
    // Another asset has no stamp at all: it keeps a clause of its own.
    expect(
      confidenceSummary(c, { evidenceLens: lens(["DJ Moore"], ["Ghost Rookie"]) }).limits,
    ).toEqual([
      "the value of DJ Moore rests on thin evidence",
      "another traded asset's value has no evidence rating",
    ]);
    expect(
      confidenceSummary(c, { evidenceLens: lens(["DJ Moore"], ["Ghost Rookie", "2029 Round 4"]) })
        .limits[1],
    ).toBe("2 other traded assets' values have no evidence rating");
    // No unrated asset beyond the named one: the named clause covers it all.
    expect(confidenceSummary(c, { evidenceLens: lens(["DJ Moore"], []) }).limits).toEqual([
      "the value of DJ Moore rests on thin evidence",
    ]);
    // Without the generic reason there is nothing to keep.
    const onlyNamed = {
      level: "MEDIUM",
      bottleneck: ["coverage"],
      statement: statementOf("MEDIUM", [pairs[0]]),
    };
    expect(
      confidenceSummary(onlyNamed, { evidenceLens: lens(["DJ Moore"], ["Ghost Rookie"]) }).limits,
    ).toEqual(["the value of DJ Moore rests on thin evidence"]);
  });
});

describe("reason-to-words — one whitelist owner", () => {
  // Every unavailable / exclusion reason the backend can put on the packet,
  // enumerated from its source modules.
  const ENUMERATED = {
    "src/api/gameplan.py": [
      "roster_snapshot_missing",
      "starter_slots_missing",
      "roster_snapshot_empty",
      "league_bundle_not_warm",
    ],
    "src/api/trade_simulator.py": [
      "team_not_in_league_bundle",
      "capacity_uncertain",
      "no_team_selected",
      "roster_capacity_unavailable",
    ],
    "src/trade/roster_capacity.py": [
      "counterparty_unresolved",
      "assessment_failed",
      "starter_slots_unresolved",
      "season_unresolved",
      "projection_basis_unavailable",
      "projection_basis_no_projection_snapshot",
      "projection_basis_scoring_card_missing",
      "drop_requirement_undetermined",
      "overage_undetermined",
      "trade_adds_no_release",
    ],
    "src/roster_intel/best_ball_utility.py": [
      "starter_slots_unresolved",
      "no_remaining_fantasy_weeks",
      "scoring_card_missing",
      "no_projection_snapshot",
    ],
    "src/trade/analyze_trade.py + trade_decision.py": [
      "no_priced_assets_either_side",
      "not_computed",
      "impact_missing",
      "partial_projection_coverage",
      "no_team_selected_or_uncomputable",
      "unknown_limit",
      "uncertain",
      "trade_ledger_not_built",
      "trade_ledger_unavailable",
      "no_identifiable_assets",
      "comparables_error",
      "asset_only_mode",
      "not_wired",
    ],
  };

  it("every enumerated reason has its own plain words", () => {
    for (const [source, reasons] of Object.entries(ENUMERATED)) {
      for (const reason of reasons) {
        expect(UNAVAILABLE_WORDS[reason], `${source}: ${reason}`).toBeTruthy();
        const words = unavailableText(reason);
        expect(hasInternalIdentifier(words), `${reason} -> ${words}`).toBe(false);
        expect(words).not.toMatch(/_/);
      }
    }
  });

  it("an exception name, an error: code or any unlisted code is never shown", () => {
    // `trade_simulator.py`: rosterCapacity / finalRosterSimulation carry the
    // bare exception class name; posture and rosterUtility carry error:<Exc>.
    for (const reason of [
      "KeyError",
      "ZeroDivisionError",
      "HTTPError",
      "error:KeyError",
      "error:ValueError",
      "some_new_reason",
      "projection_basis_new_reason",
    ]) {
      const words = unavailableText(reason);
      expect(words, reason).not.toContain(reason);
      expect(hasInternalIdentifier(words)).toBe(false);
    }
    expect(unavailableText("KeyError")).toBe("Could not be computed right now");
    expect(unavailableText("error:KeyError")).toBe("Could not be computed right now");
    // An unlisted code that is not failure-shaped reads neutrally.
    expect(unavailableText("some_new_reason")).toBe("Not available");
    expect(unavailableText("projection_basis_new_reason")).toBe(
      "League-scored projections are not available",
    );
    // The fit row on the real failure shape.
    expect(rosterFit(feas(ROSTER_UNMEASURED)).unavailable).toBe("Could not be computed right now");
  });

  it("exception class names are identifiers; ordinary words are not", () => {
    for (const code of [
      "KeyError",
      "ZeroDivisionError",
      "HTTPError",
      "UserWarning",
      "RuntimeException",
    ]) {
      expect(hasInternalIdentifier(code), code).toBe(true);
    }
    for (const plain of ["An error occurred", "Error", "a warning", "Warning signs"]) {
      expect(hasInternalIdentifier(plain), plain).toBe(false);
    }
  });
});

describe("methodology — the engine's own record, in plain words", () => {
  const d = CONSOLIDATION.analysis.decision;

  it("the confidence statement keeps its level and axes, in words", () => {
    expect(d.confidence.statement).toMatch(/assetEvidence: .*; precision: /); // as emitted
    expect(confidenceStatementText(d.confidence)).toBe(
      "Medium confidence — limited by asset evidence (a traded player's value rests on thin or missing evidence) and precision (the lineup simulation is only moderately precise).",
    );
    expect(
      confidenceStatementText({
        level: "HIGH",
        bottleneck: [],
        statement: "High confidence — every axis is high.",
      }),
    ).toBe("High confidence — every part of the evidence is strong.");
    expect(
      confidenceStatementText({
        level: "HIGH",
        bottleneck: [],
        statement: "High confidence — the trade cannot be executed as built.",
      }),
    ).toBe("High confidence — the trade cannot be made as built: no legal roster cleanup exists.");
    expect(confidenceStatementText(PARTIAL.analysis.decision.confidence)).toBe(
      "No confidence level is given: important information is missing.",
    );
    for (const f of [CONSOLIDATION, ASSET_ONLY, AJ_BROWN, PARTIAL_LONG_TERM]) {
      expect(hasInternalIdentifier(confidenceStatementText(f.analysis.decision.confidence))).toBe(
        false,
      );
    }
  });

  it("each recorded reason keeps its numbers; band and posture labels read in words", () => {
    expect(d.reasons.map((r) => recordReasonText(r, { strategy: d.strategy }))).toEqual([
      "+1,440 package value for you after Value Adjustment — 19.4% of the larger package: a lopsided gap.",
      "+1.5 expected best-ball points per week in your legal lineup.",
      "Fits your roster without a cut.",
      "Strategy: Win now. Your competitive posture is Push (contender), so the strategy is win now.",
    ]);
    // Every posture code and band label the backend writes.
    expect(
      recordReasonText({
        text: "Your competitive posture has no measured evidence (HOLD), so the strategy is balanced.",
      }),
    ).toBe(
      "Your competitive posture has no measured evidence (Hold), so the strategy is balanced.",
    );
    for (const [label, words] of [
      ["SLIGHT EDGE", "a slight edge"],
      ["UNFAIR", "an unfair gap"],
      ["LOPSIDED", "a lopsided gap"],
      ["FAIR", "within the fair band"],
    ]) {
      expect(
        recordReasonText({
          component: "objectiveValue",
          text: `+300 package value for you after Value Adjustment — 4.0% of the larger package, ${label} band`,
        }),
      ).toMatch(new RegExp(`: ${words}\\.$`));
    }
    // A raw state code falls back to the plain reason sentence.
    expect(
      recordReasonText({
        component: "feasibility",
        stance: "against",
        text: "brand_new_state",
        evidence: { state: "brand_new_state", forcedDrops: [] },
      }),
    ).toBe("Fitting it on your roster counts against it.");
    for (const f of [CONSOLIDATION, AJ_BROWN, PARTIAL_LONG_TERM, ASSET_ONLY]) {
      const dec = f.analysis.decision;
      for (const r of dec.reasons) {
        expect(hasInternalIdentifier(recordReasonText(r, { strategy: dec.strategy }))).toBe(false);
      }
    }
  });

  it("the projection basis reads in words; source ids are never shown", () => {
    // `best_ball_utility.py::_ensemble_index`: the production basis shape.
    expect(
      projectionBasisText({
        source: "ros_ensemble:PRESEASON_FULL_SEASON:equal_family_mean",
        description:
          "full-season projection per game, rescored through this league's exact scoring card; not a weekly projection",
        pointsModel: { source: "calibrated" },
      }),
    ).toBe(
      "Projections: full-season projection per game, rescored through this league's exact scoring card; not a weekly projection; week-to-week variance: calibrated to past weekly scoring.",
    );
    expect(projectionBasisText({ source: "X_Y", description: "see tests/trade/x_y.py" })).toBe(
      "Projections: league-scored per-game projections.",
    );
  });

  it("version ids read as version numbers, never as ids", () => {
    expect(versionLabel("fairness_bands_v1")).toBe("version 1");
    expect(versionLabel("trade_decision_v2")).toBe("version 2");
    expect(versionLabel("weird")).toBeNull();
  });

  it("legacy gap words in Points in favor use the canonical band vocabulary", () => {
    const band = market(CONSOLIDATION).band;
    expect(band.level).toBe("lopsided");
    expect(CONSOLIDATION.analysis.reasonsFor[0]).toMatch(/\(stretch gap\)$/); // as emitted
    expect(argumentLine(CONSOLIDATION.analysis.reasonsFor[0], { band })).toBe(
      "+1,440 package value after Value Adjustment (a lopsided gap).",
    );
    expect(argumentLine("x (stretch gap)", { band: { level: "unfair" } })).toBe(
      "x (an unfair gap).",
    );
    expect(argumentLine("x (lean gap)", { band })).toBe("x (a slight edge).");
    expect(argumentLine("x (even gap)")).toBe("x (within the fair band).");
    expect(argumentLine("x (stretch gap)")).toBe("x (an unfair or lopsided gap).");
  });
});

describe("a strategy-decided answer says what pushed toward it", () => {
  it("REAL strategy-decided NO: the forced cut that turned the value negative is at a glance", () => {
    const a = STRATEGY_CUT_NO.analysis;
    const d = a.decision;
    expect([d.headline, d.deciding, d.primaryReason.component]).toEqual([
      "NO",
      "strategy",
      "strategy",
    ]);
    expect(a.lenses.market.detail.vaAdjustedGap).toBeGreaterThan(0); // the value row reads "+"
    const items = decisionReasonSentences(d, { analysis: a });
    expect(items.map((r) => r.role)).toEqual(["main", "supportAgainst", "counter"]);
    expect(items[1].sentence).toBe(
      "After the forced cut of RB Bench One (worth 3,000), you come out 1,426 behind on trade value — an unfair gap against you (13.8% of the larger package).",
    );
    // Every number is the decision's own.
    const ev = d.reasons.find((r) => r.component === "objectiveValue").evidence;
    expect([ev.forcedReleaseCost, ev.netGap]).toEqual([3000, -1426]);
    expect(items[2].sentence).toBe("Your projected weekly lineup gets much stronger.");
  });

  it("REAL strategy-decided YES: the factor for it is shown too", () => {
    const d = SUPERFLEX.analysis.decision;
    expect([d.headline, d.deciding]).toEqual(["YES", "strategy"]);
    const items = decisionReasonSentences(d, { analysis: SUPERFLEX.analysis });
    expect(items.map((r) => r.role)).toEqual(["main", "supportFor", "counter"]);
    expect(items[1].sentence).toMatch(
      /^You come out ahead on trade value — a lopsided gap in your favor/,
    );
  });

  it("a value-decided answer is unchanged: no extra line", () => {
    const items = decisionReasonSentences(CONSOLIDATION.analysis.decision, {
      analysis: CONSOLIDATION.analysis,
    });
    expect(items.map((r) => r.role)).not.toContain("supportFor");
    expect(items.map((r) => r.role)).not.toContain("supportAgainst");
  });
});

describe("comparable trades, package model, assumptions, roster notes", () => {
  it("every comparable reason line reads plainly; format dispositions are worded", () => {
    // `comparable_trades.py::_reasons`: every line it can write.
    const cases = [
      ["Format: NATIVE_COMPARABLE", "Format: the same league format as yours"],
      [
        "Format: VALIDATED_TRANSFORMABLE",
        "Format: a different format that can be translated to yours",
      ],
      ["Format: BROAD_CONTEXT", "Format: a different or unknown format, shown for context only"],
      [
        "Format: TARGET_UNSUPPORTED",
        "this trade couldn't be matched cleanly, so it is not priced for your league",
      ],
      ["1 days ago", "1 day ago"],
      ["Format: SOMETHING_NEW", "Format: not stated"],
      [
        "Format comparability unknown for this league",
        "Format comparability unknown for this league",
      ],
      ["Same asset: A.J. Brown, $5 FAAB", "Same asset: A.J. Brown, $5 FAAB"],
      ["Same pick round: 2027 Round 1 +2 more", "Same pick round: 2027 Round 1 +2 more"],
      ["Moved the other way: Marvin Harrison Jr.", "Moved the other way: Marvin Harrison Jr."],
      [
        "Shape not compared until both sides have assets",
        "Shape not compared until both sides have assets",
      ],
      ["3-team trade; yours is 2-for-1", "3-team trade; yours is 2-for-1"],
      ["Same 2-for-1 shape", "Same 2-for-1 shape"],
      ["2-for-1 shape vs your 1-for-1", "2-for-1 shape vs your 1-for-1"],
      ["today", "today"],
      ["12 days ago", "12 days ago"],
    ];
    for (const [line, words] of cases) {
      expect(comparableReasonText(line), line).toBe(words);
      // Asset labels after "Same asset:" are names ("$5 FAAB" included).
      const prose = /^(?:Same asset|Same pick round|Moved the other way): /.test(words)
        ? words.slice(0, words.indexOf(": "))
        : words;
      expect(hasInternalIdentifier(prose)).toBe(false);
    }
    expect(comparableReasonText("scoreBreakdown: 0.4")).toBeNull();
    expect(comparableReasonText("")).toBeNull();
  });

  it("REAL KTC rollback: the package model by its display name", () => {
    const pm = KTC_ROLLBACK.analysis.lenses.market.detail.packageModel;
    expect(pm.label).toMatch(/port of keeptradecut\.com/); // as emitted
    expect(packageModelLabel(pm)).toBe("KTC adjustment method");
    expect(packageModelLabel(market(CONSOLIDATION).packageModel)).toBe(
      "Chase Upside adjustment (geometric)",
    );
    expect(packageModelLabel({ family: "new", label: "Some (x = 1)" })).toBe(
      "the active package adjustment",
    );
  });

  it("the simulation's assumptions follow the actual points model", () => {
    const lines = roster(CONSOLIDATION).detail.assumptions;
    expect(lines[0]).toMatch(/league's calibrated per-position variance/); // as emitted
    const basis = roster(CONSOLIDATION).detail.basis;
    expect(basis.pointsModel.source).toBe("fallback-constants");
    const plain = assumptionLines(lines, basis);
    expect(plain[0]).toBe(
      "Each simulated week is drawn around each player's per-game projection, with default per-position variance, not yet calibrated to this league; players are treated as independent.",
    );
    expect(plain.join(" ")).not.toMatch(/league's calibrated/);
    expect(assumptionLines(lines, { pointsModel: { source: "calibrated" } })[0]).toMatch(
      /with per-position variance calibrated to past weekly scoring;/,
    );
    expect(plain.slice(1)).toEqual([
      "Injury / availability probabilities are not modelled.",
      "Bye weeks are not modelled.",
      "The lineup is re-solved exactly for every simulated week (best ball).",
    ]);
  });

  it("every roster-capacity note is a plain line, or already said elsewhere", () => {
    // Every note `roster_capacity.py` and `displacement.py` can write.
    const NOTES = [
      ["league roster size is not configured — capacity is UNKNOWN, not unlimited", null, null],
      [
        "league carries 5 taxi slot(s) and this source does not say which roster members occupy them — Sleeper lists taxi players inside `players`, so active occupancy is a RANGE and the capacity conclusion is partial",
        "Your league has 5 taxi spots and who fills them is not known, so your roster count is a range.",
        null,
      ],
      [
        "1 rostered player(s) did not join to the board — they still occupy a roster spot and are still cut candidates, but their value is unknown",
        null,
        "One of your rostered players is not on the value board: that player still takes a roster spot and could still be cut, but the value is unknown.",
      ],
      [
        "3 rostered player(s) did not join to the board — they still occupy a roster spot and are still cut candidates, but their value is unknown",
        null,
        "3 of your rostered players are not on the value board: they still take roster spots and could still be cut, but their values are unknown.",
      ],
      [
        "no waiver-level values available — cut costs fall back to raw board value",
        null,
        "No waiver-wire values are available, so a cut costs the player's full board value.",
      ],
      [
        "starter slots unavailable (KeyError) — cut ladder unguarded",
        "This league's starting slots could not be read, so a forced cut may be a player your lineup needs.",
        null,
      ],
      [
        "no starter slots resolved for this league — the cut ladder is not lineup-guarded, so a forced drop may be a player the lineup needs",
        "This league's starting slots could not be read, so a forced cut may be a player your lineup needs.",
        null,
      ],
      [
        "no starter slots configured for this league — cut ladder built without a lineup-feasibility guard",
        "This league's starting slots could not be read, so a forced cut may be a player your lineup needs.",
        null,
      ],
      [
        "positional scarcity unavailable (KeyError) — multiplier inert",
        null,
        "Position scarcity is not available, so cut costs do not account for how scarce each position is.",
      ],
      [
        "1 outgoing player(s) are not on this roster and free no spot: Marvin Harrison Jr.",
        "Marvin Harrison Jr. is not on your roster, so sending that player frees no roster spot.",
        null,
      ],
      [
        "2 outgoing player(s) are not on this roster and free no spot: A, B",
        "A and B are not on your roster, so sending them frees no roster spot.",
        null,
      ],
      [
        "roster is ALREADY 2 over the 58-man limit before this trade — the drops below include getting back to legal size",
        "Your roster is already 2 over the 58-player limit before this trade.",
        null,
      ],
      [
        "every forced drop scored the same effective cut cost, so the cut ladder's own rung order carried no priority — these are ordered by release cost instead",
        null,
        null,
      ],
      [
        "cut ladder offers 1 release(s) but 2 are needed — every remaining player is required to fill a starting slot, so no legal path back to roster size was modelled",
        "Only 1 cut is possible but 2 are needed: every remaining player is needed to fill a starting slot.",
        null,
      ],
      [
        "cut ladder offers 0 release(s) but 2 are needed — every remaining player is required to fill a starting slot, so no legal path back to roster size was modelled",
        "No cut is possible, but 2 are needed: every remaining player is needed to fill a starting slot.",
        null,
      ],
      ["roster is empty — no cut ladder", "Your roster is empty, so there is no one to cut.", null],
      [
        "roster cannot fill 2 starting slot(s) before any cut — ladder measured against that baseline",
        "Your roster cannot fill 2 starting slots even before any cut.",
        null,
      ],
      [
        "cut ladder truncated at 30 rungs — deeper cuts exist but are far past any budget-feasible plan",
        null,
        null,
      ],
      ["some brand_new note — UNKNOWN", null, null],
    ];
    for (const [note, fit, detail] of NOTES) {
      const out = rosterNoteLines([note]);
      expect(out.fit, note).toEqual(fit ? [fit] : []);
      expect(out.detail, note).toEqual(detail ? [detail] : []);
      for (const line of [...out.fit, ...out.detail])
        expect(hasInternalIdentifier(line)).toBe(false);
    }
    // REAL: an outgoing player this roster does not hold, and a roster
    // already over its limit.
    expect(rosterNoteLines(feas(OUTGOING_NOT_HELD).detail.notes).fit).toEqual([
      "RB Buf Depth is not on your roster, so sending that player frees no roster spot.",
    ]);
    // REAL over-limit packet: a cut is shown, so it includes getting back to size.
    expect(feas(OVER_LIMIT).detail.forcedDrops.length).toBeGreaterThan(0);
    expect(rosterNoteLines(feas(OVER_LIMIT).detail.notes, feas(OVER_LIMIT).detail).fit).toEqual([
      "Your roster is already 1 over the 8-player limit before this trade; the cuts shown include getting back under it.",
    ]);
    // No cut, and the trade brings it back under: never "the cuts shown".
    const over =
      "roster is ALREADY 2 over the 58-man limit before this trade — the drops below include getting back to legal size";
    expect(
      rosterNoteLines([over], { state: "resolves_overage", forcedDrops: [], requiresDrops: false })
        .fit,
    ).toEqual([
      "Your roster is already 2 over the 58-player limit; this trade brings it back under.",
    ]);
    // The taxi range only beside an answer it actually leaves uncertain.
    const taxi = (n) =>
      `league carries ${n} taxi slot(s) and this source does not say which roster members occupy them — Sleeper lists taxi players inside \`players\`, so active occupancy is a RANGE and the capacity conclusion is partial`;
    expect(rosterNoteLines([taxi(5)], { certainty: "exact", requiresDrops: false }).fit).toEqual(
      [],
    );
    expect(rosterNoteLines([taxi(1)], { certainty: "partial", requiresDrops: null }).fit).toEqual([
      "Your league has 1 taxi spot and who fills it is not known, so your roster count is a range.",
    ]);
  });

  it("one remaining week reads as one week", () => {
    expect(
      argumentLine("WR X is unavailable for all 1 remaining weeks (listed OUT this week)"),
    ).toBe("WR X is unavailable for the 1 remaining week (listed as out this week).");
    expect(
      argumentLine("X would reach the lineup in only 40% of the 1 remaining weeks simulated"),
    ).toBe("X would reach the lineup in only 40% of the 1 remaining week simulated.");
    expect(argumentLine("X is unavailable for all 3 remaining weeks (bye week)")).toBe(
      "X is unavailable for all 3 remaining weeks (bye week).",
    );
    expect(availabilityNote({ availability: { weeks: 1, eligibleWeeks: 0 } })).toBe(
      "Out the 1 remaining week",
    );
    expect(
      availabilityNote({ availability: { weeks: 1, eligibleWeeks: 1, unavailableWeeks: 1 } }),
    ).toBe("out 1 of 1 week");
    expect(availabilityNote({ availability: { weeks: 4, eligibleWeeks: 0 } })).toBe(
      "Out all 4 remaining weeks",
    );
  });
});

describe("strategySentence — from the structured fields, never the all-caps codes", () => {
  it("each strategy source", () => {
    const d = CONSOLIDATION.analysis.decision.strategy;
    expect(strategySentence(d)).toBe("Win now — your team reads as a contender.");
    expect(
      strategySentence({
        source: "user",
        label: "Long-term value",
        inferredClassification: "PUSH",
      }),
    ).toBe("Long-term value — your choice; your team reads as a contender.");
    expect(strategySentence({ source: "posture_no_evidence", label: "Balanced" })).toMatch(
      /no evidence yet, so balanced is used/,
    );
    expect(strategySentence({ source: "posture_unknown" })).toMatch(/could not be read/);
    expect(strategySentence({ source: "asset_only" })).toBe("Not used in Asset-only analysis.");
    for (const cls of ["PUSH", "HOLD", "RETOOL", "REBUILD"]) {
      expect(
        strategySentence({ source: "posture", label: "Balanced", inferredClassification: cls }),
      ).not.toMatch(INTERNAL);
    }
  });
});

describe("warRoomValueSummaryFor — exactly the calculator headline's totals (fix 1)", () => {
  // Real board-shaped rows through the canonical dispatch the headline uses.
  const priced = (name, v) => ({ name, rankDerivedValue: v, values: { full: v } });
  const unpricedRow = (name) => ({ name, rankDerivedValue: null, values: { full: 0 } });
  const headline = (sides) => ({
    totals: adjustedSideTotals(sides[0].assets, sides[1].assets, TRADE_VALUE_MODE),
    evaluation: tradeEvaluationState(sides),
  });

  it("an asset the board does not price but the user priced counts at the user's value, never 0", () => {
    // Side A (the team's) gives a priced player; Side B gives a board-unpriced
    // rookie the user typed a value for (the override sits on the row, as
    // `sidesWithOverrides` builds it).
    const sides = [
      { assets: [priced("Mine", 3000)] },
      { assets: [{ ...unpricedRow("Rookie"), customValue: 2500 }] },
    ];
    const { totals, evaluation } = headline(sides);
    expect(evaluation.state).toBe("complete");
    const s = warRoomValueSummaryFor({
      sideTotals: totals,
      mySide: 0,
      evaluation,
      overrideCount: 1,
    });
    expect(s.receivingValue).toBe(2500);
    expect(s.receivingValue).toBe(totals[1].raw);
    expect(s.sendingValue).toBe(totals[0].raw);
    expect(s.vaAdjustedGap).toBe(totals[1].adjusted - totals[0].adjusted);
    expect(s.overridesApplied).toBe(true);
  });

  it("an asset with no board value and no override gives no total — it is named instead", () => {
    const sides = [{ assets: [priced("Mine", 3000)] }, { assets: [unpricedRow("Ghost Rookie")] }];
    const { totals, evaluation } = headline(sides);
    expect(warRoomValueSummaryFor({ sideTotals: totals, mySide: 0, evaluation })).toEqual({
      unpriced: ["Ghost Rookie"],
    });
  });

  it("nothing to summarise without a team side or with an empty trade", () => {
    const sides = [{ assets: [priced("Mine", 3000)] }, { assets: [priced("Theirs", 2000)] }];
    const { totals, evaluation } = headline(sides);
    expect(warRoomValueSummaryFor({ sideTotals: totals, mySide: null, evaluation })).toBeNull();
    expect(
      warRoomValueSummaryFor({
        sideTotals: totals,
        mySide: 0,
        evaluation: tradeEvaluationState([{ assets: [] }, { assets: [] }]),
      }),
    ).toBeNull();
    expect(
      warRoomValueSummaryFor({ sideTotals: totals, mySide: 0, evaluation }).overridesApplied,
    ).toBe(false);
  });
});

describe("decisionReasons / reasonSentence — two distinct reasons, the backend's priority", () => {
  it("CONSOLIDATION: primary reason first, then the next independent component", () => {
    const d = CONSOLIDATION.analysis.decision;
    const picked = decisionReasons(d);
    expect(picked.map((p) => p.role)).toEqual(["main", "also"]);
    expect(picked[0].reason).toBe(d.primaryReason);
    expect(picked[1].reason.component).toBe("rosterBenefit");
    expect(picked[0].reason.component).not.toBe(picked[1].reason.component);
  });
  it("a named counterargument takes the second slot", () => {
    const d = structuredClone(CONSOLIDATION.analysis.decision);
    d.mainCounterargument = d.reasons.find((r) => r.component === "rosterBenefit");
    expect(decisionReasons(d)[1]).toEqual({ role: "counter", reason: d.mainCounterargument });
  });
  it("nothing is invented: one reason when only one exists; none for NOT ENOUGH EVIDENCE", () => {
    const gate = {
      component: "feasibility",
      stance: "against",
      kind: "gate",
      text: "No legal roster cleanup exists for this trade",
    };
    expect(decisionReasons({ headline: "NO", primaryReason: gate, reasons: [gate] })).toEqual([
      { role: "main", reason: gate },
    ]);
    expect(decisionReasons(PARTIAL.analysis.decision)).toEqual([]);
    // a neutral context line (a clean fit, the strategy echo) is not a reason
    const d = ASSET_ONLY.analysis.decision;
    expect(decisionReasons(d)).toHaveLength(1);
  });
  it("words each component from its stance and band, keeping the band's percentage", () => {
    const d = CONSOLIDATION.analysis.decision;
    const pct = d.primaryReason.evidence.band.relativePct.toFixed(1);
    expect(reasonSentence(d.primaryReason)).toBe(
      `You come out ahead on trade value — a lopsided gap in your favor (${pct}% of the larger package).`,
    );
    const aj = AJ_BROWN.analysis.decision;
    expect(reasonSentence(aj.primaryReason)).toMatch(
      /^You come out behind on trade value — a lopsided gap against you/,
    );
    expect(reasonSentence(aj.reasons.find((r) => r.component === "rosterBenefit"))).toBe(
      "Your projected weekly lineup gets much weaker.",
    );
    expect(reasonSentence({ component: "rosterBenefit", stance: "neutral", evidence: {} })).toBe(
      "Your projected weekly lineup barely changes.",
    );
    expect(
      reasonSentence({
        component: "objectiveValue",
        stance: "neutral",
        evidence: { band: { level: "fair" } },
      }),
    ).toBe("Trade value is close to even.");
    const strategy = d.reasons.find((r) => r.component === "strategy");
    expect(reasonSentence(strategy, { strategy: d.strategy })).toBe(
      "Your strategy decided it: win now — your team reads as a contender.",
    );
    // A known component never falls back to the backend's raw text (it
    // carries all-caps band labels): an unrecognised band still reads plainly.
    expect(
      reasonSentence({
        component: "objectiveValue",
        stance: "for",
        text: "+1,440 package value — LOPSIDED band",
        evidence: { band: { level: "mystery" } },
      }),
    ).toBe("You come out ahead on trade value.");
    for (const r of d.reasons) {
      expect(reasonSentence(r, { strategy: d.strategy })).not.toMatch(INTERNAL);
    }
    // unrecognised but plain -> the backend's words, ending in one period
    expect(reasonSentence({ component: "evidence", text: "Missing X" })).toBe("Missing X.");
    expect(reasonSentence({ component: "evidence", text: "Missing X." })).toBe("Missing X.");
    // The execution gate keeps the backend's own plain sentence
    // (`trade_decision.py` decide(): component feasibility, kind gate, no state).
    const gate = {
      component: "feasibility",
      stance: "against",
      kind: "gate",
      text: "No legal roster cleanup exists for this trade",
      evidence: { ladderExhausted: true },
    };
    // ...with the final period the backend's text lacks.
    expect(reasonSentence(gate)).toBe("No legal roster cleanup exists for this trade.");
    // A gate without usable text: the fixed sentence, never empty.
    expect(reasonSentence({ ...gate, text: "" })).toBe(
      "No legal roster cleanup exists for this trade.",
    );
    expect(
      reasonSentence({
        component: "feasibility",
        stance: "neutral",
        text: "Plain backend line",
        evidence: {},
      }),
    ).toBe("Plain backend line.");
    // An unknown roster state: the backend's text is the raw state code
    // (`trade_decision.py` `.get(state, state)`), never shown; the fixed
    // sentence by stance instead.
    for (const [stance, words] of [
      ["against", "Fitting it on your roster counts against it."],
      ["for", "Fitting it on your roster counts in its favor."],
      ["neutral", "Fitting it on your roster does not push either way."],
    ]) {
      expect(
        reasonSentence({
          component: "feasibility",
          stance,
          kind: "contextual",
          text: "brand_new_state",
          evidence: { state: "brand_new_state", forcedDrops: [] },
        }),
      ).toBe(words);
    }
    // Nothing plain to say -> null (the War Room skips it; never "Biggest reason:" alone).
    expect(reasonSentence({ component: "mystery", text: "rosterLens_gate" })).toBeNull();
    expect(reasonSentence({ component: "mystery", text: "" })).toBeNull();
    expect(reasonSentence(null)).toBeNull();
  });
});

describe("expandable detail", () => {
  it("AJ_BROWN: the incoming player's lineup share, from the payload", () => {
    const p = roster(AJ_BROWN).detail.players.find((x) => x.role === "incoming");
    expect(incomingLineupSentences(roster(AJ_BROWN).detail)).toEqual([
      `${p.name} makes your best lineup in ${formatPctPoint(p.lineupEntryPctAfter)} of simulated weeks.`,
    ]);
    expect(incomingLineupSentences(roster(AJ_BROWN).detail)[0]).toBe(
      "A.J. Brown makes your best lineup in 61% of simulated weeks.",
    );
    expect(
      incomingLineupSentences({
        players: [{ role: "incoming", name: "X", lineupEntryPctAfter: null }],
      }),
    ).toEqual([]);
  });

  it("keeps the availability note beside the lineup share whenever the backend gives one (P0)", () => {
    const players = [
      {
        role: "incoming",
        name: "Hurt Receiver",
        lineupEntryPctAfter: 41.6,
        availability: { weeks: 12, eligibleWeeks: 9, unavailableWeeks: 3, uncertainWeeks: 1 },
      },
      {
        role: "incoming",
        name: "Season Over",
        lineupEntryPctAfter: 0,
        availability: { weeks: 12, eligibleWeeks: 0, unavailableWeeks: 12 },
      },
    ];
    expect(incomingLineupSentences({ players })).toEqual([
      "Hurt Receiver makes your best lineup in 42% of simulated weeks (availability: out 3 of 12 weeks, uncertain 1).",
      "Season Over makes your best lineup in 0% of simulated weeks (availability: out all 12 remaining weeks).",
    ]);
  });
  it("the simulation error is explained as a model estimate, with the payload's numbers", () => {
    const d = roster(AJ_BROWN).detail;
    const text = simulationExplanation(d);
    expect(text).toMatch(/^This is a model estimate, not a guarantee\./);
    expect(text).toContain(`${d.basis.draws} weeks of the league's remaining weeks 7–18`);
    expect(text).toContain(
      `about ±${roundTenth(d.standardError).toFixed(1)} points per week (its standard error)`,
    );
    expect(text).toMatch(/not errors in the projections themselves/);
    expect(simulationExplanation({ standardError: 0.01 })).toContain("±0.1 or less");
  });
  it("errors are words a person can act on", () => {
    expect(analysisErrorText("timeout")).toBe("it took too long to finish");
    expect(analysisErrorText("invalid_analysis")).toMatch(/did not match this trade/);
    expect(analysisErrorText("HTTP 503")).toBe("the server had a problem");
    // data_not_ready: loading (Retry helps) vs the scoring-identity gate (it cannot).
    expect(analysisErrorCode(503, { error: "data_not_ready" })).toBe("data_not_ready");
    expect(
      analysisErrorCode(503, {
        error: "data_not_ready",
        message: "Rankings are not compatible: league 'x' scores players differently.",
        scoringFingerprint: "sf1:a",
        loadedScoringFingerprint: "sf1:b",
      }),
    ).toBe("scoring_incompatible");
    expect(analysisErrorText("scoring_incompatible")).toBe(
      "this league's scoring isn't compatible with the loaded rankings, so a personalized analysis isn't available",
    );
    expect(analysisErrorCode(413, { error: "Request body too large." })).toBe(
      "Request body too large.",
    );
    expect(analysisErrorText("Request body too large.")).toBe("this trade is too large to analyze");
    expect(analysisErrorText("HTTP 413")).toBe("this trade is too large to analyze");
    expect(analysisErrorCode(502, null)).toBe("HTTP 502");
    expect(analysisErrorText("TypeError: Failed to fetch")).toBe("the connection failed");
    expect(analysisErrorText("boom")).toBe("something went wrong");
    // Every error the analyze route and the league resolver return
    // (server.py `_build_trade_simulation`, `_resolve_league_for_request`,
    // the scoring identity gate), in words, never the code.
    const ROUTE_ERRORS = {
      auth_required: "your session has expired — sign in again",
      "No data available yet.": "the server has no player data yet",
      invalid_body: "the server could not read the request",
      data_not_ready: "this league's data is still loading on the server — try again shortly",
      team_not_found: "your team was not found in this league",
      unknown_league: "this league is not available",
      inactive_league: "this league is not available",
      no_leagues_configured: "no league is set up on the server",
    };
    for (const [code, words] of Object.entries(ROUTE_ERRORS)) {
      expect(analysisErrorText(code), code).toBe(words);
    }
    for (const [status, words] of [
      ["HTTP 502", "the server had a problem"],
      ["HTTP 500", "the server had a problem"],
      ["HTTP 404", "the server refused the request"],
      ["HTTP 401", "your session has expired — sign in again"],
      ["HTTP 429", "too many requests were made — wait a moment, then retry"],
    ]) {
      expect(analysisErrorText(status), status).toBe(words);
    }
    for (const odd of ["Unexpected token < in JSON", { error: "x" }, "rate_limited", "KeyError"]) {
      expect(analysisErrorText(odd)).toBe("something went wrong");
    }
    expect(listJoin(["a", "b", "c"])).toBe("a, b and c");
  });
});

describe("no all-caps labels (owner directive 2026-10-19)", () => {
  it("the War Room stylesheet uppercases nothing and neutralises the legacy global th rule", () => {
    const css = fs.readFileSync(
      path.resolve(__dirname, "../components/trade/war-room.module.css"),
      "utf8",
    );
    expect(css).not.toMatch(/text-transform:\s*uppercase/);
    // globals.css still styles every bare `th` uppercase + sticky; the War
    // Room's tables must undo it rather than inherit it.
    const tableTh = css.slice(css.indexOf(".table th,"));
    expect(tableTh).toMatch(/text-transform:\s*none/);
    expect(tableTh).toMatch(/position:\s*static/);
  });
});
