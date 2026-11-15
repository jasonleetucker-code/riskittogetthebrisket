// Brisket Trade Advisor — pure trade-builder state (design §8.3).
//
// What this module is: the reducer, selectors and request builder for the
// public League Hub advisor.  What it is NOT: a valuation engine.  It holds
// asset IDENTITIES (`p:<sleeperId>`, `pick:<leagueKey>:<season>:r<N>:o<rid>`),
// display labels, roster ids and the server's fairness enums + fixed text
// (FAIR / NOT_FAIR / UNABLE_TO_DETERMINE, per team and overall — owner
// amendment 2026-10-20).  It never holds, derives, sorts by or compares a
// value — the backend orders asset lists (value-free) and decides fairness
// (spec §4, §5.2).  Nothing here may import the private trade or rankings
// modules.
//
// Server-safe and dependency-free so the reducer can run in the /league page
// chunk (the team step is server-rendered) and in Node tests.

export const MIN_TEAMS = 2;
// Fallback ceiling only.  The live cap is the teams endpoint's
// `limits.maxTeams` (public config ceiling, also capped at the league's
// team count) — callers pass it as `max`.
export const MAX_TEAMS = 4;
const SLOT_NAMES = Object.freeze(["Your team", "Trade partner"]);
// The ONE public asset order (spec §4.2): side → position → name → id, picks
// by season / round / origin.  It never depends on a value.
export const ASSET_SORT = "position_alpha";
export const SESSION_KEY = "brisketAdvisor:v2";

// The public answer is fairness only (owner amendment 2026-10-20): three
// results, per team and overall.  Anything else is not a result.
export const RESULTS = Object.freeze(["FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"]);
// Presentation only.  The meaning travels in the server's own label and
// text plus an icon, never in colour alone.
export const RESULT_TONE = Object.freeze({
  FAIR: "positive",
  NOT_FAIR: "warning",
  UNABLE_TO_DETERMINE: "neutral",
});
// Short form for the per-team tab badges; the full server label is shown
// beside it in the panel.
export const RESULT_SHORT = Object.freeze({
  FAIR: "Fair",
  NOT_FAIR: "Not fair",
  UNABLE_TO_DETERMINE: "Unable to determine",
});

export function initialAdvisorState() {
  return {
    phase: "build", // build | submitting | result
    teamCount: MIN_TEAMS,
    slots: [null, null],
    legs: [], // {id, kind, label, from, to}
    result: null,
    view: null, // the team whose result is shown (perspective switch)
    error: null,
    staleIds: [],
    notice: null,
  };
}

function clampCount(n, max = MAX_TEAMS) {
  const count = Number(n);
  const ceiling = Number.isInteger(max) && max >= MIN_TEAMS ? max : MAX_TEAMS;
  if (!Number.isInteger(count)) return MIN_TEAMS;
  return Math.min(ceiling, Math.max(MIN_TEAMS, count));
}

function otherSlot(slots, from) {
  // Two-team trades have exactly one possible destination.
  if (slots.length !== 2) return null;
  const [a, b] = slots;
  if (from === a) return b ?? null;
  if (from === b) return a ?? null;
  return null;
}

// Re-establish leg invariants after the team line-up changed: a leg from a
// team no longer in the trade is removed (it was that team's asset); a leg
// to a team no longer in the trade is unrouted; with two teams every leg is
// retargeted to the only other team.
function reconcileLegs(legs, slots) {
  const inTrade = new Set(slots.filter((rid) => rid != null));
  const removed = [];
  const kept = [];
  for (const leg of legs) {
    if (!inTrade.has(leg.from)) {
      removed.push(leg.label);
      continue;
    }
    let to = leg.to;
    if (slots.length === 2) {
      to = otherSlot(slots, leg.from);
    } else if (to != null && (!inTrade.has(to) || to === leg.from)) {
      to = null;
    }
    kept.push(to === leg.to ? leg : { ...leg, to });
  }
  return { legs: kept, removed };
}

