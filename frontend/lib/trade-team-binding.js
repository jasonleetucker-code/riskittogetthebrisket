/**
 * trade-team-binding — which league team each /trade side is, by id (spec
 * docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §3.2), and whether the private
 * multi-team analysis is switched on.  Kept apart from
 * ./trade-multi-team.js so the page chunk carries only these few helpers; the
 * ledger builder and the War Room copy load with the lazy multi-team War Room.
 *
 * Identity is by id only: a team is its Sleeper `roster_id`, a player is
 * `p:<sleeperId>`, a pick is its canonical league pick id
 * (`sleeper.teams[].pickDetails[].assetId`).  Display names decide nothing.
 */

export const MULTI_TEAM_ENDPOINT = "/api/trade/analyze-multi";

/** A league team's stable id, or null. */
export function teamRosterId(team) {
  const raw = team?.roster_id ?? team?.rosterId;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 ? n : null;
}

/** `{rosterId, name}` per league team, in league order; teams without an id are skipped. */
export function teamOptions(teams) {
  const out = [];
  for (const t of teams || []) {
    const rosterId = teamRosterId(t);
    if (rosterId != null) out.push({ rosterId, name: String(t?.name || `Team ${rosterId}`) });
  }
  return out;
}

const PICK_ROW = /^(?:\d{4})\s/;

/**
 * The canonical asset id of one builder entry, or `{reason}` when it has none:
 *   * an owned pick entry → its `assetId` (league pick identity);
 *   * a generic market pick ("2027 Mid 1st", no owner) → `generic_pick`;
 *   * a player row with a Sleeper id → `p:<id>`; without one → `no_player_id`.
 */
export function entryAssetRef(entry) {
  if (!entry) return { reason: "no_player_id" };
  const assetId = String(entry.assetId || "").trim();
  if (assetId) return { id: assetId, kind: "pick" };
  const isPick =
    String(entry.pos || "").toUpperCase() === "PICK" ||
    entry.assetClass === "pick" ||
    PICK_ROW.test(String(entry.name || ""));
  if (isPick) return { reason: "generic_pick" };
  const pid = String(entry.playerId ?? entry.raw?.playerId ?? "").trim();
  if (pid && /^[A-Za-z0-9]{1,16}$/.test(pid)) return { id: `p:${pid}`, kind: "player" };
  return { reason: "no_player_id" };
}

/** Every asset id a league team holds in the loaded contract (players + owned picks). */
export function teamHoldings(team) {
  const ids = new Set();
  for (const pid of team?.playerIds || []) {
    if (pid != null && String(pid).trim()) ids.add(`p:${String(pid).trim()}`);
  }
  for (const d of team?.pickDetails || []) {
    if (d?.assetId) ids.add(String(d.assetId));
  }
  return ids;
}

/**
 * The team a side's assets prove, by id: the ONE league team that holds every
 * identified asset on the side.  `null` when the side is empty, holds an
 * unidentified asset, or no single team holds all of it — the War Room then
 * asks instead of assuming.
 */
export function inferSideRosterId(side, teams) {
  const refs = (side?.assets || []).map(entryAssetRef);
  if (!refs.length || refs.some((r) => !r.id)) return null;
  let found = null;
  for (const t of teams || []) {
    const rid = teamRosterId(t);
    if (rid == null) continue;
    const held = teamHoldings(t);
    if (refs.every((r) => held.has(r.id))) {
      if (found != null) return null; // two teams claim it: not proven
      found = rid;
    }
  }
  return found;
}

/**
 * The binding the War Room uses for each side: an explicit choice wins
 * (`null` = explicitly none); `undefined` falls back to `inferSideRosterId`.
 */
export function effectiveBindings(sides, explicit, teams) {
  return (sides || []).map((side, i) => {
    const e = explicit?.[i];
    if (e === null) return { rosterId: null, basis: "none" };
    if (Number.isInteger(e)) return { rosterId: e, basis: "explicit" };
    const inferred = inferSideRosterId(side, teams);
    return inferred == null
      ? { rosterId: null, basis: "none" }
      : { rosterId: inferred, basis: "roster" };
  });
}

/**
 * Is the private multi-team analysis switched on?  For a signed-in session
 * the route answers its flag FIRST — off is `503 multi_team_analysis_disabled`
 * before the body is read — and on answers the empty probe with `400
 * invalid_request`, so the probe runs no analysis.  Only that 400 means "on".
 * A 401 (the API gate in front of every private route, an expired session), a
 * network failure or any other answer is `false`: the page keeps its existing
 * behaviour rather than offering an analysis it cannot run.
 */
export async function probeMultiTeamAnalysis(
  fetchImpl = typeof fetch === "function" ? fetch : null,
) {
  if (!fetchImpl) return false;
  try {
    const res = await fetchImpl(MULTI_TEAM_ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 503 && data?.error === "multi_team_analysis_disabled") return false;
    return res.status === 400 && data?.error === "invalid_request";
  } catch {
    return false;
  }
}
