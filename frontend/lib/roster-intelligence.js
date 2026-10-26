/**
 * roster-intelligence.js — pure display helpers for the canonical
 * Team Strength surface served by `GET /api/roster/intelligence`.
 *
 * The canonical owner is `src/roster_intel/strength.py` (feature
 * inventory row 1.1), reached through `src/api/roster_intelligence.py`.
 * Every number this module hands to a component was computed there.
 * Nothing here sums player values, weights anything, or classifies a
 * team — the whole point of the migration that introduced this file is
 * that `/rosters` stopped doing exactly that.
 *
 * The rule it exists to keep, from CLAUDE.md: "There is no frontend
 * ranking engine, period — not even a fallback." A materializer may
 * reshape and format a backend number; it may not produce one.
 *
 * ── Three quantities, deliberately not merged ─────────────────────────
 * `V1-35` says the named team quantities "may not collapse into one
 * team score", and the backend already publishes them side by side for
 * that reason. This module keeps them apart in the vocabulary it hands
 * the UI:
 *
 *   `total`            THE Team Strength number — the meaningful core
 *   `fullRosterValue`  the whole-roster PORTFOLIO sum, named separately
 *                      because a 58-man best-ball roster books bench
 *                      player #40 at full market value
 *   `starterValue` /   the split inside the core; a diagnostic about
 *   `reserveValue`     lineup structure, not a second strength
 *
 * ── Missing is never zero ─────────────────────────────────────────────
 * Four absences are carried through as absences rather than numbers,
 * because the backend went to some trouble to distinguish them:
 *
 *   `available: false`   the lineup could not be read. NOT a strength
 *                        of 0 — see `build_team_strength`'s refusal
 *                        branch, which propagates the core's reason.
 *   `leagueRank: null`   NOT MEASURED, never "last". `rank_team_strengths`
 *                        excludes unreadable rosters from the ranking
 *                        population instead of ranking them bottom.
 *   `unpricedCount > 0`  part of the roster has no canonical value, so
 *                        the total is a statement about the rest.
 *   `unfilledStarterSlots`  the core could not fill the league's lineup,
 *                        so part of the strength is UNMEASURED.
 */

/** Rendered wherever a rank exists as a concept but was not measured. */
export const NOT_MEASURED = "Not measured";

/**
 * Classify a non-2xx `/api/roster/intelligence` response into the states
 * the page renders distinctly.
 *
 * Returns null for 2xx; otherwise `{ kind, message }` with kind one of
 * "not_ready" | "team_required" | "team_not_found" | "league" | "auth" |
 * "unavailable" | "error".
 *
 * `team_required` and `team_not_found` are separated from the generic
 * error on purpose: both are fixable by the user (pick a team / pick a
 * different one) and neither means the engine is broken.
 */
export function classifyRosterIntelligenceFailure(status, body) {
  if (status >= 200 && status < 300) return null;
  const code = body && typeof body === "object" ? body.error : "";
  const message =
    (body && typeof body === "object" && (body.message || body.detail)) || "";
  if (status === 401) {
    return { kind: "auth", message: "Sign in to see roster intelligence." };
  }
  if (code === "team_required") return { kind: "team_required", message };
  if (code === "team_not_found") return { kind: "team_not_found", message };
  if (code === "unknown_league" || code === "inactive_league" || code === "no_leagues_configured") {
    return { kind: "league", message };
  }
  if (code === "data_not_ready") return { kind: "not_ready", message };
  if (code === "roster_intelligence_unavailable") {
    return { kind: "unavailable", message };
  }
  return { kind: "error", message: message || `HTTP ${status}` };
}

/** A finite number, or null. Never a coerced 0 — that is the defect this
 *  whole surface exists to remove. */
