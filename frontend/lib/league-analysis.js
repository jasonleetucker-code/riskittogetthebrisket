/**
 * League analysis utilities — shared by trades, rosters, league hub.
 * Pure functions, no React dependencies.
 */

import { effectiveValue, powerWeightedTotal, TRADE_ALPHA, parsePickToken } from "@/lib/trade-logic";
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
 * This is the Next.js equivalent of Static's getTradeItemValue.
 */
export function resolveTradeItemValue(itemName, rowLookup, posMap) {
  if (!itemName) return { name: itemName, value: 0, pos: "", isPick: false };
  const name = String(itemName).trim();
  const isPick = !!parsePickToken(name);
  const key = name.toLowerCase();
  const row = rowLookup.get(key);

  if (row) {
    return {
      name,
      value: row.values?.full || 0,
      pos: isPick ? "PICK" : (row.pos || ""),
      isPick,
    };
  }

  // Try without parenthetical (e.g. "2026 1st (from Team)")
  const stripped = name.replace(/\s*\([^)]*\)\s*$/, "").trim();
  if (stripped !== name) {
    const strippedRow = rowLookup.get(stripped.toLowerCase());
    if (strippedRow) {
      return {
        name,
        value: strippedRow.values?.full || 0,
        pos: isPick ? "PICK" : (strippedRow.pos || ""),
        isPick,
      };
    }
  }

  // Fallback — check position map
  const pos = isPick ? "PICK" : (posMap?.[name] || "");
  return { name, value: 0, pos, isPick };
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

// ── Analyze Sleeper Trade History ───────────────────────────────────────
/**
 * Analyze all Sleeper trades within the rolling window.
 * Returns { windowDays, analyzed, teamScores }.
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
        const resolved = resolveTradeItemValue(rawItem, rowLookup, posMap);
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

      sides.push({ team: side.team, linear: linearTotal, weighted: weightedTotal, items });
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

    // Track team scores
    for (const s of sides) {
      if (!teamScores[s.team]) teamScores[s.team] = { won: 0, lost: 0, totalGain: 0, trades: 0 };
      teamScores[s.team].trades++;
      if (s === winner && pctGap >= 3) {
        teamScores[s.team].won++;
        teamScores[s.team].totalGain += winner.weighted - (loser ? loser.weighted : 0);
      } else if (s === loser && pctGap >= 3) {
        teamScores[s.team].lost++;
        teamScores[s.team].totalGain -= winner.weighted - loser.weighted;
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
 * @returns {{ total, byGroup, playerDetails, pickDetails }}
 */
export function buildTeamValueBreakdown(team, playerMeta, rows, valueMode = "full") {
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

  // Resolve pick values
  if (valueMode === "full") {
    const pickSources = teamPicks.length > 0 ? teamPicks : teamPlayers.filter((p) => parsePickToken(p));
    for (const pickName of pickSources) {
      if (!parsePickToken(pickName)) continue;
      const row = rowLookup.get(pickName.toLowerCase());
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
export function buildAllTeamSummaries(sleeperTeams, playerMeta, rows, valueMode = "full") {
  const teams = (sleeperTeams || []).map((team) => {
    const breakdown = buildTeamValueBreakdown(team, playerMeta, rows, valueMode);
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