// Every edit made while a result is showing returns to the builder and
// clears that result — a result never sits beside a trade it was not
// computed for.
function edited(state, patch) {
  return { ...state, ...patch, phase: "build", result: null, view: null, error: null };
}

export function advisorReducer(state, action) {
  switch (action.type) {
    case "SET_SLOT": {
      const index = action.index;
      if (!Number.isInteger(index) || index < 0 || index >= state.teamCount) return state;
      const rid = action.rosterId == null ? null : Number(action.rosterId);
      if (rid != null && !Number.isInteger(rid)) return state;
      if (state.slots[index] === rid) return state;
      // A team already in another slot is disabled in the picker; refuse it
      // here too.  There is no swap.
      if (rid != null && state.slots.some((r, i) => i !== index && r === rid)) return state;
      const slots = state.slots.slice();
      slots[index] = rid;
      const { legs, removed } = reconcileLegs(state.legs, slots);
      return edited(state, {
        slots,
        legs,
        staleIds: state.staleIds.filter((id) => legs.some((l) => l.id === id)),
        notice: removed.length ? { kind: "removed", labels: removed } : null,
      });
    }
    case "SET_TEAM_COUNT": {
      const teamCount = clampCount(action.count, action.max);
      if (teamCount === state.teamCount) return state;
      const slots = state.slots.slice(0, teamCount);
      while (slots.length < teamCount) slots.push(null);
      const { legs, removed } = reconcileLegs(state.legs, slots);
      return edited(state, {
        teamCount,
        slots,
        legs,
        staleIds: state.staleIds.filter((id) => legs.some((l) => l.id === id)),
        notice: removed.length ? { kind: "removed", labels: removed } : null,
      });
    }
    case "ADD_ASSET": {
      const asset = action.asset;
      const from = Number(action.from);
      if (!asset || typeof asset.id !== "string") return state;
      if (!state.slots.includes(from)) return state;
      // The same player or pick can appear only once in a trade.
      if (state.legs.some((l) => l.id === asset.id)) return state;
      const leg = {
        id: asset.id,
        kind: asset.kind === "pick" ? "pick" : "player",
        label: String(asset.label || asset.id),
        from,
        to: otherSlot(state.slots, from),
      };
      return edited(state, { legs: [...state.legs, leg], notice: null });
    }
    case "REMOVE_ASSET": {
      if (!state.legs.some((l) => l.id === action.id)) return state;
      return edited(state, {
        legs: state.legs.filter((l) => l.id !== action.id),
        staleIds: state.staleIds.filter((id) => id !== action.id),
      });
    }
    case "SET_DESTINATION": {
      const to = action.to == null || action.to === "" ? null : Number(action.to);
      const leg = state.legs.find((l) => l.id === action.id);
      if (!leg) return state;
      if (to != null && (!state.slots.includes(to) || to === leg.from)) return state;
      if (leg.to === to) return state;
      return edited(state, {
        legs: state.legs.map((l) => (l.id === action.id ? { ...l, to } : l)),
      });
    }
    case "SUBMIT":
      return { ...state, phase: "submitting", error: null };
    case "RESULT":
      return {
        ...state,
        phase: "result",
        result: action.result,
        view: defaultView(action.result, state.slots),
        error: null,
        staleIds: [],
      };
    case "SET_VIEW": {
      // Perspective switch: a different team's row of the SAME response.
      // No request, no recomputation.
      const rid = Number(action.rosterId);
      if (!state.result || !state.result.teams.some((t) => t.rosterId === rid)) return state;
      return rid === state.view ? state : { ...state, view: rid };
    }
    case "FAIL": {
      const error = action.error || { kind: "unavailable" };
      const staleIds = error.kind === "stale" && Array.isArray(error.assetIds) ? error.assetIds.slice() : [];
      return { ...state, phase: "build", result: null, view: null, error, staleIds };
    }
    case "EDIT":
      return { ...state, phase: "build", result: null, view: null, error: null };
    case "NEW_TRADE":
      // Keeps the teams, clears the assets.
      return { ...state, phase: "build", legs: [], result: null, view: null, error: null, staleIds: [], notice: null };
    case "START_OVER":
      return initialAdvisorState();
    case "DISMISS_NOTICE":
      return { ...state, notice: null };
    case "RESTORE": {
      if (!action.state) return state;
      const next = { ...initialAdvisorState(), ...action.state, phase: action.state.result ? "result" : "build" };
      return { ...next, view: next.result ? defaultView(next.result, next.slots) : null };
    }
    default:
      return state;
  }
}

