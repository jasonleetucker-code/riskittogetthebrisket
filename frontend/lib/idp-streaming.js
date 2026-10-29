/**
 * idp-streaming.js — pure helpers for the "Weekly IDP Streaming" mode of the
 * private /waiver-advisor page (owner directive 2026-10-29).
 *
 * DISPLAY ONLY.  Every number arrives from `POST /api/waiver/streaming`
 * (`src/waivers/streaming.py`), which composes the existing owners: the
 * league-scored weekly projections, the dynasty drop assessment, the exact
 * lineup solver (through the streaming solver), the FAAB engine and roster
 * capacity.  Nothing here projects, scores, values, bids, ranks, optimizes or
 * decides legality — the same no-frontend-engine rule `buildRows` and
 * `lib/waiver-advisor.js` follow.  The helpers only (a) build the request body,
 * (b) classify a failure into a named state, (c) turn a backend code into
 * words and (d) format a backend number.  A missing number renders as its
 * stated reason, never as 0.
 */

export const IDP_STREAMING_ENDPOINT = "/api/waiver/streaming";
export const IDP_STREAMING_FLAG = "idp_streaming";

export const STREAMING_POSITION_OPTIONS = [
  { value: "ALL", label: "All IDP" },
  { value: "DL", label: "DL" },
  { value: "LB", label: "LB" },
  { value: "DB", label: "DB" },
];

export const STREAMING_HORIZON_OPTIONS = [1, 2, 3, 4].map((n) => ({
  value: n,
  label: `${n} wk`,
}));

/** Streaming capacity choices.  The backend bounds it (config `maxCapacity`). */
export const STREAMING_CAPACITY_OPTIONS = [0, 1, 2, 3, 4, 5, 6, 7];

/** Week choices: "current" lets the backend resolve the NFL week itself. */
export const STREAMING_WEEK_OPTIONS = [
  { value: "", label: "Current week" },
  ...Array.from({ length: 18 }, (_, i) => ({
    value: String(i + 1),
    label: `Week ${i + 1}`,
  })),
];

/**
 * The POST body.  The team is never guessed: without an owner id the body
 * carries none, and the backend answers `team_required` — or, when either flag
 * is off, `feature_disabled` FIRST.  That makes the team-less request the
 * gate probe.  The dynasty budget is passed as the user typed it; the backend
 * validates it (`bad_dynastyBudget`).
 */
export function buildStreamingRequest({
  leagueKey,
  ownerId,
  week,
  horizonWeeks,
  position,
  capacity,
  dynastyBudget,
} = {}) {
  const body = {};
  if (leagueKey) body.leagueKey = leagueKey;
  if (ownerId) body.teamOwnerId = String(ownerId);
  if (week !== undefined && week !== null && week !== "")
    body.week = Number(week);
  if (horizonWeeks != null) body.horizonWeeks = Number(horizonWeeks);
  if (position) body.position = position;
  if (capacity !== undefined && capacity !== null && capacity !== "") {
    body.capacity = Number(capacity);
  }
  if (
    dynastyBudget !== undefined &&
    dynastyBudget !== null &&
    dynastyBudget !== ""
  ) {
    body.dynastyBudget = Number(dynastyBudget);
  }
  return body;
}

const FAILURE_COPY = {
  data_not_ready: "This league's rosters haven't loaded yet.",
  no_rosters_loaded: "No rosters are loaded for this league yet.",
  unknown_team: "That team isn't in this league's rosters.",
  team_required: "Pick your team to see streaming advice.",
  starter_slots_unknown:
    "This league's starting lineup slots are unknown, so lineup gains cannot be computed.",
  not_in_season:
    "It is not the NFL season, so there is no current week to stream. Pick a week.",
  projections_refused:
    "Weekly projections are unavailable for this league and week (scoring could not be verified or no source answered).",
  idp_streaming_unavailable:
    "Weekly IDP streaming couldn't finish for this team.",
  unknown_league: "That league isn't configured.",
  inactive_league: "That league is inactive.",
  bad_week: "That week isn't valid.",
  bad_horizonWeeks: "That horizon isn't valid.",
  bad_position: "That position filter isn't valid.",
  bad_capacity: "That streaming capacity isn't valid.",
  bad_dynastyBudget: "The dynasty budget must be a number from 0 to 100,000.",
  bad_capacityCurve: "That request isn't valid.",
};

const REASON_COPY = {
  config_unreadable: "the streaming configuration could not be read",
  league_settings_unreadable: "this league's settings could not be read",
};

/**
 * Classify a non-OK answer.  `disabled` is the gate: `503 feature_disabled`
 * (either flag off) or a backend without the route (plain 404).
 */
