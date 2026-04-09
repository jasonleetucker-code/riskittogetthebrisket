/**
 * Trade calculator logic — the authoritative implementation for Next.js.
 * Covers: stud-exponent package weighting, value modes, LAM, scarcity,
 * edge detection, pick valuation, verdict calculation, persistence.
 *
 * ── Stud-Exponent Trade Model ──
 * For each side of a trade:
 *   1. Rank assets by effective value within that side (highest = rank 1)
 *   2. Compute weighted value per asset:
 *        weighted = (value ^ alpha) / (1 + beta * (packageRank - 1))
 *   3. Sum all weighted values for the side total
 * Compare side totals; convert gap back to display scale:
 *        adjustment = |sideA_total - sideB_total| ^ (1 / alpha)
 *
 * alpha: stud exponent — top-end players are disproportionately valuable
 * beta:  package-rank discount — 2nd/3rd/4th pieces in a package are worth less
 *
 * No React dependencies — pure functions + constants.
 */

// ── Value Modes ──────────────────────────────────────────────────────────
export const VALUE_MODES = [
  { key: "full", label: "Our Value" },
  { key: "raw", label: "Raw" },
  { key: "scoring", label: "Scoring Adj." },
  { key: "scarcity", label: "Scarcity Adj." },
];

// ── Persistence Keys ─────────────────────────────────────────────────────
export const STORAGE_KEY = "next_trade_workspace_v1";
export const RECENT_KEY = "next_trade_recent_assets_v1";
export const SETTINGS_KEY = "next_settings_v1";

// ── Verdict Thresholds (1–9999 scale) ────────────────────────────────────
const VERDICT_NEAR_EVEN = 256;
const VERDICT_LEAN = 769;
const VERDICT_STRONG_LEAN = 1538;

// ── Stud-Exponent Parameters ────────────────────────────────────────────
// Default alpha: concentrates value at the top — a star + role player is
// worth more than two mid-tier pieces.
export const TRADE_ALPHA = 1.678;

// Default beta: package-rank discount — 2nd asset in a package is worth
// less than if it were traded alone.
export const TRADE_BETA = 0.15;

// ── Pick Year Discount ──────────────────────────────────────────────────
// Future-year picks are worth less than current-year picks.
// Matches static: year+1 → 0.85, year+2 → 0.72, year+3+ → 0.60
const PICK_YEAR_DISCOUNTS = [1.0, 0.85, 0.72, 0.60];

/**
 * Pick year discount multiplier.
 * @param {string} pickName - Pick name (e.g. "2027 Early 1st")
 * @param {number} currentYear - Current draft year from settings
 * @returns {number} Multiplier (1.0 for current year, <1 for future)
 */
export function pickYearDiscount(pickName, currentYear) {
  const m = String(pickName || "").match(/^(20\d{2})/);
  if (!m) return 1.0;
  const pickYear = parseInt(m[1], 10);
  const delta = Math.max(0, pickYear - currentYear);
  return PICK_YEAR_DISCOUNTS[Math.min(delta, PICK_YEAR_DISCOUNTS.length - 1)];
}

/**
 * Get the effective value for a row, adjusted by LAM, TEP, and pick year discount.
 * @param {object} row - Player row
 * @param {string} valueMode - Value mode key
 * @param {object} [settings] - User settings (from useSettings)
 * @returns {number}
 */
export function effectiveValue(row, valueMode, settings) {
  const raw = Number(row.values?.[valueMode] || 0);
  if (!settings || raw <= 0) return raw;
  const pos = row.pos || "WR";
  let val = raw;

  // LAM adjustment
  const lam = lamMultiplier(pos, settings.lamStrength ?? 1.0, settings.leagueFormat ?? "superflex");
  val *= lam;

  // TEP adjustment for TEs (applies tepMultiplier when > 1)
  if (pos === "TE" && (settings.tepMultiplier ?? 1.0) > 1.0) {
    val *= settings.tepMultiplier;
  }

  // Pick year discount for future picks
  if (pos === "PICK" && settings.pickCurrentYear) {
    val *= pickYearDiscount(row.name, settings.pickCurrentYear);
  }

  return val;
}

