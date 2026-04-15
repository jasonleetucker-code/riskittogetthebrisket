/**
 * Trade calculator logic — the authoritative implementation for Next.js.
 * Covers: value modes, power-weighted totals, edge detection,
 * pick valuation, verdict calculation, persistence.
 *
 * No React dependencies — pure functions + constants.
 */

// ── Value Modes ──────────────────────────────────────────────────────────
export const VALUE_MODES = [
  { key: "full", label: "Our Value" },
  { key: "raw", label: "Raw" },
];

// ── Persistence Keys ─────────────────────────────────────────────────────
export const STORAGE_KEY = "next_trade_workspace_v1";
export const RECENT_KEY = "next_trade_recent_assets_v1";
export const SETTINGS_KEY = "next_settings_v1";

// ── Verdict Thresholds (1–9999 scale) ────────────────────────────────────
const VERDICT_NEAR_EVEN = 350;
const VERDICT_LEAN = 900;
const VERDICT_STRONG_LEAN = 1800;

// ── Power-Weighted Calculation ───────────────────────────────────────────
// Alpha exponent concentrates value at the top — a star + role player is
// worth more than two mid-tier pieces.  Matches static calculator exactly.
export const TRADE_ALPHA = 1.45;

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
 * Get the effective value for a row, adjusted by TEP and pick year discount.
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

/**
 * Power-weighted side total.
 * Each asset's value is raised to `alpha`, summed, then root-alpha'd back.
 * This penalizes quantity over quality.
 * @param {object[]} side - Array of player rows
 * @param {string} valueMode - Value mode key
 * @param {number} [alpha] - Power exponent
 * @param {object} [settings] - User settings (from useSettings)
 */
export function powerWeightedTotal(side, valueMode, alpha = TRADE_ALPHA, settings = null) {
  if (!side.length) return 0;
  const sum = side.reduce((acc, r) => {
    const v = effectiveValue(r, valueMode, settings);
    return acc + Math.pow(Math.max(v, 0), alpha);
  }, 0);
  return Math.pow(sum, 1 / alpha);
}

/** Simple linear total (sum of values). */
export function sideTotal(side, valueMode, settings = null) {
  return side.reduce((sum, r) => sum + effectiveValue(r, valueMode, settings), 0);
}

/** Gap = Side A power-weighted total − Side B power-weighted total. */
export function tradeGap(sideA, sideB, valueMode) {
  return powerWeightedTotal(sideA, valueMode) - powerWeightedTotal(sideB, valueMode);
}