// The result opens on the selected team ("your team"), falling back to the
// response's own perspective echo, then its first team.
function defaultView(result, slots) {
  const ids = (result?.teams || []).map((t) => t.rosterId);
  for (const rid of [slots?.[0], result?.perspectiveRosterId]) {
    if (ids.includes(rid)) return rid;
  }
  return ids[0] ?? null;
}

// ── Selectors ──────────────────────────────────────────────────────────────

export function teamsById(teams) {
  const map = new Map();
  for (const t of teams || []) map.set(t.rosterId, t);
  return map;
}

export function teamLabel(team) {
  if (!team) return "";
  return team.teamName && team.teamName !== team.displayName
    ? `${team.teamName} (${team.displayName})`
    : team.displayName || team.teamName || `Team ${team.rosterId}`;
}

export function slotName(index) {
  // "Your team", "Trade partner", then Team C, Team D, … for any team count.
  return SLOT_NAMES[index] || `Team ${String.fromCharCode(65 + index)}`;
}

/**
 * Client-side readiness, in the order the user should fix things.  These
 * mirror the server's public validation (spec §4.5 "build-then-refuse") so
 * Analyze stays disabled until the trade can actually be judged; the server
 * still enforces every rule independently.
 *
 *   - every slot has a team;
 *   - every team both SENDS and RECEIVES at least one asset (the public
 *     `send_and_receive` rule, for any team count);
 *   - every asset has a destination that is another team in the trade
 *     (self-destinations are refused by the reducer);
 *   - no more assets than `limits.maxLegs`.
 */
export function tradeIssues(state, teams = [], limits = null) {
  const byId = teamsById(teams);
  const issues = [];
  state.slots.forEach((rid, i) => {
    if (rid == null) {
      issues.push({
        code: "choose_team",
        slot: i,
        message: i === 0 ? "Choose your team." : i === 1 ? "Choose a trade partner." : `Choose ${slotName(i)}.`,
      });
    }
  });
  if (issues.length) return issues;
  if (state.legs.length === 0) {
    issues.push({ code: "empty_trade", message: "Add at least one player or pick to the trade." });
    return issues;
  }
  const sends = new Map(state.slots.map((rid) => [rid, 0]));
  const receives = new Map(state.slots.map((rid) => [rid, 0]));
  // Both maps start at a real count of 0 for every team in the trade; a
  // leg naming a team outside it changes no team's count.
  for (const leg of state.legs) {
    if (sends.has(leg.from)) sends.set(leg.from, sends.get(leg.from) + 1);
    if (leg.to != null && receives.has(leg.to)) receives.set(leg.to, receives.get(leg.to) + 1);
  }
  state.slots.forEach((rid, i) => {
    const name = i === 0 ? "Your team" : teamLabel(byId.get(rid)) || slotName(i);
    const s = sends.get(rid);
    const r = receives.get(rid);
    if (!s && !r) {
      issues.push({
        code: "idle_team",
        slot: i,
        message: `${name} must send and receive at least one player or pick.`,
      });
    } else if (!s) {
      issues.push({
        code: "team_sends_nothing",
        slot: i,
        message: `${name} must also send at least one player or pick.`,
      });
    } else if (!r) {
      issues.push({
        code: "team_receives_nothing",
        slot: i,
        message: `${name} must also receive at least one player or pick.`,
      });
    }
  });
  for (const leg of state.legs) {
    if (leg.to == null) {
      issues.push({ code: "choose_destination", id: leg.id, message: `Choose where ${leg.label} goes.` });
    }
  }
  const maxLegs = limits && Number.isInteger(limits.maxLegs) && limits.maxLegs > 0 ? limits.maxLegs : null;
  if (maxLegs != null && state.legs.length > maxLegs) {
    issues.push({ code: "too_many_assets", message: "This trade has too many assets." });
  }
  return issues;
}