// ── Stud-Exponent Package Helpers ────────────────────────────────────────
// These are the canonical trade math functions.  The frontend trade page
// calls these directly — there is no separate backend trade calculator.

/**
 * Assign package ranks within one side of a trade.
 * Returns an array of { row, value, packageRank } sorted by value descending.
 * Highest value = package rank 1.
 */
export function assignPackageRanks(side, valueMode, settings = null) {
  const items = side.map((r) => ({
    row: r,
    value: effectiveValue(r, valueMode, settings),
  }));
  items.sort((a, b) => b.value - a.value);
  return items.map((item, i) => ({
    ...item,
    packageRank: i + 1,
  }));
}

/**
 * Stud-exponent weighted value for a single asset.
 *   weighted = (value ^ alpha) / (1 + beta * (packageRank - 1))
 *
 * @param {number} value - Asset's effective value
 * @param {number} packageRank - Rank within its trade side (1 = best)
 * @param {number} alpha - Stud exponent (> 1 rewards top-end)
 * @param {number} beta - Package-rank discount (0 = no discount)
 */
export function studWeightedValue(value, packageRank, alpha = TRADE_ALPHA, beta = TRADE_BETA) {
  if (value <= 0) return 0;
  return Math.pow(value, alpha) / (1 + beta * (packageRank - 1));
}

/**
 * Weighted side total using the stud-exponent package model.
 * Ranks assets within the side, applies exponent + rank discount, sums.
 *
 * @param {object[]} side - Array of player rows
 * @param {string} valueMode - Value mode key
 * @param {number} alpha - Stud exponent
 * @param {number} beta - Package-rank discount factor
 * @param {object} [settings] - User settings for LAM/TEP/pick adjustments
 */
export function weightedSideTotal(side, valueMode, alpha = TRADE_ALPHA, beta = TRADE_BETA, settings = null) {
  if (!side.length) return 0;
  const ranked = assignPackageRanks(side, valueMode, settings);
  return ranked.reduce((sum, item) => {
    return sum + studWeightedValue(item.value, item.packageRank, alpha, beta);
  }, 0);
}

/**
 * Convert a weighted gap back to the display-value scale via inverse exponent.
 *   adjustment = |weightedGap| ^ (1 / alpha)
 * Sign is preserved to indicate which side wins.
 */
export function inverseGapAdjustment(weightedGap, alpha = TRADE_ALPHA) {
  if (weightedGap === 0) return 0;
  const sign = weightedGap > 0 ? 1 : -1;
  return sign * Math.pow(Math.abs(weightedGap), 1 / alpha);
}

/**
 * Backward-compatible power-weighted total.
 * Now delegates to the stud-exponent model (weightedSideTotal + inverse gap).
 * The returned value is on the display-value scale (1-9999).
 */
export function powerWeightedTotal(side, valueMode, alpha, settings = null) {
  const a = alpha ?? settings?.alpha ?? TRADE_ALPHA;
  const b = settings?.beta ?? TRADE_BETA;
  if (!side.length) return 0;
  const weighted = weightedSideTotal(side, valueMode, a, b, settings);
  // Convert back to display scale so verdict thresholds still work
  return Math.pow(Math.max(weighted, 0), 1 / a);
}

/** Simple linear total (sum of values), optionally LAM-adjusted. */
export function sideTotal(side, valueMode, settings = null) {
  return side.reduce((sum, r) => sum + effectiveValue(r, valueMode, settings), 0);
}

/** Gap = Side A stud-weighted total − Side B stud-weighted total (display scale). */
export function tradeGap(sideA, sideB, valueMode, settings = null) {
  const a = settings?.alpha ?? TRADE_ALPHA;
  const b = settings?.beta ?? TRADE_BETA;
  const wA = weightedSideTotal(sideA, valueMode, a, b, settings);
  const wB = weightedSideTotal(sideB, valueMode, a, b, settings);
  return inverseGapAdjustment(wA - wB, a);
}

