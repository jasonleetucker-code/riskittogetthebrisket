// ── Rankings page helpers ────────────────────────────────────────────────────
// Tier labels, value-band classification, and fast-scan chip logic.
// Pure functions — no React dependencies, fully testable.
//
// Tests: frontend/__tests__/rankings-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

// ── Tier labels ──────────────────────────────────────────────────────────────
// The backend assigns canonicalTierId (integer, 1-based) via gap-detection
// in src/canonical/player_valuation.py.  Tier 1 is the best; tier IDs
// increase at each natural value cliff.  Labels are purely numeric —
// "Tier 1", "Tier 2", … — so what the user sees matches the math.

/**
 * Return a human-readable tier label for a row.
 * Prefers backend canonicalTierId; falls back to rank-based derivation
 * when the canonical pipeline has not stamped the row.
 */
export function tierLabel(row) {
  const tierId = row?.canonicalTierId;
  if (tierId != null && tierId > 0) {
    return `Tier ${tierId}`;
  }
  return rankBasedTierLabel(row?.rank);
}

/**
 * Rank-based tier label fallback used only when canonicalTierId is
 * absent (canonical pipeline not active).  Produces the same "Tier N"
 * shape as the backend-stamped path.
 */
export function rankBasedTierLabel(rank) {
  const tierId = rankBasedTierId(rank);
  return tierId == null ? "Unranked" : `Tier ${tierId}`;
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
// These are *descriptive* — they help users frame relative value.
//
// Short symbols ("S+" / "S" / "D+" / "D" / "F") keep the value-band
// badge visually distinct from the numeric "Tier N" row header so the
// two layers never look like they disagree.
const VALUE_BANDS = [
  { min: 8000, label: "S+", css: "vb-elite",    title: "Elite value (8000+)" },
  { min: 6000, label: "S",  css: "vb-bluechip", title: "Blue-chip value (6000-7999)" },
  { min: 4000, label: "D+", css: "vb-starter",  title: "Starter value (4000-5999)" },
  { min: 2000, label: "D",  css: "vb-depth",    title: "Depth value (2000-3999)" },
  { min: 1,    label: "F",  css: "vb-fringe",   title: "Fringe value (1-1999)" },
];

/**
 * Return a value-band object { label, css, title } for a given value (1-9999).
 */
export function valueBand(value) {
  const v = Number(value) || 0;
  for (const band of VALUE_BANDS) {
    if (v >= band.min) return band;
  }
  return { label: "—", css: "", title: "" };
}

// ── Fast-scan chips ──────────────────────────────────────────────────────────
// Return an array of chip descriptors for a row.  Each chip is
// { label, css, title } where css maps to a badge class.
// Chips are sparse — most rows get zero or one.

/**
 * Compute fast-scan chips for a player row.
 *
 * Chip semantics (deterministic, explicit):
 *
 * * ``R``  — rookie flag set on the row.
 * * ``1-src``  — *semantic* single source: the player matched a
 *   single source even though the structural eligibility set
 *   contains more than one source for this position.  This
 *   indicates a real matching failure on at least one source.  The
 *   audit reason behind it is in ``row.sourceAudit.reason`` — a UI
 *   tooltip can surface ``"matching_failure_other_sources_eligible"``
 *   directly.
 * * ``solo`` — structurally single source: only one source could
 *   ever cover this player (e.g. a rookie in a config where the
 *   second IDP source is a veteran-only board).  This is **not** a
 *   matching failure and is rendered as a neutral info chip rather
 *   than the amber warning.
 * * ``!``  — at least one anomaly flag from
 *   :data:`src.api.data_contract._compute_anomaly_flags`.
 * * ``~``  — depth-aware percentile spread > 0.10; sources placed
 *   the player in different relative tiers.
 *
 * Returns array of ``{ label, css, title }`` objects.  Empty array
 * for clean rows.
 */
export function rowChips(row, options = {}) {
  const chips = [];
  if (row?.rookie) {
    chips.push({ label: "R", css: "badge-green", title: "Rookie" });
  }
  if (row?.isSingleSource) {
    const reason = row?.sourceAudit?.reason || "single source";
    chips.push({
      label: "1-src",
      css: "badge-amber",
      title: `Single source — matching failure (${reason})`,
    });
  } else if (row?.isStructurallySingleSource) {
    chips.push({
      label: "solo",
      css: "badge-blue",
      title: "Only one source structurally covers this player (no matching failure)",
    });
  }
  const flags = row?.anomalyFlags || [];
  if (flags.length > 0) {
    chips.push({ label: "!", css: "badge-red", title: `Flagged: ${flags.join(", ")}` });
  }
  if (row?.hasSourceDisagreement) {
    chips.push({ label: "~", css: "badge-amber", title: "Sources disagree significantly (percentile spread > 10%)" });
  }
  // News / injury chip — wired in by the rankings page from
  // ``useNews().byPlayer``.  ``options.newsItem`` is a NewsItem object
  // for this player or undefined.  We render a chip whose label +
  // tone reflect severity so a user scanning the board can see at a
  // glance which of their players has fresh news.
  const news = options?.newsItem;
  if (news) {
    const severity = String(news.severity || "info").toLowerCase();
    const label = severity === "injury"
      ? "INJ"
      : severity === "alert" || severity === "high"
        ? "!N"
        : "N";
    const css = severity === "injury"
      ? "badge-red"
      : severity === "alert" || severity === "high"
        ? "badge-amber"
        : "badge-blue";
    const headline = String(news.headline || news.summary || "Recent news").slice(0, 140);
    const url = typeof news.url === "string" && news.url.startsWith("http")
      ? news.url
      : null;
    chips.push({
      label,
      css,
      title: `${headline} (${news.providerLabel || news.provider || "news"})`,
      url,
    });
  }
  return chips;
}

// ── Default row limit ────────────────────────────────────────────────────────
// Re-exported from thresholds for backward compatibility.
export { RANKINGS_DEFAULT_ROW_LIMIT as DEFAULT_ROW_LIMIT } from "./thresholds.js";
