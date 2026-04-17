/**
 * League analysis utilities — shared by trades, rosters, league hub.
 * Pure functions, no React dependencies.
 */

import { effectiveValue, TRADE_ALPHA, parsePickToken, getPlayerEdge, resolvePickRow } from "@/lib/trade-logic";
import { normalizePos } from "@/lib/dynasty-data";

// ── Position Group Helpers ──────────────────────────────────────────────
export const POS_GROUPS = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "PICKS"];
export const OFFENSE_GROUPS = ["QB", "RB", "WR", "TE"];

export const POS_GROUP_COLORS = {
  QB: "#e74c3c",
  RB: "#27ae60",
  WR: "#3498db",
  TE: "#e67e22",
  DL: "#9b59b6",
  LB: "#8e44ad",
  DB: "#16a085",
  PICKS: "#f39c12",
};

export const POS_GROUP_LABELS = {
  QB: "Quarterbacks",
  RB: "Running Backs",
  WR: "Wide Receivers",
  TE: "Tight Ends",
  DL: "Defensive Line",
  LB: "Linebackers",
  DB: "Defensive Backs",
  PICKS: "Draft Picks",
};

const STARTER_SLOTS = { QB: 2, RB: 3, WR: 4, TE: 2, DL: 2, LB: 2, DB: 2 };

export function posGroup(pos) {
  if (!pos) return "Other";
  const p = normalizePos(pos);
  if (["QB", "RB", "WR", "TE"].includes(p)) return p;
  if (["DL", "DE", "DT", "EDGE", "NT"].includes(p)) return "DL";
  if (["LB", "OLB", "ILB"].includes(p)) return "LB";
  if (["DB", "CB", "S", "FS", "SS"].includes(p)) return "DB";
  return "Other";
}

// ── Timestamp Helpers ───────────────────────────────────────────────────
export function normalizeTradeTimestampMs(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n < 1_000_000_000_000 ? n * 1000 : n;
}

export function filterTradesToRollingWindow(trades, windowDays = 365) {
  if (!Array.isArray(trades) || !trades.length) return [];
  const cutoffMs = Date.now() - windowDays * 24 * 60 * 60 * 1000;
  return trades.filter((t) => {
    const ts = normalizeTradeTimestampMs(t?.timestamp);
    return Number.isFinite(ts) && ts >= cutoffMs;
  });
}

// ── Trade Grading ───────────────────────────────────────────────────────
export function gradeTradeHistorySide(pct, isWinner) {
  if (pct < 3) return { grade: "A", color: "var(--green)", label: "Fair trade" };
  if (isWinner) {
    if (pct < 8) return { grade: "A", color: "var(--green)", label: "Slight win" };
    if (pct < 15) return { grade: "A-", color: "var(--green)", label: "Good win" };
    if (pct < 25) return { grade: "B+", color: "#2ecc71", label: "Clear win" };
    return { grade: "A+", color: "#00ff88", label: "Big win" };
  }
  if (pct < 8) return { grade: "B+", color: "#2ecc71", label: "Slight overpay" };
  if (pct < 15) return { grade: "B", color: "var(--amber)", label: "Overpay" };
  if (pct < 25) return { grade: "C", color: "#e67e22", label: "Bad deal" };
  if (pct < 40) return { grade: "D", color: "var(--red)", label: "Robbery" };
  return { grade: "F", color: "#ff4444", label: "Fleeced" };
}

// ── Row Lookup Map ──────────────────────────────────────────────────────
export function buildRowLookup(rows) {
  const map = new Map();
  for (const r of rows) {
    map.set(r.name.toLowerCase(), r);
  }
  return map;
}

// ── Resolve Trade Item → Row Value ──────────────────────────────────────
/**
 * Resolve a trade item name to a value using the rows from useDynastyData.
 *
 * Picks need a multi-candidate lookup because Sleeper labels them as
 * "2026 1.04 (from Team X)" or "2027 Mid 1st (own)" while rankings
 * stores canonical rows as "2026 Pick 1.04" or "2027 Mid 1st".  The
 * `resolvePickRow` helper walks parsed candidates + backend alias map
 * so pick values surface correctly in trade history.
 */
