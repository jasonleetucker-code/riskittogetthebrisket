/**
 * trade-war-room-copy — the Trade War Room's plain-English presentation
 * (owner directive 2026-10-19, "Trade Calculator Clarity", Part 1).
 *
 * DISPLAY ONLY, like `lib/trade-war-room.js`.  Every sentence here is built
 * from fields `POST /api/trade/analyze` already published -- the decision's
 * own reasons, stances, band levels and confidence; the lenses' totals,
 * points and roster states.  Nothing here decides, weighs, re-ranks or
 * re-derives a recommendation: `analysis.decision` is the ONLY verdict, and
 * the War Room renders its `headlineText` verbatim.
 *
 * Numbers keep their exact values: each sentence formats the payload field
 * with the rounding rules declared in `lib/trade-war-room.js` (trade value to
 * the nearest whole point; points per week to one decimal, magnitude rounded
 * half away from zero).  `trade-war-room-plain.test.js` pins every sentence
 * against the raw payload fields.
 *
 * Missing stays missing: a function returns null (or `{ unavailable }`) and
 * the caller renders words, never 0.
 *
 * Kept out of `lib/trade-war-room.js` on purpose: that module is imported by
 * the /trade page chunk (side resolution), this one only by the War Room's
 * own lazy chunk, so the copy never weighs on the page's bundle budget.
 */

import {
  availabilityNote,
  formatPctPoint,
  formatSignedValue,
  formatValue,
  roundTenth,
  simulatedWeeksLabel,
  unavailableText,
} from "./trade-war-room";

// ── Small helpers ─────────────────────────────────────────────────────────

function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

