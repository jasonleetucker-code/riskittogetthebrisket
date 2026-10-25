// Brisket Trade Advisor — public endpoint client (frozen contract, design §4).
//
// Three public, value-free endpoints under /api/public/league/trade-advisor/.
// Every response is passed through an ALLOWLIST here before any component
// sees it: only the keys the contract names survive, typed as strings,
// integers, booleans and enums.  A field the backend adds by mistake (a
// value, a rank, a score) therefore never reaches React state, the DOM,
// sessionStorage or the RSC payload — the response models on the server
// are the first line, this is the second (design §8.6, §13).
//
// Error copy is FIXED client text keyed by the contract's error codes (the
// same wording as the server's fixed table, spec §4.4); no server-provided
// error string is rendered.  The analyze result's labels / reasonText /
// note are the one exception: they are the server's fixed fairness copy
// (spec §4.4) and are rendered verbatim.
//
// Isolation: imports nothing.  Never `credentials: "include"`.

import { ASSET_SORT, RESULTS } from "./trade-advisor.js";

export const ADVISOR_API = "/api/public/league/trade-advisor";

const TEAM_REASONS = [
  "within_fairness_threshold",
  "outside_fairness_threshold",
  "asset_not_evaluable",
  "ownership_unverifiable",
  "evaluation_unavailable",
];
const OVERALL_REASONS = ["all_teams_fair", "not_all_teams_fair", "evidence_insufficient"];
const ROSTER_STATES = ["current", "stale", "unknown"];
const PROJECTIONS = ["early", "mid", "late"];

const isInt = (v) => typeof v === "number" && Number.isInteger(v);
const str = (v) => (typeof v === "string" ? v : null);
const int = (v) => (isInt(v) ? v : null);
const oneOf = (v, allowed, fallback = null) => (allowed.includes(v) ? v : fallback);

function rostersBlock(r) {
  const o = r && typeof r === "object" ? r : {};
  const asOf = str(o.asOf);
  return {
    state: oneOf(o.state, ROSTER_STATES, "unknown"),
    asOf: asOf && /^\d{4}-\d{2}-\d{2}/.test(asOf) ? asOf.slice(0, 10) : null,
  };
}

/** Teams payload → allowlisted shape, or null when it is not one. */
export function sanitizeTeamsPayload(data) {
  if (!data || typeof data !== "object" || !Array.isArray(data.teams)) return null;
  const limits = data.limits && typeof data.limits === "object" ? data.limits : {};
  const teams = [];
  for (const t of data.teams) {
    if (!t || !isInt(t.rosterId)) continue;
    teams.push({
      rosterId: t.rosterId,
      displayName: str(t.displayName) || `Team ${t.rosterId}`,
      teamName: str(t.teamName),
    });
  }
  if (teams.length < 2) return null;
  return {
    generation: str(data.generation) || "",
    limits: {
      minTeams: int(limits.minTeams) ?? 2,
      maxTeams: int(limits.maxTeams) ?? 4,
      maxLegs: int(limits.maxLegs) ?? 128,
    },
    rosters: rostersBlock(data.rosters),
    teams,
  };
}

/** Assets payload → allowlisted shape (players and picks), or null. */
export function sanitizeAssetsPayload(data) {
  if (!data || typeof data !== "object" || !Array.isArray(data.assets)) return null;
  const assets = [];
  const seen = new Set();
  for (const a of data.assets) {
    if (!a || typeof a.id !== "string" || seen.has(a.id)) continue;
    seen.add(a.id);
    if (a.kind === "pick") {
      assets.push({
        id: a.id,
        kind: "pick",
        label: str(a.label) || a.id,
        side: "pick",
        season: int(a.season),
        round: int(a.round),
        originRosterId: int(a.originRosterId),
        projection: oneOf(a.projection, PROJECTIONS, null),
        evaluable: a.evaluable === true,
      });
    } else if (a.kind === "player") {
      assets.push({
        id: a.id,
        kind: "player",
        label: str(a.label) || a.id,
        side: oneOf(a.side, ["offense", "defense", "other"], "other"),
        position: str(a.position),
        nflTeam: str(a.nflTeam),
        evaluable: a.evaluable === true,
      });
    }
  }
  return {
    generation: str(data.generation) || "",
    rosterId: int(data.rosterId),
    sort: oneOf(data.sort, [ASSET_SORT], null),
    pickOwnership: oneOf(data.pickOwnership, ["observed", "unavailable"], "unavailable"),
    rosters: rostersBlock(data.rosters),
    assets,
  };
}

