/**
 * waiver-advisor.js — pure helpers for the Waiver Advisor page (Workstream E).
 *
 * DISPLAY ONLY.  Every number arrives from `POST /api/waiver/advisor`
 * (`src/waivers/advisor.py`), which composes the existing owners: Perfect
 * Waivers, the FAAB engine (through `find_waiver_targets`), the exact lineup
 * solver, roster capacity, droppability and competitive posture.  Nothing here
 * values, prices, bids, ranks or decides legality — the same
 * no-frontend-engine rule `buildRows` and `WaiverBidFigure` follow.  The
 * helpers only (a) build the request body, (b) classify a failure into a named
 * state, and (c) turn a backend state into words.  A missing number renders
 * as its stated reason, never as 0.
 */

export const WAIVER_ADVISOR_ENDPOINT = "/api/waiver/advisor";
export const WAIVER_ADVISOR_FLAG = "waiver_advisor";

export const ADVISOR_POSITION_OPTIONS = [
  { value: "ALL", label: "All positions" },
  { value: "QB", label: "QB" },
  { value: "RB", label: "RB" },
  { value: "WR", label: "WR" },
  { value: "TE", label: "TE" },
  { value: "DL", label: "DL" },
  { value: "LB", label: "LB" },
  { value: "DB", label: "DB" },
];

/**
 * The POST body.  The team is never guessed: without an owner id the body
 * carries none, and the backend answers `team_required` — or, when the flag is
 * off, `feature_disabled` FIRST.  That makes the team-less request the gate
 * probe: the page learns it is switched off before it renders anything.
 */
export function buildAdvisorRequest({ leagueKey, ownerId, position = "ALL", limit } = {}) {
  const body = { position: position || "ALL" };
  if (ownerId) body.teamOwnerId = String(ownerId);
  if (leagueKey) body.leagueKey = leagueKey;
  if (Number.isFinite(limit) && limit > 0) body.limit = Math.floor(limit);
  return body;
}

const FAILURE_COPY = {
  data_not_ready: "This league's rosters haven't loaded yet.",
  unknown_team: "That team isn't in this league's rosters.",
  team_required: "Pick your team to see waiver advice.",
  waiver_advisor_unavailable: "The waiver advisor couldn't finish for this team.",
  unknown_league: "That league isn't configured.",
  inactive_league: "That league is inactive.",
};

/**
 * Classify a non-OK answer.
 *
 * `disabled` is the gate: the backend answers `503 feature_disabled` (flag
 * `waiver_advisor` off), and a backend without the route answers a plain
 * 404 — both mean the page must show nothing but "not available".
 */
export function classifyAdvisorFailure(status, body) {
  const code = body && typeof body === "object" ? String(body.error || "") : "";
  if (code === "feature_disabled" || (status === 404 && !code)) {
    return { kind: "disabled", code: code || "route_not_registered" };
  }
  if (status === 401) return { kind: "auth", code, message: "Sign in to use the waiver advisor." };
  const message = FAILURE_COPY[code] || (code ? `Unavailable (${code}).` : "Unavailable.");
  if (status >= 500) return { kind: "unavailable", code, message };
  return { kind: "degraded", code, message };
}

/** A late answer for another league or team must never render. */
export function isStaleAdvisorPayload(payload, { leagueKey, ownerId } = {}) {
  if (!payload || typeof payload !== "object") return true;
  if (leagueKey && payload.leagueKey && payload.leagueKey !== leagueKey) return true;
  if (ownerId && payload.team?.ownerId && String(payload.team.ownerId) !== String(ownerId)) {
    return true;
  }
  return false;
}

// ── formatting (unit formatting only — never arithmetic on a value) ────

export function fmtValue(v) {
  const n = Number(v);
  return v != null && Number.isFinite(n) ? Math.round(n).toLocaleString() : null;
}

export function fmtSigned(v) {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return null;
  const r = Math.round(n);
  return r > 0 ? `+${r.toLocaleString()}` : r.toLocaleString();
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
  no_ktc_coverage: "no KTC coverage",
  ktc_value_out_of_declared_range: "KTC value out of range",
  ceiling_only_no_rival_model: "no rival model (ceiling-only)",
  engine_no_clearing: "engine published no clearing price",
  engine_returned_no_bid: "engine returned no bid",
  no_team_context_rival_model_not_run: "no team context — rival model not run",
  starter_slots_unknown: "starter slots unknown",
  team_pool_not_found: "team roster pool not found",
  candidate_position_unknown: "player's position unknown",
  capacity_context_unavailable: "roster capacity unavailable",
  league_bundle_not_warm: "posture bundle not built yet",
  team_not_in_posture_bundle: "team not in posture bundle",
};

