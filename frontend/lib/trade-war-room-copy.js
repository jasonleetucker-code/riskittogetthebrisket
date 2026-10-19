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
  unavailableWords,
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

/** Clauses joined into one sentence: like `listJoin`, but clauses that carry
 *  their own commas get an Oxford comma (two) or semicolons (three or more),
 *  so where one clause ends and the next begins stays readable. */
function clauseJoin(items) {
  const xs = (items || []).filter(Boolean);
  if (xs.length <= 1 || !xs.some((x) => x.includes(","))) return listJoin(xs);
  if (xs.length === 2) return `${xs[0]}, and ${xs[1]}`;
  return `${xs.slice(0, -1).join("; ")}; and ${xs[xs.length - 1]}`;
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

/** A backend clause ready to sit inside a sentence: its end punctuation is
 *  dropped (a period only when it does not belong to a name -- "Marvin
 *  Harrison Jr.", "C.J."), and a leading ordinary word is lowercased.  A
 *  leading word followed by another capitalised word ("Justin Herbert …"),
 *  or one in capitals ("DJ Moore …"), may be a name and is left alone. */
function clauseText(text) {
  let t = String(text || "").trim();
  if (/[?!]$/.test(t)) t = t.slice(0, -1).trim();
  else if (/\.$/.test(t) && !/(?:\b(?:Jr|Sr|St)|\b[A-Z])\.$/.test(t)) t = t.slice(0, -1).trim();
  return t.replace(/^(?:A|[A-Z][a-z]+)(?=\s+[a-z(]|[,;:]|$)/, (w) => w.toLowerCase());
}

/** A sentence that ends with its own punctuation, adding a period only when
 *  the text has none. */
export function sentenceEnd(text) {
  const t = String(text || "").trim();
  if (!t) return "";
  return /[.!?]$/.test(t) ? t : `${t}.`;
}

function lowerFirst(text) {
  return text ? `${text.charAt(0).toLowerCase()}${text.slice(1)}` : text;
}

/** Reasons whose words only repeat the sentence they would sit in ("could
 *  not be measured (not computed)"): left out. */
const REDUNDANT_REASONS = new Set(["not_computed"]);

/** " (the reason, in words)" for an unavailable reason, or "" when it has no
 *  words or they would only repeat the sentence. */
function reasonSuffix(reason) {
  if (REDUNDANT_REASONS.has(reason)) return "";
  const words = unavailableWords(reason);
  return words ? ` (${lowerFirst(words)})` : "";
}

/** A backend name list ("A, B, C") as names, so the sentence can be plural. */
function nameList(captured) {
  return String(captured || "")
    .split(", ")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** "a traded player has" / "2 traded players have" / "some traded players
 *  have" -- the count from the roster lens, "some" when it is not stated. */
function unprojectedWho(count) {
  if (count === 1) return "a traded player has";
  return isNum(count) && count > 1 ? `${count} traded players have` : "some traded players have";
}

/** "…no league-scored projection, so the lineup effect is left out" -- the
 *  roster lens abstained.  Never "could not be measured": it is not counted. */
function unprojectedClause(count) {
  return `${unprojectedWho(count)} no league-scored projection, so the lineup effect is left out rather than counted as zero`;
}

function unprojectedCount(rosterLens) {
  const ids = rosterLens?.detail?.coverage?.tradedUnprojectedPlayerIds;
  return Array.isArray(ids) && ids.length ? ids.length : null;
}

/**
 * The confidence why "no current-season roster effect to measure" is written
 * whenever the roster component is not evaluated and that is not an evidence
 * gap -- which covers two different facts.  The roster lens says which:
 * partial projection coverage under a long-term strategy (an estimate EXISTS
 * and is shown, labelled, at a glance; it is only left out of the decision)
 * or a season with no fantasy weeks to measure.
 */
function rosterEffectClause(rosterLens) {
  const reason = rosterLens?.unavailableReason;
  if (reason === "partial_projection_coverage")
    return unprojectedClause(unprojectedCount(rosterLens));
  if (reason === "no_remaining_fantasy_weeks")
    return "no fantasy weeks remain this season, so there is no lineup effect to measure";
  if (reason === "season_unresolved")
    return "no current-season projection applies, so there is no lineup effect to measure";
  return "there is no current-season lineup effect to measure";
}

/**
 * What each limiting axis means, in plain English.  Keyed on the reason
 * strings `src/trade/trade_decision.py::_confidence` writes and on every line
 * `analyze_trade.py::_uncertainty` can put on the coverage axis (matched by
 * their stable openings, so wording tweaks that keep the opening still map).
 * An unrecognised reason that is already plain is the backend's own clause,
 * verbatim; only one carrying an internal identifier (an axis key, a
 * snake_case code, an all-caps label) falls back to the axis' own sentence.
 *
 * `topic` is what a clause is ABOUT, so one fact said twice -- the generic
 * asset-evidence reason beside the coverage axis' named uncertainty line --
 * collapses to one clause, the `named` one when there is one.
 */
const LIMIT_WORDS = [
  // ── fixed reasons per axis (`trade_decision.py::_confidence`) ──
  {
    re: /^asset-only/i,
    words: () => "this Asset-only analysis leaves out your roster and lineup",
  },
  {
    re: /^no current-season roster effect/i,
    words: (m, ctx) => rosterEffectClause(ctx.rosterLens),
    topic: "lineupEffect",
  },
  {
    re: /^strategy defaulted/i,
    words: () =>
      "your strategy fell back to balanced because your team's direction has no evidence yet",
  },
  { re: /^a near tie/i, words: () => "the trade is close to even" },
  { re: /^package gap/i, words: () => "the trade-value gap is small" },
  { re: /^roster effect/i, words: () => "the change to your lineup is modest" },
  { re: /^deciding margin/i, words: () => "the deciding margin is modest" },
  {
    re: /^value and roster disagree/i,
    words: () => "trade value and your lineup point different ways, so your strategy decided",
  },
  {
    re: /low or no confidence stamp/i,
    words: () => "a traded player's value rests on thin or missing evidence",
    topic: "thinEvidence",
  },
  {
    re: /^sources disagree on a traded asset/i,
    words: () => "the ranking sources disagree about a traded player's value",
    topic: "sourceDisagreement",
  },
  { re: /moderately precise/i, words: () => "the lineup simulation is only moderately precise" },
  { re: /^roster estimate imprecise/i, words: () => "the lineup simulation is imprecise" },
  // ── the coverage axis' uncertainty lines (`analyze_trade.py::_uncertainty`) ──
  {
    re: /^No league-scored projection for (\d+) traded player/i,
    words: (m) => unprojectedClause(Number(m[1])),
    topic: "lineupEffect",
    named: true,
  },
  {
    re: /^Roster impact not available \(([^)]*)\)/i,
    words: (m) => {
      return `the impact on your lineup is not available${reasonSuffix(m[1])}`;
    },
    topic: "lineupEffect",
  },
  {
    re: /^Several cut candidates cost about the same/i,
    words: () => "several cut candidates cost about the same, so the likely cut is not certain",
  },
  {
    re: /^Taxi occupancy is unknown/i,
    words: () => "who is on your taxi squad is unknown, so the number of forced cuts is a range",
  },
  {
    re: /^Roster impact is shown before cleanup/i,
    words: () =>
      "the lineup impact is shown before any cut because which players would be cut is uncertain",
  },
  {
    re: /^Low-confidence canonical value for (.+)$/i,
    words: (m) => {
      const xs = nameList(m[1]);
      return xs.length > 1
        ? `the values of ${listJoin(xs)} rest on thin evidence`
        : `the value of ${xs[0]} rests on thin evidence`;
    },
    topic: "thinEvidence",
    named: true,
  },
  {
    re: /^Sources disagree on (.+)$/i,
    words: (m) => `the ranking sources disagree about ${listJoin(nameList(m[1]))}`,
    topic: "sourceDisagreement",
    named: true,
  },
  {
    re: /^Not on the board, so not priced: (.+)$/i,
    words: (m) => {
      const xs = nameList(m[1]);
      return xs.length > 1
        ? `${listJoin(xs)} are not on the board and have no value (unknown, not zero)`
        : `${xs[0]} is not on the board and has no value (unknown, not zero)`;
    },
  },
  {
    re: /^On the board but unpriced\b.*?: (.+)$/i,
    words: (m) => {
      const xs = nameList(m[1]);
      return xs.length > 1
        ? `${listJoin(xs)} have no value on the board (unknown, not zero) and are left out of the totals`
        : `${xs[0]} has no value on the board (unknown, not zero) and is left out of the totals`;
    },
  },
  {
    re: /^Counted as sent, but not taken off this roster\b.*?: (.+)$/i,
    words: (m) => {
      const xs = nameList(m[1]);
      return xs.length > 1
        ? `${listJoin(xs)} are counted as sent but not taken off your roster, because no specific owned picks were chosen`
        : `${xs[0]} is counted as sent but not taken off your roster, because no specific owned pick was chosen`;
    },
  },
  {
    re: /^Not held by this team, so not counted as sent: (.+)$/i,
    words: (m) => {
      const xs = nameList(m[1]);
      return xs.length > 1
        ? `${listJoin(xs)} are not held by your team and are not counted as sent`
        : `${xs[0]} is not held by your team and is not counted as sent`;
    },
  },
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

const ROMAN_NUMERAL = /^(?:I{2,3}|IV|VI{0,3}|IX|X{1,3})$/;

/**
 * An internal identifier a person should not read: a snake_case code, a
 * camelCase key, an all-caps label of three or more letters, a `kind:Detail`
 * code ("error:KeyError"), or any of those in quotes ("'valueAdjustment'",
 * "'LOPSIDED'").  Real names are not identifiers: a capital after an
 * apostrophe or inside a word ("Henry To'oTo'o", "JuJu", "McCloud") is not
 * camelCase, and a roman-numeral suffix ("Kenneth Walker III") is not a label.
 */
export function hasInternalIdentifier(text) {
  const s = String(text || "");
  if (/[A-Za-z0-9]_[A-Za-z0-9]/.test(s)) return true;
  // kind:Detail -- a lowercase word glued to a colon and another word.
  if (/(?:^|[^A-Za-z])[a-z]+:[A-Za-z_]/.test(s)) return true;
  // camelCase: a lowercase run that STARTS a token (not after a letter or an
  // apostrophe), then a capital.
  if (/(?:^|[^A-Za-z'’])[a-z]+[A-Z]/.test(s)) return true;
  for (const m of s.matchAll(/(?:^|[^A-Za-z'’])([A-Z]{3,})(?![A-Za-z'’])/g)) {
    if (!ROMAN_NUMERAL.test(m[1])) return true;
  }
  // A quoted token: the opening quote follows no letter (so the apostrophes
  // inside "To'oTo'o" are not quotes) and the closing one precedes none.
  for (const m of s.matchAll(/(?:^|[^A-Za-z0-9])['‘’"“]([A-Za-z0-9_]+)['’"”](?![A-Za-z])/g)) {
    const t = m[1];
    if (/^[a-z]+[A-Z]/.test(t) || (/^[A-Z]{3,}$/.test(t) && !ROMAN_NUMERAL.test(t))) return true;
  }
  return false;
}

/** A backend string that is a bare code rather than words: an identifier, or
 *  a single lowercase token ("blocked", "uncertain"). */
function isRawCode(text) {
  const t = String(text || "").trim();
  return hasInternalIdentifier(t) || /^[a-z]+$/.test(t);
}

/** One limiting axis as `{ text, topic, named }` (see LIMIT_WORDS). */
function limitClause(axis, why, ctx = {}) {
  const w = typeof why === "string" ? why.trim() : "";
  if (w) {
    for (const { re, words, topic = null, named = false } of LIMIT_WORDS) {
      const m = w.match(re);
      if (m) return { text: words(m, ctx), topic, named };
    }
    if (!isRawCode(w)) return { text: clauseText(w), topic: null, named: false };
  }
  return { text: AXIS_WORDS[axis] || GENERIC_LIMIT, topic: null, named: false };
}

/**
 * One limiting axis as a plain clause.  A known reason maps to its own plain
 * wording; an unrecognised reason that is already plain (no internal
 * identifier) is the backend's clause verbatim; only a reason that would
 * leak an identifier falls back to the axis' own sentence.  `rosterLens`
 * (the analysis' `lenses.roster`) says what "no current-season roster effect"
 * actually means for this trade.
 */
export function plainLimit(axis, why, { rosterLens = null } = {}) {
  return limitClause(axis, why, { rosterLens }).text;
}

/** "another traded player's value has no evidence rating" -- what a generic
 *  thin-evidence reason still says once a named clause covers the
 *  low-confidence assets. */
function unratedClause(count) {
  return count === 1
    ? "another traded player's value has no evidence rating"
    : `${count} other traded players' values have no evidence rating`;
}

/** Traded assets with no confidence stamp that are not low-confidence ones
 *  (`lenses.evidence.detail`): what a named low-confidence clause leaves out. */
function unratedOthers(evidenceLens) {
  const d = evidenceLens?.detail || {};
  const low = new Set((d.lowConfidenceAssets || []).map((a) => a?.name).filter(Boolean));
  return (d.unstampedAssets || []).filter((n) => n && !low.has(n)).length;
}

/** Clauses deduplicated by MEANING: same text, or same topic -- the named
 *  clause wins its topic, in the position the topic first appeared.  The
 *  generic thin-evidence reason also covers assets with NO stamp, so when a
 *  named low-confidence clause replaces it and such assets remain, they keep
 *  a clause of their own. */
function dedupeClauses(clauses, { unrated = 0 } = {}) {
  const out = [];
  const genericThin = (c) => c.topic === "thinEvidence" && !c.named;
  let thinGenericReplaced = false;
  for (const c of clauses) {
    const i = out.findIndex((o) => o.text === c.text || (c.topic && o.topic === c.topic));
    if (i < 0) {
      out.push(c);
    } else if (c.named && !out[i].named) {
      thinGenericReplaced = thinGenericReplaced || genericThin(out[i]);
      out[i] = c;
    } else if (genericThin(c) && out[i].named) {
      thinGenericReplaced = true;
    }
  }
  if (thinGenericReplaced && unrated > 0) {
    const at = out.findIndex((o) => o.topic === "thinEvidence");
    out.splice(at + 1, 0, { text: unratedClause(unrated), topic: null, named: true });
  }
  return out.map((c) => c.text);
}

/**
 * `decision.confidence` as display words.
 *   level     "Medium confidence" (null when the backend states no level,
 *             e.g. when `decision.headline` is the not-enough-evidence code)
 *   detail    what limits it, in plain English (no internal axis names, no
 *             all-caps band labels); null when nothing needs saying
 *   limits    the plain clauses, in the backend's order, one per FACT (two
 *             axes naming the same fact collapse to one clause)
 *   statement the backend's full statement, verbatim (methodology view only)
 * `rosterLens` is the analysis' `lenses.roster`, read for what an unevaluated
 * roster effect means; `evidenceLens` (`lenses.evidence`) for which traded
 * assets have no evidence stamp.  Never a probability: the backend says so
 * (`isProbability: false`).
 */
export function confidenceSummary(confidence, { rosterLens = null, evidenceLens = null } = {}) {
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
    const limits = dedupeClauses(
      bottleneck.map((axis, i) => limitClause(axis, whys.length ? whys[i] : null, { rosterLens })),
      { unrated: unratedOthers(evidenceLens) },
    );
    return {
      level,
      detail: sentenceEnd(`Limited because ${clauseJoin(limits)}`),
      limits,
      statement,
    };
  }
  // HIGH: the only second sentence the backend writes is the execution gate.
  const detail = /cannot be executed as built/i.test(statement)
    ? "The trade cannot be made as built: no legal roster cleanup exists."
    : null;
  return { level, detail, limits: [], statement };
}

/**
 * One line of the analysis' uncertainty list for the expandable detail, as a
 * sentence ending in a period: the backend's own sentence when it is plain;
 * its plain clause when it carries a code -- always for "Roster impact not
 * available (<reason>)", whose parenthesis is a reason code
 * ("error:KeyError", "not_computed").
 */
export function uncertaintyLine(text, { rosterLens = null } = {}) {
  const t = typeof text === "string" ? text.trim() : "";
  if (!t) return null;
  if (!isRawCode(t) && !/^Roster impact not available \(/i.test(t)) return sentenceEnd(t);
  const plain = plainLimit("coverage", t, { rosterLens });
  return sentenceEnd(`${plain.charAt(0).toUpperCase()}${plain.slice(1)}`);
}

/** How a host injury designation reads ("listed OUT this week" in the
 *  backend's argument lines, `analyze_trade.py::_availability_reason`). */
const DESIGNATION_WORDS = {
  OUT: "listed as out",
  QUESTIONABLE: "listed as questionable",
  DOUBTFUL: "listed as doubtful",
  IR: "on injured reserve",
  PUP: "on the physically-unable-to-perform list",
  NA: "listed as not active",
  SUS: "suspended",
  DNR: "listed as did not report",
  COV: "on the illness list",
};

/**
 * One "Points in favor / against" line (`analysis.reasonsFor` /
 * `reasonsAgainst`) for the expandable detail: the backend's sentence with
 * its all-caps injury designation worded ("listed as out this week"), ending
 * in a period like every other line there.
 */
export function argumentLine(text) {
  const t = typeof text === "string" ? text.trim() : "";
  if (!t) return null;
  return sentenceEnd(
    t.replace(
      /\blisted ([A-Z]{2,}) this week\b/g,
      (_, code) => `${DESIGNATION_WORDS[code] || `listed as ${code.toLowerCase()}`} this week`,
    ),
  );
}

// ── What is missing (`decision.missingEvidence`) ──────────────────────────

/** Gaps whose text is fixed backend prose then a list of names after ": ";
 *  only the prose is checked for identifiers -- names are names. */
const NAME_LIST_GAPS = new Set([
  "off_board_assets",
  "unpriced_assets",
  "unheld_assets",
  "quarantined_values",
  "stale_values",
]);
/** The gap code from its text, for the evidence gate's `primaryReason`, which
 *  carries the first gap's text and evidence but not its code. */
const GAP_OPENINGS = [
  [/^The roster effect could not be measured\b/, "roster_unknown"],
  [/^Whether the trade fits your roster is unknown\b/, "roster_limit_unknown"],
  [/^Not on the board, so not priced: /, "off_board_assets"],
  [/^On the board but unpriced\b/, "unpriced_assets"],
  [/^Your team does not hold: /, "unheld_assets"],
  [/^Value withheld as untrustworthy\b/, "quarantined_values"],
  [/^Value rests mostly on stale sources: /, "stale_values"],
];
const GENERIC_GAP = "Some information the recommendation needs is missing.";

/**
 * One missing-evidence gap (`decision.missingEvidence[i]`, or the evidence
 * gate's `primaryReason`) as a plain sentence.  The two gaps whose backend
 * text embeds a reason code -- `roster_unknown` ("…could not be measured
 * (not_computed).") and `roster_limit_unknown` ("…is unknown
 * (roster_capacity_unavailable).") -- are worded from `evidence.reason`; every
 * other gap is the backend's sentence when it is plain, and a generic line
 * when it would show an internal identifier.  Never empty.
 */
export function missingEvidenceText(gap) {
  if (!gap || typeof gap !== "object") return null;
  const text = typeof gap.text === "string" ? gap.text.trim() : "";
  const code = gap.code || GAP_OPENINGS.find(([re]) => re.test(text))?.[1] || null;
  const why = reasonSuffix(gap.evidence?.reason);
  if (code === "roster_unknown") return `The effect on your lineup could not be measured${why}.`;
  if (code === "roster_limit_unknown")
    return `Whether the trade fits your roster is unknown${why}.`;
  if (!text) return GENERIC_GAP;
  const at = text.indexOf(": ");
  const prose = NAME_LIST_GAPS.has(code) && at > 0 ? text.slice(0, at) : text;
  return isRawCode(prose) ? GENERIC_GAP : sentenceEnd(text);
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
  // sentenceEnd, not a literal ".": a name can end the sentence with its own
  // period ("…cut Marvin Harrison Jr.").
  const cut = who
    ? ` ${sentenceEnd(`You would need to cut ${who}${tied ? " (a close call between candidates)" : ""}`)}`
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
 * the at-a-glance rows below it.  A gate or missing evidence is the backend's
 * own sentence when it is plain, worded from its evidence when it is not;
 * a reason with nothing plain to say returns null (the caller skips it, so
 * no reason ever renders empty).
 */
export function reasonSentence(reason, { strategy = null } = {}) {
  if (!reason || typeof reason !== "object") return null;
  const ev = reason.evidence || {};
  const text = typeof reason.text === "string" ? reason.text.trim() : "";
  const verbatim = text && !isRawCode(text) ? sentenceEnd(text) : null;
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
    case "feasibility": {
      // The execution gate ("No legal roster cleanup exists for this trade")
      // keeps the backend's own sentence; a roster state this module does not
      // know keeps the backend's text only when it is plain -- the backend
      // falls back to the raw state code -- else a fixed sentence by stance.
      if (reason.kind === "gate")
        return verbatim || "No legal roster cleanup exists for this trade.";
      const fit = fitSentence(ev.state, ev.forcedDrops || []);
      if (fit) return fit;
      // The backend's text for an unknown state IS the state (`.get(state, state)`).
      if (verbatim && text !== ev.state) return verbatim;
      if (reason.stance === "against") return "Fitting it on your roster counts against it.";
      if (reason.stance === "for") return "Fitting it on your roster counts in its favor.";
      return "Fitting it on your roster does not push either way.";
    }
    case "strategy": {
      const s = strategySentence(strategy);
      return s
        ? `Your strategy decided it: ${s.charAt(0).toLowerCase()}${s.slice(1)}`
        : "Your strategy decided it.";
    }
    case "evidence":
      // The evidence gate carries the first missing-evidence gap.
      return missingEvidenceText(reason);
    default:
      // Any other gate: the backend's own sentence, when it is plain.
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

/**
 * `decisionReasons`, each with its plain sentence.  A reason with nothing
 * plain to say is skipped -- and when that is the MAIN reason the whole list
 * is dropped, because a counterargument shown alone would read as the reason.
 */
export function decisionReasonSentences(decision) {
  const items = decisionReasons(decision).map((r) => ({
    ...r,
    sentence: reasonSentence(r.reason, { strategy: decision.strategy }),
  }));
  if (!items.length || !items[0].sentence) return [];
  return items.filter((r) => r.sentence);
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
      `Only players with a projection are counted (${unprojectedWho(unprojectedCount(lens))} none), so this does not count toward the recommendation.`,
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
