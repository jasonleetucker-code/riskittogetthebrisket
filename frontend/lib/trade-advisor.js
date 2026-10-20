// Brisket Trade Advisor — pure trade-builder state (design §8.3).
//
// What this module is: the reducer, selectors and request builder for the
// public League Hub advisor.  What it is NOT: a valuation engine.  It holds
// asset IDENTITIES (`p:<sleeperId>`, `pick:<leagueKey>:<season>:r<N>:o<rid>`),
// display labels, roster ids and the server's recommendation enum + fixed
// text.  It never holds, derives, sorts by or compares a value — the backend
// orders asset lists and decides the recommendation (design §8.6).  Nothing
// here may import the private trade or rankings modules.
//
// Server-safe and dependency-free so the reducer can run in the /league page
// chunk (the team step is server-rendered) and in Node tests.

export const MIN_TEAMS = 2;
export const MAX_TEAMS = 4;
export const SLOT_NAMES = Object.freeze(["Your team", "Trade partner", "Team C", "Team D"]);
export const SORTS = Object.freeze(["value_desc", "value_asc", "alpha"]);
export const DEFAULT_SORT = "value_desc";
export const SORT_LABELS = Object.freeze({
  value_desc: "Highest value first",
  value_asc: "Lowest value first",
  alpha: "A to Z",
});
export const SESSION_KEY = "brisketAdvisor:v1";

// Categories the backend may answer with (design §3); anything else is
// treated as UNAVAILABLE rather than guessed at.
export const CATEGORIES = Object.freeze([
  "STRONGLY_FAVORABLE",
  "FAVORABLE",
  "APPROXIMATELY_EVEN",
  "UNFAVORABLE",
  "STRONGLY_UNFAVORABLE",
  "UNAVAILABLE",
]);
// Presentation tone only: the meaning travels in the server's own words
// and an icon, never in colour alone (directive Phase 12).
export const CATEGORY_TONE = Object.freeze({
  STRONGLY_FAVORABLE: "positive",
  FAVORABLE: "positive",
  APPROXIMATELY_EVEN: "neutral",
  UNFAVORABLE: "warning",
  STRONGLY_UNFAVORABLE: "warning",
  UNAVAILABLE: "neutral",
});

export function initialAdvisorState() {
  return {
    phase: "build", // build | submitting | result
    teamCount: MIN_TEAMS,
    slots: [null, null],
    legs: [], // {id, kind, label, from, to}
    result: null,
    error: null,
    staleIds: [],
    notice: null,
  };
}

function clampCount(n) {
  const count = Number(n);
  if (!Number.isInteger(count)) return MIN_TEAMS;
  return Math.min(MAX_TEAMS, Math.max(MIN_TEAMS, count));
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
// clears that result — a recommendation never sits beside a trade it was
// not computed for.
function edited(state, patch) {
  return { ...state, ...patch, phase: "build", result: null, error: null };
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
      const teamCount = clampCount(action.count);
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
      return { ...state, phase: "result", result: action.result, error: null, staleIds: [] };
    case "FAIL": {
      const error = action.error || { kind: "unavailable" };
      const staleIds = error.kind === "stale" && Array.isArray(error.assetIds) ? error.assetIds.slice() : [];
      return { ...state, phase: "build", result: null, error, staleIds };
    }
    case "EDIT":
      return { ...state, phase: "build", result: null, error: null };
    case "NEW_TRADE":
      // Keeps the teams, clears the assets.
      return { ...state, phase: "build", legs: [], result: null, error: null, staleIds: [], notice: null };
    case "START_OVER":
      return initialAdvisorState();
    case "DISMISS_NOTICE":
      return { ...state, notice: null };
    case "RESTORE":
      return action.state ? { ...initialAdvisorState(), ...action.state, phase: action.state.result ? "result" : "build" } : state;
    default:
      return state;
  }
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
  return SLOT_NAMES[index] || `Team ${index + 1}`;
}

/**
 * Client-side readiness, in the order the user should fix things.  These
 * mirror the server's validation (design §2.10 rule 8) so the Analyze button
 * is honest; the server enforces every rule independently.
 */
export function tradeIssues(state, teams = []) {
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
  const sends = new Map(state.slots.map((rid) => [rid, 0]));
  const receives = new Map(state.slots.map((rid) => [rid, 0]));
  for (const leg of state.legs) {
    sends.set(leg.from, (sends.get(leg.from) || 0) + 1);
    if (leg.to != null) receives.set(leg.to, (receives.get(leg.to) || 0) + 1);
  }
  if (state.teamCount === 2) {
    state.slots.forEach((rid, i) => {
      if (!sends.get(rid)) {
        issues.push({
          code: "team_sends_nothing",
          slot: i,
          message: `${i === 0 ? "Your team" : teamLabel(byId.get(rid)) || slotName(i)} must send at least one player or pick.`,
        });
      }
    });
  } else {
    state.slots.forEach((rid, i) => {
      if (!sends.get(rid) && !receives.get(rid)) {
        issues.push({
          code: "idle_team",
          slot: i,
          message: `${teamLabel(byId.get(rid)) || slotName(i)} must send or receive at least one player or pick.`,
        });
      }
    });
  }
  for (const leg of state.legs) {
    if (leg.to == null) {
      issues.push({ code: "choose_destination", id: leg.id, message: `Choose where ${leg.label} goes.` });
    }
  }
  return issues;
}