/** Linear gap (for display alongside stud-weighted). */
export function linearGap(sideA, sideB, valueMode, settings = null) {
  return sideTotal(sideA, valueMode, settings) - sideTotal(sideB, valueMode, settings);
}

// ── Verdict ──────────────────────────────────────────────────────────────
export function verdictFromGap(gap) {
  const abs = Math.abs(gap);
  if (abs < VERDICT_NEAR_EVEN) return "Near even";
  if (abs < VERDICT_LEAN) return "Lean";
  if (abs < VERDICT_STRONG_LEAN) return "Strong lean";
  return "Major gap";
}

export function colorFromGap(gap) {
  if (Math.abs(gap) < VERDICT_NEAR_EVEN) return "";
  return gap > 0 ? "green" : "red";
}

/**
 * Verdict bar position (0 = Side B wins, 50 = even, 100 = Side A wins).
 * Clamped so the marker never fully touches either edge.
 */
export function verdictBarPosition(gap, maxGap = 4000) {
  const clamped = Math.max(-maxGap, Math.min(maxGap, gap));
  return 50 + (clamped / maxGap) * 50;
}

// ── LAM (League Adjustment Multiplier) ───────────────────────────────────
// Buckets map: position → multiplier at a given LAM strength.
// The multiplier skews values based on league scoring format.
// In superflex leagues, QBs are worth more; in standard, RBs dominate.
const LAM_BUCKETS = {
  QB:  { superflex: 1.15, standard: 0.85 },
  RB:  { superflex: 0.95, standard: 1.10 },
  WR:  { superflex: 1.00, standard: 1.00 },
  TE:  { superflex: 0.90, standard: 0.92 },
  DL:  { superflex: 0.70, standard: 0.70 },
  LB:  { superflex: 0.75, standard: 0.75 },
  DB:  { superflex: 0.72, standard: 0.72 },
  PICK:{ superflex: 1.00, standard: 1.00 },
};

/**
 * Compute LAM multiplier for a position at a given strength.
 * @param {string} pos - Normalized position (QB, RB, WR, TE, DL, LB, DB, PICK)
 * @param {number} strength - 0 (no adjustment) to 1 (full adjustment)
 * @param {string} format - "superflex" or "standard"
 * @returns {number} Multiplier to apply to raw value
 */
export function lamMultiplier(pos, strength = 0.5, format = "superflex") {
  const bucket = LAM_BUCKETS[pos] || LAM_BUCKETS.WR;
  const mult = bucket[format] ?? bucket.superflex ?? 1.0;
  // Interpolate between 1.0 (no effect) and full multiplier
  return 1 + (mult - 1) * strength;
}

// ── Scarcity Model ───────────────────────────────────────────────────────
// Position scarcity adjusts values based on replacement-level depth.
// Positions with fewer quality starters relative to league demand get a premium.
const SCARCITY_DEFAULTS = {
  // { startersPerTeam, totalTeams, poolMultiplier }
  QB:  { starters: 1, teams: 12, poolMult: 1.0 },
  RB:  { starters: 2, teams: 12, poolMult: 1.2 },
  WR:  { starters: 3, teams: 12, poolMult: 1.0 },
  TE:  { starters: 1, teams: 12, poolMult: 0.8 },
  DL:  { starters: 2, teams: 12, poolMult: 0.6 },
  LB:  { starters: 2, teams: 12, poolMult: 0.65 },
  DB:  { starters: 2, teams: 12, poolMult: 0.6 },
};

/**
 * Build scarcity model from current rows.
 * Returns per-position: replacementRank, replacementValue, pressure.
 */
