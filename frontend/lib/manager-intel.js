/**
 * Manager Intelligence — pure helpers for /managers.
 *
 * Display layer only: every count, exposure share and value comes from
 * GET /api/manager-intel/profile.  Nothing here recomputes a value or an
 * exposure denominator; it filters, labels and formats what the backend
 * published.  Missing stays missing: a null value renders "—", never 0.
 */

import {
  describePickOwnershipReason,
  pickOwnershipUnavailableReason,
} from "@/lib/pick-ownership";

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

// ── activity: recent trades, acquisitions, feed (Batches B1 + B2) ───────
//
// Same rule as above: GET /api/manager-intel/activity computes every value,
// total, package comparison, at-time grade and coverage state.  These helpers
// only filter, label and build links.  An unpriced asset stays "—", a missing
// date stays "Undated", and an unread league is named, never hidden.

export const ACTIVITY_WINDOWS = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "season", label: "Season" },
];

export const TRADE_DIRECTIONS = [
  { value: "any", label: "In or out" },
  { value: "in", label: "Acquired" },
  { value: "out", label: "Sent" },
];

export function activityQuery(
  username,
  { window = "30d", season = "", league = "", scope = "dynasty" } = {},
) {
  const params = new URLSearchParams({
    username: String(username || "").trim(),
  });
  if (window && window !== "30d") params.set("window", window);
  if (season) params.set("season", String(season));
  if (league) params.set("league", String(league));
  if (scope && scope !== "dynasty") params.set("scope", scope);
  return `/api/manager-intel/activity?${params.toString()}`;
}

/** The current season and the two before it, newest first. */
export function seasonOptions(currentSeason) {
  const year = Number.parseInt(currentSeason, 10);
  if (!Number.isFinite(year)) return [];
  return [year, year - 1, year - 2].map(String);
}

/** "Oct 12, 2026", or "Undated" — an absent stamp is never epoch zero. */
export function formatDate(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0)
    return "Undated";
  const d = new Date(ms);
  return Number.isNaN(d.getTime())
    ? "Undated"
    : d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
}

/** A dated event's date; an undated one says so (with its bound, if any). */
export function eventDateText(item) {
  if (typeof item?.occurredAt === "number") return formatDate(item.occurredAt);
  const bound = item?.occurredBound?.notAfter;
  return typeof bound === "number"
    ? `Undated (on or before ${formatDate(bound)})`
    : "Undated";
}

export function assetLabel(asset) {
  if (!asset) return "";
  if (asset.kind === "pick") return asset.label || "Unknown pick";
  return asset.name || `Player ${asset.playerId}`;
}

const VALUE_REASONS = {
  board_unavailable: "board not loaded",
  not_on_board: "not on the board",
  unpriced_by_board: "board does not price him",
  pick_already_used: "pick already used",
  draft_status_unknown: "draft status unknown",
  no_board_row_for_ref: "no board value for this pick",
  outside_board_grammar: "pick outside the board",
  pick_unparseable: "unreadable pick",
  row_present_but_unpriced: "board does not price it",
  alias_target_missing: "no board value for this pick",
};

export function valueReasonText(reason) {
  return VALUE_REASONS[reason] || (reason ? String(reason) : "");
}

export function sideAssets(side, direction) {
  if (!side) return [];
  return direction === "in"
    ? [...(side.playersIn || []), ...(side.picksIn || [])]
    : [...(side.playersOut || []), ...(side.picksOut || [])];
}

export function faabText(amount) {
  return typeof amount === "number" ? `$${amount} FAAB` : "";
}

function assetMatches(asset, q) {
  return assetLabel(asset).toLowerCase().includes(q);
}

/**
 * Filter trades by league and by a player/pick text, optionally only among
 * what the MANAGER acquired ("in") or sent ("out").
 */