export function canAnalyze(state, teams) {
  return state.phase !== "submitting" && tradeIssues(state, teams).length === 0;
}

/** The analyze body (frozen contract §4.3): identities and routing only. */
export function toAnalyzeRequest(state) {
  return {
    perspectiveRosterId: state.slots[0],
    teams: state.slots.slice(),
    assets: state.legs.map((l) => ({ id: l.id, from: l.from, to: l.to })),
  };
}

/** A stable key for "this exact trade" (cache of the last result). */
export function tradeKey(request) {
  return JSON.stringify([request.perspectiveRosterId, request.teams, request.assets.map((a) => [a.id, a.from, a.to])]);
}

/**
 * What each team sends and receives, in the order the legs were added.
 * Two-team trades read as "You send / You receive" from the perspective.
 */
export function tradeSummary(state, teams = []) {
  const byId = teamsById(teams);
  const perspective = state.slots[0];
  const name = (rid) => teamLabel(byId.get(rid)) || (rid == null ? "" : `Team ${rid}`);
  return {
    youSend: state.legs.filter((l) => l.from === perspective).map((l) => l.label),
    youReceive: state.legs.filter((l) => l.to === perspective).map((l) => l.label),
    teams: state.slots
      .filter((rid) => rid != null)
      .map((rid) => ({
        rosterId: rid,
        name: name(rid),
        isYou: rid === perspective,
        sends: state.legs.filter((l) => l.from === rid).map((l) => ({ label: l.label, to: l.to, toName: l.to == null ? null : name(l.to) })),
        receives: state.legs.filter((l) => l.to === rid).map((l) => ({ label: l.label, from: l.from, fromName: name(l.from) })),
      })),
  };
}

// ── Asset filtering over the server's order ────────────────────────────────
//
// The backend returns an already-ordered list for the requested sort.  These
// filters only REMOVE rows; they never reorder, so the server's order is
// what the user sees.

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
  const q = String(query || "").trim().toLowerCase();
  return (assets || []).filter((a) => {
    if (group !== "all" && a.side !== group) return false;
    if (position && a.position !== position) return false;
    if (q && !String(a.label || "").toLowerCase().includes(q)) return false;
    return true;
  });
}

// ── Session persistence (identities, labels, result enum + text only) ─────

const RESULT_KEYS = ["category", "recommendation", "headline", "message", "reasonCode", "reasonText", "unavailableAssetIds", "generation", "key", "teamCount"];

export function serializeAdvisorState(state) {
  return JSON.stringify({
    teamCount: state.teamCount,
    slots: state.slots,
    legs: state.legs.map((l) => ({ id: l.id, kind: l.kind, label: l.label, from: l.from, to: l.to })),
    result: state.result ? Object.fromEntries(RESULT_KEYS.map((k) => [k, state.result[k] ?? null])) : null,
  });
}

/**
 * Restore a saved builder.  The URL wins: when `?team=` names a different
 * team than the saved "your team", start fresh with the URL team.  Teams
 * that are no longer in the league are dropped (and their legs with them).
 */
export function restoreAdvisorState(raw, { urlTeam = null, teams = [] } = {}) {
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
  const teamCount = clampCount(saved.teamCount);
  const slots = saved.slots.slice(0, teamCount).map((rid) => (known.has(rid) ? rid : null));
  while (slots.length < teamCount) slots.push(null);
  if (new Set(slots.filter((r) => r != null)).size !== slots.filter((r) => r != null).length) return fresh();
  const rawLegs = Array.isArray(saved.legs) ? saved.legs : [];
  const seen = new Set();
  const legs = [];
  for (const l of rawLegs) {
    if (!l || typeof l.id !== "string" || seen.has(l.id)) continue;
    seen.add(l.id);
    legs.push({ id: l.id, kind: l.kind === "pick" ? "pick" : "player", label: String(l.label || l.id), from: l.from, to: l.to ?? null });
  }
  const reconciled = reconcileLegs(legs, slots).legs;
  const result = saved.result && CATEGORIES.includes(saved.result.category) ? saved.result : null;
  return { ...initialAdvisorState(), teamCount, slots, legs: reconciled, result, phase: result ? "result" : "build" };
}