/** "A", "A and B", "A, B and C". */
export function listJoin(items) {
  const xs = (items || []).map((x) => String(x || "").trim()).filter(Boolean);
  if (xs.length <= 1) return xs[0] || "";
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

/** One decimal of a points figure, with the same rounding everywhere. */
function tenth(v) {
  const mag = roundTenth(v);
  return mag == null ? null : mag.toFixed(1);
}

// ── Confidence ────────────────────────────────────────────────────────────

const CONFIDENCE_LEVEL_WORDS = {
  HIGH: "High confidence",
  MEDIUM: "Medium confidence",
  LOW: "Low confidence",
};

/**
 * The backend's per-axis reasons out of its confidence statement
 * ("Medium confidence — limited by assetEvidence: …; precision: …"), with the
 * axis keys -- internal names -- left out.  The bottleneck keys and their
 * order come from the same packet, so the parse is exact or it refuses: an
 * unexpected shape returns [] and the caller shows the statement verbatim.
 */
export function confidenceLimits(statement, bottleneck) {
  if (typeof statement !== "string" || !Array.isArray(bottleneck) || !bottleneck.length) return [];
  const marker = "limited by ";
  const at = statement.indexOf(marker);
  if (at < 0) return [];
  const tail = statement.slice(at + marker.length);
  const out = [];
  let pos = 0;
  for (let i = 0; i < bottleneck.length; i += 1) {
    const key = `${bottleneck[i]}: `;
    if (tail.indexOf(key, pos) !== pos) return [];
    const start = pos + key.length;
    let end = tail.length;
    if (i + 1 < bottleneck.length) {
      end = tail.indexOf(`; ${bottleneck[i + 1]}: `, start);
      if (end < 0) return [];
      pos = end + 2;
    }
    const why = tail.slice(start, end).trim();
    if (!why) return [];
    out.push(why);
  }
  return out;
}

/**
 * What each limiting axis means, in plain English.  Keyed on the reason
 * strings `src/trade/trade_decision.py::_confidence` writes (matched by their
 * stable openings, so wording tweaks that keep the opening still map); an
 * unrecognised reason falls back to the axis' own plain sentence -- never to
 * the raw string, which carries internal axis names and all-caps band labels.
 */
const LIMIT_WORDS = [
  // ── fixed reasons per axis (`trade_decision.py::_confidence`) ──
  [/^asset-only/i, () => "this Asset-only analysis leaves out your roster and lineup"],
  [
    /^no current-season roster effect/i,
    () => "there is no current-season lineup effect to measure",
  ],
  [
    /^strategy defaulted/i,
    () => "your strategy fell back to balanced because your team's direction has no evidence yet",
  ],
  [/^a near tie/i, () => "the trade is close to even"],
  [/^package gap/i, () => "the trade-value gap is small"],
  [/^roster effect/i, () => "the change to your lineup is modest"],
  [/^deciding margin/i, () => "the deciding margin is modest"],
  [
    /^value and roster disagree/i,
    () => "trade value and your lineup point different ways, so your strategy decided",
  ],
  [
    /low or no confidence stamp/i,
    () => "a traded player's value rests on thin or missing evidence",
  ],
  [
    /^sources disagree on a traded asset/i,
    () => "the ranking sources disagree about a traded player's value",
  ],
  [/moderately precise/i, () => "the lineup simulation is only moderately precise"],
  [/^roster estimate imprecise/i, () => "the lineup simulation is imprecise"],
  // ── the coverage axis may carry the analysis' first uncertainty line
  //    (`analyze_trade.py::_uncertainty`); every line it can emit ──
  [
    /^No league-scored projection for (\d+) traded player/i,
    (m) =>
      `${m[1] === "1" ? "a traded player has" : `${m[1]} traded players have`} no league-scored projection, so the lineup effect is left out rather than counted as zero`,
  ],
  [
    /^Roster impact not available \(([^)]*)\)/i,
    (m) => {
      const why = unavailableText(m[1]);
      return `the impact on your lineup is not available (${why.charAt(0).toLowerCase()}${why.slice(1)})`;
    },
  ],
  [
    /^Several cut candidates cost about the same/i,
    () => "several cut candidates cost about the same, so the likely cut is not certain",
  ],
  [
    /^Taxi occupancy is unknown/i,
    () => "who is on your taxi squad is unknown, so the number of forced cuts is a range",
  ],
  [
    /^Roster impact is shown before cleanup/i,
    () =>
      "the lineup impact is shown before any cut because which players would be cut is uncertain",
  ],
  [
    /^Low-confidence canonical value for (.+)$/i,
    (m) => `the value of ${m[1]} rests on thin evidence`,
  ],
  [/^Sources disagree on (.+)$/i, (m) => `the ranking sources disagree about ${m[1]}`],
  [
    /^Not on the board, so not priced: (.+)$/i,
    (m) => `${m[1]} is not on the board, so it has no value (unknown, not zero)`,
  ],
  [
    /^On the board but unpriced\b.*?: (.+)$/i,
    (m) => `${m[1]} has no value on the board (unknown, not zero), so it is left out of the totals`,
  ],
  [
    /^Counted as sent, but not taken off this roster\b.*?: (.+)$/i,
    (m) =>
      `${m[1]} is counted as sent but not taken off your roster, because no specific owned pick was chosen`,
  ],
  [
    /^Not held by this team, so not counted as sent: (.+)$/i,
    (m) => `${m[1]} is not held by your team, so it is not counted as sent`,
  ],
];
const AXIS_WORDS = {
  coverage: "part of the analysis is uncertain (see Arguments, objections and uncertainty)",
  margin: "the deciding margin is narrow",
  agreement: "the evidence points different ways",
  assetEvidence: "the evidence behind a traded player's value is thin",
  precision: "the lineup simulation is not very precise",
  evidence: "important information is missing",
};
const GENERIC_LIMIT = "part of the evidence is weaker (see Sources, simulations and methodology)";

/** An internal identifier a person should not read: an ALL-CAPS code, or a
 *  snake_case / camelCase key. */
export function hasInternalIdentifier(text) {
  return /\b[A-Z]{3,}\b|\b[a-z0-9]+_[a-z0-9_]+\b|\b[a-z]+[A-Z][A-Za-z]*\b/.test(String(text || ""));
}

/**
 * One limiting axis as a plain clause.  A known reason maps to its own plain
 * wording; an unrecognised reason that is already plain (no internal
 * identifier) is the backend's sentence verbatim; only a reason that would
 * leak an identifier falls back to the axis' own sentence.
 */
export function plainLimit(axis, why) {
  const w = typeof why === "string" ? why.trim().replace(/\.$/, "") : "";
  if (w) {
    for (const [re, words] of LIMIT_WORDS) {
      const m = w.match(re);
      if (m) return words(m);
    }
    if (!hasInternalIdentifier(w)) return w;
  }
  return AXIS_WORDS[axis] || GENERIC_LIMIT;
}