export function filterTrades(
  trades,
  { league = "", query = "", direction = "any" } = {},
) {
  const q = String(query || "")
    .trim()
    .toLowerCase();
  return (trades || []).filter((t) => {
    if (league && t.leagueId !== league) return false;
    if (!q) return true;
    const me = (t.sides || []).find((s) => s.isManager);
    if (!me) return false;
    const pool =
      direction === "in"
        ? sideAssets(me, "in")
        : direction === "out"
          ? sideAssets(me, "out")
          : [...sideAssets(me, "in"), ...sideAssets(me, "out")];
    return pool.some((a) => assetMatches(a, q));
  });
}

export function filterAcquisitions(
  acquisitions,
  { league = "", method = "", query = "" } = {},
) {
  const q = String(query || "")
    .trim()
    .toLowerCase();
  return (acquisitions || []).filter((a) => {
    if (league && a.leagueId !== league) return false;
    if (method && a.method !== method) return false;
    if (q && !assetLabel(a.player).toLowerCase().includes(q)) return false;
    return true;
  });
}

export function filterFeed(feed, { league = "" } = {}) {
  return (feed || []).filter((f) => !league || f.leagueId === league);
}

const METHOD_LABELS = {
  TRADE: "Trade",
  WAIVER: "Waiver",
  FREE_AGENT: "Free agent",
  DRAFT: "Draft",
  OTHER: "Commissioner",
};

export function methodLabel(method) {
  return METHOD_LABELS[method] || "Other";
}

/** "Waiver · $12 FAAB" / "Draft · 2.06" / "Free agent". */
export function methodDetail(acq) {
  const base = methodLabel(acq?.method);
  if (acq?.method === "WAIVER" && typeof acq.faabBid === "number")
    return `${base} · $${acq.faabBid}`;
  if (acq?.method === "DRAFT" && acq.draft) {
    const d = acq.draft;
    if (typeof d.auctionAmount === "number")
      return `${base} · $${d.auctionAmount}`;
    if (d.round != null && d.slot != null)
      return `${base} · ${d.round}.${String(d.slot).padStart(2, "0")}`;
    if (d.round != null) return `${base} · round ${d.round}`;
  }
  return base;
}

const FEED_KIND_LABELS = {
  trade: "Trade",
  waiver: "Waiver claim",
  free_agent: "Free-agent add",
  drop: "Drop",
  commissioner: "Commissioner move",
  draft: "Draft pick",
};

export function feedKindLabel(kind) {
  return FEED_KIND_LABELS[kind] || "Move";
}

const SUBSEQUENT_LABELS = {
  still_rostered: "Still rostered",
  traded_away: "Later traded away",
  dropped: "Later dropped",
  unknown: "Left roster — not seen how",
};

export function subsequentLabel(subsequent) {
  return SUBSEQUENT_LABELS[subsequent?.state] || "Unknown";
}

export function rosterStatusText(acq) {
  if (acq?.stillRostered === true) return slotLabel(acq.currentSlot);
  if (acq?.stillRostered === false) return "Not rostered";
  return "Unknown";
}

const ATTRIBUTION_TEXT = {
  previous_owner_possible:
    "Possibly the roster's previous owner — not counted as this manager's acquisition.",
  attribution_uncertain:
    "No party's current owner made this trade — it may predate an ownership change.",
};

export function attributionNote(attribution) {
  return attribution?.uncertain
    ? ATTRIBUTION_TEXT[attribution.basis] || "Attribution uncertain."
    : "";
}

const COVERAGE_LABELS = {
  complete: "Read",
  partial: "Partly read",
  none: "Not read",
  unavailable: "Could not be read",
  rate_limited: "Rate-limited",
};

export function coverageLabel(state) {
  return COVERAGE_LABELS[state] || "Unknown";
}

/**
 * Leagues whose transactions, drafts or (when draft capital is served)
 * traded picks were not fully read.
 */
