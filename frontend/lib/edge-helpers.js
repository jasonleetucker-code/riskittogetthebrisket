// ── Edge helpers ─────────────────────────────────────────────────────────────
// Shared logic for actionable lenses, edge summaries, and per-row action labels.
// Pure functions — no React dependencies, fully testable.
// Designed for reuse by /rankings, /edge, and /finder pages.
//
// All signals are derived from existing trust + source fields on the row object:
//   sourceRankSpread, confidenceBucket, isSingleSource, hasSourceDisagreement,
//   anomalyFlags, sourceRanks, marketGapDirection, quarantined, rank, sourceCount
//
// Nothing is predicted or editorialized.  Every label traces to a measurable
// property of the source data.
//
// Tests: frontend/__tests__/edge-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import {
  MARKET_PREMIUM_SPREAD,
  PREMIUM_SUMMARY_VALUE_RATIO,
  LENS_DISAGREEMENT_SPREAD,
  LENS_INEFFICIENCY_SPREAD,
  LENS_INEFFICIENCY_RANK,
  EDGE_CAUTION_RANK_LIMIT,
  EDGE_PREMIUM_RANK_LIMIT,
} from "./thresholds.js";
import {
  formatMarketGap,
  marketGapAtLeast,
  marketGapRatioOf,
} from "./display-helpers.js";
import { isEligibleForAnalysis } from "./display-helpers.js";
import { getRetailLabel } from "./dynasty-data.js";

/**
 * True when a row is "top-ranked" for the Edge page Premium sections
 * (Sell / Buy Signals).  Qualifies strictly by OUR consensus rank —
 * inside the top ``EDGE_PREMIUM_RANK_LIMIT`` (250 today) on the
 * blended board.
 *
 * Previously qualified on ``consensus OR ktc`` rank, which pulled in
 * players KTC priced high but our blend ranked deep (Mac Jones,
 * Jacoby Brissett, etc.).  That defeated the "only trade-relevant"
 * intent — if OUR board doesn't think a player is top-250, a market
 * gap on them isn't actionable.
 */
export function isTopRankedForEdgePremium(row) {
  if (!row) return false;
  const consensusRank = Number(row.rank);
  if (
    Number.isFinite(consensusRank) &&
    consensusRank >= 1 &&
    consensusRank <= EDGE_PREMIUM_RANK_LIMIT
  ) {
    return true;
  }
  return false;
}

// ── Action-frame labels ──────────────────────────────────────────────────────
// Each row gets at most one primary action label + optional caution labels.
// Rules are evaluated top-to-bottom; first match wins for primary.
// Caution labels can stack.

/**
 * Compute the primary action-frame label for a row.
 * Returns { label, css, title } or null.
 *
 * Priority:
 *   1. Market premium — REMOVED, see the note in the body
 *   2. Consensus asset (multi-source, backend high-confidence bucket,
 *      no backend disagreement stamp)
 *   3. null (no primary label — row is ordinary)
 */
export function actionLabel(row) {
  if (!row || row.quarantined) return null;

  // NOTE: The former "Market premium: X" action label was removed.
  // The Market/Edge column already renders this same information as
  // "KTC higher by N" / "Experts higher by N".  Duplicating it here
  // made every premium row carry two near-identical labels.
  //
  // The Signal column is now strictly: consensus asset (positive
  // informational) + any number of caution labels.  If you want the
  // retail-vs-expert gap, look at the Edge column.

  // Consensus asset: tight multi-source agreement.
  //
  // `confidenceBucket` is the BACKEND's answer to exactly this
  // question, and it is the only agreement test applied here. There
  // used to be a second one — `sourceRankSpread <= 30`, a frontend copy
  // of a backend constant that had already been retired once. Measured
  // on the pinned 2026-07-30 contract: of the 111 rows the backend
  // called high-confidence, multi-source and undisputed, the extra
  // check suppressed "Consensus asset" on **54** — nearly half — with
  // ordinal spreads running to 486 on rows the backend was confident
  // about.
  //
  // Since B11 the backend decides confidence with `src/api/confidence.js`'s
  // Python sibling — five axes over provider families, combined by
  // bottleneck, agreement measured in VALUE space — so NO spread of any
  // kind decides it, and there is nothing here to mirror even if someone
  // wanted to. Recomputing a backend verdict on the client is the thing
  // this codebase's "no frontend ranking engine, period" rule exists to
  // prevent; B11 extends it explicitly to confidence.
  //
  // The gate is deliberately less saturated than the rule it replaced:
  // 253 rows are high-confidence on the 2026-08-14 board against 102
  // before, because the retired percentile spread grew mechanically with
  // depth and produced a cliff at rank 100 with no evidentiary basis.
  // The widening here is that fix arriving, not a regression — do not
  // add a filter to hold the old row count.
  //
  // `hasSourceDisagreement` stays: it is a backend stamp too, off the
  // percentile signal, and it is what keeps "Consensus asset" and
  // "Caution: wide disagreement" from rendering together.
  if (
    row.confidenceBucket === "high" &&
    (row.sourceCount || 0) >= 2 &&
    !row.hasSourceDisagreement
  ) {
    return {
      label: "Consensus asset",
      css: "action-consensus",
      title: "Multiple sources agree closely on this player's value",
    };
  }

  return null;
}

