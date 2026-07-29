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

import { familyOf } from "@/lib/position-family";

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

/**
 * Project one trade from the PUBLIC league payload
 * (src/public_league/activity.py) into the same ActivityEvent shape
 * ``tradeToEvent`` produces from the private contract.
 *
 * The two payloads describe the same trades with different vocabulary:
 * the public one already resolves team names, owners and asset names
 * server-side (and carries a public-safe ``grade`` block per side),
 * so this projection is a rename rather than a re-derivation.
 */
function publicTradeToEvent(trade) {
  const ts = tsOf(trade?.createdAt);
  const sides = Array.isArray(trade?.sides) ? trade.sides : [];
  const teamNames = sides.map((s) => s?.teamName).filter(Boolean);
  const ownerIds = sides.map((s) => s?.ownerId).filter(Boolean);
  const rosterIds = sides.map((s) => s?.rosterId).filter((r) => r != null);

  const playerNames = [];
  for (const side of sides) {
    for (const asset of side?.receivedAssets || []) {
      const name = asset?.name || asset?.label;
      if (typeof name === "string" && name.trim()) playerNames.push(name);
    }
  }

  const summary =
    teamNames.length >= 2
      ? `${teamNames[0]} ↔ ${teamNames.slice(1).join(", ")}`
      : teamNames.join(", ") || "Trade";

  return {
    id: `trade::${trade?.transactionId || ts}`,
    type: "trade",
    ts,
    title: summary,
    detail: playerNames.length
      ? playerNames.slice(0, 6).join(" · ")
      : `Multi-asset trade between ${teamNames.length} teams`,
    teamNames,
    rosterIds,
    ownerIds,
    playerNames,
    // Public-safe grade badges: letter + label + colour only, never
    // the underlying per-side totals.
    grades: sides
      .map((s) => (s?.grade ? { teamName: s?.teamName, ...s.grade } : null))
      .filter(Boolean),
    url: null,
    severity: "info",
    season: trade?.season ?? null,
  };
}

/**
 * Build the feed from the PUBLIC league activity section + news.
 *
 * ``/league/activity`` lives under the public-only route prefix, where
 * ``useApp()`` hard-codes ``rawData: null`` so the private contract can
 * never hydrate.  The page was still calling ``buildActivityEvents``
 * with that null, so its trade half was permanently empty — for
 * signed-in users too.  This is the builder that route should use.
 */
export function buildPublicActivityEvents(publicTrades, newsItems) {
  const events = [];
  if (Array.isArray(publicTrades)) {
    for (const t of publicTrades) events.push(publicTradeToEvent(t));
  }
  if (Array.isArray(newsItems)) {
    for (const n of newsItems) events.push(newsToEvent(n));
  }
  events.sort((a, b) => b.ts - a.ts);
  return events;
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

export function filterEvents(
  events,
  { scope = "league", rosterNames = [], type = "all", ownerId = null } = {},
) {
  if (!Array.isArray(events)) return [];
  const lowerRoster = new Set(
    (rosterNames || [])
      .filter((n) => typeof n === "string" && n.length)
      .map((n) => n.toLowerCase()),
  );
  const myOwner = ownerId == null ? null : String(ownerId);
  return events.filter((e) => {
    if (type !== "all" && e.type !== type) return false;
    if (scope === "roster") {
      // A trade the user was party to is theirs regardless of whether
      // the assets are still on their roster — owner match is both
      // cheaper and more accurate than name matching, so prefer it
      // when the event carries owner ids (public payload) and the
      // caller knows who the user is.
      if (myOwner && (e.ownerIds || []).some((o) => String(o) === myOwner)) {
        return true;
      }
      if (!lowerRoster.size) return false;
      return (e.playerNames || []).some(
        (n) => typeof n === "string" && lowerRoster.has(n.toLowerCase()),
      );
    }
    return true;
  });
}

/** Coarse position family — thin alias over the shared
 * ``lib/position-family`` map, identical to ``movers.familyOf``. */
export function familyOfPos(pos) {
  return familyOf(pos);
}
