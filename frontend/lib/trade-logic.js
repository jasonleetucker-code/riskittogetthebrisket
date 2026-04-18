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
export const SETTINGS_KEY = "next_settings_v2";

// ── Verdict Thresholds (1–9999 scale) ────────────────────────────────────
const VERDICT_NEAR_EVEN = 350;
const VERDICT_LEAN = 900;
const VERDICT_STRONG_LEAN = 1800;

// ── Legacy Power-Weighted Alpha (trade history only) ─────────────────────
// The Trade Calculator no longer uses this; it has moved to the KTC-style
// Value Adjustment model below.  `TRADE_ALPHA` is kept as a retrospective
// grading exponent for past trades on the `/trades` history page, where a
// consolidation premium can't be attributed after the fact.
export const TRADE_ALPHA = 1.65;

// ── KTC-Style Value Adjustment (V2 formula) ──────────────────────────────
// Mirrors KeepTradeCut's "Value Adjustment" row: the side with fewer pieces
// gets a consolidation / roster-spot bonus.
//
// Formula (hybrid — top-gap scarcity with per-extra ratio boost):
//
//   top_gap         = max(0, (small_top − large_top) / small_top)
//   top_scarcity    = clamp(SLOPE · top_gap − INTERCEPT, 0, CAP)
//   for each extraᵢ:
//       extra_gapᵢ  = max(0, (small_top − extraᵢ) / small_top)
//       effᵢ        = clamp(top_scarcity + BOOST · max(0, extra_gapᵢ − top_gap),
//                           0, EFFECTIVE_CAP)
//       VA         += extraᵢ · effᵢ · DECAYⁱ
//
// The per-extra boost is the key V2 innovation.  It says: if a specific
// extra is a low-value throw-in (large extra_gap relative to top_gap),
// give it proportionally more consolidation premium.  A throw-in pick
// 3.x "costs a roster slot" far cheaper than its face value, so a
// larger fraction becomes VA.  Conversely, an extra piece near
// ``large_top`` is "real" value, so its weight stays close to
// top_scarcity — matching the old V1 behavior for that case.
//
// Calibration against 13 observed KTC data points (Superflex, TEP=1):
//
//   case  layout   small           large                KTC    V2    err%
//   A     1v2      9999            7846+5717            3712   3748   +1.0
//   B     1v2      7846            5717+4829            3034   3421  +12.8
//   C     1v2      7846            6949+5717            1166   1257   +7.8
//   D     1v3      4342            2667+2324+1172       1820   1945   +6.9
//   E     1v3      7798            4519+4208+2906       3834   3403  -11.2
//   F     1v3      9999            7471+4862+2215       4879   4973   +1.9
//   G     1v2      7795            6883+2950            2077   2084   +0.3
//   H     1v3      7795            5086+4021+2950       3587   3945  +10.0
//   I     1v2      9999            7813+5086            4103   3823   -6.8
//   J     1v3      9999            7813+3811+2756       4848   4509   -7.0
//   K     1v2      7509            6737+2179            1887   1852   -1.9
//   L     3v5      9999+9983+5086  9603+7687+7298+      4586   4085  -10.9
//                                  4206+2670
//   M     2v3      7795+1914       5086+4021+3943       3371   2978  -11.7
//
//   mean |err| = 6.9%,  max |err| = 12.8%,  rms = 8.1%
//   (V1 was mean 28.3%, max 100%, rms 42.8% on the same 13 points.)
//
// The calibration script at ``scripts/calibrate_va_formula.py`` grids
// several candidate formula families against all 13 observed points.
// V2 is the winner under a blended (mean + max/4) objective.  If you
// tune these coefficients, re-run the script to check that the full
// 13-point regression doesn't regress.
export const VA_SCARCITY_SLOPE = 3.75;
export const VA_SCARCITY_INTERCEPT = 0.45;
export const VA_SCARCITY_CAP = 0.55;
export const VA_PER_EXTRA_BOOST = 1.4;
export const VA_EFFECTIVE_CAP = 1.0;
export const VA_POSITION_DECAY = 0.35;

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
 * Get the effective value for a row, adjusted by pick year discount.
 *
 * NOTE: TE premium is NOT applied here.  ``settings.tepMultiplier``
 * is threaded through the backend rankings override pipeline (see
 * ``frontend/lib/dynasty-data.js::fetchDynastyData`` and
 * ``src/api/data_contract.py::_compute_unified_rankings``), which
 * bakes the boost into every TE row's ``rankDerivedValue`` stamp
 * before the contract reaches the trade calculator.  Multiplying
 * again on render would double-boost every TE whenever the TEP
 * slider is > 1.0, and would completely miss the TEP-native source
 * carve-out (dynastyNerdsSfTep).  The backend is now the single
 * source of truth for TEP — do NOT reintroduce the multiplication
 * here.
 *
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

  // Pick year discount for future picks
  if (pos === "PICK" && settings.pickCurrentYear) {
    val *= pickYearDiscount(row.name, settings.pickCurrentYear);
  }

  return val;
}