/**
 * `decision.confidence` as display words.
 *   level     "Medium confidence" (null when the backend states no level,
 *             e.g. when `decision.headline` is the not-enough-evidence code)
 *   detail    what limits it, in plain English (no internal axis names, no
 *             all-caps band labels); null when nothing needs saying
 *   limits    the plain clauses, one per limiting axis, in the backend's order
 *   statement the backend's full statement, verbatim (methodology view only)
 * Never a probability: the backend says so (`isProbability: false`).
 */
export function confidenceSummary(confidence) {
  if (!confidence || typeof confidence !== "object") return null;
  const statement = typeof confidence.statement === "string" ? confidence.statement : "";
  const level = CONFIDENCE_LEVEL_WORDS[confidence.level] || null;
  if (!level) {
    return {
      level: null,
      detail: "No confidence level is given: important information is missing.",
      limits: [],
      statement,
    };
  }
  const bottleneck = Array.isArray(confidence.bottleneck) ? confidence.bottleneck : [];
  if (level !== CONFIDENCE_LEVEL_WORDS.HIGH && bottleneck.length) {
    const whys = confidenceLimits(statement, bottleneck);
    const limits = [
      ...new Set(bottleneck.map((axis, i) => plainLimit(axis, whys.length ? whys[i] : null))),
    ];
    const text = listJoin(limits);
    return { level, detail: `Limited because ${text}.`, limits, statement };
  }
  // HIGH: the only second sentence the backend writes is the execution gate.
  const detail = /cannot be executed as built/i.test(statement)
    ? "The trade cannot be made as built: no legal roster cleanup exists."
    : null;
  return { level, detail, limits: [], statement };
}

/** How the backend's competitive-posture labels read to a person. */
const POSTURE_PLAIN = {
  PUSH: "a contender",
  HOLD: "too close to call",
  RETOOL: "retooling",
  REBUILD: "rebuilding",
};

/**
 * `decision.strategy` as one plain sentence, built from its structured fields
 * (`source`, `label`, `inferredClassification`) rather than its reasoning
 * string, which carries all-caps posture codes ("contender (PUSH)").
 */
export function strategySentence(strategy) {
  if (!strategy || typeof strategy !== "object") return null;
  const label = strategy.label || null;
  const posture = POSTURE_PLAIN[strategy.inferredClassification] || null;
  switch (strategy.source) {
    case "user":
      return `${label || "Your strategy"} — your choice${
        posture ? `; your team reads as ${posture}` : ""
      }.`;
    case "posture":
      return `${label} — your team reads as ${posture || "measured by its competitive window"}.`;
    case "posture_no_evidence":
      return `${label} — your team's direction has no evidence yet, so balanced is used.`;
    case "posture_unknown":
      return "No strategy — your team's direction could not be read. Choose one with the Strategy control.";
    case "asset_only":
      return "Not used in Asset-only analysis.";
    default:
      return label ? `${label}.` : null;
  }
}

// ── Reasons ───────────────────────────────────────────────────────────────

const BAND_PHRASE = {
  slight: "a slight edge",
  unfair: "an unfair gap",
  lopsided: "a lopsided gap",
};

/**
 * The fit sentence for one roster-capacity state (`lenses.feasibility`).
 * Cut names are the backend's forced drops, in its order.
 */
export function fitSentence(state, names = [], { tied = false, openSpotsBefore = null } = {}) {
  const who = listJoin(names);
  const cut = who
    ? ` You would need to cut ${who}${tied ? " (a close call between candidates)" : ""}.`
    : "";
  switch (state) {
    case "fits_cleanly":
      return "The trade fits. No player cut needed.";
    case "uses_final_spot":
      // A full roster that swaps one for one stays full: no spot is "used".
      return openSpotsBefore === 0
        ? "The trade fits. No player cut needed."
        : "The trade fits, filling your last open roster spot. No player cut needed.";
    case "resolves_overage":
      return "The trade brings your roster back under the limit. No player cut needed.";
    case "cut_required":
      return `The trade does not fit as built.${cut || " A player would need to be cut."}`;
    case "worsens_overage":
      return `Your roster is already over the limit, and this trade adds to it.${cut}`;
    case "reduces_overage":
      return `Your roster is already over the limit; this trade reduces the overage.${cut}`;
    case "overage_unchanged":
      return `Your roster is already over the limit, and this trade leaves that unchanged.${cut}`;
    default:
      return null;
  }
}

