/**
 * team-plan.js — pure display helpers for the home "This week" panel
 * (owner directive 2026-11-21, intake DYN10, top-10 item #5).
 *
 * DISPLAY ONLY.  Every number and every decision arrives from
 * `GET /api/team/plan` (src/api/team_plan.py, which itself only composes the
 * canonical owners: posture, Team Strength / Weakness, the age portfolio,
 * Gameplan targets, trade suggestions, Perfect Waivers, draft capital and
 * roster freshness).  Nothing here values, ranks, scores, thresholds, sorts or
 * re-orders anything — the same no-frontend-engine rule `buildRows` and
 * `lib/bdvm.js` follow.  The helpers only (a) turn backend codes into words,
 * (b) pick the backend's own fields out for each row and (c) format backend
 * numbers for reading.  A missing number is a stated "not available", never 0.
 *
 * The route is behind the owner-held flag `team_advisor_plan` (default OFF).
 * Any answer that is not a plan (503 flag off, 401, 404, a league out of
 * scope, a network failure) is "no plan", and the panel renders nothing.
 */

import {
  draftCapitalBudgetsUnavailableReason,
  draftCapitalBudgetsUnavailableText,
} from "@/lib/draft-capital-budgets";
import {
  PICK_OWNERSHIP_UNAVAILABLE_LABEL,
  pickOwnershipUnavailableReason,
} from "@/lib/pick-ownership";

/** The owner-held flag behind `GET /api/team/plan` (default OFF). */
export const TEAM_PLAN_FLAG = "team_advisor_plan";

// The request and the "is this a plan for me?" check live in
// `components/terminal/useTeamPlan.js` (kept out of this module so it stays in
// the panel's lazy chunk).  This module only reads a plan already accepted.

// ── words ──────────────────────────────────────────────────────────────

const REASON_COPY = {
  league_bundle_not_warm: "the league analysis has not been built yet",
  gameplan_targets_not_warm: "trade targets have not been built for this team yet",
  perfect_waivers_not_warm: "Perfect Waivers has not run for this team recently",
  draft_capital_not_warm: "the draft-capital board has not been built yet",
  no_canonical_pick_action_owner: "no approved rule turns draft capital into a pick move yet",
  partially_assessed: "only part of it could be measured",
  age_vs_league_median_unmeasured: "age versus the league median could not be measured",
  team_not_matched_in_draft_capital: "this team could not be matched on the draft-capital board",
  roster_intelligence_error: "roster intelligence did not answer",
  team_not_in_contract: "this team is not on the loaded board",
  suggestions_error: "trade suggestions did not answer",
  suggestions_refused: "trade suggestions declined to run",
  team_roster_empty: "this team's roster is empty",
  owner_unavailable: "its source did not answer",
  owner_returned_no_block: "its source returned nothing",
  league_lineup_unresolved: "the league's lineup could not be resolved",
  all_outgoing_assets_constrained: "every tradeable player is protected",
  perfect_waivers_payload_malformed: "Perfect Waivers returned an unreadable answer",
  no_aged_players: "no player ages are known",
  pick_ownership_unavailable: "pick ownership is unavailable",
  no_need_positions: "no position needs help",
};

