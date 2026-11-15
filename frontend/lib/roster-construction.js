/**
 * roster-construction.js — pure helpers for the private /roster-construction
 * page (Roster Construction V1, owner directive 2026-10-30, flag
 * `roster_construction`, default OFF).
 *
 * DISPLAY ONLY.  Every number arrives from `GET /api/roster-construction`
 * (src/api/roster_construction_api.py over src/roster_intel/construction.py),
 * which solves each team-week with the existing exact lineup solver.  Nothing
 * here scores, ranks, values, optimizes or decides legality — the same
 * no-frontend-engine rule `buildRows` and `lib/idp-streaming.js` follow.  The
 * helpers (a) build the request URL, (b) classify a failure into a named
 * state, (c) turn a backend code into words and (d) format a backend number.
 * A missing number renders as "—" or a stated reason, never as 0.
 */

export const ROSTER_CONSTRUCTION_ENDPOINT = "/api/roster-construction";
export const ROSTER_CONSTRUCTION_FLAG = "roster_construction";
export const ROSTER_CONSTRUCTION_SCHEMA = "roster_construction.v1";

/** Display order for position groups; anything else sorts after, by name. */
const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DL", "LB", "DB", "DEF"];

export function sortPositions(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const idx = (p) => {
    const i = POSITION_ORDER.indexOf(String(p || ""));
    return i === -1 ? POSITION_ORDER.length : i;
  };
  return [...list].sort((a, b) => {
    const d = idx(a?.position) - idx(b?.position);
    return d !== 0
      ? d
      : String(a?.position || "").localeCompare(String(b?.position || ""));
  });
}

// ── request ────────────────────────────────────────────────────────────

/**
 * The request URL.  Without a `rosterId` the backend answers the league
 * overview (the team list) — or `feature_disabled` first, which makes that
 * team-less request the gate probe.  A team is never guessed.
 */
export function buildRosterConstructionUrl({ leagueKey, rosterId, season } = {}) {
  const params = [];
  if (leagueKey) params.push(`leagueKey=${encodeURIComponent(leagueKey)}`);
  if (season) params.push(`season=${encodeURIComponent(season)}`);
  if (rosterId != null && String(rosterId) !== "")
    params.push(`rosterId=${encodeURIComponent(String(rosterId))}`);
  return params.length
    ? `${ROSTER_CONSTRUCTION_ENDPOINT}?${params.join("&")}`
    : ROSTER_CONSTRUCTION_ENDPOINT;
}

// ── failures ───────────────────────────────────────────────────────────

const FAILURE_COPY = {
  data_not_ready: "The league data for this view is not ready yet.",
  unknown_league: "That league is not configured.",
  inactive_league: "That league is not active.",
  unknown_season: "No roster history exists for that season.",
  unknown_team: "That team is not in this league's roster history.",
  team_required: "Pick a team.",
  auth_required: "Sign in to use Roster Construction.",
  roster_construction_unavailable: "Roster Construction is not answering.",
};

const REASON_COPY = {
  wab_requires_best_ball:
    "the lineup marginal is only computed for best-ball leagues",
  posture_is_current_season_only:
    "competitive posture describes the current season, not a past one",
  requires_forward_projection: "it needs a forward projection (a later version)",
  trade_desk_dependency: "it depends on the Trade Desk (a later version)",
  league_snapshot_mismatch: "the loaded league snapshot is for a different league",
  posture_lookup_failed: "the competitive posture lookup failed",
  position_value_partially_priced:
    "some of this team's players at the position have no board value, so its total is a lower bound",
  contract_not_loaded: "the canonical board has not loaded",
};