export function canAnalyze(state, teams, limits = null) {
  return state.phase !== "submitting" && tradeIssues(state, teams, limits).length === 0;
}

/** The analyze body (frozen contract §4.3): identities and routing only. */
export function toAnalyzeRequest(state) {
  return {
    perspectiveRosterId: state.slots[0],
    teams: state.slots.slice(),
    assets: state.legs.map((l) => ({ id: l.id, from: l.from, to: l.to })),
  };
}

/**
 * A stable key for "this exact trade" (cache of the last result).  Order-
 * and perspective-free, like the server's answer: the same teams and the
 * same transfers are the same trade however they were entered.
 */
export function tradeKey(request) {
  const teams = request.teams.slice().sort((a, b) => a - b);
  const assets = request.assets
    .map((a) => [a.id, a.from, a.to])
    .sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
  return JSON.stringify([teams, assets]);
}

/**
 * What each team sends and receives, team by team in slot order ("your
 * team" first), each asset in the order it was added.  Identities and
 * labels only.
 */
export function tradeSummary(state, teams = []) {
  const byId = teamsById(teams);
  const perspective = state.slots[0];
  const name = (rid) => teamLabel(byId.get(rid)) || (rid == null ? "" : `Team ${rid}`);
  return {
    teams: state.slots
      .filter((rid) => rid != null)
      .map((rid) => ({
        rosterId: rid,
        name: name(rid),
        isYou: rid === perspective,
        sends: state.legs
          .filter((l) => l.from === rid)
          .map((l) => ({ id: l.id, label: l.label, to: l.to, toName: l.to == null ? null : name(l.to) })),
        receives: state.legs
          .filter((l) => l.to === rid)
          .map((l) => ({ id: l.id, label: l.label, from: l.from, fromName: name(l.from) })),
      })),
  };
}

// ── Asset filtering over the server's order ────────────────────────────────
//
// The backend returns the list in its one value-free order (position, then
// name; picks by year and round).  These filters only REMOVE rows; they
// never reorder, so the server's order is what the user sees.

export const ASSET_GROUPS = Object.freeze([
  { value: "all", label: "All" },
  { value: "offense", label: "Offense" },
  { value: "defense", label: "Defense" },
  { value: "pick", label: "Picks" },
]);

// The board carries family-level defensive positions; DT/DE fold into DL and
// CB/S into DB (design Risk 12 — reported, not invented).
export const POSITION_LABELS = Object.freeze({
  DL: "DL (DT/DE)",
  DB: "DB (CB/S)",
});

export function positionsPresent(assets, group = "all") {
  const seen = [];
  for (const a of assets || []) {
    if (a.kind !== "player" || !a.position) continue;
    if (group !== "all" && a.side !== group) continue;
    if (!seen.includes(a.position)) seen.push(a.position);
  }
  return seen;
}

export function filterAssets(assets, { group = "all", position = "", query = "" } = {}) {
  const q = String(query || "")
    .trim()
    .toLowerCase();
  return (assets || []).filter((a) => {
    if (group !== "all" && a.side !== group) return false;
    if (position && a.position !== position) return false;
    if (
      q &&
      !String(a.label || "")
        .toLowerCase()
        .includes(q)
    )
      return false;
    return true;
  });
}