function num(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * The league's Team Strength ladder, from the payload's own
 * `leagueContext`.
 *
 * The backend already ordered it (`_league_context_order`: ranked teams
 * first, best first, unranked last on an explicit `inf`). We preserve
 * that order rather than re-sorting — re-sorting here would be a second
 * opinion about the ladder, and a `?? 0` in the comparator is precisely
 * how an unranked team becomes #1. Rows are stamped `measured` so a
 * consumer can render the absence rather than infer it from a null.
 */
export function teamStrengthLadder(payload, { myOwnerId = "" } = {}) {
  const context = Array.isArray(payload?.leagueContext) ? payload.leagueContext : [];
  return context.map((t) => {
    const rank = num(t?.strengthRank);
    return {
      ownerId: String(t?.ownerId ?? ""),
      teamName: String(t?.teamName ?? ""),
      rank,
      measured: rank !== null,
      rankLabel: rank === null ? NOT_MEASURED : `#${rank}`,
      strengthTotal: num(t?.strengthTotal),
      youngCoreIndex: num(t?.youngCoreIndex),
      valueWeightedCoreAge: num(t?.valueWeightedCoreAge),
      isMe: Boolean(myOwnerId) && String(t?.ownerId ?? "") === String(myOwnerId),
    };
  });
}

/**
 * The requested team's canonical strength block, reshaped for render.
 *
 * Returns null when the payload carries no team — distinct from a team
 * whose strength is `available: false`, which is a real answer with a
 * real reason and is returned with `available: false`.
 */
export function teamStrengthDetail(payload) {
  const team = payload?.team;
  const strength = team?.strength;
  if (!strength || typeof strength !== "object") return null;

  const order = Array.isArray(strength.positionOrder) ? strength.positionOrder : [];
  const byPosition = Array.isArray(strength.byPosition) ? strength.byPosition : [];
  // The backend declares the display order and the groups together.
  // We render the groups it published, in the order it published them —
  // no local group list, so a league running an exotic slot cannot lose
  // a column and FLEX cannot become one (a FLEX-seated RB is summed
  // under RB by `MeaningfulCore.by_position`).
  const positionIndex = new Map(byPosition.map((p) => [String(p?.position ?? ""), p]));
  const positions = (order.length ? order : byPosition.map((p) => p?.position))
    .map((name) => positionIndex.get(String(name)))
    .filter(Boolean)
    .map((p) => {
      const rank = num(p?.leagueRank);
      return {
        position: String(p?.position ?? ""),
        value: num(p?.value),
        // Counts are `null` when the payload does not carry them, NOT
        // 0.  `0` is a real answer here — a group with no reserves —
        // so coercing an absent count into it would publish "this team
        // has no reserve at RB" on the strength of a missing field.
        count: num(p?.count),
        starterValue: num(p?.starterValue),
        starterCount: num(p?.starterCount),
        reserveValue: num(p?.reserveValue),
        reserveCount: num(p?.reserveCount),
        rank,
        rankLabel: rank === null ? NOT_MEASURED : `#${rank}`,
      };
    });

  const unfilledStarterSlots = Array.isArray(strength.unfilledStarterSlots)
    ? strength.unfilledStarterSlots.map(String)
    : [];
  const unfilledReserveSlots = Array.isArray(strength.unfilledReserveSlots)
    ? strength.unfilledReserveSlots.map(String)
    : [];
  const rank = num(strength.leagueRank);

  return {
    ownerId: String(team?.ownerId ?? ""),
    teamName: String(team?.teamName ?? ""),
    rosteredCount: num(team?.rosteredCount),
    available: strength.available !== false,
    unavailableReason: strength.unavailableReason || "",
    // Read verbatim. Not rounded here either: the backend already
    // rounded to 3dp and a second rounding rule is a second opinion.
    total: num(strength.total),
    starterValue: num(strength.starterValue),
    reserveValue: num(strength.reserveValue),
    // Named separately from `total` everywhere it is shown.
    fullRosterValue: num(strength.fullRosterValue),
    positions,
    // Same rule: `0` means "we read the roster and everything is
    // priced", `null` means the payload never said.  The caveat below
    // fires on `> 0`, so an unknown count makes no claim either way
    // rather than asserting a clean roster.
    unpricedCount: num(strength.unpricedCount),
    unfilledStarterSlots,
    unfilledReserveSlots,
    isComplete: strength.isComplete === true,
    rank,
    rankLabel: rank === null ? NOT_MEASURED : `#${rank}`,
    percentile: num(strength.leaguePercentile),
  };
}

/**
 * Why a total is only part of the story, as a list of plain sentences.
 *
 * Empty when the strength is complete. Derived from the backend's own
 * completeness fields; it invents no threshold and no severity.
 */
export function strengthCaveats(detail) {
  if (!detail || !detail.available) return [];
  const out = [];
  if (detail.unfilledStarterSlots.length) {
    out.push(
      `${detail.unfilledStarterSlots.length} starting ${
        detail.unfilledStarterSlots.length === 1 ? "slot" : "slots"
      } could not be filled (${detail.unfilledStarterSlots.join(", ")}), so part of ` +
        "this team's strength is unmeasured rather than low.",
    );
  }
  if (detail.unfilledReserveSlots.length) {
    out.push(
      `${detail.unfilledReserveSlots.length} reserve ${
        detail.unfilledReserveSlots.length === 1 ? "slot" : "slots"
      } could not be filled (${detail.unfilledReserveSlots.join(", ")}).`,
    );
  }
  if (detail.unpricedCount > 0) {
    out.push(
      `${detail.unpricedCount} rostered ${
        detail.unpricedCount === 1 ? "player has" : "players have"
      } no canonical value, so ${
        detail.unpricedCount === 1 ? "it is" : "they are"
      } excluded from the total rather than counted as zero.`,
    );
  }
  return out;
}

/** The Sleeper ownerId for a team NAME, which is what `settings.selectedTeam`
 *  stores. Returns "" when the name is unknown — the endpoint then falls back
 *  to the session's own team, which is the correct default. */
export function ownerIdForTeamName(sleeperTeams, teamName) {
  if (!teamName) return "";
  const match = (sleeperTeams || []).find((t) => t?.name === teamName);
  return match?.ownerId ? String(match.ownerId) : "";
}

/** Whole-number display for an uncapped aggregate. Aggregates may exceed
 *  9999 (inventory row 7.5) and are never clamped here. */
export function formatStrengthValue(value) {
  if (value === null || value === undefined) return "—";
  return Math.round(value).toLocaleString();
}

// ── Team Weakness / Need Priority (C2-WEAK-01) ──────────────────────────
//
// The canonical owner is `src/roster_intel/weakness.py` (inventory row
// 1.2), served as `team.weakness` and — projected — as each
// `leagueContext[].needLevelByPosition` / `urgentPositions`. Nothing below
// classifies a position: levels, priorities, reasons and the worst-first
// order are read verbatim. `/rosters`' Trade Targets card used to rank
// "Weakest / Strongest" itself from raw full-roster `byGroup` sums against
// the league average — a page-local need rule that could name a room weak
// while the lineup solve says it starts two top-12 players.

/** Display words for the owner's need levels. A label, not a threshold. */
export const NEED_LEVEL_LABELS = Object.freeze({
  critical: "Critical need",
  high: "High need",
  moderate: "Moderate need",
  none: "No need",
});

/** Human sentence for a backend `unavailableReason` code. Unknown codes
 *  are shown as-is rather than hidden. */
function describeUnavailable(reason) {
  const text = {
    team_not_in_contract: "this team has no roster in the loaded league data",
    no_rosters_loaded: "no league rosters are loaded yet",
    unknown_team_count: "the league's team count is unknown",
    team_mismatch: "the loaded answer is for a different team",
    not_loaded: "roster intelligence has not loaded",
    droppability_not_requested: "the cut ladder was not requested",
    droppability_missing: "the response carried no cut ladder for this team",
  }[reason];
  return text || (reason ? String(reason) : "not measured");
}

/**
 * The requested team's canonical need answer, reshaped for render.
 *
 * Always returns an object with `state`:
 *   "ok"          — `needs` (worst-first, verbatim), `needPositions`
 *                   (positions whose served level is not "none", in the
 *                   owner's order), `strongest` (served positional
 *                   strength ranks, best first)
 *   "unavailable" — `reason` / `reasonText`. Never accompanied by a
 *                   fallback answer: an unmeasured need is not "no need".
 *
 * `ownerId`, when given, must match the payload's team — the hook keeps
 * the previous team's payload while a new one loads, and rendering one
 * team's needs under another team's name is worse than rendering none.
 */
export function teamNeedDetail(payload, { ownerId = "" } = {}) {
  const team = payload?.team;
  const unavailable = (reason) => ({
    state: "unavailable",
    reason,
    reasonText: describeUnavailable(reason),
    needs: [],
    needPositions: [],
    strongest: [],
  });
  if (!team || typeof team !== "object") return unavailable("not_loaded");
  if (ownerId && String(team.ownerId ?? "") !== String(ownerId)) {
    return unavailable("team_mismatch");
  }
  const weakness = team.weakness;
  if (!weakness || typeof weakness !== "object") return unavailable("not_loaded");
  if (weakness.available === false) {
    return unavailable(weakness.unavailableReason || "not_measured");
  }
  const needs = (Array.isArray(weakness.needs) ? weakness.needs : [])
    .filter((n) => n && typeof n === "object" && n.position)
    .map((n) => ({
      position: String(n.position),
      level: String(n.level || ""),
      label: NEED_LEVEL_LABELS[n.level] || String(n.level || ""),
      priority: num(n.priority),
      reasons: Array.isArray(n.reasons) ? n.reasons.map(String) : [],
      unknownRungs: num(n.unknownRungs),
    }));
  // The served order IS the priority order (`ordered_needs`); a
  // position the owner rates "none" is not a need however it compares.
  const needPositions = needs.filter((n) => n.level && n.level !== "none");
  const strength = teamStrengthDetail(payload);
  const strongest = (strength?.positions || [])
    .filter((p) => p.rank !== null)
    .sort((a, b) => a.rank - b.rank || a.position.localeCompare(b.position))
    .map((p) => ({ position: p.position, rank: p.rank, rankLabel: p.rankLabel }));
  return {
    state: "ok",
    reason: "",
    reasonText: "",
    needs,
    needPositions,
    urgentPositions: Array.isArray(weakness.urgentPositions)
      ? weakness.urgentPositions.map(String)
      : [],
    strongest,
  };
}

/**
 * `Map<ownerId, { needLevelByPosition, urgentPositions, measured }>` from
 * the payload's `leagueContext` — every OTHER team's canonical need answer.
 * `measured: false` when the backend stamped `null` (that team's weakness
 * was not measured); a consumer must skip such a team, not guess.
 */
export function leagueNeedIndex(payload) {
  const out = new Map();
  const context = Array.isArray(payload?.leagueContext) ? payload.leagueContext : [];
  for (const row of context) {
    const ownerId = String(row?.ownerId ?? "");
    if (!ownerId) continue;
    const levels = row?.needLevelByPosition;
    const measured = Boolean(levels) && typeof levels === "object";
    out.set(ownerId, {
      measured,
      needLevelByPosition: measured ? { ...levels } : null,
      urgentPositions:
        measured && Array.isArray(row?.urgentPositions) ? row.urgentPositions.map(String) : [],
    });
  }
  return out;
}

// ── Droppability (C2-DROP-01) ───────────────────────────────────────────

/**
 * The requested team's canonical cut ladder, from
 * `GET /api/roster/intelligence?droppability=1` — owner
 * `src/draft/displacement.py` via `src/roster_intel/droppability.py`.
 *
 * Every rung is a release the exact lineup solver has validated, in the
 * owner's cheapest-first order; players the lineup needs are NOT rungs.
 * Returns `{ state: "ok", rungs, undroppableCount }` or
 * `{ state: "unavailable", reason, reasonText }`. No fallback ranking of
 * the roster by raw value exists — that was the shape #1017 deleted from
 * the backend, and /waivers carried a copy of it.
 */
export function teamCutLadder(payload, { ownerId = "" } = {}) {
  const unavailable = (reason) => ({
    state: "unavailable",
    reason,
    reasonText: describeUnavailable(reason),
    rungs: [],
    undroppableCount: null,
  });
  const team = payload?.team;
  if (!team || typeof team !== "object") return unavailable("not_loaded");
  if (ownerId && String(team.ownerId ?? "") !== String(ownerId)) {
    return unavailable("team_mismatch");
  }
  if (payload?.droppabilityIncluded !== true) return unavailable("droppability_not_requested");
  const ladder = team.droppability?.cutLadder;
  if (!ladder || !Array.isArray(ladder.rungs)) return unavailable("droppability_missing");
  const rungs = ladder.rungs
    .filter((r) => r && typeof r === "object" && r.name)
    .map((r) => ({
      rung: num(r.rung),
      playerId: String(r.playerId ?? ""),
      name: String(r.name),
      position: String(r.position || "").toUpperCase(),
      baseValue: num(r.baseValue),
      valueBasis: String(r.valueBasis || ""),
      effectiveCutCost: num(r.effectiveCutCost),
    }));
  return {
    state: "ok",
    reason: "",
    reasonText: "",
    rungs,
    undroppableCount: Array.isArray(ladder.undroppable) ? ladder.undroppable.length : null,
  };
}