/** Turn a snake_case code into words when there is no curated copy. */
export function humanizeCode(code) {
  const s = String(code ?? "").trim();
  if (!s) return "";
  const words = s.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function reasonText(code) {
  if (code == null || code === "") return "unstated";
  const s = String(code);
  return REASON_COPY[s] || humanizeCode(s).toLowerCase();
}

/**
 * Classify a non-OK answer.  `disabled` is the gate: `503 feature_disabled`
 * (flag off) or a backend without the route (plain 404).  Everything else is
 * a stated state, never a blank.
 */
export function classifyRosterConstructionFailure(status, body) {
  const code = body && typeof body === "object" ? String(body.error || "") : "";
  if (code === "feature_disabled" || (status === 404 && !code)) {
    return {
      kind: "disabled",
      code: code || "route_not_registered",
      flag: body?.flag || null,
    };
  }
  if (status === 401) {
    return { kind: "auth", code, message: FAILURE_COPY.auth_required };
  }
  let message =
    FAILURE_COPY[code] || (code ? `Unavailable (${code}).` : "Unavailable.");
  const reason = body && typeof body === "object" ? body.reason : null;
  if (reason) message = `${message.replace(/\.$/, "")} — ${reasonText(reason)}.`;
  if (status >= 500) return { kind: "unavailable", code, message };
  return { kind: "degraded", code, message };
}

/** A late answer for another league or team must never render. */
export function isStaleRosterConstructionPayload(
  payload,
  { leagueKey, rosterId } = {},
) {
  if (!payload || typeof payload !== "object") return true;
  if (leagueKey && payload.leagueKey && payload.leagueKey !== leagueKey)
    return true;
  if (
    rosterId != null &&
    String(rosterId) !== "" &&
    payload.team?.rosterId != null &&
    String(payload.team.rosterId) !== String(rosterId)
  ) {
    return true;
  }
  return false;
}

// ── formatting (unit formatting only — never arithmetic on a value) ────

const isNum = (v) => v != null && v !== "" && Number.isFinite(Number(v));

/** Fantasy points with one decimal, or null. */
export function fmtPoints(v) {
  return isNum(v) ? Number(v).toFixed(1) : null;
}

/** Dynasty value as a whole number with separators, or null. */
export function fmtValue(v) {
  return isNum(v) ? Math.round(Number(v)).toLocaleString("en-US") : null;
}

/** A 0..1 share as a whole percent, or null. */
export function fmtShare(v) {
  return isNum(v) ? `${Math.round(Number(v) * 100)}%` : null;
}

/** A 0..1 ratio with two decimals, or null. */
export function fmtRatio(v) {
  return isNum(v) ? Number(v).toFixed(2) : null;
}

/** Rank beside ITS OWN denominator: "10 of 10", or null. */
export function fmtRank(rank, of) {
  if (!isNum(rank)) return null;
  return isNum(of) ? `${rank} of ${of}` : `${rank}`;
}

/** A backend percentile (1 = best of the league, 0 = worst) as "90th". */
export function fmtPercentile(v) {
  if (!isNum(v)) return null;
  const n = Math.round(Number(v) * 100);
  const mod100 = n % 100;
  const suffix =
    mod100 >= 11 && mod100 <= 13
      ? "th"
      : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
  return `${n}${suffix}`;
}

/** "5 of 6" from a {value, of} count, or null. */
export function fmtCountOf(count) {
  if (!count || !isNum(count.value)) return null;
  return isNum(count.of) ? `${count.value} of ${count.of}` : `${count.value}`;
}

/** Ownership spells as "Wk 1–6, 9–17", or null. */
export function fmtSpells(spells) {
  if (!Array.isArray(spells) || spells.length === 0) return null;
  return spells
    .map((s) =>
      s.fromWeek === s.toWeek ? `Wk ${s.fromWeek}` : `Wk ${s.fromWeek}–${s.toWeek}`,
    )
    .join(", ")
    .replace(/, Wk /g, ", ");
}

/** "Wk 3, 7" from a list of weeks, or null. */
export function fmtWeeks(weeks) {
  if (!Array.isArray(weeks) || weeks.length === 0) return null;
  return `Wk ${weeks.join(", ")}`;
}

// ── labelled concepts ──────────────────────────────────────────────────

/**
 * The lineup basis shown in the header.  The backend stamps `lineupBasis`
 * when it has one; otherwise it is read from `rules.lineupMode`.  A league
 * that submits lineups is labelled "hypothetical optimal" — the production
 * ranks here are what the roster COULD have scored, not what was submitted.
 */
export function lineupBasisText(payload) {
  const stamped = payload?.lineupBasis ?? payload?.rules?.lineupBasis;
  const mode = String(payload?.rules?.lineupMode || "").toLowerCase();
  const key = String(stamped || mode || "").toLowerCase();
  if (
    key === "best_ball" ||
    key === "optimal_best_ball" ||
    key === "host_best_ball_optimal"
  ) {
    return {
      label: "Best ball",
      detail: "The league's own optimal legal lineup each week.",
      hypothetical: false,
    };
  }
  if (
    key === "hypothetical_optimal" ||
    key === "managed" ||
    key === "manual" ||
    key === "submitted"
  ) {
    return {
      label: "Hypothetical optimal",
      detail:
        "This league submits lineups. Ranks are the optimal legal lineup each roster could have started, not the lineups that were submitted.",
      hypothetical: true,
    };
  }
  if (key === "unverified_assumed_optimal" || key === "unverified") {
    return {
      label: "Assumed optimal",
      detail:
        "Whether this league is best ball could not be verified from its settings. Ranks assume the optimal legal lineup each week; they are not checked against the host.",
      hypothetical: false,
      unverified: true,
    };
  }
  return {
    label: "Unknown",
    detail: "The league's lineup mode was not stated.",
    hypothetical: false,
  };
}

const SCENARIO_COPY = {
  end_roster_plus_player:
    "Replays the team's final-week roster across every week, plus this player. It is ex-post: realized points, no transaction costs, no roster-cap effects, and not a decision evaluation.",
};

export function scenarioText(scenario) {
  if (!scenario) return null;
  return SCENARIO_COPY[scenario] || humanizeCode(scenario);
}

const POOL_SCOPE_COPY = {
  rostered: "players on any roster in the league (free agents are not in the pool)",
};

export function poolScopeText(scope) {
  if (!scope) return null;
  return POOL_SCOPE_COPY[scope] || humanizeCode(scope).toLowerCase();
}

const TAG_COPY = {
  injured: "Injured",
  developmental: "Developmental",
  productive_veteran: "Productive veteran",
  low_contribution: "Low contribution",
};

export function tagLabel(tag) {
  return TAG_COPY[tag] || humanizeCode(tag);
}

const SLOT_COPY = {
  FLEX: "FLEX",
  SUPER_FLEX: "Superflex",
};

export function slotLabel(slot) {
  return SLOT_COPY[slot] || String(slot);
}

// ── diagnoses ──────────────────────────────────────────────────────────

const RULE_TITLES = {
  "RC-D1": "Value and production disagree",
  "RC-D2": "Strong starters, thin coverage",
  "RC-D3": "Contender carrying low-opportunity bench players",
  "RC-D4": "Reliance on aging starters",
  "RC-D5": "Developmental roster, future starting coverage",
  "RC-D6": "Valuable asset, low lineup marginal here",
  "RC-D7": "Tier-up / tier-down opportunity",
};

export function ruleTitle(rule) {
  return RULE_TITLES[rule] || humanizeCode(rule);
}

/**
 * The state of one diagnosis as {label, tone}.  NO ACTION is a first-class
 * answer, and a rule that was not evaluated says so rather than passing.
 */
export function diagnosisState(d) {
  if (!d) return { label: "Unknown", tone: "neutral" };
  if (d.status === "not_evaluated")
    return { label: "Not evaluated", tone: "outline" };
  if (d.status === "not_fired") return { label: "Not triggered", tone: "outline" };
  if (d.verdict === "REVIEW") return { label: "Review", tone: "warning" };
  if (d.verdict === "NO_ACTION") return { label: "No action", tone: "neutral" };
  return { label: humanizeCode(d.verdict) || "Unknown", tone: "neutral" };
}

export function overallVerdictText(overall) {
  if (!overall || !overall.verdict) {
    return { label: "Unknown", note: "No overall verdict was stated." };
  }
  if (overall.verdict === "NO_ACTION") {
    return {
      label: "No action",
      note: "Nothing the rules checked calls for review. No action is a valid result.",
    };
  }
  if (overall.verdict === "REVIEW") {
    return {
      label: "Review",
      note: "At least one rule fired. Each is evidence to read, not a transaction.",
    };
  }
  return { label: humanizeCode(overall.verdict), note: "" };
}

function evidenceValueText(key, value, names) {
  if (value == null) return "—";
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return names?.get(value) || value;
  if (Array.isArray(value)) {
    const rankPair =
      /rank$/i.test(key) &&
      value.length === 2 &&
      value.every((v) => typeof v === "number");
    if (rankPair) return `${value[0]} of ${value[1]}`;
    return (
      value.map((v) => evidenceValueText(key, v, names)).join("; ") || "none"
    );
  }
  if (typeof value === "object") {
    // A {value, of} count reads "5 of 6".
    const keys = Object.keys(value);
    if (
      keys.length === 2 &&
      keys.includes("value") &&
      keys.includes("of") &&
      typeof value.value === "number"
    ) {
      return `${value.value} of ${value.of}`;
    }
    const parts = Object.entries(value)
      .filter(([k]) => k !== "playerId")
      .map(
        ([k, v]) =>
          `${humanizeCode(k).toLowerCase()} ${evidenceValueText(k, v, names)}`,
      )
      .join(", ");
    if (value.playerId != null) {
      const who = names?.get(String(value.playerId)) || String(value.playerId);
      return parts ? `${who} (${parts})` : who;
    }
    return parts;
  }
  return String(value);
}

/**
 * An evidence object as labelled rows; every key the backend sent shows.
 * `names` (optional Map from `playerNameIndex`) resolves player ids to names.
 */
export function evidenceRows(evidence, names) {
  if (!evidence || typeof evidence !== "object") return [];
  return Object.entries(evidence).map(([key, value]) => ({
    key,
    label: humanizeCode(key),
    text: evidenceValueText(key, value, names),
  }));
}

/** Index of players by id, for resolving ids named in evidence. */
export function playerNameIndex(players) {
  const out = new Map();
  for (const p of Array.isArray(players) ? players : []) {
    if (p?.playerId != null) out.set(String(p.playerId), p.name || String(p.playerId));
  }
  return out;
}

/**
 * Join production and value onto one row per position for the mismatch view.
 * Pairing only — each side keeps its own rank, denominator and as-of.  No
 * difference is computed: the two denominators differ on purpose.
 */
export function mismatchRows(positions, diagnoses) {
  const byPos = new Map();
  for (const d of Array.isArray(diagnoses) ? diagnoses : []) {
    if (d?.rule === "RC-D1" && d.position) byPos.set(d.position, d);
  }
  return sortPositions(positions).map((p) => ({
    position: p.position,
    production: p.production || null,
    value: p.value || null,
    diagnosis: byPos.get(p.position) || null,
  }));
}

/**
 * The rules the backend did not evaluate, as [{rule, reason}].  The backend
 * sends "RC-D5:reason" strings; {rule, reason} objects are read too.
 */
export function rulesNotEvaluated(overall) {
  const list = Array.isArray(overall?.rulesNotEvaluated)
    ? overall.rulesNotEvaluated
    : [];
  return list.map((e) => {
    if (e && typeof e === "object") return { rule: e.rule, reason: e.reason };
    const [rule, ...rest] = String(e).split(":");
    return { rule, reason: rest.join(":") || null };
  });
}

/** Rule ids that were evaluated (fired or not), from the diagnoses sent. */
export function rulesEvaluated(overall, diagnoses) {
  if (Array.isArray(overall?.rulesEvaluated)) return overall.rulesEvaluated;
  const out = new Set();
  for (const d of Array.isArray(diagnoses) ? diagnoses : []) {
    if (d?.rule && d.status !== "not_evaluated") out.add(d.rule);
  }
  return [...out].sort();
}

/** "Wk 3 (bye)" style entries from an exclusions list of numbers or {week, reason}. */
export function exclusionText(e) {
  if (e == null) return "";
  if (typeof e === "number") return `Week ${e}`;
  if (typeof e === "object") {
    const who = e.rosterId != null ? `Roster ${e.rosterId}, ` : "";
    const wk = e.week != null ? `week ${e.week}` : "a week";
    return `${who}${wk}${e.reason ? `: ${reasonText(e.reason)}` : ""}`;
  }
  return String(e);
}

/** Why a player's lineup marginal is unknown, from `unavailableWeeks`. */
export function marginalUnavailableText(marg) {
  const u = marg?.unavailableWeeks;
  if (!u || typeof u !== "object") return null;
  const parts = Object.entries(u).map(
    ([reason, n]) => `${reasonText(reason)} (${n} week${n === 1 ? "" : "s"})`,
  );
  return parts.length ? parts.join("; ") : null;
}
