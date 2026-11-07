/**
 * gameplan-view.js — pure display helpers for the /rosters "Team Gameplan"
 * section (owner decision 2026-11-07, W20-F001).
 *
 * The owner of every number and label is the backend: `GET /api/gameplan`
 * (`src/api/gameplan.py`, engines in `src/roster_intel/`).  This module
 * reshapes served fields for render and nothing else — it computes no team
 * score, derives no posture, ranks nothing.
 *
 * ── What is surfaced ──────────────────────────────────────────────────
 *   posture        `competitivePosture` (canonical owner
 *                  `src/roster_intel/window.py::competitive_posture`)
 *   window         `roster.competitiveWindow.mostLikely` (closest of five
 *                  states; affinities are NOT probabilities)
 *   needs          `roster.weakness` through the one existing reader,
 *                  `roster-intelligence.js::teamNeedDetail`
 *   strengths      positions whose `roster.positions[].tradeableSurplus`
 *                  is a positive number (served order, no re-sort)
 *   opportunities  `targetPositions[]` with viability "viable" and
 *                  `targetPlayers[]` with `recommended: true`
 *
 * ── What is deliberately NOT surfaced ─────────────────────────────────
 *   `roster.values.market` / `consensus` / `leagueAdjusted` — measured as
 *   fake 0.0 for every team (master audit W20-F010) and `leagueAdjusted`
 *   is a withdrawn lens.  `partners` / `packages` — engine scores with
 *   declared evidence ceilings, not decisions.
 *
 * ── Missing is never zero ─────────────────────────────────────────────
 * Every section returns `state: "ok" | "unavailable"` with a reason; an
 * absent field is never coerced to 0, "none" or an empty-looking success.
 */

import { teamNeedDetail } from "@/lib/roster-intelligence";

export const POSTURE_LABELS = Object.freeze({
  PUSH: "Push — competing now",
  HOLD: "Hold — no clear direction",
  RETOOL: "Retool — reload around the current core",
  REBUILD: "Rebuild — building for later",
});

export const WINDOW_LABELS = Object.freeze({
  championship_contender: "Championship contender",
  playoff_contender: "Playoff contender",
  retool: "Retooling",
  productive_struggle: "Productive struggle",
  rebuild: "Rebuilding",
});

const UNAVAILABLE_REASONS = Object.freeze({
  league_bundle_not_warm: "the league build has not been prepared yet",
  team_not_in_posture_set: "this team is not in the league build",
  not_loaded: "the gameplan has not loaded",
});

function reasonText(reason) {
  return UNAVAILABLE_REASONS[reason] || (reason ? String(reason) : "not measured");
}

const unavailable = (reason) => ({ state: "unavailable", reason, reasonText: reasonText(reason) });

function isObj(v) {
  return v && typeof v === "object" && !Array.isArray(v);
}

function postureView(payload) {
  const p = payload?.competitivePosture;
  if (!isObj(p)) return unavailable("not_loaded");
  if (p.available === false) return unavailable(p.unavailableReason || "not_measured");
  const label = typeof p.label === "string" ? p.label : "";
  if (!label) return unavailable("not_measured");
  const measured = p.evidence === "measured";
  const conf = typeof p.confidence === "number" && Number.isFinite(p.confidence) ? p.confidence : null;
  return {
    state: "ok",
    label,
    text: POSTURE_LABELS[label] || label,
    // No competitiveness evidence is a HOLD by definition, and not a
    // confident one — say so instead of showing a number.
    measured,
    confidencePct: measured && conf !== null ? Math.round(conf * 100) : null,
  };
}

function windowView(payload) {
  const w = payload?.roster?.competitiveWindow;
  if (!isObj(w) || typeof w.mostLikely !== "string" || !w.mostLikely) {
    return unavailable("not_loaded");
  }
  return { state: "ok", key: w.mostLikely, text: WINDOW_LABELS[w.mostLikely] || w.mostLikely };
}

function strengthsView(payload) {
  const positions = payload?.roster?.positions;
  if (!isObj(positions)) return unavailable("not_loaded");
  const items = Object.values(positions)
    .filter((p) => isObj(p) && p.position)
    .filter((p) => typeof p.tradeableSurplus === "number" && p.tradeableSurplus > 0)
    .map((p) => ({
      position: String(p.position),
      surplusPlayers: (Array.isArray(p.surplusPlayers) ? p.surplusPlayers : [])
        .map(String)
        .slice(0, 3),
    }));
  return { state: "ok", items };
}

function opportunitiesView(payload) {
  const tp = payload?.targetPositions;
  const players = payload?.targetPlayers;
  if (!Array.isArray(tp) || !Array.isArray(players)) return unavailable("not_loaded");
  const positions = tp
    .filter((t) => isObj(t) && t.viability === "viable" && t.position)
    .map((t) => ({
      position: String(t.position),
      reason: typeof t.reason === "string" ? t.reason : "",
    }));
  // "noCandidates" is NOT MEASURED, never "nothing available".
  const notMeasured = tp
    .filter((t) => isObj(t) && t.viability === "noCandidates" && t.position)
    .map((t) => String(t.position));
  const recommendedPlayers = players
    .filter((t) => isObj(t) && t.recommended === true && t.name)
    .slice(0, 5)
    .map((t) => ({
      playerId: t.playerId == null ? "" : String(t.playerId),
      name: String(t.name),
      position: String(t.position || ""),
      reason: typeof t.reason === "string" ? t.reason : "",
    }));
  return { state: "ok", positions, notMeasured, players: recommendedPlayers };
}

/**
 * Reshape one `/api/gameplan` payload for render.  `ownerId`, when given,
 * must match the payload's team: the hook keeps the previous team's payload
 * while a new one loads, and one team's gameplan under another team's name
 * is worse than none.
 */
export const GAMEPLAN_TEAM_MISMATCH = "team_mismatch";

export function gameplanView(payload, { ownerId = "" } = {}) {
  if (!isObj(payload) || !isObj(payload.team)) {
    return { state: "unavailable", reason: "not_loaded", reasonText: reasonText("not_loaded") };
  }
  if (ownerId && String(payload.team.ownerId ?? "") !== String(ownerId)) {
    return { state: "unavailable", reason: GAMEPLAN_TEAM_MISMATCH, reasonText: "the loaded answer is for a different team" };
  }
  const needs = teamNeedDetail(
    { team: { ownerId: payload.team.ownerId, weakness: payload.roster?.weakness } },
    { ownerId: String(payload.team.ownerId ?? "") },
  );
  return {
    state: "ok",
    teamName: String(payload.team.teamName || ""),
    posture: postureView(payload),
    window: windowView(payload),
    needs,
    strengths: strengthsView(payload),
    opportunities: opportunitiesView(payload),
    // The payload carries no wall-clock timestamp (only a content hash in
    // `timing.sourceStamp`), so none is shown — a hash is not a freshness.
    asOf: typeof payload.timing?.asOf === "string" ? payload.timing.asOf : null,
  };
}