export function resolveTradeItemValue(itemName, rowLookup, posMap, pickAliases) {
  if (!itemName) return { name: itemName, value: 0, pos: "", isPick: false };
  const name = String(itemName).trim();
  const isPick = !!parsePickToken(name);

  if (isPick) {
    const row = resolvePickRow(name, rowLookup, pickAliases);
    if (row) {
      return {
        name,
        value: row.values?.full || 0,
        pos: "PICK",
        isPick: true,
      };
    }
    // No match — fall through to empty pick result below.
    return { name, value: 0, pos: "PICK", isPick: true };
  }

  const key = name.toLowerCase();
  const row = rowLookup.get(key);
  if (row) {
    return {
      name,
      value: row.values?.full || 0,
      pos: row.pos || "",
      isPick: false,
    };
  }

  // Try without parenthetical (e.g. "Jameson Williams (some annotation)")
  const stripped = name.replace(/\s*\([^)]*\)\s*$/, "").trim();
  if (stripped !== name) {
    const strippedRow = rowLookup.get(stripped.toLowerCase());
    if (strippedRow) {
      return {
        name,
        value: strippedRow.values?.full || 0,
        pos: strippedRow.pos || "",
        isPick: false,
      };
    }
  }

  // Fallback — check position map
  const pos = posMap?.[name] || "";
  return { name, value: 0, pos, isPick: false };
}

// ── Normalize Trade Asset Label ─────────────────────────────────────────
function normalizeTradeAssetLabel(raw) {
  if (!raw || typeof raw !== "string") return "";
  return raw.trim();
}

function getTradeSideItemLabels(items) {
  if (!Array.isArray(items)) return [];
  return items.map(normalizeTradeAssetLabel).filter(Boolean);
}

// ── Owner / Roster → current team name map ─────────────────────────────
/**
 * Build lookup maps from Sleeper identifiers to the CURRENT team name.
 *
 * Returns `{ byOwner, byRoster }`.  Both are lowercase-keyed Maps.
 * Callers should prefer owner_id (authoritative per-human) and fall
 * back to roster_id only when ownerId is missing on the source.
 *
 * Why owner-first:
 *   - Historical trades store the team name as it was at trade time.
 *     Grouping by that name splits a single manager's record when
 *     they rename their team (e.g. "Draft Daddies" → "Russini
 *     Panini").  Aggregating by owner_id unifies those cleanly.
 *   - Grouping by roster_id alone is WRONG for dynasty leagues that
 *     have had orphaned rosters change hands across seasons — the
 *     roster_id stays stable but the human behind it changed, so
 *     historical trades from the previous manager would be
 *     attributed to the new one.  Owner_id is stable per human
 *     across the league chain and splits manager changes correctly.
 */
export function buildSleeperIdentityMaps(sleeperTeams) {
  const byOwner = new Map();
  const byRoster = new Map();
  for (const t of sleeperTeams || []) {
    const name = String(t?.name || "");
    const oid = t?.ownerId;
    if (oid) byOwner.set(String(oid).toLowerCase(), name);
    const rid = t?.roster_id;
    if (rid != null) byRoster.set(String(rid), name);
  }
  return { byOwner, byRoster };
}

// Legacy export retained for any caller that still imports the old
// rosterId-only map.  Internal call sites should use
// ``buildSleeperIdentityMaps`` directly.
export function buildRosterIdNameMap(sleeperTeams) {
  return buildSleeperIdentityMaps(sleeperTeams).byRoster;
}

/**
 * Pick a stable aggregation key for a trade side.
 *
 * Preference order: `ownerId` (per-human, splits orphan takeovers) →
 * `rosterId` (per-roster, legacy fallback when the scraper did not
 * emit ownerId) → team name (last-resort fallback when neither id is
 * present on older scraper output).
 */
function sideAggregationKey(side) {
  if (side == null) return "";
  if (side.ownerId) return `oid:${String(side.ownerId).toLowerCase()}`;
  if (side.rosterId != null) return `rid:${side.rosterId}`;
  return `name:${side.team || ""}`;
}