/** Words for a backend reason code; the raw code when unmapped. */
export function reasonText(code) {
  if (!code) return "unavailable";
  if (REASON_LABEL[code]) return REASON_LABEL[code];
  return String(code).replace(/_/g, " ");
}

/** Plan status → label + tone (status words, not a judgment invented here). */
export function planStatusLabel(plan) {
  switch (plan?.status) {
    case "in_plan":
      return { label: "In optimal plan", tone: "accent" };
    case "next_best_move":
      return { label: "Next best move", tone: "neutral" };
    case "not_in_plan":
      return { label: "Not in plan", tone: "outline" };
    default:
      return { label: "Plan unavailable", tone: "outline" };
  }
}

/** "Drop X" / "Open spot" / null — the release Perfect Waivers paired. */
export function releaseText(release) {
  if (!release) return null;
  if (release.kind === "openSpot") return "Open roster spot";
  if (release.kind === "drop") return release.name ? `Drop ${release.name}` : "Drop (unnamed)";
  return null;
}

/** Lineup cell text, or the stated reason when it could not be evaluated. */
export function lineupText(lineup) {
  if (!lineup || lineup.state !== "evaluated") {
    return { text: `Unknown — ${reasonText(lineup?.reason)}`, starts: null };
  }
  if (lineup.entersOptimalLineup) {
    return { text: lineup.slot ? `Starts (${lineup.slot})` : "Starts", starts: true };
  }
  return { text: "Bench", starts: false };
}

/** Forced-drop summary for an add on its own — always "reported, not applied". */
export function forcedDropText(capacity) {
  if (!capacity || capacity.state === "unavailable") {
    return { text: `Unknown — ${reasonText(capacity?.reason)}`, known: false };
  }
  if (capacity.requiresDrops === null || capacity.requiresDrops === undefined) {
    return { text: "Unknown — roster cap or taxi occupancy undetermined", known: false };
  }
  if (capacity.requiresDrops === false) return { text: "No drop needed", known: true };
  const names = (capacity.forcedDrops || []).map((d) => d.name).filter(Boolean);
  const head = names.length ? names.join(", ") : "a release";
  return {
    text: capacity.forcedDropsAreUpperBound ? `Up to: ${head}` : head,
    known: true,
  };
}

/** The expected-winning-bid range, or its stated absence. */
export function expectedWinText(faab) {
  const exp = faab?.expectedWinningBid;
  if (!exp || exp.state !== "estimated") {
    return { text: `Unavailable — ${reasonText(exp?.reason)}`, estimated: false };
  }
  const lo = fmtDollars(exp.low);
  const hi = fmtDollars(exp.high);
  const mid = fmtDollars(exp.median);
  if (lo && hi) return { text: `${lo}–${hi}`, estimated: true, median: mid };
  return { text: mid || "Unavailable", estimated: Boolean(mid), median: mid };
}

export function maxRationalText(faab) {
  const m = faab?.maxRationalBid;
  if (!m || m.state !== "available") return "Unavailable";
  return fmtDollars(m.value) || "Unavailable";
}

export function recommendedBidText(faab) {
  if (!faab || faab.state === "unavailable") return `Unavailable — ${reasonText(faab?.reason)}`;
  return fmtDollars(faab.recommendedBid) || "Unavailable";
}

/** Posture strip: label + a context-only note, or the stated absence. */
export function postureText(posture) {
  if (!posture || posture.state !== "available") {
    return { label: "Unavailable", note: reasonText(posture?.reason) };
  }
  const conf = fmtPct(posture.confidence);
  return {
    label: posture.label || "Unknown",
    note: conf ? `${conf} confidence · context only` : "no measured confidence · context only",
  };
}

/** Value-confidence bucket → ds Badge tone (the backend's bucket, verbatim). */
export function confidenceTone(bucket) {
  switch (String(bucket || "").toLowerCase()) {
    case "high":
      return "positive";
    case "medium":
      return "neutral";
    case "low":
      return "warning";
    default:
      return "outline";
  }
}