/** Turn a snake_case code into lower-case words when there is no curated copy. */
export function humanizeCode(code) {
  return String(code ?? "")
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

export function reasonText(code) {
  if (code == null || String(code).trim() === "") return "no reason given";
  return REASON_COPY[code] || humanizeCode(code);
}

/** The one phrase for an unavailable section: "not available yet (reason)". */
export function notAvailableText(code) {
  return `not available yet (${reasonText(code)})`;
}

const KIND_LABELS = {
  buy_target: "Buy target",
  sell_high: "Sell high",
  waiver_move: "Waiver move",
  pick_action: "Pick move",
  aging_asset_risk: "Aging room",
  do_nothing: "No move",
};

/** Where each kind comes from, in reader's words (the raw owner travels too). */
const KIND_SOURCE = {
  buy_target: "Gameplan targets",
  sell_high: "Trade suggestions",
  waiver_move: "Perfect Waivers",
  pick_action: "Draft capital",
  aging_asset_risk: "Age portfolio",
  do_nothing: "Every assessed check",
};

export function kindLabel(kind) {
  return KIND_LABELS[kind] || humanizeCode(kind) || "Move";
}

// ── numbers ────────────────────────────────────────────────────────────

/**
 * A backend number for reading, or `null` when there is none.  Formatting
 * only: integers keep every digit; fractions keep two places, or two
 * significant figures when smaller, so a real non-zero never reads as "0".
 */
export function formatNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  if (Math.abs(value) < 0.01) return value.toPrecision(2);
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function dollars(value) {
  const n = formatNumber(value);
  return n == null ? null : `$${n}`;
}

const NOT_AVAILABLE = "not available";

/** One value for reading: null is "not available", never 0. */
function valueText(value) {
  if (value == null) return NOT_AVAILABLE;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return formatNumber(value) ?? NOT_AVAILABLE;
  if (typeof value === "string") return value.trim() === "" ? NOT_AVAILABLE : value;
  if (Array.isArray(value)) {
    if (value.length === 0) return "none";
    if (value.every((v) => v == null || ["string", "number", "boolean"].includes(typeof v))) {
      return value.map(valueText).join(", ");
    }
    return null;
  }
  return null;
}

/** "lineupGain" -> "Lineup gain". */
export function labelForKey(key) {
  const words = String(key ?? "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

// ── actions ────────────────────────────────────────────────────────────

function playerText(p) {
  if (!p || typeof p !== "object") return null;
  const name = p.name || p.playerId;
  if (!name) return null;
  return p.position ? `${name} (${p.position})` : String(name);
}

function namesText(list) {
  const names = (Array.isArray(list) ? list : []).filter((n) => n != null && String(n).trim());
  return names.length ? names.join(", ") : null;
}

/** The one-line "what" of an action, from its owner's subject verbatim. */
export function actionSubjectText(action) {
  const subject = action?.subject && typeof action.subject === "object" ? action.subject : {};
  switch (action?.kind) {
    case "buy_target":
      return playerText(subject) || "Player not named";
    case "sell_high": {
      const give = namesText(subject.give) || "players not named";
      const receive = namesText(subject.receive) || "players not named";
      return `Give ${give} for ${receive}`;
    }
    case "waiver_move": {
      const add = playerText(subject.add) || "player not named";
      const rel = subject.release;
      let release = "release not stated";
      if (rel && typeof rel === "object") {
        if (rel.kind === "openSpot") release = "into an open roster spot";
        else release = `release ${playerText(rel) || "a player not named"}`;
      }
      return `Add ${add}, ${release}`;
    }
    case "aging_asset_risk":
      return subject.position
        ? `${subject.position} room is older than league peers`
        : "A position room is older than league peers";
    case "do_nothing":
      return "Hold: no move cleared any assessed check";
    default:
      return kindLabel(action?.kind);
  }
}

const UNCERTAINTY_LABELS = {
  confidence: "Confidence",
  marketEdge: "Market edge",
  availability: "Availability",
  bidConfidence: "Bid confidence",
  solverProvenOptimal: "Solver proven optimal",
  solverStatus: "Solver",
  stopBandClass: "Stop rule",
  budgetState: "FAAB balance",
  ruleStatus: "Rule",
  youngCoreIndexStatus: "Young-core index",
};

function uncertaintyValue(key, value) {
  if (key === "coverage" && value && typeof value === "object") {
    const aged = formatNumber(value.aged);
    const total = formatNumber(value.total);
    return aged != null && total != null ? `${aged} of ${total} players aged` : NOT_AVAILABLE;
  }
  if (key === "notAssessed" && Array.isArray(value)) {
    return value.length ? value.map((n) => kindLabel(n?.kind)).join(", ") : "none";
  }
  if (value == null) return "not measured";
  return valueText(value);
}

/**
 * The action's uncertainty, as `[{label, text}]` in the owner's field order.
 * `null` reads "not measured" — an unmeasured edge is not a zero edge.
 */
export function actionUncertainty(action) {
  const u = action?.uncertainty && typeof action.uncertainty === "object" ? action.uncertainty : {};
  const out = [];
  for (const [key, value] of Object.entries(u)) {
    const text = uncertaintyValue(key, value);
    if (text == null) continue;
    const label =
      key === "coverage" ? "Age coverage" : key === "notAssessed" ? "Not assessed" : null;
    out.push({ key, label: label || UNCERTAINTY_LABELS[key] || labelForKey(key), text });
  }
  return out;
}

/**
 * The action's evidence fields that read as one line each, in the owner's
 * order.  Nested objects are left out (their identity is already in the
 * subject); a null stays "not available".
 */
export function actionEvidence(action) {
  const e = action?.evidence && typeof action.evidence === "object" ? action.evidence : {};
  const out = [];
  for (const [key, value] of Object.entries(e)) {
    const text = valueText(value);
    if (text == null) continue;
    out.push({ key, label: labelForKey(key), text });
  }
  return out;
}

/** The plan's actions in the payload's own order (backend-ranked). */
export function planActions(plan) {
  const actions = Array.isArray(plan?.actions) ? plan.actions : [];
  return actions
    .filter((a) => a && typeof a === "object")
    .map((a, i) => ({
      key: `${a.kind || "action"}-${a.rank ?? i}-${a.ownerRank ?? ""}`,
      rank: a.rank ?? null,
      kind: a.kind || "",
      kindLabel: kindLabel(a.kind),
      source: KIND_SOURCE[a.kind] || "Team plan",
      owner: a.owner || null,
      subject: actionSubjectText(a),
      reason: typeof a.reason === "string" && a.reason.trim() ? a.reason : null,
      uncertainty: actionUncertainty(a),
      evidence: actionEvidence(a),
    }));
}

// ── context ────────────────────────────────────────────────────────────

/** Roster freshness: `current` / `stale` / `unknown`, stated, never hidden. */
export function rosterFreshnessView(plan) {
  const rf = plan?.rosterFreshness && typeof plan.rosterFreshness === "object"
    ? plan.rosterFreshness
    : {};
  const state = rf.state === "current" || rf.state === "stale" ? rf.state : "unknown";
  const age = formatNumber(rf.ageHours);
  const ageText = age != null ? `fetched ${age} ${age === "1" ? "hour" : "hours"} ago` : null;
  const sourceText =
    rf.source === "last_good"
      ? "the last good snapshot"
      : rf.source === "live"
        ? "a live fetch"
        : null;
  let text;
  if (state === "current") text = ageText ? `Current, ${ageText}` : "Current";
  else if (state === "stale") {
    text = ["Stale", ageText, sourceText ? `from ${sourceText}` : null].filter(Boolean).join(", ");
  } else text = "Freshness unknown";
  return { state, stale: state === "stale", unknown: state === "unknown", text, ageText, sourceText };
}

function sectionOf(plan, key) {
  const s = plan?.[key];
  return s && typeof s === "object" ? s : null;
}

function postureText(section) {
  if (!section) return notAvailableText(null);
  if (section.available !== true) return notAvailableText(section.unavailableReason);
  const posture = section.posture && typeof section.posture === "object" ? section.posture : {};
  if (!posture.label) return NOT_AVAILABLE;
  const noEvidence = posture.evidence === "none" ? ", no competitiveness evidence" : "";
  return `${posture.label} (a classification, not a verdict${noEvidence})`;
}

function strengthText(section) {
  if (!section) return notAvailableText(null);
  if (section.available !== true) return notAvailableText(section.unavailableReason);
  const strength = section.strength && typeof section.strength === "object" ? section.strength : {};
  if (strength.available === false) return notAvailableText(strength.unavailableReason);
  const rank = formatNumber(strength.leagueRank);
  const of = formatNumber(section.teamCount);
  if (rank == null) return "league rank not available";
  return of != null ? `Rank ${rank} of ${of}` : `Rank ${rank}`;
}

function weaknessText(section) {
  if (!section) return notAvailableText(null);
  if (section.available !== true) return notAvailableText(section.unavailableReason);
  const w = section.weakness && typeof section.weakness === "object" ? section.weakness : {};
  if (!Array.isArray(w.urgentPositions)) return NOT_AVAILABLE;
  if (w.urgentPositions.length === 0) return "none urgent";
  const needs = Array.isArray(w.needs) ? w.needs : [];
  return w.urgentPositions
    .map((pos) => {
      const level = needs.find((n) => n?.position === pos)?.level;
      return level ? `${pos} (${level})` : String(pos);
    })
    .join(", ");
}

function coreAgeText(section) {
  if (!section) return notAvailableText(null);
  if (section.available !== true) return notAvailableText(section.unavailableReason);
  const p = section.portfolio && typeof section.portfolio === "object" ? section.portfolio : {};
  const age = formatNumber(p.valueWeightedCoreAge);
  return age != null ? `${age} (value-weighted)` : "not available (unmeasured)";
}

function draftCapitalText(section) {
  if (!section) return notAvailableText(null);
  const ownership = section.pickOwnership || {};
  const ownershipUnavailable = pickOwnershipUnavailableReason({
    pickOwnershipState: ownership.state,
    pickOwnershipReason: ownership.reason,
  });
  const suffix = ownershipUnavailable ? `; ${PICK_OWNERSHIP_UNAVAILABLE_LABEL.toLowerCase()}` : "";
  if (section.available !== true) return `${notAvailableText(section.unavailableReason)}${suffix}`;
  const year = section.upcomingDraftYear != null ? String(section.upcomingDraftYear) : "Upcoming";
  const parts = [];
  if (!section.upcomingClass) {
    parts.push(`${year} class ${notAvailableText(section.upcomingClassUnavailableReason)}`);
  } else {
    // The one client reader of draft-capital budgets decides "unavailable".
    const budgetsReason = draftCapitalBudgetsUnavailableReason({
      teamTotalsState: section.teamTotalsState,
      teamTotalsReason: section.teamTotalsReason,
      teamTotals: [section.upcomingClass],
    });
    const amount = dollars(section.upcomingClass.auctionDollars);
    parts.push(
      budgetsReason || amount == null
        ? draftCapitalBudgetsUnavailableText(budgetsReason || "no_team_budgets")
        : `${year} class ${amount}`,
    );
  }
  const allYears = section.allYears ? dollars(section.allYears.auctionDollars) : null;
  if (allYears != null) parts.push(`all classes ${allYears}`);
  if (section.freshness === "stale_while_revalidate") parts.push("last valid board");
  return `${parts.join("; ")}${suffix}`;
}

/** The context rows above the actions, each one an answer or a stated reason. */
export function planContextRows(plan) {
  return [
    { key: "posture", label: "Posture", text: postureText(sectionOf(plan, "posture")) },
    { key: "strength", label: "Team strength", text: strengthText(sectionOf(plan, "teamStrength")) },
    { key: "weakness", label: "Weak spots", text: weaknessText(sectionOf(plan, "teamWeakness")) },
    { key: "age", label: "Core age", text: coreAgeText(sectionOf(plan, "agePortfolio")) },
    { key: "draft", label: "Draft capital", text: draftCapitalText(sectionOf(plan, "draftCapital")) },
    { key: "rosters", label: "Rosters", text: rosterFreshnessView(plan).text },
  ];
}

// ── completeness ───────────────────────────────────────────────────────

function partsText(parts) {
  const list = (Array.isArray(parts) ? parts : [])
    .map((p) => (p?.position ? `${p.position}: ${reasonText(p.reason)}` : null))
    .filter(Boolean);
  return list.length ? list.join("; ") : null;
}

/**
 * `planState` plus what was not assessed, in words.  `incomplete` means an
 * absent move of those kinds is UNKNOWN, not "nothing to do".
 */
export function planStateView(plan) {
  const state = plan?.planState;
  const completeness =
    plan?.completeness && typeof plan.completeness === "object" ? plan.completeness : {};
  const unassessed = (Array.isArray(completeness.unassessed) ? completeness.unassessed : []).map(
    (u, i) => {
      const parts = partsText(u?.parts);
      return {
        key: `${u?.kind || "kind"}-${i}`,
        kindLabel: kindLabel(u?.kind),
        // A partly measured kind is not "unavailable": say what was missed.
        text:
          u?.reason === "partially_assessed"
            ? `only partly assessed${parts ? ` (${parts})` : ""}`
            : notAvailableText(u?.reason),
      };
    },
  );
  const notAssessable = (
    Array.isArray(completeness.notAssessable) ? completeness.notAssessable : []
  ).map((u, i) => ({
    key: `${u?.kind || "kind"}-${i}`,
    kindLabel: kindLabel(u?.kind),
    reason: reasonText(u?.reason),
  }));
  const unmapped = (
    Array.isArray(completeness.unmappedCandidates) ? completeness.unmappedCandidates : []
  ).map((u, i) => ({
    key: `${u?.kind || "kind"}-${i}`,
    label: labelForKey(u?.kind),
    count: formatNumber(u?.count),
  }));
  return {
    state: state === "actions" || state === "do_nothing" || state === "incomplete" ? state : "unknown",
    incomplete: state === "incomplete",
    doNothing: state === "do_nothing",
    unassessed,
    notAssessable,
    unmapped,
  };
}

/** Everything the panel renders, from one payload. */
export function buildTeamPlanView(plan) {
  const team = plan?.team && typeof plan.team === "object" ? plan.team : {};
  return {
    teamName: String(team.teamName || "").trim() || null,
    advisoryOnly: plan?.advisoryOnly === true,
    actions: planActions(plan),
    context: planContextRows(plan),
    freshness: rosterFreshnessView(plan),
    planState: planStateView(plan),
  };
}