/** Linear gap (for display alongside power-weighted). */
export function linearGap(sideA, sideB, valueMode) {
  return sideTotal(sideA, valueMode) - sideTotal(sideB, valueMode);
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

// Tier-centre slot used to translate tier labels to slot-specific rows.
// Matches backend _suppress_generic_pick_tiers_when_slots_exist() in
// src/api/data_contract.py: Early=2, Mid=6, Late=10.
const TIER_CENTRE_SLOT = { early: 2, mid: 6, late: 10 };

// Round numeric digit ("1") for the round label ("1st").  Kept here so
// both slot-based and tier-based candidates can be generated without
// re-deriving the mapping at every call site.
const ROUND_NUM = { "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5 };

/**
 * Given a raw pick label from any source (Sleeper roster, Sleeper trade
 * history, rankings row), return a de-duplicated, lowercased list of
 * candidate canonical row names to probe against `rowLookup`.
 *
 * Sleeper labels arrive as "2026 1.04 (from Team X)" or "2027 Mid 1st
 * (own)" — the rankings pipeline stores the same asset as
 * "2026 Pick 1.04" or "2027 Mid 1st".  Without candidate expansion the
 * slot-based Sleeper label misses the rankings row and the pick is
 * valued at 0 in trade history + roster breakdown (while the rankings
 * page shows the correct value).
 *
 * Returns lowercased strings so callers can match rowLookup (which
 * uses `r.name.toLowerCase()` as the key).
 */
export function buildPickLookupCandidates(rawLabel) {
  if (!rawLabel) return [];
  const raw = String(rawLabel).trim();
  const candidates = [];
  const push = (v) => {
    if (!v) return;
    const key = String(v).trim().toLowerCase();
    if (key && !candidates.includes(key)) candidates.push(key);
  };

  // 1) Raw label exactly as provided.
  push(raw);

  // 2) Strip trailing "(...)" annotation like "(from Team X)" or "(own)".
  const stripped = raw.replace(/\s*\([^)]*\)\s*$/, "").trim();
  if (stripped && stripped !== raw) push(stripped);

  // 3) Parse into {year, round, tier, slot} and enumerate every
  //    canonical form the rankings pipeline might have used.
  const parsed = parsePickToken(stripped || raw);
  if (parsed) {
    const { year, round, tier, slot } = parsed;
    const roundDigit = ROUND_NUM[round];

    if (slot && roundDigit) {
      // "2026 Pick 1.04" (rankings canonical, slot-specific)
      push(`${year} Pick ${roundDigit}.${String(slot).padStart(2, "0")}`);
      // "2026 1.04" (already pushed as stripped, but guaranteed here)
      push(`${year} ${roundDigit}.${String(slot).padStart(2, "0")}`);
    }

    if (tier) {
      const cap = tier.charAt(0).toUpperCase() + tier.slice(1);
      // "2027 Early 1st" (tier canonical — used for future years)
      push(`${year} ${cap} ${round}`);
      // If we only know the tier, generate the tier-centre slot form
      // so years that DO have slot-specific rows still resolve.
      if (roundDigit) {
        const centreSlot = TIER_CENTRE_SLOT[tier] || 6;
        push(`${year} Pick ${roundDigit}.${String(centreSlot).padStart(2, "0")}`);
        push(`${year} ${roundDigit}.${String(centreSlot).padStart(2, "0")}`);
      }
    }

    // 4) If we have a slot but no tier — derive the tier from the slot
    //    (early 1-4, mid 5-8, late 9-12) and push tier-based candidates.
    if (slot && !tier && roundDigit) {
      const derivedTier = slot <= 4 ? "Early" : slot <= 8 ? "Mid" : "Late";
      push(`${year} ${derivedTier} ${round}`);
    }
  }

  return candidates;
}

/**
 * True if a row is a suppressed generic-tier pick — one that the backend
 * kept on the legacy board for name-search purposes but cleared of
 * ranking fields because a slot-specific sibling exists (e.g. "2026 Mid
 * 1st" when "2026 Pick 1.06" is the authoritative row).  These rows
 * can still carry stale values from the legacy pipeline, so callers
 * must treat them as non-authoritative and consult `pickAliases` or
 * slot-specific candidates instead.
 */
function isSuppressedGenericPickRow(row) {
  if (!row) return false;
  return Boolean(row.pickGenericSuppressed || row.raw?.pickGenericSuppressed);
}

/**
 * Resolve a pick label (raw or annotated) to a row using rowLookup and
 * optional backend-authored pickAliases map.  Returns null if no
 * candidate resolves.  Callers should NOT fall back to an untyped 0 —
 * a null return means the pick genuinely has no known value.
 *
 * Resolution order is deliberate:
 *   1. `pickAliases` lookup (authoritative for suppressed generic tiers).
 *      Without this, step 2 could return a suppressed row with stale
 *      values before the alias-to-slot redirect is ever consulted.
 *   2. Direct `rowLookup` walk over candidate names, skipping any
 *      suppressed generic-tier row so the fallback chain continues to a
 *      valid slot-specific sibling.  This keeps the resolver robust
 *      even when `pickAliases` is missing (stale data, older contract).
 *
 * @param {string} rawLabel - raw pick label (any source)
 * @param {Map<string, object>} rowLookup - lowercased name → row
 * @param {object} [pickAliases] - optional backend alias map
 *   ({ "2026 Mid 1st": "2026 Pick 1.06", ... })
 */
export function resolvePickRow(rawLabel, rowLookup, pickAliases) {
  if (!rawLabel || !rowLookup) return null;

  const candidates = buildPickLookupCandidates(rawLabel);

  // 1) Backend alias map first.  Walk every candidate through the alias
  //    table so annotated/stripped/tier forms all redirect to the
  //    slot-specific canonical row when the backend has flagged the
  //    generic tier as suppressed.
  if (pickAliases && typeof pickAliases === "object") {
    const aliasLower = new Map();
    for (const [k, v] of Object.entries(pickAliases)) {
      if (typeof k === "string" && typeof v === "string") {
        aliasLower.set(k.toLowerCase(), v.toLowerCase());
      }
    }
    for (const key of candidates) {
      const target = aliasLower.get(key);
      if (!target) continue;
      const row = rowLookup.get(target);
      if (row && !isSuppressedGenericPickRow(row)) return row;
    }
  }

  // 2) Direct candidate lookup.  Skip suppressed generic-tier rows so a
  //    later candidate (typically the slot-specific "Pick N.NN" form)
  //    gets a chance to resolve even without a pickAliases map.
  for (const key of candidates) {
    const row = rowLookup.get(key);
    if (!row) continue;
    if (isSuppressedGenericPickRow(row)) continue;
    return row;
  }

  return null;
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