export function buildScarcityModel(rows) {
  const byPos = {};
  for (const r of rows) {
    if (!r.pos || r.pos === "?" || r.pos === "PICK") continue;
    if (!byPos[r.pos]) byPos[r.pos] = [];
    byPos[r.pos].push(r.values?.full || 0);
  }

  const model = {};
  for (const [pos, cfg] of Object.entries(SCARCITY_DEFAULTS)) {
    const vals = (byPos[pos] || []).sort((a, b) => b - a);
    const poolSize = vals.length;
    const replacementRank = Math.ceil(cfg.starters * cfg.teams);
    const replacementValue = vals[Math.min(replacementRank - 1, vals.length - 1)] || 0;
    const topValue = vals[0] || 0;
    const span = topValue - replacementValue;
    const pressure = poolSize > 0 ? Math.min(1.5, (cfg.starters * cfg.teams) / poolSize) : 1.0;
    model[pos] = { poolSize, replacementRank, replacementValue, topValue, span, pressure };
  }
  return model;
}

/**
 * Scarcity multiplier for a single player.
 * Players well above replacement get less adjustment; those near it get more.
 * @param {number} value - Player's current value
 * @param {string} pos - Position
 * @param {object} scarcityModel - From buildScarcityModel()
 * @param {number} strength - 0 to 1
 * @returns {number} Multiplier
 */
export function scarcityMultiplier(value, pos, scarcityModel, strength = 0.35) {
  const entry = scarcityModel?.[pos];
  if (!entry || entry.span <= 0) return 1.0;
  // Players above replacement: pressure scales up
  // Players at/below replacement: minimal adjustment
  const aboveReplacement = Math.max(0, value - entry.replacementValue) / entry.span;
  const adj = 1 + (entry.pressure - 1) * aboveReplacement * 0.5;
  return 1 + (adj - 1) * strength;
}

// ── Edge Detection ───────────────────────────────────────────────────────
const MIN_EDGE_PCT = 3; // minimum % gap to signal

/**
 * Compute edge signal for a player row.
 * Compares the player's consensus value against external source values.
 * @param {object} row - Player row with canonicalSites and values
 * @returns {{ signal: 'BUY'|'SELL'|null, edgePct: number, sources: string[] }}
 */
export function getPlayerEdge(row) {
  if (!row?.canonicalSites || !row?.values?.full) return { signal: null, edgePct: 0, sources: [] };

  const ourValue = row.values.full;
  if (ourValue <= 0) return { signal: null, edgePct: 0, sources: [] };

  // Compare against external sources
  const externalKeys = ["ktc"];
  const externals = [];
  for (const key of externalKeys) {
    const v = Number(row.canonicalSites[key]);
    if (Number.isFinite(v) && v > 0) externals.push({ key, value: v });
  }

  if (externals.length === 0) return { signal: null, edgePct: 0, sources: [] };

  const avgExternal = externals.reduce((s, e) => s + e.value, 0) / externals.length;
  const pctDiff = ((ourValue - avgExternal) / avgExternal) * 100;

  if (Math.abs(pctDiff) < MIN_EDGE_PCT) return { signal: null, edgePct: 0, sources: externals.map((e) => e.key) };

  return {
    signal: pctDiff < 0 ? "BUY" : "SELL",
    edgePct: Math.round(Math.abs(pctDiff)),
    sources: externals.map((e) => e.key),
  };
}

// ── Pick Token Parsing ───────────────────────────────────────────────────
const ROUND_LABELS = { "1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "5": "5th" };

/**
 * Parse a pick token string into structured parts.
 * Handles: "2026 1.06", "2026 early 1st", "2026 1st", "2026 mid 2nd"
 * @returns {{ year: string, round: string, tier: string|null, slot: number|null }}
 */
export function parsePickToken(token) {
  const s = String(token || "").trim();

  // "2026 1.06" format
  const slotMatch = s.match(/^(\d{4})\s+(\d)\.(\d{2})/);
  if (slotMatch) {
    const round = ROUND_LABELS[slotMatch[2]] || `${slotMatch[2]}th`;
    const slot = parseInt(slotMatch[3], 10);
    const tier = slot <= 4 ? "early" : slot <= 8 ? "mid" : "late";
    return { year: slotMatch[1], round, tier, slot };
  }

  // "2026 early 1st" or "2026 1st" format
  const labelMatch = s.match(/^(\d{4})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th)/i);
  if (labelMatch) {
    return { year: labelMatch[1], round: labelMatch[3].toLowerCase(), tier: (labelMatch[2] || "").toLowerCase() || null, slot: null };
  }

  return null;
}