export function coverageProblems(activity) {
  const picksServed = activity?.draftCapital?.available === true;
  const picksProblem = (l) =>
    picksServed && l.tradedPicks != null && l.tradedPicks !== "complete";
  return (activity?.coverage?.leagues || [])
    .filter(
      (l) =>
        l.rosterHeld !== false &&
        (l.transactions !== "complete" ||
          l.drafts !== "complete" ||
          picksProblem(l)),
    )
    .map((l) => ({
      leagueId: l.leagueId,
      name: l.name || "Unnamed league",
      text:
        l.transactions !== "complete"
          ? `transactions ${coverageLabel(l.transactions).toLowerCase()}${
              l.weeksFailed
                ? ` (${l.weeksFailed} week${l.weeksFailed === 1 ? "" : "s"} missing)`
                : ""
            }`
          : l.drafts !== "complete"
            ? `drafts ${coverageLabel(l.drafts).toLowerCase()}`
            : `traded picks ${coverageLabel(l.tradedPicks).toLowerCase()}`,
    }));
}

/** "+1,234" / "−1,234" / "0" / "—". */
export function signedValue(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  if (n === 0) return "0";
  return `${n > 0 ? "+" : "−"}${Math.abs(n).toLocaleString("en-US")}`;
}

/**
 * The Trade Calculator link for one trade.  Each calculator side lists what
 * that team SENDS (the calculator's convention — see TradeDeskView), named
 * the way the calculator resolves rows: players by their board row name,
 * picks by the board row the backend valued them from.  An asset the board
 * cannot name is left out and reported, and FAAB has no calculator asset,
 * so ``complete`` is false whenever anything could not travel.
 */
export function tradeCalculatorShare(trade) {
  const missing = [];
  const sides = (trade?.sides || []).map((side) => {
    const players = [];
    for (const asset of sideAssets(side, "out")) {
      const name = asset.kind === "pick" ? asset.boardRowName : asset.boardName;
      if (name) players.push(name);
      else missing.push(assetLabel(asset));
    }
    return { name: side.displayName || `Roster ${side.rosterId}`, players };
  });
  const faab = (trade?.sides || []).some((s) => typeof s.faabOut === "number");
  return {
    trade: { sides },
    missing,
    faabOmitted: faab,
    complete: missing.length === 0 && !faab,
  };
}

/**
 * ``/trade?share=…`` for one trade, or null when nothing in it can be named
 * on the calculator.  ``encode`` is ``lib/trade-share``'s ``encodeTrade``
 * (injected, so this module stays a dependency-free helper set; the
 * activity view passes it).
 */
export function tradeCalculatorUrl(trade, encode) {
  const share = tradeCalculatorShare(trade);
  if (typeof encode !== "function") return null;
  if (!share.trade.sides.some((s) => s.players.length)) return null;
  try {
    return `/trade?share=${encode(share.trade)}`;
  } catch {
    return null;
  }
}

// ── draft capital, pick movement, tendencies (Batch B3) ─────────────────
//
// The activity payload's ``draftCapital`` / ``tendencies`` blocks are
// backend-computed (``src/intel/manager_trade_intel.py``): which picks are
// held, their values, totals and every count.  These helpers only filter and
// label.  Unknown pick ownership is read through ``lib/pick-ownership`` (the
// one frontend reader of that stamp) and is never shown as "no picks".

/** Draft-capital league entries, optionally one league. */
export function draftCapitalLeagues(draftCapital, league = "") {
  return (draftCapital?.leagues || []).filter(
    (e) => !league || e.leagueId === league,
  );
}

/** Why a league's picks are unknown (a sentence), or "" when they are known. */
export function pickOwnershipText(entry) {
  const reason = pickOwnershipUnavailableReason(entry);
  if (!reason) return "";
  if (reason === "rosters_unavailable")
    return "This league's rosters could not be read, so its picks are unknown.";
  if (entry?.coverage === "rate_limited")
    return "Sleeper rate-limited the traded-picks read, so who owns which pick is unknown.";
  if (entry?.coverage === "none")
    return "The traded-picks feed was not read in this lookup (budget reached), so picks are unknown.";
  return describePickOwnershipReason(reason);
}