/**
 * One decision reason (`decision.reasons[i]`, `primaryReason`,
 * `mainCounterargument`) as a short sentence.  Keyed on the backend's own
 * component, stance and evidence -- the band LEVEL the fairness-band owner
 * assigned, the magnitude the roster lens assigned -- so the sentence says
 * which way the reason points and how strongly, and the exact numbers stay in
 * the at-a-glance rows below it.  Anything unrecognised (a gate, missing
 * evidence) is the backend's text, verbatim.
 */
export function reasonSentence(reason, { strategy = null } = {}) {
  if (!reason || typeof reason !== "object") return null;
  const ev = reason.evidence || {};
  const verbatim = typeof reason.text === "string" && reason.text ? reason.text : null;
  switch (reason.component) {
    case "objectiveValue": {
      const level = ev.band?.level;
      const cut =
        isNum(ev.forcedReleaseCost) && ev.forcedReleaseCost > 0
          ? ", counting the player you must cut"
          : "";
      // The band's own basis, to the backend's one decimal.
      const rel = isNum(ev.band?.relativePct)
        ? ` (${ev.band.relativePct.toFixed(1)}% of the larger package)`
        : "";
      const band = BAND_PHRASE[level];
      if (reason.stance === "for")
        return `You come out ahead on trade value${cut}${band ? ` — ${band} in your favor` : ""}${rel}.`;
      if (reason.stance === "against")
        return `You come out behind on trade value${cut}${band ? ` — ${band} against you` : ""}${rel}.`;
      return `Trade value is close to even${cut}${rel}.`;
    }
    case "rosterBenefit": {
      const much = ev.magnitude === "large" ? "much " : "";
      if (reason.stance === "for") return `Your projected weekly lineup gets ${much}stronger.`;
      if (reason.stance === "against") return `Your projected weekly lineup gets ${much}weaker.`;
      return "Your projected weekly lineup barely changes.";
    }
    case "feasibility":
      // A gate (e.g. "No legal roster cleanup exists for this trade") or any
      // reason without a mappable roster state keeps the backend's own plain
      // sentence.
      if (reason.kind === "gate") return verbatim;
      return fitSentence(ev.state, ev.forcedDrops || []) || verbatim;
    case "strategy": {
      const s = strategySentence(strategy);
      return s
        ? `Your strategy decided it: ${s.charAt(0).toLowerCase()}${s.slice(1)}`
        : "Your strategy decided it.";
    }
    default:
      // Gates and missing evidence: the backend's own plain sentence.
      return verbatim;
  }
}

/**
 * The two reasons shown at once, in the backend's own priority:
 *   1. `primaryReason` -- the decision's deciding reason ("Biggest reason");
 *   2. `mainCounterargument` when the backend names one ("On the other
 *      hand"), otherwise the next reason in the backend's order that is a
 *      DIFFERENT component: an independent one first (value / lineup), then a
 *      contextual one only if it actually pushes for or against ("Also").
 * A neutral context line (a clean fit, the strategy echo) is not a reason --
 * it is already its own row.  A not-enough-evidence decision has no reasons: the missing
 * evidence is listed instead.  Nothing is invented to fill a second slot.
 */
export function decisionReasons(decision) {
  if (!decision || decision.headline === "NOT_ENOUGH_EVIDENCE") return [];
  const all = Array.isArray(decision.reasons) ? decision.reasons : [];
  const main = decision.primaryReason || all[0] || null;
  if (!main) return [];
  const out = [{ role: "main", reason: main }];
  const counter = decision.mainCounterargument;
  if (counter && counter.component !== main.component) {
    out.push({ role: "counter", reason: counter });
    return out;
  }
  const next =
    all.find((r) => r && r.component !== main.component && r.kind === "independent") ||
    all.find(
      (r) => r && r.component !== main.component && (r.stance === "for" || r.stance === "against"),
    );
  if (next) out.push({ role: "also", reason: next });
  return out;
}

