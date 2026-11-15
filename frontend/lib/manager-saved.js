/**
 * Manager Intelligence Batch F — saved managers, new-activity check and
 * scoped leaderboards (C6-MGR-02).
 *
 * Display helpers only.  The saved list, every leaderboard rank, value,
 * population count and reason are computed by the backend
 * (`src/intel/manager_saved.py`, `manager_alerts.py`,
 * `manager_leaderboard.py`); this module builds requests and labels.
 * Saved managers are keyed by the permanent Sleeper user id — never the
 * username, which can change.  A missing value reads "—", never 0.
 */

import { LEAGUE_ID_RE, USERNAME_RE, formatDate } from "./manager-intel";

export const SAVED_ENDPOINT = "/api/manager-intel/saved";
export const SAVED_REFRESH_ENDPOINT = "/api/manager-intel/saved/refresh";
export const LEADERBOARD_ENDPOINT = "/api/manager-intel/leaderboard";
export const LEADERBOARD_PATH = "/managers/leaderboards";

export const USER_ID_RE = /^\d{1,24}$/;

export const POPULATIONS = [
  { value: "saved", label: "Saved managers" },
  { value: "league", label: "A league" },
];

/** True when ``userId`` is on the saved list (by id, never by name). */
export function isSaved(saved, userId) {
  const id = String(userId || "");
  if (!USER_ID_RE.test(id)) return false;
  return (saved?.managers || []).some((m) => m.userId === id);
}

/** The POST body that saves a manager — the id only; the server resolves names. */
export function saveBody(userId, { alerts } = {}) {
  const id = String(userId || "");
  if (!USER_ID_RE.test(id)) return null;
  return typeof alerts === "boolean" ? { userId: id, alerts } : { userId: id };
}

export function deleteUrl(userId) {
  const id = String(userId || "");
  return USER_ID_RE.test(id)
    ? `${SAVED_ENDPOINT}?userId=${encodeURIComponent(id)}`
    : null;
}

export function savedCapText(saved) {
  const count = saved?.count ?? (saved?.managers || []).length;
  const limit = saved?.limit;
  return typeof limit === "number" ? `${count} of ${limit} saved` : `${count} saved`;
}

/** True only when both the count and the limit are known and the list is full;
 *  an unknown count is unknown fullness, never "full". */
export function atCap(saved) {
  return (
    typeof saved?.count === "number" &&
    typeof saved?.limit === "number" &&
    saved.count >= saved.limit
  );
}

const NAME_STATE_TEXT = {
  current: "",
  stored: "Name not re-checked just now",
  not_found: "Sleeper no longer finds this account",
  id_mismatch: "Sleeper answered for a different account — name not updated",
};

export function nameStateText(entry) {
  return NAME_STATE_TEXT[entry?.nameState] ?? NAME_STATE_TEXT.stored;
}

export function formerNamesText(entry) {
  const prev = (entry?.previousUsernames || []).filter(Boolean);
  return prev.length ? `formerly ${prev.map((p) => `@${p}`).join(", ")}` : "";
}

/** One line about a saved manager's activity checks. */
export function alertStateText(entry) {
  if (entry?.alerts === false) return "Alerts off";
  const st = entry?.alertState || {};
  if (!st.seeded) {
    return st.lastStatus && st.lastStatus !== "ok" && st.lastStatus !== "partial"
      ? `Not read yet (last attempt: ${String(st.lastStatus).replace(/_/g, " ")})`
      : "Not checked yet — the first check records recent activity without alerting";
  }
  const parts = [`Checked ${formatDate(st.lastCheckedAt)}`];
  if (st.lastStatus === "partial") parts.push("some leagues not fully read");
  if (typeof st.lastAlertAt === "number")
    parts.push(`last new activity ${formatDate(st.lastAlertAt)}`);
  return parts.join(" · ");
}

export function lookupHref(entry) {
  // The username is the lookup's handle; the id also resolves on Sleeper.
  const handle = USERNAME_RE.test(String(entry?.username || ""))
    ? entry.username
    : entry?.userId;
  return USERNAME_RE.test(String(handle || ""))
    ? `/managers?username=${encodeURIComponent(handle)}`
    : null;
}

// ── new-activity check ──────────────────────────────────────────────────

const KIND_LABELS = {
  trade: "Trade",
  waiver: "Waiver claim",
  free_agent: "Free-agent add",
  drop: "Drop",
  commissioner: "Commissioner move",
  draft: "Draft pick",
};

export function eventLine(ev) {
  const parts = [KIND_LABELS[ev?.kind] || "Move"];
  if (ev?.leagueName) parts.push(`in ${ev.leagueName}`);
  let line = parts.join(" ");
  if (ev?.added?.length) line += ` — added ${ev.added.join(", ")}`;
  if (ev?.dropped?.length) line += `; gave up ${ev.dropped.join(", ")}`;
  if (typeof ev?.faabBid === "number") line += ` (FAAB $${ev.faabBid})`;
  return line;
}