/** "Own" for the manager's own pick, else whose pick it originally was. */
export function pickOriginText(pick) {
  if (!pick) return "";
  if (pick.own) return "Own";
  return `From ${pick.originOwnerName || `roster ${pick.originRosterId}`}`;
}

/** "2027–2029 · 2026 draft complete" — which classes the list covers. */
export function draftYearsText(draftYears) {
  const held = draftYears?.heldSeasons || [];
  if (!held.length) return "No upcoming classes";
  const span =
    held.length === 1 ? `${held[0]}` : `${held[0]}–${held[held.length - 1]}`;
  const done = [
    ...(draftYears.retiredSeasons || []),
    ...(draftYears.draftCompleteSeasons || []),
  ];
  const unique = [...new Set(done)].sort();
  return unique.length ? `${span} · ${unique.join(", ")} draft complete` : span;
}

/** "3 held · 1 acquired · 2 own traded away", or "" when unknown. */
export function capitalCountsText(entry) {
  const c = entry?.counts;
  if (!c) return "";
  return `${c.held} held · ${c.acquired} acquired · ${c.ownTradedAway} own traded away`;
}

/** The priced-only total with what it leaves out ("7,000 · 4 unpriced"). */
export function capitalValueText(entry) {
  if (!entry || entry.picks == null) return "—";
  const total = formatValue(entry.pricedValue);
  return entry.unpricedPickCount
    ? `${total} · ${entry.unpricedPickCount} unpriced`
    : total;
}

/** Pick-movement rows (windowed trade stream), optionally one league. */
export function pickMovementRows(draftCapital, league = "") {
  return (draftCapital?.movements?.rows || []).filter(
    (r) => !league || r.leagueId === league,
  );
}

export function stillHeldText(row) {
  if (row?.stillHeld === true) return "Still held";
  if (row?.stillHeld === false) return "No longer held";
  if (row?.stillHeldReason === "class_not_in_owned_horizon")
    return "Class drafted or outside horizon";
  return "Unknown";
}

/** "n = 5 trades · last 30 days" or the insufficient-sample sentence. */
export function tendencySampleText(block, tendencies) {
  if (!block) return "";
  const unit = block.unit === "players" ? "players" : "trades";
  const win = windowText(tendencies);
  if (!block.sufficientSample)
    return `Insufficient sample — n = ${block.n} ${unit} (at least ${block.minSample} needed) · ${win}`;
  return `n = ${block.n} ${unit} · ${win}`;
}

function windowText(tendencies) {
  const w = tendencies?.window;
  if (w === "season") return `${tendencies?.season || "this"} season`;
  return typeof w === "string" ? `last ${w.replace("d", " days")}` : "";
}

/** "2 · 7,500" (count · priced value); the value reads "—" when none priced. */
export function tendencyFlowText(flow) {
  if (!flow || !flow.count) return "0";
  const unpriced = flow.unpricedCount
    ? ` (${flow.unpricedCount} unpriced)`
    : "";
  return `${flow.count} · ${formatValue(flow.pricedValue)}${unpriced}`;
}

const SHAPE_LABELS = {
  picks_for_players: "Picks for players",
  players_for_picks: "Players for picks",
  players_for_players: "Players for players",
  picks_for_picks: "Picks for picks",
  mixed: "Players and picks",
  other: "Other",
  consolidation: "Consolidation (fewer pieces in)",
  depth: "Depth (more pieces in)",
  even: "Even piece count",
};

export function shapeLabel(key) {
  return SHAPE_LABELS[key] || key;
}

/** ``[{key, label, count}]`` for a counts block, zero rows dropped. */
export function shapeRows(counts) {
  return Object.entries(counts || {})
    .filter(([, n]) => n > 0)
    .map(([key, count]) => ({ key, label: shapeLabel(key), count }));
}