/** Simple linear total (sum of values). */
export function sideTotal(side, valueMode, settings = null) {
  return side.reduce((sum, r) => sum + effectiveValue(r, valueMode, settings), 0);
}

/** Descending-sorted effective values for a side. */
function sortedSideValues(side, valueMode, settings) {
  return side
    .map((r) => Math.max(0, effectiveValue(r, valueMode, settings)))
    .sort((a, b) => b - a);
}

/**
 * Compute the KTC-style Value Adjustment between two sides.
 *
 * The side with fewer pieces receives a bonus representing the
 * consolidation / roster-spot premium.  Uses the V2 hybrid formula:
 * a top-gap scarcity that sets the baseline, plus a per-extra boost
 * that scales up each extra's effective weight when it is smaller
 * than the matched top-large piece (throw-in premium).
 *
 * Returns { adjustment, recipientIdx } where:
 *   - adjustment: ≥ 0 bonus to apply to the receiving side's total
 *   - recipientIdx: 0 for sideA, 1 for sideB, or null when counts tie
 *
 * @param {object[]} sideA
 * @param {object[]} sideB
 * @param {string} valueMode
 * @param {object} [settings]
 */
export function computeValueAdjustment(sideA, sideB, valueMode, settings = null) {
  const aValues = sortedSideValues(sideA, valueMode, settings);
  const bValues = sortedSideValues(sideB, valueMode, settings);

  if (aValues.length === bValues.length) {
    return { adjustment: 0, recipientIdx: null };
  }

  const recipientIdx = aValues.length < bValues.length ? 0 : 1;
  const small = recipientIdx === 0 ? aValues : bValues;
  const large = recipientIdx === 0 ? bValues : aValues;

  if (small.length === 0 || small[0] <= 0) {
    return { adjustment: 0, recipientIdx: null };
  }

  const topSmall = small[0];
  const topLarge = large[0] || 0;
  const topGap = Math.max(0, (topSmall - topLarge) / topSmall);

  // If the small side's top is no better than the large side's top,
  // there's no consolidation upgrade to reward — return zero VA
  // regardless of any throw-ins on the large side.  This preserves
  // the V1 invariant; every KTC data point we've calibrated against
  // has topSmall > topLarge (including case L at a 0.04 gap).
  if (topGap === 0) {
    return { adjustment: 0, recipientIdx };
  }

  const rawScarcity = VA_SCARCITY_SLOPE * topGap - VA_SCARCITY_INTERCEPT;
  const topScarcity = Math.max(0, Math.min(VA_SCARCITY_CAP, rawScarcity));

  const extras = large.slice(small.length);

  // Per-extra effective weight with a "throw-in" boost.
  //
  // For each extra, compute its own gap ratio relative to the small
  // side's top.  The further this extra's gap is below topGap, the
  // smaller (more "filler") the extra is — and the higher its
  // effective weight should climb (KTC rewards trading filler for
  // consolidation).  When extra_gap ≈ topGap (the extra is as valuable
  // as ``topLarge``), the boost goes to zero and we reduce back to the
  // plain V1 behavior for that piece.
  //
  // If topScarcity is zero AND no extras beat the gap floor (only
  // happens for near-even tops AND matched extras), VA stays zero.
  let adjustment = 0;
  for (let p = 0; p < extras.length; p++) {
    const extra = extras[p];
    const extraGap = topSmall > 0
      ? Math.max(0, (topSmall - extra) / topSmall)
      : 0;
    const boostTerm = VA_PER_EXTRA_BOOST * Math.max(0, extraGap - topGap);
    const effective = Math.max(
      0,
      Math.min(VA_EFFECTIVE_CAP, topScarcity + boostTerm),
    );
    adjustment += extra * effective * Math.pow(VA_POSITION_DECAY, p);
  }

  return { adjustment, recipientIdx };
}