/**
 * Resolve the display name for a trade side.
 *
 * Resolution order:
 *   1. If the side carries an ownerId and that owner still holds a
 *      team in the current league, use the CURRENT team name.  This
 *      unifies renamed teams under their current name.
 *   2. If the side carries an ownerId that is NOT in the current
 *      league (orphan takeover: this owner left and the roster was
 *      handed off to someone else), fall back to the HISTORICAL team
 *      name from the side — never to `byRoster`, because rosterId
 *      now resolves to the new manager and would mis-attribute the
 *      trade.
 *   3. If the side has no ownerId at all (legacy scraper data), use
 *      the rosterId map when present and finally the historical
 *      team name.
 */
function sideDisplayName(side, identityMaps) {
  if (side == null) return "";
  if (side.ownerId) {
    const current = identityMaps?.byOwner?.get(String(side.ownerId).toLowerCase());
    if (current) return current;
    // ownerId present but not in current league → orphan takeover.
    // Keep the historical team name rather than leaking the new
    // manager's name via rosterId.
    return side.team || "";
  }
  if (side.rosterId != null && identityMaps?.byRoster) {
    const current = identityMaps.byRoster.get(String(side.rosterId));
    if (current) return current;
  }
  return side.team || "";
}

// ── Analyze Sleeper Trade History ───────────────────────────────────────
/**
 * Analyze all Sleeper trades within the rolling window.
 * Returns { windowDays, analyzed, teamScores }.
 *
 * Aggregation is keyed by `ownerId` (Sleeper user id) so trades from
 * managers who renamed their team roll up under the current team
 * name, while trades from an orphaned roster that changed hands stay
 * split across the two owners.  Falls back to rosterId and then team
 * name for older scraper output that did not emit ownerId.
 */
export function analyzeSleeperTradeHistory(rawData, rows, windowDays = 365, alpha = TRADE_ALPHA) {
  const trades = rawData?.sleeper?.trades;
  if (!Array.isArray(trades) || !trades.length) {
    return { windowDays, analyzed: [], teamScores: {} };
  }

  const filtered = filterTradesToRollingWindow(trades, windowDays);
  if (!filtered.length) return { windowDays, analyzed: [], teamScores: {} };

  const rowLookup = buildRowLookup(rows);
  const posMap = rawData?.sleeper?.positions || {};
  const pickAliases = rawData?.pickAliases || null;
  const identityMaps = buildSleeperIdentityMaps(rawData?.sleeper?.teams);
  const teamScores = {};
  const analyzed = [];

  for (const trade of filtered) {
    const ts = normalizeTradeTimestampMs(trade.timestamp);
    const date = ts ? new Date(ts).toLocaleDateString() : "?";
    const sides = [];

    for (const side of trade.sides || []) {
      let linearTotal = 0;
      let weightedTotal = 0;
      const items = [];

      for (const rawItem of getTradeSideItemLabels(side?.got)) {
        const resolved = resolveTradeItemValue(rawItem, rowLookup, posMap, pickAliases);
        const safeVal = Number.isFinite(resolved.value) ? Math.max(0, resolved.value) : 0;
        linearTotal += safeVal;
        weightedTotal += Math.pow(Math.max(safeVal, 1), alpha);
        items.push({
          name: resolved.name,
          val: Math.round(safeVal),
          pos: resolved.pos,
          isPick: resolved.isPick,
        });
      }

      const displayTeam = sideDisplayName(side, identityMaps);
      sides.push({
        team: displayTeam,
        historicalTeam: side.team || "",
        ownerId: side.ownerId || null,
        rosterId: side.rosterId ?? null,
        linear: linearTotal,
        weighted: weightedTotal,
        items,
      });
    }

    // Determine winner using stud-adjusted values
    sides.sort((a, b) => b.weighted - a.weighted);
    const winner = sides[0];
    const loser = sides.length > 1 ? sides[sides.length - 1] : null;
    const pctGap =
      loser && winner.weighted > 0
        ? ((winner.weighted - loser.weighted) / winner.weighted) * 100
        : 0;

    const winnerGrade = gradeTradeHistorySide(pctGap, true);
    const loserGrade = loser ? gradeTradeHistorySide(pctGap, false) : null;

    // Track team scores, keyed by ownerId (falls back to rosterId /
    // name) so renamed teams roll up per human while orphan
    // takeovers stay split.
    for (const s of sides) {
      const key = sideAggregationKey(s);
      if (!teamScores[key]) {
        teamScores[key] = {
          displayName: s.team,
          ownerId: s.ownerId,
          rosterId: s.rosterId,
          won: 0,
          lost: 0,
          totalGain: 0,
          trades: 0,
        };
      }
      teamScores[key].trades++;
      if (s === winner && pctGap >= 3) {
        teamScores[key].won++;
        teamScores[key].totalGain += winner.weighted - (loser ? loser.weighted : 0);
      } else if (s === loser && pctGap >= 3) {
        teamScores[key].lost++;
        teamScores[key].totalGain -= winner.weighted - loser.weighted;
      }
    }

    analyzed.push({ trade, date, sides, winner, loser, pctGap, winnerGrade, loserGrade });
  }

  return { windowDays, analyzed, teamScores };
}