export function classifyStreamingFailure(status, body) {
  const code = body && typeof body === "object" ? String(body.error || "") : "";
  if (code === "feature_disabled" || (status === 404 && !code)) {
    return {
      kind: "disabled",
      code: code || "route_not_registered",
      flag: body?.flag || null,
    };
  }
  if (status === 401) {
    return {
      kind: "auth",
      code,
      message: "Sign in to use weekly IDP streaming.",
    };
  }
  let message =
    FAILURE_COPY[code] || (code ? `Unavailable (${code}).` : "Unavailable.");
  const reason = body && typeof body === "object" ? body.reason : null;
  if (reason)
    message = `${message.replace(/\.$/, "")} — ${REASON_COPY[reason] || reasonText(reason)}.`;
  if (status >= 500) return { kind: "unavailable", code, message };
  return { kind: "degraded", code, message };
}

/** A late answer for another league or team must never render. */
export function isStaleStreamingPayload(payload, { leagueKey, ownerId } = {}) {
  if (!payload || typeof payload !== "object") return true;
  if (leagueKey && payload.leagueKey && payload.leagueKey !== leagueKey)
    return true;
  if (
    ownerId &&
    payload.team?.ownerId &&
    String(payload.team.ownerId) !== String(ownerId)
  ) {
    return true;
  }
  return false;
}

// ── formatting (unit formatting only — never arithmetic on a value) ────

/** Fantasy points with one decimal, or null. */
export function fmtPoints(v) {
  const n = Number(v);
  return v != null && Number.isFinite(n) ? n.toFixed(1) : null;
}

/** Signed fantasy points ("+3.4"), or null. */
export function fmtSignedPoints(v) {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return null;
  const s = n.toFixed(1);
  return n > 0 ? `+${s}` : s;
}

export function fmtValue(v) {
  const n = Number(v);
  return v != null && Number.isFinite(n)
    ? Math.round(n).toLocaleString("en-US")
    : null;
}

export function fmtSignedValue(v) {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return null;
  const r = Math.round(n);
  return r > 0 ? `+${r.toLocaleString("en-US")}` : r.toLocaleString("en-US");
}

export function fmtDollars(v) {
  const n = Number(v);
  return v != null && Number.isFinite(n) ? `$${Math.round(n)}` : null;
}

export function fmtPct(v) {
  const n = Number(v);
  return v != null && Number.isFinite(n) ? `${Math.round(n * 100)}%` : null;
}

const REASON_LABEL = {
  ok: "projected",
  not_in_projection_set: "no projection",
  provider_published_no_projection: "provider published no projection",
  schedule_lists_team_on_bye_but_provider_projects: "bye per schedule",
  league_bundle_not_warm: "posture bundle not built yet",
  team_not_in_posture_bundle: "team not in posture bundle",
};

/** Words for a backend reason code; the raw code (de-underscored) when unmapped. */
export function reasonText(code) {
  if (!code) return "unavailable";
  if (REASON_LABEL[code]) return REASON_LABEL[code];
  return String(code).replace(/_/g, " ");
}

const NO_MOVE_COPY = {
  below_materiality:
    "No move clears the materiality threshold: the best available change adds too few lineup points to be worth a transaction.",
  no_droppable_player:
    "No roster player can be released under your protections and the drop assessment, and there is no open roster spot.",
  no_projected_free_agent:
    "No available defender at this filter has a weekly projection, so there is nothing to stream.",
  no_move_improves_the_lineup:
    "No legal add/drop improves your projected starting lineup this week.",
};

/** The backend's no-move reason, in plain language. */
export function noMoveReasonText(code) {
  if (!code)
    return "Holding the roster is projected to be as good as any legal move.";
  return NO_MOVE_COPY[code] || `No move recommended (${reasonText(code)}).`;
}

/** Solver status words — "bounded" states its proven gap. */
export function solverStatusText(solver) {
  if (!solver || !solver.status)
    return { label: "Solver status unknown", tone: "outline" };
  if (solver.status === "optimal")
    return { label: "Optimal — proven best", tone: "positive" };
  if (solver.status === "bounded") {
    const gap = fmtPoints(solver.boundGap);
    return {
      label: gap
        ? `Bounded — best found, proven within ${gap} points`
        : "Bounded — best found, gap not proven",
      tone: "warning",
    };
  }
  return { label: `Solver: ${reasonText(solver.status)}`, tone: "outline" };
}