const ID = /^[A-Za-z0-9:_-]{1,64}$/;
const ids = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === "string" && ID.test(x)) : []);

/**
 * Analyze payload → allowlisted fairness result, or null when it is not one.
 * One response carries EVERY participating team's result plus the overall
 * result (spec §4.3); the perspective switch reads other rows of it.  A
 * team row or overall block with an unknown result enum makes the whole
 * payload unusable rather than guessed at.
 */
export function sanitizeAnalyzePayload(data) {
  if (!data || typeof data !== "object" || data.status !== "success") return null;
  const o = data.overall && typeof data.overall === "object" ? data.overall : null;
  if (!o || !RESULTS.includes(o.result) || !Array.isArray(data.teams) || data.teams.length < 2) return null;
  const teams = [];
  for (const t of data.teams) {
    if (!t || !isInt(t.rosterId) || !RESULTS.includes(t.result)) return null;
    teams.push({
      rosterId: t.rosterId,
      result: t.result,
      label: str(t.label) || "",
      reasonCode: oneOf(t.reasonCode, TEAM_REASONS, null),
      reasonText: str(t.reasonText),
      unavailableAssetIds: ids(t.unavailableAssetIds),
    });
  }
  const trade = [];
  for (const leg of Array.isArray(data.trade) ? data.trade : []) {
    if (!leg || typeof leg.id !== "string" || !ID.test(leg.id) || !isInt(leg.from) || !isInt(leg.to)) continue;
    trade.push({ id: leg.id, from: leg.from, to: leg.to });
  }
  return {
    overall: {
      result: o.result,
      label: str(o.label) || "",
      reasonCode: oneOf(o.reasonCode, OVERALL_REASONS, null),
      reasonText: str(o.reasonText),
      note: str(o.note),
    },
    teams,
    trade,
    perspectiveRosterId: int(data.perspectiveRosterId),
    teamCount: int(data.teamCount),
    generation: str(data.generation) || "",
    rosters: rostersBlock(data.rosters),
  };
}

/**
 * Bootstrap state for the hub from a teams-endpoint read.
 *
 *   ready    — the advisor is served; `data` is the allowlisted teams payload
 *   disabled — flag off (503 advisor_unavailable/disabled) or the route is
 *              absent / the league is not public (404): fall back to Overview
 *   unknown  — no usable answer (timeout, network, 5xx, not_ready): the
 *              client asks again
 */
export function classifyTeamsResult({ status, data } = {}) {
  if (status === 200) {
    const payload = sanitizeTeamsPayload(data);
    return payload ? { state: "ready", data: payload } : { state: "unknown" };
  }
  if (status === 404) return { state: "disabled" };
  if (status === 503 && data && data.error === "advisor_unavailable" && data.reason === "disabled") {
    return { state: "disabled" };
  }
  return { state: "unknown" };
}

// ── Errors (fixed copy, keyed by the contract's codes) ─────────────────────

// The server's fixed copy for every public `invalid_trade` reason (spec
// §4.4 / §4.5), held here so no server string is rendered.
const INVALID_TRADE_COPY = {
  perspective_not_in_trade: "The selected team must be part of the trade.",
  too_few_teams: "A trade needs at least two teams.",
  duplicate_team: "A team can only appear once in a trade.",
  too_many_teams: "This trade has more teams than the advisor supports.",
  team_not_in_league: "One or more teams are not in this league.",
  empty_trade: "Add at least one player or pick to the trade.",
  too_many_assets: "This trade has too many assets.",
  unknown_asset: "One or more assets are not recognized.",
  duplicate_asset: "An asset can only appear once in a trade.",
  invalid_origin: "Every asset must come from a team in the trade.",
  invalid_destination: "Every asset must go to a team in the trade.",
  destination_is_origin: "An asset can't be sent to the team that owns it.",
  idle_team: "Every team in the trade must send or receive an asset.",
  one_sided_trade: "Every team in the trade must both send and receive at least one asset.",
};