// ── Build Player Meta Map ───────────────────────────────────────────────
/**
 * Build a lookup map: lowercase player name → { name, pos, group, meta, isPick }.
 * Uses row values from useDynastyData.
 */
export function buildPlayerMetaMap(rows) {
  const map = {};
  for (const r of rows) {
    if (r.pos === "PICK" || r.pos === "K") continue;
    const group = posGroup(r.pos);
    map[r.name.toLowerCase()] = {
      name: r.name,
      pos: r.pos,
      group,
      meta: r.values?.full || 0,
      isPick: false,
    };
  }
  return map;
}

// ── Team Value Breakdown ────────────────────────────────────────────────
function sumTopN(values, n) {
  if (!Array.isArray(values) || n <= 0) return 0;
  return values
    .filter((v) => Number.isFinite(v) && v > 0)
    .sort((a, b) => b - a)
    .slice(0, n)
    .reduce((s, v) => s + v, 0);
}

/**
 * Compute per-position-group value breakdown for a team.
 * @param {object} team - { players: string[], picks: string[] }
 * @param {object} playerMeta - from buildPlayerMetaMap
 * @param {object[]} rows - all rows for pick value lookup
 * @param {string} valueMode - "full" | "players" | "starters"
 * @param {object} [pickAliases] - optional backend alias map
 * @returns {{ total, byGroup, playerDetails, pickDetails }}
 */
export function buildTeamValueBreakdown(team, playerMeta, rows, valueMode = "full", pickAliases = null) {
  const byGroup = {};
  POS_GROUPS.forEach((g) => { byGroup[g] = 0; });
  const playerDetails = [];
  const buckets = { QB: [], RB: [], WR: [], TE: [], DL: [], LB: [], DB: [] };
  let pickValue = 0;
  const pickDetails = [];

  const teamPlayers = Array.isArray(team.players) ? team.players : [];
  const teamPicks = Array.isArray(team.picks) ? team.picks : [];

  // Build row lookup for pick resolution
  const rowLookup = buildRowLookup(rows);

  for (const pName of teamPlayers) {
    if (parsePickToken(pName)) continue;
    const key = pName.toLowerCase();
    const pm = playerMeta[key];
    if (!pm) continue;
    playerDetails.push(pm);
    if (valueMode !== "starters") {
      if (byGroup[pm.group] !== undefined) byGroup[pm.group] += pm.meta;
    }
    if (buckets[pm.group]) buckets[pm.group].push(pm.meta);
  }

  // Resolve pick values using multi-candidate lookup so Sleeper labels
  // like "2026 1.04 (from Team X)" resolve against rankings rows stored
  // as "2026 Pick 1.04".
  if (valueMode === "full") {
    const pickSources = teamPicks.length > 0 ? teamPicks : teamPlayers.filter((p) => parsePickToken(p));
    for (const pickName of pickSources) {
      if (!parsePickToken(pickName)) continue;
      const row = resolvePickRow(pickName, rowLookup, pickAliases);
      const val = row ? (row.values?.full || 0) : 0;
      pickValue += val;
      if (val > 0) {
        pickDetails.push({ name: pickName, meta: val, pos: "PICK", group: "PICKS", isPick: true });
      }
    }
  }

  if (valueMode === "starters") {
    Object.keys(buckets).forEach((g) => {
      byGroup[g] = sumTopN(buckets[g], STARTER_SLOTS[g] || 0);
    });
  }

  byGroup.PICKS = valueMode === "full" ? pickValue : 0;
  const total = POS_GROUPS.reduce((s, g) => s + (byGroup[g] || 0), 0);

  return { total, byGroup, playerDetails, pickDetails };
}