export const REASON_ROLE_WORDS = {
  main: "Biggest reason",
  counter: "On the other hand",
  also: "Also",
};

// ── At a glance: trade value ──────────────────────────────────────────────

function gapClause(gap) {
  const r = Math.round(gap);
  if (r > 0) return `you get ${formatValue(r)} more than you give`;
  if (r < 0) return `you give ${formatValue(-r)} more than you get`;
  return "the two sides are even";
}

/**
 * The trade-value row from the market lens detail (or the calculator's own
 * totals in the same shape, while the analysis runs -- see
 * `valueSummaryFromSideTotals`).  The headline difference is the OFFICIAL
 * one, `vaAdjustedGap` (the package gap the decision uses); the raw gap is
 * named beside it only when Value Adjustment changes it.
 */
export function tradeValueSummary(d) {
  if (!d || !isNum(d.receivingValue) || !isNum(d.sendingValue)) return null;
  const receive = formatValue(d.receivingValue);
  const send = formatValue(d.sendingValue);
  const raw = isNum(d.rawGap) ? d.rawGap : d.receivingValue - d.sendingValue;
  const gap = isNum(d.vaAdjustedGap) ? d.vaAdjustedGap : raw;
  const adjIn = isNum(d.receivingValueAdjustment) ? d.receivingValueAdjustment : 0;
  const adjOut = isNum(d.sendingValueAdjustment) ? d.sendingValueAdjustment : 0;
  const vaChanges = Math.round(adjIn) !== 0 || Math.round(adjOut) !== 0;
  const sentence = vaChanges
    ? `You receive ${receive} and send ${send}. After Value Adjustment, ${gapClause(gap)} (${formatSignedValue(raw)} before it).`
    : `You receive ${receive} and send ${send}, so ${gapClause(gap)}.`;
  return {
    receive,
    send,
    difference: formatSignedValue(gap),
    rawDifference: formatSignedValue(raw),
    vaChanges,
    sentence,
  };
}

// ── At a glance: impact on your team ──────────────────────────────────────

/** "Your projected lineup scores about 5.7 fewer points per week." */
export function lineupPointsSentence(ppg) {
  const mag = tenth(ppg);
  if (mag == null) return null;
  if (mag === "0.0")
    return "Your projected lineup scores about the same each week (less than 0.1 points either way).";
  return `Your projected lineup scores about ${mag} ${ppg > 0 ? "more" : "fewer"} points per week.`;
}

/**
 * The roster lens (`lenses.roster`) as the "Impact on your team" row:
 *   { sentence, note, partial }  or  { unavailable }
 * A partial-coverage estimate is shown, labelled, and never presented as the
 * complete answer (the decision does not count it).
 */
export function weeklyImpact(lens) {
  if (!lens) return { unavailable: unavailableText(null) };
  const d = lens.detail || {};
  const partial = lens.unavailableReason === "partial_projection_coverage";
  if ((!lens.available && !partial) || !isNum(d.ppg)) {
    return { unavailable: unavailableText(lens.unavailableReason) };
  }
  const notes = [];
  if (isNum(d.ppgBeforeCleanup)) {
    if (
      tenth(d.ppgBeforeCleanup) === tenth(d.ppg) &&
      Math.sign(d.ppgBeforeCleanup) === Math.sign(d.ppg)
    ) {
      notes.push("The required cut does not change this.");
    } else {
      const before = tenth(d.ppgBeforeCleanup);
      notes.push(
        before === "0.0"
          ? "Before the required cut it would be about the same."
          : `Before the required cut it would be about ${before} ${d.ppgBeforeCleanup > 0 ? "more" : "fewer"}.`,
      );
    }
  }
  if (partial) {
    notes.push(
      "Only players with a projection are counted (a traded player has none), so this does not count toward the recommendation.",
    );
  }
  return { sentence: lineupPointsSentence(d.ppg), note: notes.join(" ") || null, partial };
}

// ── At a glance: does it fit your roster? ─────────────────────────────────