/**
 * Compute caution labels for a row.  Can return 0-N labels.
 * Each is { label, css, title }.
 */
export function cautionLabels(row) {
  const labels = [];
  if (!row) return labels;

  if (row.isSingleSource) {
    labels.push({
      label: "Caution: single source",
      css: "caution-single",
      title: "Only one source contributed a value — confidence is lower",
    });
  }
  if ((row.anomalyFlags || []).length > 0 && !row.quarantined) {
    labels.push({
      label: "Caution: flagged",
      css: "caution-flagged",
      title: `Data quality flags: ${(row.anomalyFlags || []).join(", ")}`,
    });
  }
  if (row.hasSourceDisagreement) {
    // Backend stamp: percentile spread above the depth-aware threshold
    // — sources split on this player's tier more than is typical at
    // his rank depth.  The backend trims the single most extreme
    // source on each side only when 5+ sources contribute
    // (_PERCENTILE_SPREAD_TRIM_MIN_N in data_contract.py), so the
    // tooltip only claims trimming when it actually applied.
    // Effective (post-Hampel) source count, computed conservatively
    // (Codex review round 11): prefer the mirrored effective map;
    // else derive it as sourceRanks minus droppedSources — counting
    // raw sourceRanks alone would include Hampel-rejected sources and
    // could claim trimming on a row whose effective count was < 5.
    // When neither effective map nor droppedSources is available
    // (legacy payloads mirror neither), effectiveCount stays null and
    // the trimming claim is simply omitted rather than guessed.
    let effectiveCount = null;
    if (row.effectiveSourceRanks && Object.keys(row.effectiveSourceRanks).length > 0) {
      effectiveCount = Object.keys(row.effectiveSourceRanks).length;
    } else if (row.sourceRanks && Array.isArray(row.droppedSources)) {
      const dropped = new Set(row.droppedSources);
      effectiveCount = Object.keys(row.sourceRanks).filter((k) => !dropped.has(k)).length;
    }
    const trimNote =
      effectiveCount != null && effectiveCount >= 5
        ? " (excluding the single most extreme source on each side)"
        : "";
    labels.push({
      label: "Caution: wide disagreement",
      css: "caution-disagree",
      title: `Sources split on this player's tier more than is typical at his rank depth${trimNote}`,
    });
  }
  return labels;
}

// ── Board lenses ─────────────────────────────────────────────────────────────
// Each lens is a { key, label, description, filter, sort } descriptor.
// filter(row) → boolean, sort(a,b) → number.
// The rankings page applies these to produce different board views.

/**
 * Lens definitions.  Each lens filters and sorts the ranked player list
 * to surface a specific type of signal.
 *
 * "consensus" is the default lens — shows all rows sorted by rank.
 */