// ── Build All Team Summaries ────────────────────────────────────────────
/**
 * Build summary data for all teams in the league.
 * Returns sorted array of team objects with value breakdowns.
 */
export function buildAllTeamSummaries(sleeperTeams, playerMeta, rows, valueMode = "full", pickAliases = null) {
  const teams = (sleeperTeams || []).map((team) => {
    const breakdown = buildTeamValueBreakdown(team, playerMeta, rows, valueMode, pickAliases);
    return {
      name: team.name,
      roster_id: team.roster_id,
      total: breakdown.total,
      byGroup: breakdown.byGroup,
      playerCount: (team.players || []).length,
      pickCount: Array.isArray(team.picks) ? team.picks.length : 0,
      players: breakdown.playerDetails,
      pickDetails: breakdown.pickDetails,
    };
  });

  teams.sort((a, b) => b.total - a.total);
  return teams;
}

// ── Group Averages ──────────────────────────────────────────────────────
export function computeGroupAverages(teams) {
  const avg = {};
  POS_GROUPS.forEach((g) => {
    const vals = teams.map((t) => t.byGroup[g] || 0);
    avg[g] = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  });
  return avg;
}

// ── Position Ranks per Group ────────────────────────────────────────────
export function computePositionRanks(teams) {
  const ranks = {};
  POS_GROUPS.forEach((g) => {
    const sorted = teams.slice().sort((a, b) => (b.byGroup[g] || 0) - (a.byGroup[g] || 0));
    sorted.forEach((t, i) => {
      if (!ranks[t.name]) ranks[t.name] = {};
      ranks[t.name][g] = i + 1;
    });
  });
  return ranks;
}

// ── Heatmap Color ───────────────────────────────────────────────────────
export function heatmapColor(rank, total) {
  const p = (rank - 1) / Math.max(total - 1, 1);
  if (p <= 0.25) return `rgb(${(10 + (p / 0.25) * 20) | 0},${(80 + (p / 0.25) * 60) | 0},${(100 + (p / 0.25) * 40) | 0})`;
  if (p <= 0.5) { const t = (p - 0.25) / 0.25; return `rgb(${(30 + t * 30) | 0},${(140 - t * 40) | 0},${(140 - t * 20) | 0})`; }
  if (p <= 0.75) { const t = (p - 0.5) / 0.25; return `rgb(${(60 + t * 100) | 0},${(100 - t * 40) | 0},${(120 - t * 30) | 0})`; }
  const t = (p - 0.75) / 0.25;
  return `rgb(${(160 + t * 60) | 0},${(60 - t * 20) | 0},${(90 - t * 20) | 0})`;
}

export function heatmapTextColor(bgColor) {
  const m = String(bgColor || "").match(/rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)/i);
  if (!m) return "#111";
  const r = Number(m[1]) || 0;
  const g = Number(m[2]) || 0;
  const b = Number(m[3]) || 0;
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  return lum < 0.54 ? "#f0f0f0" : "#111";
}

// ── Ordinal suffix ──────────────────────────────────────────────────────
export function ordinal(n) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

// ── Waiver Wire Gems ────────────────────────────────────────────────────
/**
 * Find unrostered players with high trade value.
 * @param {object[]} rows - all player rows
 * @param {object[]} sleeperTeams - teams with .players arrays
 * @returns {object[]} Sorted array of { name, pos, value }
 */
