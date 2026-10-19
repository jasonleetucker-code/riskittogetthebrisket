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
  formatPctPoint,
  formatPpg,
  formatSignedPpg,
  formatSignedValue,
  formatValue,
  roundTenth,
  valueSummaryFromSideTotals,
  warRoomValueSummaryFor,
} from "@/lib/trade-war-room";
import { TRADE_VALUE_MODE, adjustedSideTotals, tradeEvaluationState } from "@/lib/trade-logic";
import {
  analysisErrorText,
  confidenceLimits,
  confidenceSummary,
  decisionReasons,
  fitSentence,
  incomingLineupSentences,
  lineupPointsSentence,
  listJoin,
  plainLimit,
  reasonSentence,
  rosterFit,
  rosterSpotsLine,
  simulationExplanation,
  strategySentence,
  tradeValueSummary,
  weeklyImpact,
} from "@/lib/trade-war-room-copy";

import AJ_BROWN from "./fixtures/trade-war-room-mock/aj-brown-herbert.json";
import CONSOLIDATION from "./fixtures/trade-war-room/consolidation.json";
import FORCED from "./fixtures/trade-war-room/forced-cut.json";
import PARTIAL from "./fixtures/trade-war-room/partial-coverage.json";
import ASSET_ONLY from "./fixtures/trade-war-room/asset-only.json";

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
    expect(fitSentence("cut_required", ["A", "B"], { tied: true })).toMatch(
      /cut A and B \(a close call between candidates\)/,
    );
    expect(fitSentence("resolves_overage")).toMatch(/back under the limit/);
    expect(fitSentence("reduces_overage")).toMatch(/reduces the overage/);
    expect(fitSentence("worsens_overage", ["X"])).toMatch(/adds to it\. You would need to cut X/);
    expect(fitSentence("overage_unchanged")).toMatch(/leaves that unchanged/);
    expect(fitSentence("mystery")).toBeNull();
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
const INTERNAL = /[a-z][A-Z]|\b[A-Z]{3,}\b/;

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
        "the value of A.J. Brown, Ghost Rookie rests on thin evidence",
      ],
      ["Sources disagree on Justin Herbert", "the ranking sources disagree about Justin Herbert"],
      [
        "Not on the board, so not priced: Mystery Man",
        "Mystery Man is not on the board, so it has no value (unknown, not zero)",
      ],
      [
        "On the board but unpriced — unknown, not worth 0, so left out of the package math: RB Unpriced",
        "RB Unpriced has no value on the board (unknown, not zero), so it is left out of the totals",
      ],
      [
        "Counted as sent, but not taken off this roster because no specific owned pick was chosen: 2027 Round 1",
        "2027 Round 1 is counted as sent but not taken off your roster, because no specific owned pick was chosen",
      ],
      [
        "Not held by this team, so not counted as sent: 2027 1st (held by Rival)",
        "2027 1st (held by Rival) is not held by your team, so it is not counted as sent",
      ],
    ];
    for (const [line, plain] of cases) expect(plainLimit("coverage", line)).toBe(plain);
    // ...and none of them reads "could not be measured": they were measured.
    for (const [line] of cases)
      expect(plainLimit("coverage", line)).not.toMatch(/could not be measured/);
  });

  it("an unknown plain line is the backend's sentence verbatim; one with an identifier is not", () => {
    expect(plainLimit("coverage", "A brand-new caveat nobody mapped yet")).toBe(
      "A brand-new caveat nobody mapped yet",
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
    // unrecognised -> the backend's words, verbatim
    expect(reasonSentence({ component: "evidence", text: "Missing X" })).toBe("Missing X");
    // The execution gate keeps the backend's own plain sentence
    // (`trade_decision.py` decide(): component feasibility, kind gate, no state).
    const gate = {
      component: "feasibility",
      stance: "against",
      kind: "gate",
      text: "No legal roster cleanup exists for this trade",
      evidence: { ladderExhausted: true },
    };
    expect(reasonSentence(gate)).toBe("No legal roster cleanup exists for this trade");
    expect(
      reasonSentence({
        component: "feasibility",
        stance: "neutral",
        text: "Plain backend line",
        evidence: {},
      }),
    ).toBe("Plain backend line");
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
    expect(analysisErrorText("HTTP 503")).toBe("the server had a problem (HTTP 503)");
    expect(analysisErrorText("TypeError: Failed to fetch")).toBe("the connection failed");
    expect(analysisErrorText("boom")).toBe("an error occurred (boom)");
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