/**
 * Normalize a pick token to canonical lookup label.
 * "2026 1.06" → "2026 Mid 1st", "2026 early 2nd" → "2026 Early 2nd"
 */
export function normalizePickLabel(token) {
  const parsed = parsePickToken(token);
  if (!parsed) return token;
  const tier = parsed.tier ? parsed.tier.charAt(0).toUpperCase() + parsed.tier.slice(1) : "Mid";
  return `${parsed.year} ${tier} ${parsed.round}`;
}

// ── Trade Side Helpers ───────────────────────────────────────────────────
export function addAssetToSide(side, row) {
  if (!row) return side;
  if (side.some((r) => r.name === row.name)) return side;
  return [...side, row];
}

export function removeAssetFromSide(side, name) {
  return side.filter((r) => r.name !== name);
}

export function isAssetInTrade(sideA, sideB, name) {
  return sideA.some((r) => r.name === name) || sideB.some((r) => r.name === name);
}

// ── Balancing Suggestions ────────────────────────────────────────────────
/**
 * Find players from a roster that could balance a trade gap.
 * @param {number} gap - Current trade gap (positive = Side A ahead)
 * @param {object[]} rosterRows - Available rows from the behind team's roster
 * @param {string} valueMode - Current value mode
 * @param {number} maxResults - Max suggestions to return
 * @returns {object[]} Sorted array of { name, pos, value } that best fill the gap
 */
export function findBalancers(gap, rosterRows, valueMode, maxResults = 5) {
  const target = Math.abs(gap);
  if (target < VERDICT_NEAR_EVEN) return [];

  return rosterRows
    .map((r) => ({ name: r.name, pos: r.pos, value: Number(r.values?.[valueMode] || 0) }))
    .filter((r) => r.value > 0 && r.value <= target * 1.3)
    .sort((a, b) => Math.abs(a.value - target) - Math.abs(b.value - target))
    .slice(0, maxResults);
}

// ── Workspace Serialization ──────────────────────────────────────────────
export function serializeWorkspace(sideA, sideB, valueMode, activeSide) {
  return {
    valueMode,
    activeSide,
    sideA: sideA.map((r) => r.name),
    sideB: sideB.map((r) => r.name),
  };
}

export function deserializeWorkspace(parsed, rowByName) {
  if (!parsed || typeof parsed !== "object") return null;
  const valueMode = VALUE_MODES.some((m) => m.key === parsed.valueMode) ? parsed.valueMode : "full";
  const activeSide = parsed.activeSide === "B" ? "B" : "A";
  const sideA = Array.isArray(parsed.sideA) ? parsed.sideA.map((n) => rowByName.get(n)).filter(Boolean) : [];
  const sideB = Array.isArray(parsed.sideB) ? parsed.sideB.map((n) => rowByName.get(n)).filter(Boolean) : [];
  return { valueMode, activeSide, sideA, sideB };
}

export function addRecent(recentNames, name) {
  return [name, ...recentNames.filter((x) => x !== name)].slice(0, 20);
}

export function filterPickerRows(rows, sideA, sideB, query, filter) {
  const inTrade = new Set([...sideA, ...sideB].map((r) => r.name));
  const q = query.trim().toLowerCase();
  let list = rows.filter((r) => !inTrade.has(r.name));
  if (filter !== "all") list = list.filter((r) => r.assetClass === filter);
  if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));
  return list.slice(0, 80);
}