const CHECK_MODE_TEXT = {
  baseline_seeded: "First check — recent activity recorded; new moves are reported from now on.",
  ok: "",
  unread: "Could not be read from Sleeper this time.",
  rate_limited: "Sleeper is rate-limiting us — try again later.",
  not_saved: "No longer saved.",
};

export function checkModeText(mode) {
  return CHECK_MODE_TEXT[mode] ?? "";
}

/** Summary rows of a refresh response: one per checked manager. */
export function refreshRows(result) {
  return (result?.checked || []).map((c) => ({
    userId: c.userId,
    name: c.displayName || c.userId,
    mode: c.mode,
    note: checkModeText(c.mode),
    events: c.newEvents || [],
  }));
}

// ── leaderboards ────────────────────────────────────────────────────────

export function leaderboardQuery({ population, leagueId, window } = {}) {
  if (population === "saved") return `${LEADERBOARD_ENDPOINT}?population=saved`;
  if (population !== "league" || !LEAGUE_ID_RE.test(String(leagueId || "")))
    return null;
  const params = new URLSearchParams({ population: "league", leagueId: String(leagueId) });
  if (window) params.set("window", window);
  return `${LEADERBOARD_ENDPOINT}?${params.toString()}`;
}

export function leaderboardHref({ population = "saved", leagueId } = {}) {
  if (population === "league") {
    return LEAGUE_ID_RE.test(String(leagueId || ""))
      ? `${LEADERBOARD_PATH}?population=league&league=${encodeURIComponent(leagueId)}`
      : null;
  }
  return `${LEADERBOARD_PATH}?population=saved`;
}

/** Initial leaderboard inputs from a query string (invalid values dropped). */
export function readLeaderboardParams(search) {
  const q = new URLSearchParams(search || "");
  const league = q.get("league") || "";
  const validLeague = LEAGUE_ID_RE.test(league) ? league : "";
  const population = q.get("population") === "league" || validLeague ? "league" : "saved";
  return { population, leagueId: validLeague };
}

/** "Your saved managers · 12 managers (9 with data)" — population and n. */
export function populationText(population) {
  if (!population) return "";
  const noun = population.kind === "league" ? "team" : "manager";
  const n = population.n;
  const base =
    typeof n === "number"
      ? `${population.label} · ${n} ${noun}${n === 1 ? "" : "s"}`
      : `${population.label} · size unknown`;
  if (population.kind === "saved" && typeof population.withData === "number")
    return `${base} (${population.withData} with recent data)`;
  return base;
}

export function boardCountText(board, population) {
  const ranked = typeof board?.n === "number" ? board.n : null;
  const total = typeof population?.n === "number" ? population.n : null;
  if (ranked === null) return "Ranked count unknown";
  return total === null ? `${ranked} ranked` : `${ranked} of ${total} ranked`;
}

const REASON_TEXT = {
  not_yet_read: "not read yet",
  snapshot_undated: "last read date unknown",
  snapshot_stale: "last read over 72 hours ago",
  activity_partially_read: "activity not fully read",
  pick_ownership_unavailable: "pick ownership unknown",
  earlier_season: "earlier season — picks not read",
  canonical_board_is_superflex: "not a Superflex league — board totals withheld",
  board_unavailable: "board not loaded",
  unpriced: "not priced by the board",
  no_current_owner: "no current owner",
  unavailable: "unavailable",
};

export function reasonText(reason) {
  if (!reason) return "";
  return REASON_TEXT[reason] || String(reason).replace(/_/g, " ");
}

export function boardValueText(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString("en-US");
}

/** One display row per ranked member, then the unranked with their reason. */
export function boardRows(board) {
  const ranked = (board?.rows || []).map((r) => ({
    id: r.id,
    rank: r.rank,
    name: r.displayName || r.username || r.teamName || "Unknown manager",
    sub: r.teamName && r.teamName !== r.displayName ? r.teamName : r.username ? `@${r.username}` : "",
    userId: r.userId || null,
    value: boardValueText(r.value),
    asOf: r.asOf ?? null,
    reason: "",
  }));
  const unranked = (board?.unranked || []).map((r) => ({
    id: r.id,
    rank: null,
    name: r.displayName || r.username || r.teamName || "Unknown manager",
    sub: r.teamName && r.teamName !== r.displayName ? r.teamName : r.username ? `@${r.username}` : "",
    userId: r.userId || null,
    value: "—",
    asOf: r.asOf ?? null,
    reason: reasonText(r.reason),
  }));
  return [...ranked, ...unranked];
}

export function savedErrorMessage(status, body) {
  if (body && typeof body.message === "string" && body.message) return body.message;
  if (status === 409) return "Your saved list is full — remove a manager first.";
  if (status === 429) return "Too many requests — wait a moment and try again.";
  if (status === 401) return "Sign in to save managers.";
  if (status === 403) return "Guest passes cannot save managers.";
  return "Saved managers are unavailable right now.";
}