export function findWaiverWireGems(rows, sleeperTeams) {
  const rosteredSet = new Set();
  for (const team of sleeperTeams || []) {
    for (const p of team.players || []) {
      rosteredSet.add(p.toLowerCase());
    }
  }

  const gems = [];
  for (const row of rows) {
    if (row.pos === "PICK" || row.pos === "K" || row.pos === "?") continue;
    if (rosteredSet.has(row.name.toLowerCase())) continue;
    if ((row.values?.full || 0) < 500) continue;
    gems.push({ name: row.name, pos: row.pos, value: row.values?.full || 0 });
  }

  gems.sort((a, b) => b.value - a.value);
  return gems.slice(0, 25);
}

// ── League Edge Map ─────────────────────────────────────────────────────
const MIN_EDGE_PCT = 3;

/**
 * Build league-wide edge analysis — per-team market overvalue/undervalue signals.
 * Uses getPlayerEdge from trade-logic.js for individual player edge signals.
 */
export function buildLeagueEdgeMap(rows, sleeperTeams, myTeamName = "") {
  const rowLookup = buildRowLookup(rows);
  const teamEdges = [];

  for (const team of sleeperTeams || []) {
    let totalSellEdge = 0;
    let totalBuyEdge = 0;
    let sellCount = 0;
    let buyCount = 0;
    const topSells = [];
    const topBuys = [];

    for (const pName of team.players || []) {
      if (parsePickToken(pName)) continue;
      const row = rowLookup.get(pName.toLowerCase());
      if (!row) continue;
      const edge = getPlayerEdge(row);
      if (!edge || !edge.signal) continue;

      if (edge.signal === "SELL") {
        totalSellEdge += edge.edgePct;
        sellCount++;
        topSells.push({ name: pName, pct: edge.edgePct });
      } else if (edge.signal === "BUY") {
        totalBuyEdge += edge.edgePct;
        buyCount++;
        topBuys.push({ name: pName, pct: edge.edgePct });
      }
    }

    topSells.sort((a, b) => b.pct - a.pct);
    topBuys.sort((a, b) => b.pct - a.pct);

    teamEdges.push({
      name: team.name,
      isMe: team.name === myTeamName,
      sellEdge: Math.round(totalSellEdge),
      buyEdge: Math.round(totalBuyEdge),
      sellCount,
      buyCount,
      topSells: topSells.slice(0, 3),
      topBuys: topBuys.slice(0, 3),
    });
  }

  // Sort by most exploitable (highest sell edge)
  teamEdges.sort((a, b) => b.sellEdge - a.sellEdge);
  return teamEdges;
}

// ── Trade Tendencies ────────────────────────────────────────────────────
/**
 * Analyze per-manager trading patterns: avg given/got, net, position bias.
 * @param {object} rawData - the rawData from useDynastyData
 * @param {object[]} rows - all player rows
 * @returns {object[]} Sorted array of { manager, trades, avgGiven, avgGot, net, tendency }
 */