// ── Session persistence (identities, labels, result enum + text only) ─────

// A result is kept only in the allowlisted public shape: the result enums,
// the server's fixed labels and text, roster ids and asset ids.
function cleanResult(r) {
  if (!r || typeof r !== "object" || !r.overall || !RESULTS.includes(r.overall.result) || !Array.isArray(r.teams)) {
    return null;
  }
  const teams = r.teams.filter((t) => t && Number.isInteger(t.rosterId) && RESULTS.includes(t.result));
  if (!teams.length) return null;
  const text = (v) => (typeof v === "string" ? v : null);
  return {
    overall: {
      result: r.overall.result,
      label: text(r.overall.label) || "",
      reasonCode: text(r.overall.reasonCode),
      reasonText: text(r.overall.reasonText),
      note: text(r.overall.note),
    },
    teams: teams.map((t) => ({
      rosterId: t.rosterId,
      result: t.result,
      label: text(t.label) || "",
      reasonCode: text(t.reasonCode),
      reasonText: text(t.reasonText),
      unavailableAssetIds: Array.isArray(t.unavailableAssetIds)
        ? t.unavailableAssetIds.filter((x) => typeof x === "string")
        : [],
    })),
    perspectiveRosterId: Number.isInteger(r.perspectiveRosterId) ? r.perspectiveRosterId : null,
    teamCount: Number.isInteger(r.teamCount) ? r.teamCount : null,
    generation: text(r.generation) || "",
    key: text(r.key),
  };
}

export function serializeAdvisorState(state) {
  return JSON.stringify({
    teamCount: state.teamCount,
    slots: state.slots,
    legs: state.legs.map((l) => ({ id: l.id, kind: l.kind, label: l.label, from: l.from, to: l.to })),
    result: cleanResult(state.result),
  });
}

/**
 * Restore a saved builder.  The URL wins: when `?team=` names a different
 * team than the saved "your team", start fresh with the URL team.  Teams
 * that are no longer in the league are dropped (and their legs with them).
 */
export function restoreAdvisorState(raw, { urlTeam = null, teams = [], maxTeams = MAX_TEAMS } = {}) {
  const known = new Set((teams || []).map((t) => t.rosterId));
  const url = urlTeam == null || urlTeam === "" ? null : Number(urlTeam);
  const fresh = () => {
    const s = initialAdvisorState();
    if (url != null && known.has(url)) s.slots[0] = url;
    return s;
  };
  let saved = null;
  try {
    saved = raw ? JSON.parse(raw) : null;
  } catch {
    saved = null;
  }
  if (!saved || typeof saved !== "object" || !Array.isArray(saved.slots)) return fresh();
  if (url != null && saved.slots[0] !== url) return fresh();
  const teamCount = clampCount(saved.teamCount, maxTeams);
  const slots = saved.slots.slice(0, teamCount).map((rid) => (known.has(rid) ? rid : null));
  while (slots.length < teamCount) slots.push(null);
  if (new Set(slots.filter((r) => r != null)).size !== slots.filter((r) => r != null).length) return fresh();
  const rawLegs = Array.isArray(saved.legs) ? saved.legs : [];
  const seen = new Set();
  const legs = [];
  for (const l of rawLegs) {
    if (!l || typeof l.id !== "string" || seen.has(l.id)) continue;
    seen.add(l.id);
    legs.push({
      id: l.id,
      kind: l.kind === "pick" ? "pick" : "player",
      label: String(l.label || l.id),
      from: l.from,
      to: l.to ?? null,
    });
  }
  const reconciled = reconcileLegs(legs, slots).legs;
  const result = cleanResult(saved.result);
  return { ...initialAdvisorState(), teamCount, slots, legs: reconciled, result, phase: result ? "result" : "build" };
}
