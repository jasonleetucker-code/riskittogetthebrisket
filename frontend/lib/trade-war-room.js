/**
 * trade-war-room — request building and presentation for the Trade War Room.
 *
 * DISPLAY ONLY.  Every recommendation, value, VA gap, best-ball impact,
 * lineup-entry rate and roster-capacity state is read verbatim from
 * `POST /api/trade/analyze` (`src/trade/analyze_trade.py`, the one decision
 * owner).  Nothing here scores, weighs or re-derives a trade — the same
 * materializer relationship `buildRows` has with the canonical contract.
 *
 * What lives here:
 *   - `tradeRequestForTeam`: which side of a two-side trade the selected team
 *     GIVES.  The ONE mapping both "Simulate impact" and the War Room use, so
 *     the two can never disagree about which way a trade points.
 *   - `analyzeRequestKey` / `validAnalyzePayload`: request identity, so a late
 *     answer for an earlier trade, team, league or mode can never publish.
 *   - formatters and labels.  Missing stays missing: formatters return null and
 *     callers render a word, never "0".
 */

export const RECOMMENDATION_LABELS = {
  MAKE: "Make the trade",
  LEAN_MAKE: "Lean make",
  TOO_CLOSE: "Too close / depends",
  LEAN_PASS: "Lean pass",
  PASS: "Pass",
};

export const RECOMMENDATION_TONES = {
  MAKE: "positive",
  LEAN_MAKE: "positive",
  TOO_CLOSE: "neutral",
  LEAN_PASS: "negative",
  PASS: "negative",
};

const PICK_NAME = /\d{4}/;

/**
 * The simulate/analyze body for the selected team.  The side holding more of
 * the team's rostered assets is the side it GIVES; with no match at all it
 * defaults to side A (Swap Sides flips it).  Owned picks send their ownership
 * label so the simulator removes that specific pick.
 */
export function tradeRequestForTeam(sides, rosterNames, teamName) {
  if (!Array.isArray(sides) || sides.length !== 2 || !teamName) return null;
  const owned = rosterNames instanceof Set ? rosterNames : new Set(rosterNames || []);
  const scores = sides.map((s) =>
    (s.assets || []).reduce((n, a) => n + (owned.has(a.name) ? 1 : 0), 0),
  );
  const mySide = scores[0] >= scores[1] ? 0 : 1;
  const otherSide = mySide === 0 ? 1 : 0;
  const label = (a) => (a.assetId && a.assetLabel ? a.assetLabel : a.name);
  const playersOut = [];
  const picksOut = [];
  for (const a of sides[mySide].assets || []) {
    if (PICK_NAME.test(String(a.name || ""))) picksOut.push(label(a));
    else playersOut.push(a.name);
  }
  const playersIn = [];
  const picksIn = [];
  for (const a of sides[otherSide].assets || []) {
    if (PICK_NAME.test(String(a.name || ""))) picksIn.push(label(a));
    else playersIn.push(a.name);
  }
  return { teamName, playersIn, playersOut, picksIn, picksOut, mySide };
}

/** Identity of one analysis question: trade, team, league and mode. */
export function analyzeRequestKey(request, leagueKey, useTeamContext) {
  if (!request) return "";
  return JSON.stringify([
    leagueKey || "",
    request.teamName || "",
    useTeamContext !== false,
    [...request.playersIn].sort(),
    [...request.playersOut].sort(),
    [...request.picksIn].sort(),
    [...request.picksOut].sort(),
  ]);
}

/**
 * A 200 is only an answer to THIS question when it echoes the league, the
 * mode and a packet.  Anything else is refused rather than rendered.
 */
export function validAnalyzePayload(body, { leagueKey = "", useTeamContext = true } = {}) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return false;
  const analysis = body.analysis;
  if (!analysis || typeof analysis !== "object") return false;
  if (!RECOMMENDATION_LABELS[analysis.recommendation]) return false;
  if (!analysis.lenses || typeof analysis.lenses !== "object") return false;
  if (leagueKey && body.leagueKey && body.leagueKey !== leagueKey) return false;
  const applied = body.teamContext?.applied;
  if (typeof applied !== "boolean" || applied !== (useTeamContext !== false)) return false;
  return true;
}

// ── Formatting ───────────────────────────────────────────────────────────

export function formatSignedPpg(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "±0.0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)}`;
}

export function formatPpg(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value.toFixed(1);
}

export function formatPctPoint(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return `${Math.round(value)}%`;
}

export function formatValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(value).toLocaleString("en-US");
}

export function formatSignedValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const r = Math.round(value);
  if (r === 0) return "±0";
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toLocaleString("en-US")}`;
}

// ── Lens summaries (labels only — every number is the packet's) ──────────

const UNAVAILABLE_WORDS = {
  asset_only_mode: "Not included in Asset-Only analysis",
  no_team_selected: "Pick your team to see roster impact",
  no_team_selected_or_uncomputable: "Pick your team to see roster impact",
  partial_projection_coverage: "Abstains — a traded player has no projection",
  season_unresolved: "No current-season projection applies",
  starter_slots_unresolved: "This league's starting slots did not resolve",
  projection_basis_no_projection_snapshot: "No league-scored projection snapshot yet",
  projection_basis_scoring_card_missing: "This league's scoring card is missing",
  roster_capacity_unavailable: "Roster capacity could not be computed",
  uncertain: "Cut count uncertain (taxi occupancy unknown)",
  unknown_limit: "This league's roster limit is unknown",
  no_priced_assets_either_side: "Neither side has a priced asset",
  not_computed: "Not computed",
};

export function unavailableText(reason) {
  if (!reason) return "Unavailable";
  if (UNAVAILABLE_WORDS[reason]) return UNAVAILABLE_WORDS[reason];
  if (String(reason).startsWith("error:")) return "Could not be computed right now";
  return `Unavailable (${String(reason).replace(/_/g, " ")})`;
}

export const FEASIBILITY_WORDS = {
  fits_cleanly: "Fits — no cut needed",
  uses_final_spot: "Fits — uses your last open spot",
  cut_required: "Roster full — cut required",
  resolves_overage: "Brings you back under the limit",
  reduces_overage: "Reduces your roster overage",
  worsens_overage: "Worsens your roster overage",
  overage_unchanged: "Roster stays over the limit",
};

export const DIRECTION_WORDS = {
  favors: "Favors you",
  opposes: "Against you",
  neutral: "Neutral",
};

export const ROLE_WORDS = {
  incoming: "In",
  outgoing: "Out",
  forcedDrop: "Cut",
  promoted: "More lineup time",
  displaced: "Less lineup time",
};

/** The player rows worth a line, in a stable reading order. */
export function rosterImpactRows(rosterDetail) {
  const order = { incoming: 0, outgoing: 1, forcedDrop: 2, promoted: 3, displaced: 4 };
  return [...(rosterDetail?.players || [])].sort(
    (a, b) => (order[a.role] ?? 9) - (order[b.role] ?? 9) || String(a.name).localeCompare(String(b.name)),
  );
}