const BID_BASIS_LABEL = {
  faab_engine: "FAAB engine",
  off_board_zero_claim_only: "Off the dynasty board — $0 claim only",
  unpriced_by_engine_zero_claim_only:
    "Not priced by the FAAB engine — $0 claim only",
};

export function bidBasisText(basis) {
  return BID_BASIS_LABEL[basis] || reasonText(basis);
}

/** Bid cell: dollars + whether it is an engine price or a $0 claim. */
export function bidText(row) {
  const d = fmtDollars(row?.bid);
  if (!d) return "Unavailable";
  return row?.bidBasis === "faab_engine" ? d : `${d} claim`;
}

const DROP_CLASS = {
  churn: { label: "Churn", tone: "neutral" },
  conditional: { label: "Conditional", tone: "warning" },
  protected: { label: "Protected", tone: "outline" },
};

export function dropClassBadge(cls) {
  return (
    DROP_CLASS[cls] || {
      label: cls ? reasonText(cls) : "Unclassified",
      tone: "outline",
    }
  );
}

/** Dynasty value cell: the board value, or a stated unknown. */
export function dynastyValueText(value, state) {
  const v = fmtValue(value);
  if (v) return v;
  if (state === "unknown_off_board") return "Unknown — off the dynasty board";
  return "Unknown";
}

/** Dynasty value change of a plan, with its completeness state. */
export function dynastyChangeText(change) {
  if (!change) return { text: "Unavailable", partial: false };
  const v = fmtSignedValue(change.value);
  if (change.state === "complete")
    return { text: v ?? "Unavailable", partial: false };
  const n = change.unknownAddValues;
  return {
    text: `${v ?? "?"} (partial — ${n ?? "some"} added player${n === 1 ? "" : "s"} unvalued)`,
    partial: true,
  };
}

/** One week's projection cell for a player: points, or the stated state. */
export function weekCellText(w) {
  if (!w) return "—";
  const p = fmtPoints(w.points);
  if (w.state === "projected" && p) return p;
  if (w.state === "bye") return "Bye";
  if (w.state === "injured_out") return p ? `${p} (out)` : "Out";
  return p
    ? `${p} (${reasonText(w.state)})`
    : `— ${reasonText(w.reason || w.state)}`;
}

/** Sources + coverage for one week, in words. */
export function coverageText(w) {
  if (!w || w.state === "unprojected") return "No source";
  const srcs = (w.sources || []).join(", ") || "no source";
  const cov = fmtPct(w.coverageShare);
  const uncovered = (w.uncoveredKeys || []).length;
  return `${srcs}${cov ? ` · ${cov} of paid categories` : ""}${
    uncovered ? ` (${uncovered} uncovered)` : ""
  }`;
}

/** Display names keyed by player id, joined from the payload's own boards. */
export function playerNameIndex(payload) {
  const idx = new Map();
  for (const r of payload?.streamingBoard || [])
    idx.set(String(r.playerId), r.name);
  for (const r of payload?.safeToDrop?.players || [])
    idx.set(String(r.playerId), r.name);
  for (const p of [
    payload?.plan,
    ...(payload?.alternatives || []),
    payload?.largerBudget?.plan,
  ]) {
    for (const r of p?.addDetails || []) idx.set(String(r.playerId), r.name);
    for (const r of p?.dropDetails || []) idx.set(String(r.playerId), r.name);
  }
  return idx;
}

/** "Add A, B · Drop C" for a plan or capacity-curve row. */
export function moveSummary(plan, names) {
  if (!plan) return "No move";
  const nm = (id) => names?.get(String(id)) || String(id);
  const adds = (plan.adds || []).map(nm);
  const drops = (plan.drops || []).map(nm);
  if (!adds.length && !drops.length) return "No move";
  const parts = [];
  if (adds.length) parts.push(`Add ${adds.join(", ")}`);
  if (drops.length) parts.push(`Drop ${drops.join(", ")}`);
  return parts.join(" · ");
}

/** Posture strip — context only, never an input to the plan. */
export function postureContextText(posture) {
  const ctx = posture?.context;
  if (!ctx)
    return {
      label: "Unavailable",
      note: reasonText(posture?.unavailableReason),
    };
  const conf = fmtPct(ctx.confidence);
  return {
    label: ctx.label || ctx.mostLikely || "Unknown",
    note: `${conf ? `${conf} confidence · ` : ""}context only — never raises the dynasty budget`,
  };
}

/** FAAB balance strip. */
export function faabText(faab) {
  if (!faab || faab.state !== "known") {
    return { value: "Unknown", note: "balance unknown — $0 claims only" };
  }
  return { value: fmtDollars(faab.remaining) ?? "Unknown", note: "remaining" };
}