export function analyzeTradeTendencies(rawData, rows) {
  const trades = rawData?.sleeper?.trades;
  if (!Array.isArray(trades) || !trades.length) return [];

  const rowLookup = buildRowLookup(rows);
  const posMap = rawData?.sleeper?.positions || {};
  const pickAliases = rawData?.pickAliases || null;
  const identityMaps = buildSleeperIdentityMaps(rawData?.sleeper?.teams);
  const managerStats = {};

  // Shared resolver that handles both players and pick labels, so trade
  // tendency totals include pick value rather than silently dropping
  // picks that fail a direct rowLookup hit.
  const resolveAssetValue = (name) => {
    if (!name) return 0;
    if (parsePickToken(name)) {
      const row = resolvePickRow(name, rowLookup, pickAliases);
      return row ? (row.values?.full || 0) : 0;
    }
    const row = rowLookup.get(String(name).toLowerCase());
    return row ? (row.values?.full || 0) : 0;
  };

  for (const trade of trades) {
    if (!trade.sides || trade.sides.length < 2) continue;
    for (const side of trade.sides) {
      // Key by ownerId (falls back to rosterId / team name) so
      // renamed teams roll up into a single row per human while
      // orphan takeovers stay split across owners.
      const key = sideAggregationKey(side);
      const displayName = sideDisplayName(side, identityMaps) || "Unknown";
      if (!managerStats[key]) {
        managerStats[key] = {
          manager: displayName,
          trades: 0,
          totalGiven: 0,
          totalGot: 0,
          posBias: {},
        };
      }
      const stats = managerStats[key];
      stats.trades++;

      let gotTotal = 0;
      let gaveTotal = 0;
      for (const name of side.got || []) {
        gotTotal += resolveAssetValue(name);
      }
      for (const name of side.gave || []) {
        gaveTotal += resolveAssetValue(name);
      }
      stats.totalGot += gotTotal;
      stats.totalGiven += gaveTotal;

      // Track position bias in acquisitions
      for (const name of side.got || []) {
        let pos = (posMap[name] || "").toUpperCase();
        if (!pos) continue;
        if (["LB", "DL", "DE", "DT", "CB", "S", "DB", "EDGE"].includes(pos)) pos = "IDP";
        stats.posBias[pos] = (stats.posBias[pos] || 0) + 1;
      }
    }
  }

  return Object.entries(managerStats)
    .map(([key, s]) => {
      const avgGiven = Math.round(s.totalGiven / Math.max(s.trades, 1));
      const avgGot = Math.round(s.totalGot / Math.max(s.trades, 1));
      const net = avgGot - avgGiven;
      const topPos = Object.entries(s.posBias).sort((a, b) => b[1] - a[1])[0];
      const tendency = topPos ? `Targets ${topPos[0]}s` : "\u2014";
      // `id` is the ownerId-first aggregation key so the React table
      // can key rows uniquely even when two managers happen to share
      // a display name.
      return { id: key, manager: s.manager, trades: s.trades, avgGiven, avgGot, net, tendency };
    })
    .sort((a, b) => b.trades - a.trades);
}

// ── Contender / Rebuilder Tiers ─────────────────────────────────────────
/**
 * Score and tier all teams: contender / mid-tier / rebuilder.
 * Starter value = top 10 offensive players, weighted 70%.
 * Depth = total minus starters, weighted 20%.
 * Pick surplus penalized at -10% (rebuild signal).
 */
export function scoreTeamTiers(sleeperTeams, playerMeta, rows, pickAliases = null) {
  const rowLookup = buildRowLookup(rows);

  const scored = (sleeperTeams || []).map((team) => {
    let totalValue = 0;
    const topPlayers = [];
    let pickValue = 0;

    for (const pName of team.players || []) {
      if (parsePickToken(pName)) continue;
      const pm = playerMeta[(pName || "").toLowerCase()];
      if (!pm) continue;
      totalValue += pm.meta;
      if (OFFENSE_GROUPS.includes(pm.group)) {
        topPlayers.push(pm.meta);
      }
    }

    // Picks — use multi-candidate lookup so Sleeper labels resolve
    // against canonical rankings rows.
    for (const pickName of team.picks || []) {
      const row = resolvePickRow(pickName, rowLookup, pickAliases);
      const val = row ? (row.values?.full || 0) : 0;
      totalValue += val;
      pickValue += val;
    }

    topPlayers.sort((a, b) => b - a);
    const starterValue = topPlayers.slice(0, 10).reduce((s, v) => s + v, 0);
    const depthValue = totalValue - starterValue;
    const score = starterValue * 0.7 + depthValue * 0.2 + (pickValue > 0 ? -pickValue * 0.1 : 0);

    return {
      name: team.name,
      score,
      totalValue,
      starterValue,
      depthValue,
      pickValue,
    };
  });

  scored.sort((a, b) => b.score - a.score);
  const n = scored.length;
  const top = Math.ceil(n / 3);
  const bot = n - top;

  return scored.map((t, i) => ({
    ...t,
    tier: i < top ? "contender" : i >= bot ? "rebuilder" : "middle",
    tierLabel: i < top ? "Contender" : i >= bot ? "Rebuilder" : "Mid-Tier",
    rank: i + 1,
  }));
}
