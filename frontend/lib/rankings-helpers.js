// ── Rankings page helpers ────────────────────────────────────────────────────
// Tier labels, value-band classification, and fast-scan chip logic.
// Pure functions — no React dependencies, fully testable.
//
// Tests: frontend/__tests__/rankings-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

// ── Tier labels ──────────────────────────────────────────────────────────────
// The backend assigns canonicalTierId (integer, 1-based) via gap-detection
// in src/canonical/player_valuation.py.  These labels are a presentation
// layer only — they map numeric tier IDs to human-readable names.
//
// When canonicalTierId is null (canonical pipeline not active), we fall back
// to rank-based tiers derived from the unified rank position.

/** Fixed tier label map for the first 10 backend-detected tiers. */
const TIER_LABELS = {
  1: "Elite",
  2: "Blue-Chip",
  3: "Premium Starter",
  4: "Solid Starter",
  5: "Starter",
  6: "Flex / Depth",
  7: "Bench Depth",
  8: "Deep Stash",
  9: "Roster Fringe",
  10: "Waiver Wire",
};

/**
 * Return a human-readable tier label for a row.
 * Prefers backend canonicalTierId; falls back to rank-based derivation.
 */
export function tierLabel(row) {
  const tierId = row?.canonicalTierId;
  if (tierId != null && tierId > 0) {
    return TIER_LABELS[tierId] || `Tier ${tierId}`;
  }
  // Fallback: derive from rank position
  return rankBasedTierLabel(row?.rank);
}

/**
 * Derive a tier label purely from overall rank position.
 * Used when canonicalTierId is absent (canonical pipeline not active).
 *
 * Boundaries are intentionally generous — these are presentation labels,
 * not fantasy advice.  The cutoffs approximate natural dynasty value
 * clustering:
 *   1-12:   Elite (top-12 startup picks)
 *   13-36:  Blue-Chip (rounds 2-3)
 *   37-72:  Premium Starter (rounds 4-6)
 *   73-120: Solid Starter (rounds 7-10)
 *   121-200: Starter
 *   201-350: Flex / Depth
 *   351-500: Bench Depth
 *   501-650: Deep Stash
 *   651-800: Roster Fringe
 *   800+:   Waiver Wire
 */
export function rankBasedTierLabel(rank) {
  if (rank == null || rank <= 0) return "Unranked";
  if (rank <= 12) return "Elite";
  if (rank <= 36) return "Blue-Chip";
  if (rank <= 72) return "Premium Starter";
  if (rank <= 120) return "Solid Starter";
  if (rank <= 200) return "Starter";
  if (rank <= 350) return "Flex / Depth";
  if (rank <= 500) return "Bench Depth";
  if (rank <= 650) return "Deep Stash";
  if (rank <= 800) return "Roster Fringe";
  return "Waiver Wire";
}

/**
 * Return a numeric tier ID (1-10) for rank-based fallback grouping.
 * Mirrors the rank boundaries above.
 */
export function rankBasedTierId(rank) {
  if (rank == null || rank <= 0) return null;
  if (rank <= 12) return 1;
  if (rank <= 36) return 2;
  if (rank <= 72) return 3;
  if (rank <= 120) return 4;
  if (rank <= 200) return 5;
  if (rank <= 350) return 6;
  if (rank <= 500) return 7;
  if (rank <= 650) return 8;
  if (rank <= 800) return 9;
  return 10;
}

/**
 * Get the effective tier ID for a row (backend or rank-based fallback).
 */
export function effectiveTierId(row) {
  if (row?.canonicalTierId != null && row.canonicalTierId > 0) {
    return row.canonicalTierId;
  }
  return rankBasedTierId(row?.rank);
}

// ── Value-band labels ────────────────────────────────────────────────────────
// Interpret the 1-9999 scale for users who don't know what "4200" means.
// Bands are derived from the rank-to-value curve properties:
//   rank 1  → 9999, rank 12 → ~5700, rank 45 → ~5000, rank 200 → ~1200
//
// These are descriptive only — they help users frame relative value.

const VALUE_BANDS = [
  { min: 8000, label: "Elite",     css: "vb-elite" },
  { min: 6000, label: "Blue-Chip", css: "vb-bluechip" },
  { min: 4000, label: "Starter",   css: "vb-starter" },
  { min: 2000, label: "Depth",     css: "vb-depth" },
  { min: 1,    label: "Fringe",    css: "vb-fringe" },
];

/**
 * Return a value-band object { label, css } for a given value (1-9999).
 */
export function valueBand(value) {
  const v = Number(value) || 0;
  for (const band of VALUE_BANDS) {
    if (v >= band.min) return band;
  }
  return { label: "—", css: "" };
}

// ── Fast-scan chips ──────────────────────────────────────────────────────────
// Return an array of chip descriptors for a row.  Each chip is
// { label, css, title } where css maps to a badge class.
// Chips are sparse — most rows get zero or one.

/**
 * Compute fast-scan chips for a player row.
 * Returns array of { label, css, title } objects.
 */
export function rowChips(row) {
  const chips = [];
  if (row?.rookie) {
    chips.push({ label: "R", css: "badge-cyan", title: "Rookie" });
  }
  if (row?.isSingleSource) {
    chips.push({ label: "1-src", css: "badge-amber", title: "Single source — lower confidence" });
  }
  const flags = row?.anomalyFlags || [];
  if (flags.length > 0) {
    chips.push({ label: "!", css: "badge-red", title: `Flagged: ${flags.join(", ")}` });
  }
  if (row?.hasSourceDisagreement) {
    chips.push({ label: "~", css: "badge-amber", title: "Sources disagree significantly" });
  }
  return chips;
}

// ── Default row limit ────────────────────────────────────────────────────────
// Show a curated default rather than dumping 800 rows.  Users can expand.
// 200 covers all starters + meaningful depth in a 12-team dynasty league.
export const DEFAULT_ROW_LIMIT = 200;