/** "Roster spots: 58 now, 58 after, limit 58. Draft picks don't use roster spots." */
export function rosterSpotsLine(d) {
  if (!d || !isNum(d.rosterLimit)) return null;
  const now = isNum(d.sizeBefore) ? d.sizeBefore : "unknown";
  const after = isNum(d.sizeAfter) ? d.sizeAfter : "unknown";
  return `Roster spots: ${now} now, ${after} after, limit ${d.rosterLimit}. Draft picks don't use roster spots.`;
}

/** The feasibility lens as the "Does it fit your roster?" row. */
export function rosterFit(lens) {
  if (!lens) return { unavailable: unavailableText(null) };
  const d = lens.detail || {};
  const sentence = lens.available
    ? fitSentence(
        d.state,
        (d.forcedDrops || []).map((x) => x?.name),
        { tied: d.candidatesTied === true, openSpotsBefore: d.openSpotsBefore },
      )
    : null;
  if (!sentence)
    return { unavailable: unavailableText(lens.unavailableReason), spots: rosterSpotsLine(d) };
  return { sentence, spots: rosterSpotsLine(d) };
}

// ── Expandable detail ─────────────────────────────────────────────────────

/**
 * "A.J. Brown makes your best lineup in 61% of simulated weeks." -- one
 * sentence per INCOMING player with a measured lineup share, in the packet's
 * order.  A player without one is skipped, never "0%".
 */
export function incomingLineupSentences(rosterDetail) {
  return (rosterDetail?.players || [])
    .filter((p) => p?.role === "incoming" && isNum(p.lineupEntryPctAfter))
    .map((p) => {
      // Owner master package 2026-10-17 (P0): a lineup share is over the
      // league's REMAINING weeks, and a player who cannot play some of them
      // says so beside it -- never a bare percentage that reads as health.
      const note = availabilityNote(p);
      const avail = note ? ` (availability: ${note.charAt(0).toLowerCase()}${note.slice(1)})` : "";
      return `${p.name} makes your best lineup in ${formatPctPoint(p.lineupEntryPctAfter)} of simulated weeks${avail}.`;
    });
}

export const ROLE_PLAIN_WORDS = {
  incoming: "Coming in",
  outgoing: "Going out",
  forcedDrop: "Cut to make room",
  promoted: "Starts more often",
  displaced: "Starts less often",
};

/**
 * The simulation explained as a model estimate (the old "±0.5 simulation
 * error").  `standardError` is the Monte-Carlo error of the paired mean
 * (`src/roster_intel/best_ball_utility.py`): a precision statement about the
 * estimate, not a chance the trade works out.
 */
export function simulationExplanation(rosterDetail) {
  const d = rosterDetail || {};
  const basis = d.basis || {};
  const parts = ["This is a model estimate, not a guarantee."];
  const weeks = simulatedWeeksLabel(basis);
  if (isNum(basis.draws)) {
    parts.push(
      `Your best legal lineup was simulated over ${basis.draws.toLocaleString("en-US")} weeks${
        weeks ? ` of the league's remaining ${weeks}` : ""
      }, scored with your league's own rules.`,
    );
  }
  if (isNum(d.standardError)) {
    const se = tenth(d.standardError);
    parts.push(
      `Running the simulation again would typically move the result by about ±${
        se === "0.0" ? "0.1 or less" : se
      } points per week (its standard error). That covers the simulation's own randomness only, not errors in the projections themselves.`,
    );
  }
  return parts.join(" ");
}

/**
 * Why the War Room could not finish, in plain words.  The machine reason
 * stays available (the caller may show it in parentheses for support).
 */
export function analysisErrorText(error) {
  const e = String(error || "");
  if (e === "timeout") return "it took too long to finish";
  if (e === "invalid_analysis") return "the server's answer did not match this trade";
  if (e === "data_not_ready") return "this league's data is still loading on the server";
  if (e === "unknown_league" || e === "inactive_league") return "this league is not available";
  if (/^HTTP 5\d\d$/.test(e)) return `the server had a problem (${e})`;
  if (/^HTTP 4\d\d$/.test(e)) return `the server refused the request (${e})`;
  if (/failed to fetch|network|load failed/i.test(e)) return "the connection failed";
  return e ? `an error occurred (${e})` : "an error occurred";
}