export const LENSES = [
  {
    key: "consensus",
    label: "Consensus",
    description: "Standard board — all players sorted by unified rank.",
    filter: () => true,
    sort: null, // use default rank sort
  },
  {
    key: "disagreements",
    label: "Disagreements",
    description: `Players where sources disagree most. Spread > ${LENS_DISAGREEMENT_SPREAD} ranks between sources — potential mispricings or data issues.`,
    filter: (row) => (row.sourceRankSpread ?? 0) > LENS_DISAGREEMENT_SPREAD,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
  {
    key: "inefficiencies",
    label: "Inefficiencies",
    description: `Ranked players (top ${LENS_INEFFICIENCY_RANK}) with high source disagreement — where one market may be wrong. These are potential trade targets.`,
    filter: (row) => (row.rank ?? Infinity) <= LENS_INEFFICIENCY_RANK && (row.sourceRankSpread ?? 0) > LENS_INEFFICIENCY_SPREAD,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
  {
    key: "safest",
    label: "Safest",
    description: "High-confidence, multi-source assets with tight agreement. Lowest risk for trades — both markets agree on value.",
    filter: (row) => row.confidenceBucket === "high" && (row.sourceCount ?? 0) >= 2,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
  {
    key: "fragile",
    label: "Fragile",
    description: "Single-source, low-confidence, or flagged assets. Higher risk — value is based on thinner evidence.",
    filter: (row) =>
      row.isSingleSource ||
      row.confidenceBucket === "low" ||
      (row.anomalyFlags || []).length > 0,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
];

/**
 * Look up a lens by key.
 */
/**
 * SCREENS — the saved questions that used to be their own page.
 *
 * /finder was a board filter with these presets, rendered on a second
 * copy of the rankings table.  It computed nothing the board could not
 * express: every workflow is a lens plus a position/class pre-filter.
 * But the thresholds are NOT the same as the lenses above (WR Gaps
 * cuts at spread > 15 and rank <= 250; Disagreements cuts at
 * ${LENS_DISAGREEMENT_SPREAD}), so mapping the old page onto existing
 * lenses would have silently changed what each preset returned.
 *
 * They are carried over verbatim instead, and now run on the real
 * board — which means they inherit the source columns, tier
 * segmenting, export and player popup the standalone page never had.
 *
 * Kept separate from LENSES because they render differently: lenses
 * are the tab row ("how do I want to read the whole board"), screens
 * are a dropdown ("show me this specific question").  Ten tabs would
 * just be the old clutter in a new place.
 */
export const SCREENS = [
  {
    key: "wr-gaps",
    label: "WR Gaps",
    description:
      "Wide receivers where ranking sources disagree most — buy-low or sell-high depending on which market you trust.",
    filter: (r) =>
      r.pos === "WR" &&
      (r.sourceRankSpread ?? 0) > 15 &&
      (r.rank ?? Infinity) <= 250 &&
      !r.quarantined,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
  {
    key: "stable-idp",
    label: "Stable IDP",
    description:
      "IDP players with high confidence and tight multi-source agreement — the safest IDP trade targets.",
    filter: (r) =>
      r.assetClass === "idp" &&
      r.confidenceBucket === "high" &&
      (r.sourceCount ?? 0) >= 2 &&
      !r.quarantined,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
  {
    key: "single-risk",
    label: "1-Source Risk",
    description:
      "Players valued from only one ranking source — value could shift sharply if another source disagrees.",
    filter: (r) => r.isSingleSource && (r.rank ?? Infinity) <= 300,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
  {
    key: "rookie-spread",
    label: "Rookie Spread",
    description:
      "Rookies where sources disagree — upside signal if one market sees value the other doesn't.",
    filter: (r) =>
      r.rookie &&
      (r.sourceRankSpread ?? 0) > 10 &&
      (r.rank ?? Infinity) <= 400 &&
      !r.quarantined,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
];

/** Every view key the board can be put into — lenses plus screens. */
const ALL_VIEWS = [...LENSES, ...SCREENS];

export function isScreen(key) {
  return SCREENS.some((s) => s.key === key);
}

export function getLens(key) {
  return ALL_VIEWS.find((l) => l.key === key) || LENSES[0];
}

/**
 * Apply a lens to a list of rows.
 * Returns filtered + sorted array (does not mutate input).
 */
export function applyLens(rows, lensKey) {
  const lens = getLens(lensKey);
  const filtered = rows.filter(lens.filter);
  if (lens.sort) {
    return [...filtered].sort(lens.sort);
  }
  return filtered;
}

// ── Edge summary computation ─────────────────────────────────────────────────
// Computes compact summary lists for the Edge rail.
// Each function returns an array of { name, pos, rank, detail } objects,
// capped at `limit` entries.

/**
 * Top players where the retail market (sources flagged `isRetail` in
 * the registry — today just KTC) ranks them much higher than the
 * expert consensus (every non-retail source averaged).  These are
 * players the retail market values more than the experts do.
 *
 * Sell signals: players the retail market values much higher than the
 * expert consensus — potential sells to retail-first trade partners.
 *
 * Capped at the top ``EDGE_PREMIUM_RANK_LIMIT`` (250) on OUR blended
 * board so deep-bench players with huge source disagreements but no
 * trade relevance stay out of the rail.  Mirror of the same cap
 * applied on the /edge page via ``isTopRankedForEdgePremium``.
 */
export function topRetailPremium(rows, limit = 5) {
  const retailLabel = getRetailLabel();
  // AUDIT S-3, third instance. This gated, sorted AND LABELLED on
  // ``sourceRankSpread`` — how much the sources disagree with each other —
  // while the panel's whole premise is the retail-vs-consensus gap. The
  // rendered "Sell +45 ranks" showed the user the disagreement width and
  // called it the gap. Both now come from ``marketGapValueRatio``, the
  // magnitude of the direction actually being filtered on.  (NOT
  // ``marketGapMagnitude`` — that is the retired rank-space field, stamped
  // None on every row; naming it here was the same conflation this comment
  // exists to warn about.)
  return rows
    .filter((r) => r.marketGapDirection === "retail_premium"
      && marketGapAtLeast(r, PREMIUM_SUMMARY_VALUE_RATIO)
      && !r.quarantined
      && isTopRankedForEdgePremium(r))
    .sort((a, b) => (marketGapRatioOf(b) ?? -Infinity) - (marketGapRatioOf(a) ?? -Infinity))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `Sell — retail ${formatMarketGap(r)} higher`,
      row: r,
    }));
}

/**
 * Buy signals: players the expert consensus values much higher than
 * the retail market — potential buy-low targets from retail-first
 * trade partners.  Same top-N cap as ``topRetailPremium``.
 */
export function topConsensusPremium(rows, limit = 5) {
  return rows
    .filter((r) => r.marketGapDirection === "consensus_premium"
      && marketGapAtLeast(r, PREMIUM_SUMMARY_VALUE_RATIO)
      && !r.quarantined
      && isTopRankedForEdgePremium(r))
    .sort((a, b) => (marketGapRatioOf(b) ?? -Infinity) - (marketGapRatioOf(a) ?? -Infinity))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `Buy — experts ${formatMarketGap(r)} higher`,
      row: r,
    }));
}

/**
 * Top flagged players needing caution (anomaly flags, by rank).
 */
export function topFlaggedCautions(rows, limit = 5) {
  return rows
    .filter((r) => (r.anomalyFlags || []).length > 0 && (r.rank ?? Infinity) <= EDGE_CAUTION_RANK_LIMIT)
    .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: (r.anomalyFlags || []).slice(0, 2).join(", "),
      row: r,
    }));
}

/**
 * Top high-confidence consensus assets (multi-source, tight agreement, best rank).
 */
export function topConsensusAssets(rows, limit = 5) {
  return rows
    .filter((r) => r.confidenceBucket === "high" && (r.sourceCount ?? 0) >= 2 && !r.quarantined)
    .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `spread ${r.sourceRankSpread ?? 0}`,
      row: r,
    }));
}

/**
 * Compute all edge summary sections at once.
 * Returns an object with arrays for each section.
 */
export function computeEdgeSummary(rows) {
  // Pre-filter to ranked non-pick players
  const eligible = rows.filter(isEligibleForAnalysis);
  return {
    retailPremium: topRetailPremium(eligible),
    consensusPremium: topConsensusPremium(eligible),
    flaggedCautions: topFlaggedCautions(eligible),
    consensusAssets: topConsensusAssets(eligible)
  };
}