// The server's fixed copy for the two admission-control refusals
// (src/trade/public_advisor.py ERROR_MESSAGES, ("advisor_unavailable",
// "busy" | "timeout")), held here verbatim for the same reason as
// INVALID_TRADE_COPY: no server string is ever rendered.
// Both tables are diffed against the Python owner by
// tests/trade/test_public_advisor_client_copy_parity.py.
export const ADMISSION_COPY = Object.freeze({
  busy: "The trade advisor is busy right now. Please try again in a moment.",
  timeout: "The trade advisor took too long to answer. Please try again.",
});

export function errorFromResponse(status, body) {
  const b = body && typeof body === "object" ? body : {};
  const assetIds = Array.isArray(b.assetIds) ? b.assetIds.filter((x) => typeof x === "string") : [];
  if (status === 409 && b.error === "stale_assets") {
    return {
      kind: "stale",
      assetIds,
      message:
        "Rosters have changed since this list loaded. Some players or picks are no longer on the team sending them. The lists have been refreshed.",
    };
  }
  if (status === 429) {
    const retry = int(b.retryAfterSeconds);
    return {
      kind: "rate_limited",
      retryAfterSeconds: retry != null && retry > 0 ? retry : 60,
      message: "Too many trades analyzed in a short time. Please wait and try again.",
    };
  }
  if (status === 503 && b.error === "advisor_unavailable" && b.reason === "disabled") {
    return { kind: "disabled", message: "The trade advisor is switched off right now." };
  }
  // Admission control on the analyze route (Lane C, R2-5): every engine slot
  // was busy, or the answer did not arrive within the route's wait budget.
  // Both are retryable; the trade the reader built is kept intact.
  if (status === 503 && b.error === "advisor_unavailable" && (b.reason === "busy" || b.reason === "timeout")) {
    return { kind: b.reason, retryable: true, message: ADMISSION_COPY[b.reason] };
  }
  if (status === 400 && b.error === "invalid_trade") {
    return {
      kind: "invalid",
      assetIds,
      message:
        INVALID_TRADE_COPY[b.reason] || "This trade isn't valid. Check every team and destination, then try again.",
    };
  }
  if (status === 404 && b.error === "unknown_team") {
    return {
      kind: "invalid",
      assetIds: [],
      message: "One of these teams is no longer in the league. Start over to pick again.",
    };
  }
  if (status === 0) {
    return { kind: "offline", message: "Couldn't reach the trade advisor. Check your connection and try again." };
  }
  return { kind: "unavailable", message: "The trade advisor isn't available right now. Please try again shortly." };
}

// ── Fetch helpers ──────────────────────────────────────────────────────────

const TRANSIENT = new Set([502, 504]);

async function request(url, init, { retry = true } = {}) {
  let res;
  try {
    res = await fetch(url, { credentials: "omit", ...init });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    return { ok: false, status: 0, body: null };
  }
  if (retry && TRANSIENT.has(res.status)) return request(url, init, { retry: false });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { ok: res.ok, status: res.status, body };
}

/** GET teams.  Resolves to the classified bootstrap, plus an error when not ready. */
export async function fetchAdvisorTeams({ signal, reload = false } = {}) {
  const r = await request(`${ADVISOR_API}/teams`, { method: "GET", signal, ...(reload ? { cache: "reload" } : {}) });
  const boot = classifyTeamsResult({ status: r.status, data: r.body });
  if (boot.state === "ready") return { ok: true, ...boot };
  return { ok: false, ...boot, error: errorFromResponse(r.status, r.body) };
}

/** GET one team's assets in the server's one value-free order. */
export async function fetchAdvisorAssets(rosterId, { signal, reload = false } = {}) {
  const url = `${ADVISOR_API}/teams/${encodeURIComponent(String(rosterId))}/assets?sort=${ASSET_SORT}`;
  const r = await request(url, { method: "GET", signal, ...(reload ? { cache: "reload" } : {}) });
  if (r.ok) {
    const data = sanitizeAssetsPayload(r.body);
    if (data) return { ok: true, data };
  }
  return { ok: false, status: r.status, error: errorFromResponse(r.ok ? 500 : r.status, r.body) };
}

/** POST analyze.  Never cached by the browser. */
export async function postAdvisorAnalyze(body, { signal } = {}) {
  const r = await request(`${ADVISOR_API}/analyze`, {
    method: "POST",
    signal,
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.ok) {
    const data = sanitizeAnalyzePayload(r.body);
    if (data) return { ok: true, data };
  }
  return { ok: false, status: r.status, error: errorFromResponse(r.ok ? 500 : r.status, r.body) };
}