/**
 * Adjusted per-side totals for 2-team trade display.
 * Each entry is { raw, adjustment, adjusted } where `adjusted = raw + adjustment`
 * and only the recipient side has a non-zero adjustment.
 */
export function adjustedSideTotals(sideA, sideB, valueMode, settings = null) {
  const rawA = sideTotal(sideA, valueMode, settings);
  const rawB = sideTotal(sideB, valueMode, settings);
  const { adjustment, recipientIdx } = computeValueAdjustment(sideA, sideB, valueMode, settings);
  const adjA = recipientIdx === 0 ? adjustment : 0;
  const adjB = recipientIdx === 1 ? adjustment : 0;
  return [
    { raw: rawA, adjustment: adjA, adjusted: rawA + adjA },
    { raw: rawB, adjustment: adjB, adjusted: rawB + adjB },
  ];
}

/** Gap = Side A adjusted total − Side B adjusted total (KTC-style). */
export function tradeGapAdjusted(sideA, sideB, valueMode, settings = null) {
  const totals = adjustedSideTotals(sideA, sideB, valueMode, settings);
  return totals[0].adjusted - totals[1].adjusted;
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
const ROUND_LABELS = { "1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "5": "5th", "6": "6th" };

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
  const labelMatch = s.match(/^(\d{4})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th)/i);
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
// re-deriving the mapping at every call site.  Mirrors the backend
// draft_rounds range in Dynasty Scraper.py (1..6).
const ROUND_NUM = { "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6 };

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
 *   1. `pickAliases` lookup against the **input** label (raw or stripped
 *      of its "(from X)" / "(own)" annotation).  The alias table only
 *      contains entries for generic tier labels whose slot-specific
 *      siblings exist on the board (e.g. "2026 Mid 1st" →
 *      "2026 Pick 1.06").  Applying aliases to the input — not to the
 *      synthesized derived candidates — prevents a slot input like
 *      "2026 1.04" from being rewritten to the tier-centre slot via
 *      its derived "2026 Early 1st" candidate.
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

  const raw = String(rawLabel).trim();
  const stripped = raw.replace(/\s*\([^)]*\)\s*$/, "").trim();

  // 1) Backend alias map — only applied to the input label (raw or
  //    stripped), never to synthesized derived candidates.  This is
  //    the critical distinction: the alias table redirects generic
  //    tier labels to slot-specific canonical rows, so applying it to
  //    derived tier candidates (e.g. the "2026 Early 1st" that
  //    buildPickLookupCandidates synthesizes for a "2026 1.04" input)
  //    would systematically misroute slot picks to the tier-centre
  //    slot.  Only trust the alias map for labels the caller actually
  //    provided.
  if (pickAliases && typeof pickAliases === "object") {
    const inputForms = new Set();
    inputForms.add(raw.toLowerCase());
    if (stripped) inputForms.add(stripped.toLowerCase());
    for (const [k, v] of Object.entries(pickAliases)) {
      if (typeof k !== "string" || typeof v !== "string") continue;
      if (!inputForms.has(k.toLowerCase())) continue;
      const row = rowLookup.get(v.toLowerCase());
      if (row && !isSuppressedGenericPickRow(row)) return row;
      // Alias target matched but row is absent or suppressed — fall
      // through to direct lookup; don't keep iterating the alias map.
      break;
    }
  }

  // 2) Direct candidate lookup.  Skip suppressed generic-tier rows so a
  //    later candidate (typically the slot-specific "Pick N.NN" form)
  //    gets a chance to resolve even without a pickAliases map.
  const candidates = buildPickLookupCandidates(raw);
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

// ── Multi-Team Verdict Helpers ───────────────────────────────────────────

/** Side labels: A through E */
export const SIDE_LABELS = ["A", "B", "C", "D", "E"];
export const MAX_SIDES = 5;
export const MIN_SIDES = 2;

/**
 * Create a fresh empty side.
 * @param {number} index - 0-based index
 * @returns {{ id: number, label: string, assets: [] }}
 */
export function createSide(index) {
  return { id: index, label: SIDE_LABELS[index] || String.fromCharCode(65 + index), assets: [] };
}

/**
 * Compute the granular trade-meter verdict label from an absolute gap.
 * More categories than verdictFromGap for the inline meter badge.
 * @param {number} absGap - Absolute point gap
 * @returns {{ label: string, level: 'fair'|'slight'|'unfair'|'lopsided' }}
 */
export function meterVerdict(absGap) {
  if (absGap < 350) return { label: "FAIR", level: "fair" };
  if (absGap < 900) return { label: "SLIGHT EDGE", level: "slight" };
  if (absGap < 1800) return { label: "UNFAIR", level: "unfair" };
  return { label: "LOPSIDED", level: "lopsided" };
}

/**
 * Percentage gap for proportional display.
 * Returns 0 when both sides are empty.
 * @param {number} valA - Side A total
 * @param {number} valB - Side B total
 * @returns {number} Integer percentage 0-100
 */
export function percentageGap(valA, valB) {
  const maxVal = Math.max(valA, valB);
  if (maxVal <= 0) return 0;
  return Math.round(Math.abs(valA - valB) / maxVal * 100);
}

/**
 * For multi-team (3+), compute each side's share percentage and
 * per-team verdict (over/under contributing).
 * @param {number[]} totals - Array of side totals
 * @returns {{ shares: number[], overall: string, perTeam: string[] }}
 */
export function multiTeamAnalysis(totals) {
  const grandTotal = totals.reduce((a, b) => a + b, 0);
  if (grandTotal <= 0) {
    return {
      shares: totals.map(() => 0),
      overall: "Empty",
      perTeam: totals.map(() => "No assets"),
    };
  }
  const count = totals.length;
  const equalShare = 100 / count;
  const shares = totals.map((t) => Math.round((t / grandTotal) * 100));
  const perTeam = shares.map((s, i) => {
    const diff = s - equalShare;
    if (Math.abs(diff) < 5) return "Fair share";
    if (diff > 0) return "Overpaying";
    return "Getting a deal";
  });
  const maxDiff = Math.max(...shares.map((s) => Math.abs(s - equalShare)));
  const overall = maxDiff < 10 ? "Balanced" : "Imbalanced";
  return { shares, overall, perTeam };
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

/**
 * Serialize multi-team workspace (sides array format).
 */
export function serializeWorkspaceMulti(sides, valueMode, activeSide) {
  return {
    version: 2,
    valueMode,
    activeSide,
    sides: sides.map((s) => ({ label: s.label, assets: s.assets.map((r) => r.name) })),
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

/**
 * Deserialize multi-team workspace, with migration from old 2-side format.
 * @param {object} parsed - Raw localStorage object
 * @param {Map} rowByName - name -> row lookup
 * @returns {{ valueMode: string, activeSide: number, sides: object[] } | null}
 */
export function deserializeWorkspaceMulti(parsed, rowByName) {
  if (!parsed || typeof parsed !== "object") return null;
  const valueMode = VALUE_MODES.some((m) => m.key === parsed.valueMode) ? parsed.valueMode : "full";

  // Version 2 (new multi-team format)
  if (parsed.version === 2 && Array.isArray(parsed.sides)) {
    const activeSide = typeof parsed.activeSide === "number" ? parsed.activeSide : 0;
    const sides = parsed.sides.map((s, i) => ({
      id: i,
      label: s.label || SIDE_LABELS[i] || String.fromCharCode(65 + i),
      assets: Array.isArray(s.assets) ? s.assets.map((n) => rowByName.get(n)).filter(Boolean) : [],
    }));
    // Ensure at least 2 sides
    while (sides.length < MIN_SIDES) sides.push(createSide(sides.length));
    return { valueMode, activeSide: Math.min(activeSide, sides.length - 1), sides };
  }

  // Legacy format (sideA/sideB arrays) — migrate
  const activeSide = parsed.activeSide === "B" ? 1 : 0;
  const sideA = Array.isArray(parsed.sideA) ? parsed.sideA.map((n) => rowByName.get(n)).filter(Boolean) : [];
  const sideB = Array.isArray(parsed.sideB) ? parsed.sideB.map((n) => rowByName.get(n)).filter(Boolean) : [];
  return {
    valueMode,
    activeSide,
    sides: [
      { id: 0, label: "A", assets: sideA },
      { id: 1, label: "B", assets: sideB },
    ],
  };
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
