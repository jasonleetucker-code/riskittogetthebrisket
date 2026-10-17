/**
 * Manager Intelligence — pure helpers for /managers.
 *
 * Display layer only: every count, exposure share and value comes from
 * GET /api/manager-intel/profile.  Nothing here recomputes a value or an
 * exposure denominator; it filters, labels and formats what the backend
 * published.  Missing stays missing: a null value renders "—", never 0.
 */

export const SCOPES = [
  { value: "dynasty", label: "Dynasty" },
  { value: "keeper", label: "Keeper" },
  { value: "redraft", label: "Redraft" },
  { value: "unknown", label: "Unknown type" },
];

const SLOT_LABELS = {
  starter: "Starter",
  bench: "Bench",
  taxi: "Taxi",
  reserve: "IR",
};

export const USERNAME_RE = /^[A-Za-z0-9_]{1,40}$/;

export function slotLabel(slot) {
  return SLOT_LABELS[slot] || "Rostered";
}

export function profileQuery(username, scope = "dynasty") {
  const params = new URLSearchParams({
    username: String(username || "").trim(),
  });
  if (scope && scope !== "dynasty") params.set("scope", scope);
  return `/api/manager-intel/profile?${params.toString()}`;
}

/** Exposure as "7 / 12" plus a percentage, or "—" when unmeasurable. */
export function exposureText(exposure) {
  if (!exposure || !exposure.eligibleLeagues) return "—";
  const pct =
    exposure.share == null ? "" : ` (${Math.round(exposure.share * 100)}%)`;
  return `${exposure.owned} / ${exposure.eligibleLeagues}${pct}`;
}

export function formatValue(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US")
    : "—";
}

/** Distinct, sorted filter options present in the portfolio. */
export function filterOptions(players, field) {
  const set = new Set();
  for (const p of players || []) if (p?.[field]) set.add(p[field]);
  return [...set].sort();
}

export function filterPlayers(
  players,
  { query = "", position = "", team = "" } = {},
) {
  const q = String(query || "")
    .trim()
    .toLowerCase();
  return (players || []).filter((p) => {
    if (position && p.position !== position) return false;
    if (team && p.nflTeam !== team) return false;
    if (
      q &&
      !String(p.name || "")
        .toLowerCase()
        .includes(q)
    )
      return false;
    return true;
  });
}

/** League detail rows for one player, joined to the league list. */
export function playerLeagueRows(player, leagues) {
  const byId = new Map((leagues || []).map((l) => [l.leagueId, l]));
  return (player?.leagues || []).map((entry) => {
    const league = byId.get(entry.leagueId) || {};
    return {
      leagueId: entry.leagueId,
      name: league.name || "Unnamed league",
      slot: slotLabel(entry.slot),
      format: formatBadge(league.format),
    };
  });
}

/** "SF · TEP · IDP · 12 teams" from the backend's league_format facts. */
export function formatBadge(format) {
  if (!format) return "";
  const parts = [];
  if (format.superflex === true) parts.push("SF");
  else if (format.superflex === false) parts.push("1QB");
  if (format.tePremium) parts.push("TEP");
  if (format.idp) parts.push("IDP");
  if (format.bestBall) parts.push("Best ball");
  if (format.teams) parts.push(`${format.teams} teams`);
  return parts.join(" · ");
}

export function errorMessage(status, body) {
  if (body && typeof body.message === "string" && body.message)
    return body.message;
  if (status === 404) return "No Sleeper user by that name.";
  if (status === 429) return "Too many lookups — wait a moment and try again.";
  if (status === 401) return "Sign in to use Manager Intelligence.";
  return "Manager Intelligence is unavailable right now.";
}

// ── recent searches (per-viewer convenience; never required) ────────────

const RECENT_KEY = "managerIntel.recent";
const RECENT_MAX = 8;

export function readRecent(storage = safeStorage()) {
  try {
    const raw = storage?.getItem(RECENT_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list)
      ? list.filter((u) => USERNAME_RE.test(u)).slice(0, RECENT_MAX)
      : [];
  } catch {
    return [];
  }
}

export function rememberRecent(username, storage = safeStorage()) {
  const name = String(username || "").trim();
  if (!USERNAME_RE.test(name)) return readRecent(storage);
  const next = [
    name,
    ...readRecent(storage).filter(
      (u) => u.toLowerCase() !== name.toLowerCase(),
    ),
  ].slice(0, RECENT_MAX);
  try {
    storage?.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: the list just isn't remembered */
  }
  return next;
}

function safeStorage() {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

// ── summary / league rows ───────────────────────────────────────────────

const LEAGUE_STATE_LABELS = {
  ok: "Read",
  no_roster: "No roster held",
  unavailable: "Could not be read",
  rate_limited: "Rate-limited — not read",
};

export function leagueStateLabel(state) {
  return LEAGUE_STATE_LABELS[state] || "Unknown";
}

export function recordText(record) {
  if (!record || record.wins == null || record.losses == null) return "—";
  const ties = record.ties ? `-${record.ties}` : "";
  return `${record.wins}-${record.losses}${ties}`;
}

function pct(share) {
  return share == null ? "—" : `${Math.round(share * 100)}%`;
}

/** Summary tiles straight from the backend's summary block. */
export function summaryTiles(profile) {
  const s = profile?.summary;
  if (!s) return [];
  const superflex = s.byFormat?.superflex;
  return [
    {
      key: "leagues",
      label: "Leagues read",
      value: formatValue(s.leaguesRead),
      meta: profile.leaguesUnreadable
        ? `${profile.leaguesUnreadable} unreadable`
        : null,
    },
    {
      key: "players",
      label: "Unique players",
      value: formatValue(s.uniquePlayers),
    },
    {
      key: "instances",
      label: "Rostered spots",
      value: formatValue(s.ownedInstances),
      meta: `${formatValue(s.offenseInstances)} offense · ${formatValue(s.idpInstances)} IDP`,
    },
    {
      key: "age",
      label: "Median age",
      value: s.ageMedian == null ? "—" : String(s.ageMedian),
      meta: s.ageKnownPlayers
        ? `${s.ageKnownPlayers} player${s.ageKnownPlayers === 1 ? "" : "s"} with a known age`
        : null,
    },
    {
      key: "top10",
      label: "Top-10 concentration",
      value: pct(s.top10InstanceShare),
    },
    {
      key: "value",
      label: "Superflex board value",
      value: superflex ? formatValue(superflex.boardValue) : "—",
      meta: superflex
        ? `${formatValue(superflex.pricedInstances)} of ${formatValue(superflex.instances)} spots priced`
        : "No Superflex league read",
    },
  ];
}
