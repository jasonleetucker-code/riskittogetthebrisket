/**
 * activity-feed — pure helpers that combine Sleeper trades + news
 * items + (optionally) waiver moves into a single chronological feed.
 *
 * No I/O — caller provides ``rawData`` (the live contract) and
 * ``newsItems`` (from useNews); we project them into a uniform
 * ``ActivityEvent`` shape that the feed UI renders.
 *
 * Filtering happens at render time: the feed page lets the user
 * scope to "my roster" (events touching any selectedTeam player)
 * or "league wide" (everything).
 */

const POS_FAMILY = {
  QB: "QB", RB: "RB", FB: "RB", WR: "WR", TE: "TE",
  DL: "DL", DT: "DL", DE: "DL", EDGE: "DL", NT: "DL",
  LB: "LB", ILB: "LB", OLB: "LB", MLB: "LB",
  DB: "DB", CB: "DB", S: "DB", FS: "DB", SS: "DB",
};

function familyOf(pos) {
  return POS_FAMILY[String(pos || "").toUpperCase()] || "OTHER";
}

function tsOf(value) {
  if (!value) return 0;
  if (typeof value === "number" && Number.isFinite(value)) {
    return value < 1e12 ? value * 1000 : value;
  }
  const t = Date.parse(value);
  return Number.isFinite(t) ? t : 0;
}

function teamFromOwnerId(rawData, ownerId) {
  const teams = rawData?.sleeper?.teams || [];
  for (const t of teams) {
    if (String(t?.ownerId) === String(ownerId)) return t;
  }
  return null;
}

function tradeToEvent(trade, rawData) {
  const ts = tsOf(trade?._statusUpdatedMs || trade?.status_updated || trade?.created);
  const rosterIds = Array.isArray(trade?.roster_ids) ? trade.roster_ids : [];
  const teams = rawData?.sleeper?.teams || [];
  const teamsInTrade = rosterIds
    .map((rid) => teams.find((t) => String(t?.rosterId) === String(rid)))
    .filter(Boolean);
  const teamNames = teamsInTrade.map((t) => t?.name).filter(Boolean);

  // adds: { sleeperPlayerId/pickLabel: rosterId } — roster that received
  const adds = trade?.adds && typeof trade.adds === "object" ? trade.adds : {};
  const drops = trade?.drops && typeof trade.drops === "object" ? trade.drops : {};
  const playerNamesSeen = new Set();
  const positions = rawData?.sleeper?.positions || {};

  for (const pid of [...Object.keys(adds), ...Object.keys(drops)]) {
    const meta = positions[pid];
    const name = meta?.name || (typeof meta === "string" ? meta : null);
    if (typeof name === "string" && name.trim()) {
      playerNamesSeen.add(name);
    }
  }

  const summary = teamNames.length >= 2
    ? `${teamNames[0]} ↔ ${teamNames.slice(1).join(", ")}`
    : `${teamNames.join(", ") || "Trade"}`;

  return {
    id: `trade::${trade?.transaction_id || trade?.id || ts}`,
    type: "trade",
    ts,
    title: summary,
    detail: playerNamesSeen.size
      ? Array.from(playerNamesSeen).slice(0, 6).join(" · ")
      : `Multi-asset trade between ${teamNames.length} teams`,
    teamNames,
    rosterIds,
    playerNames: Array.from(playerNamesSeen),
    url: null,
    severity: "info",
  };
}

function newsToEvent(item) {
  const ts = tsOf(item?.ts || item?.publishedAt || item?.published);
  const playerNames = Array.isArray(item?.players)
    ? item.players.map((p) => (typeof p === "string" ? p : p?.name)).filter(Boolean)
    : [];
  return {
    id: `news::${item?.id || ts || item?.headline}`,
    type: "news",
    ts,
    title: String(item?.headline || item?.title || "News"),
    detail: String(item?.body || item?.summary || "")
      .slice(0, 300)
      || (item?.providerLabel || item?.provider || ""),
    teamNames: [],
    rosterIds: [],
    playerNames,
    url: typeof item?.url === "string" ? item.url : null,
    severity: String(item?.severity || "info").toLowerCase(),
  };
}

export function buildActivityEvents(rawData, newsItems) {
  const events = [];
  const trades = rawData?.sleeper?.trades || [];
  if (Array.isArray(trades)) {
    for (const t of trades) events.push(tradeToEvent(t, rawData));
  }
  if (Array.isArray(newsItems)) {
    for (const n of newsItems) events.push(newsToEvent(n));
  }
  events.sort((a, b) => b.ts - a.ts);
  return events;
}

export function filterEvents(events, { scope = "league", rosterNames = [], type = "all" } = {}) {
  if (!Array.isArray(events)) return [];
  const lowerRoster = new Set(
    (rosterNames || [])
      .filter((n) => typeof n === "string" && n.length)
      .map((n) => n.toLowerCase()),
  );
  return events.filter((e) => {
    if (type !== "all" && e.type !== type) return false;
    if (scope === "roster") {
      if (!lowerRoster.size) return false;
      return (e.playerNames || []).some((n) =>
        typeof n === "string" && lowerRoster.has(n.toLowerCase()),
      );
    }
    return true;
  });
}

export function familyOfPos(pos) {
  return familyOf(pos);
}
