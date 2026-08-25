// ── Display helpers ──────────────────────────────────────────────────────────
// Shared presentational logic for badge CSS classes and label formatting.
// Used by rankings, edge, and finder pages.  Pure functions, no React.
//
// Tests: frontend/__tests__/display-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import { MARKET_GAP_MIN_VALUE_RATIO } from "./thresholds.js";
import { getRetailSourceKeys, getRetailLabel } from "./dynasty-data.js";

/**
 * Return the CSS class for a position badge based on asset class.
 *
 * Picks get a distinct green badge so users can spot draft picks inline
 * alongside offense (cyan) and IDP (amber) rows on the rankings board
 * and in the trade calculator picker.
 */
export function posBadgeClass(row) {
  if (row?.assetClass === "offense") return "badge badge-cyan";
  if (row?.assetClass === "idp") return "badge badge-amber";
  if (row?.assetClass === "pick") return "badge badge-green";
  return "badge";
}

/**
 * Return the CSS class for a confidence badge.
 */
export function confBadgeClass(bucket) {
  if (bucket === "high") return "badge badge-green";
  if (bucket === "medium") return "badge badge-amber";
  return "badge badge-red";
}

/**
 * Return a short human label for a confidence bucket.
 */
export function confBadgeLabel(bucket) {
  if (bucket === "high") return "High";
  if (bucket === "medium") return "Med";
  return "Low";
}

// ── Eligibility filters ─────────────────────────────────────────────────────

/**
 * Returns true if a row is eligible for the ranked board.
 * Used by Rankings (which shows all eligible including unranked).
 *
 * Draft picks (pos "PICK") are included: KTC and IDPTradeCalc both
 * price picks on the same 0-9999 scale as players, so they get full
 * unified ranks from the backend and render alongside players on the
 * rankings board and in the trade calculator.
 */
export function isEligibleForBoard(row) {
  return !!row?.pos && row.pos !== "?";
}

/**
 * Returns true if a row is eligible for Edge/Finder analysis surfaces.
 * Requires a rank in addition to board eligibility.  Excludes picks:
 * the finder workflows (buy-low, sell-high, inefficiencies) are
 * player-discovery surfaces; draft picks are surfaced on the rankings
 * board and trade calculator, not the finder.
 */
export function isEligibleForAnalysis(row) {
  return isEligibleForBoard(row) && row.pos !== "PICK" && !!row.rank;
}

/**
 * Return a short market-gap label string, or null if insignificant.
 *
 * "Market gap" frames the retail market (sources flagged `isRetail` in
 * the registry — today just KTC) against every other registered
 * source (the expert consensus — IDPTC, DLF, etc.).  Both sides are
 * averaged and the label shows the side that ranks the player higher
 * and by how many ordinal ranks.  A "KTC +N" label means retail values
 * the player more than the consensus does; a "Consensus +N" label is
 * the reverse.
 *
 * The retail side label is resolved dynamically from the registry via
 * `getRetailLabel()`, so adding a second retail source flips the label
 * to the generic "Retail" with no code edits here.
 */
/**
 * Compute the structured market-edge descriptor for a row.
 *
 * Returns an object so callers can show explicit wording instead of the
 * legacy ambiguous dash.  The returned shape is always:
 *
 *   { label: string, css: string, title: string, kind: string }
 *
 * `kind` identifies the exact logic branch so UI code can render
 * different styles without re-implementing the branching:
 *   - "retail_higher"   retail prices player above consensus by >= threshold
 *   - "consensus_higher" consensus prices player above retail by >= threshold
 *   - "aligned"          both sides agree within threshold
 *   - "retail_only"      only retail sources ranked this player
 *   - "consensus_only"   only expert/consensus sources ranked this player
 *   - "unranked"         no per-source ranks available at all
 *
 * The legacy `marketGapLabel` behavior (returning a raw string or null)
 * is preserved in `marketGapLabelLegacy` for back-compat with tests.
 */
// ── the market gap is measured in VALUE space, not rank space ──────────
//
// `sourceRankMeta[key].valueContribution` is what the blend itself
// compares sources in: post-ladder, common-scaled 0-9999, and — the load
// bearing part — the stage AFTER ADR-015's `convert_te_value` has been
// applied.  Averaging raw ordinals instead measured pool depth and format
// basis, which is why every top-250 SELL label on the board was a tight
// end while QB inverted to mostly BUY.
//
// This computes no rank and no value; it averages two subsets of a
// backend stamp, exactly as TradeFairnessExplanation and
// SourceContributionBars already do.  `buildRows` is untouched.
//
// Returns null when the payload carries no `sourceRankMeta` at all, so a
// legacy contract DEGRADES to "can't tell" instead of being scored on a
// field that isn't there.
function sideValues(row, keys, isRetailKey) {
  const meta = row?.sourceRankMeta;
  if (!meta || typeof meta !== "object" || Object.keys(meta).length === 0)
    return null;
  const retail = [];
  const consensus = [];
  for (const key of keys) {
    const v = Number((meta[key] || {}).valueContribution);
    if (!Number.isFinite(v)) continue;
    (isRetailKey(key) ? retail : consensus).push(v);
  }
  return { retail, consensus };
}

/**
 * The signed relative gap between the two sides, in value space.
 *
 * Positive = the retail anchor values the player ABOVE expert consensus
 * (the market is high on him → SELL).  Note this inverts the sense of the
 * old rank comparison, where a LOWER mean rank meant "priced higher".
 */
function relativeValueGap(retailValues, consensusValues) {
  const mean = (xs) => xs.reduce((s, v) => s + v, 0) / xs.length;
  const r = mean(retailValues);
  const c = mean(consensusValues);
  const scale = (r + c) / 2;
  if (!(scale > 0)) return null;
  return { ratio: (r - c) / scale, retailMean: r, consensusMean: c };
}

function pctText(ratio) {
  return `${Math.round(Math.abs(ratio) * 100)}%`;
}

/**
 * The row's market gap as a relative value ratio, or null when it has none.
 *
 * An explicit accessor rather than `?? 0` at each call site: a row the backend
 * declined to price has NO gap, and folding that into a gap of zero is the
 * coercion this remediation pass exists to remove.  It also reads the LIVE
 * field — `marketGapMagnitude` is the retired rank-space one and is stamped
 * None on every row.
 */
export function marketGapRatioOf(row) {
  const ratio = Number(row?.marketGapValueRatio);
  return Number.isFinite(ratio) ? ratio : null;
}

/** True when the row carries a gap at or above `floor`. */
export function marketGapAtLeast(row, floor) {
  const ratio = marketGapRatioOf(row);
  return ratio !== null && ratio >= floor;
}

/**
 * The gap as a short human string, e.g. "by 18%".
 *
 * The single formatter.  The /edge rails previously built their own out of
 * `sourceRankSpread` and rendered "Sell +45 ranks" — a source-disagreement
 * width, described to the user as the retail-vs-consensus gap (audit S-3).
 */
export function formatMarketGap(row) {
  const ratio = marketGapRatioOf(row);
  if (ratio === null) return "by an unknown amount";
  return `by ${Math.round(Math.abs(ratio) * 100)}%`;
}

export function marketEdge(row) {
  const retailLabel = getRetailLabel();
  // Prefer ``effectiveSourceRanks`` (post-Hampel filter on the
  // backend) when present so retail-vs-consensus edge labels stay in
  // lockstep with backend marketGapDirection / confidence /
  // anomalyFlags.  Fall back to ``sourceRanks`` for legacy payloads.
  const ranks =
    row?.effectiveSourceRanks &&
    Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row?.sourceRanks;
  if (!ranks || Object.keys(ranks).length === 0) {
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title: "This player has no per-source ranks available.",
    };
  }
  const retailKeys = new Set(getRetailSourceKeys());

  const retailRanks = Object.entries(ranks)
    .filter(([key, rank]) => retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));

  const consensusRanks = Object.entries(ranks)
    .filter(([key, rank]) => !retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));

  if (retailRanks.length === 0 && consensusRanks.length > 0) {
    return {
      label: "expert only",
      css: "edge-none",
      kind: "consensus_only",
      title: `No ${retailLabel} rank for this player — only expert/consensus sources contributed.`,
    };
  }
  if (consensusRanks.length === 0 && retailRanks.length > 0) {
    return {
      label: `${retailLabel} only`,
      css: "edge-none",
      kind: "retail_only",
      title: `No expert/consensus rank for this player — only ${retailLabel} contributed.`,
    };
  }
  if (retailRanks.length === 0 && consensusRanks.length === 0) {
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title: "This player has no per-source ranks available.",
    };
  }

  const sides = sideValues(row, Object.keys(ranks), (k) => retailKeys.has(k));
  const gap =
    sides && sides.retail.length && sides.consensus.length
      ? relativeValueGap(sides.retail, sides.consensus)
      : null;
  if (!gap) {
    // No per-source value stamps (legacy payload). Say so rather than
    // falling back to the rank arithmetic this replaced.
    return {
      label: "unpriced",
      css: "edge-none",
      kind: "unranked",
      title:
        "This payload carries no per-source value contributions, so the market gap cannot be measured.",
    };
  }

  const pct = pctText(gap.ratio);
  if (Math.abs(gap.ratio) < MARKET_GAP_MIN_VALUE_RATIO) {
    return {
      label: "aligned",
      css: "edge-aligned",
      kind: "aligned",
      title: `${retailLabel} and expert consensus value this player within ${Math.round(MARKET_GAP_MIN_VALUE_RATIO * 100)}% of each other (actual difference: ${pct}).`,
    };
  }
  if (gap.ratio > 0) {
    return {
      label: `${retailLabel} higher by ${pct}`,
      css: "edge-retail",
      kind: "retail_higher",
      title: `${retailLabel} values this player ~${pct} above expert consensus.`,
    };
  }
  return {
    label: `Experts higher by ${pct}`,
    css: "edge-consensus",
    kind: "consensus_higher",
    title: `Expert consensus values this player ~${pct} above ${retailLabel}.`,
  };
}

/**
 * marketAction(row) — collapses the structured ``marketEdge()``
 * descriptor into a single trader-facing verb: BUY / SELL / HOLD.
 *
 * Rules (matching the user-facing contract):
 *   - "consensus_higher"  experts price the player above the market
 *                         → market is undervaluing → BUY
 *   - "retail_higher"     market prices the player above experts
 *                         → market is overvaluing → SELL
 *   - "aligned"           sides agree                        → HOLD
 *   - anything else (consensus_only / retail_only / unranked)
 *                         → "—"   (insufficient data)
 *
 * Returns { label, css, title, kind } so the rankings table can
 * style the cell uniformly.  Title surfaces the underlying gap
 * for hover-debug.
 */
export function marketAction(row) {
  const edge = marketEdge(row);
  if (edge.kind === "consensus_higher") {
    return {
      label: "BUY",
      css: "edge-buy",
      kind: "buy",
      title: `${edge.title} Experts > market → market is undervaluing.`,
    };
  }
  if (edge.kind === "retail_higher") {
    return {
      label: "SELL",
      css: "edge-sell",
      kind: "sell",
      title: `${edge.title} Market > experts → market is overvaluing.`,
    };
  }
  if (edge.kind === "aligned") {
    return {
      label: "HOLD",
      css: "edge-hold",
      kind: "hold",
      title: edge.title,
    };
  }
  return {
    label: "—",
    css: "edge-none",
    kind: edge.kind,
    title:
      edge.title ||
      "Insufficient source coverage to compare market vs experts.",
  };
}

/**
 * Legacy string-only market gap label.  Retained for tests and any
 * consumer that still expects the old `"KTC +N"` / `"Consensus +N"` /
 * `null` contract.  New code should prefer `marketEdge()` which
 * returns an explicit structured object.
 */
export function marketGapLabel(row) {
  // Mirror ``marketEdge``: prefer the post-Hampel ``effectiveSourceRanks``
  // when stamped, fall back to ``sourceRanks`` for legacy payloads.
  const ranks =
    row?.effectiveSourceRanks &&
    Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row?.sourceRanks;
  if (!ranks) return null;
  const retailKeys = new Set(getRetailSourceKeys());

  const retailRanks = Object.entries(ranks)
    .filter(([key, rank]) => retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));
  if (retailRanks.length === 0) return null;

  const consensusRanks = Object.entries(ranks)
    .filter(([key, rank]) => !retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));
  if (consensusRanks.length === 0) return null;

  const sides = sideValues(row, Object.keys(ranks), (k) => retailKeys.has(k));
  if (!sides || !sides.retail.length || !sides.consensus.length) return null;
  const gap = relativeValueGap(sides.retail, sides.consensus);
  if (!gap || Math.abs(gap.ratio) < MARKET_GAP_MIN_VALUE_RATIO) return null;
  const higher = gap.ratio > 0 ? getRetailLabel() : "Consensus";
  return `${higher} +${pctText(gap.ratio)}`;
}

// ── IDP market gap (IDPTC vs other IDP sources) ─────────────────────────
//
// The `marketEdge` / `marketAction` helpers above use the registry's
// retail flag — today only KTC.  KTC doesn't list IDP players, so
// IDP rows always come back as "expert only" / unranked / neutral
// from those helpers, and the offense BUY/SELL signals never fire
// for defenders.
//
// For IDP-specific Buy/Sell signals we treat IDPTC as the analogous
// "retail" anchor (the most-followed source on the IDP side, just as
// KTC is the most-followed source on the offense side) and the other
// overall_idp sources as the expert consensus.
//
// This set is a hand-maintained mirror of the source registry, and it
// had drifted both ways: it OMITTED `dlfRookieIdp` (a real
// overall_idp source — 29 rows carry a rank from it, and 28 of those
// shift their consensus mean by >=1 rank once it is counted) while
// this comment NAMED "FootballGuys IDP", which is not a key in either
// registry. Kept in sync with `RANKING_SOURCES` in dynasty-data.js and
// `_RANKING_SOURCES` in src/api/data_contract.py; `idp-consensus-keys`
// test fails if they diverge again.

const IDP_RETAIL_KEY = "idpTradeCalc";

const IDP_CONSENSUS_KEYS = new Set([
  "dlfIdp",
  "dlfRookieIdp",
  "idpShowCombined",
  "fantasyProsIdp",
  "draftSharksIdp",
]);

/**
 * Structured retail-vs-consensus descriptor for IDP rows, using
 * IDPTC as the retail anchor.
 *
 * Returns `{ label, css, kind, title }` matching the shape
 * `marketEdge()` returns, so a caller can hand the result to the
 * same UI components.
 *
 * `kind` values:
 *   - `"consensus_higher"` — IDP experts mean rank is significantly
 *     better (lower number) than IDPTC's rank → market (IDPTC)
 *     undervalues → BUY signal.
 *   - `"retail_higher"` — IDPTC ranks the player significantly above
 *     the IDP-expert consensus mean → market (IDPTC) overvalues →
 *     SELL signal.
 *   - `"aligned"`, `"retail_only"`, `"consensus_only"`, `"unranked"`
 *     — same semantics as `marketEdge`.
 */
export function idpMarketEdge(row) {
  const ranks =
    row?.effectiveSourceRanks &&
    Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row?.sourceRanks;
  if (!ranks || Object.keys(ranks).length === 0) {
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title: "No IDP source ranks available for this player.",
    };
  }
  const retailRank = Number(ranks[IDP_RETAIL_KEY]);
  const consensusRanks = Object.entries(ranks)
    .filter(([k, v]) => IDP_CONSENSUS_KEYS.has(k) && v != null)
    .map(([, v]) => Number(v))
    .filter((n) => Number.isFinite(n));

  const haveRetail = Number.isFinite(retailRank);
  const haveConsensus = consensusRanks.length > 0;

  if (!haveRetail && !haveConsensus) {
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title: "No IDP source ranks available for this player.",
    };
  }
  if (!haveRetail) {
    return {
      label: "expert only",
      css: "edge-none",
      kind: "consensus_only",
      title: "No IDPTC rank — only IDP-expert sources contributed.",
    };
  }
  if (!haveConsensus) {
    return {
      label: "IDPTC only",
      css: "edge-none",
      kind: "retail_only",
      title: "No IDP-expert rank — only IDPTC contributed.",
    };
  }

  // Same value-space treatment as the offense path.  The IDP side is
  // if anything more exposed to the pool-depth artifact: idpTradeCalc
  // publishes ~901 rows against dlfIdp/idpShowCombined/fantasyProsIdp
  // pools a fraction of that size.
  const idpSides = sideValues(
    row,
    Object.keys(ranks),
    (k) => k === IDP_RETAIL_KEY,
  );
  const idpGap =
    idpSides && idpSides.retail.length && idpSides.consensus.length
      ? relativeValueGap(idpSides.retail, idpSides.consensus)
      : null;
  if (!idpGap) {
    return {
      label: "unpriced",
      css: "edge-none",
      kind: "unranked",
      title:
        "This payload carries no per-source value contributions, so the IDP market gap cannot be measured.",
    };
  }

  const idpPct = pctText(idpGap.ratio);
  if (Math.abs(idpGap.ratio) < MARKET_GAP_MIN_VALUE_RATIO) {
    return {
      label: "aligned",
      css: "edge-aligned",
      kind: "aligned",
      title: `IDPTC and IDP-expert consensus value this player within ${Math.round(MARKET_GAP_MIN_VALUE_RATIO * 100)}% of each other (actual difference: ${idpPct}).`,
    };
  }
  if (idpGap.ratio > 0) {
    return {
      label: `IDPTC higher by ${idpPct}`,
      css: "edge-retail",
      kind: "retail_higher",
      title: `IDPTC values this player ~${idpPct} above IDP-expert consensus.`,
    };
  }
  return {
    label: `Experts higher by ${idpPct}`,
    css: "edge-consensus",
    kind: "consensus_higher",
    title: `IDP-expert consensus values this player ~${idpPct} above IDPTC.`,
  };
}

/**
 * Single-verb BUY / SELL / HOLD descriptor for IDP rows, derived
 * from `idpMarketEdge`.  Mirrors `marketAction` but with IDPTC as
 * the retail anchor.
 */
export function idpMarketAction(row) {
  const edge = idpMarketEdge(row);
  if (edge.kind === "consensus_higher") {
    return {
      label: "BUY",
      css: "edge-buy",
      kind: "buy",
      title: `${edge.title} IDP experts > IDPTC → IDPTC is undervaluing.`,
    };
  }
  if (edge.kind === "retail_higher") {
    return {
      label: "SELL",
      css: "edge-sell",
      kind: "sell",
      title: `${edge.title} IDPTC > IDP experts → IDPTC is overvaluing.`,
    };
  }
  if (edge.kind === "aligned") {
    return {
      label: "HOLD",
      css: "edge-hold",
      kind: "hold",
      title: edge.title,
    };
  }
  return {
    label: "—",
    css: "edge-none",
    kind: edge.kind,
    title:
      edge.title ||
      "Insufficient IDP source coverage to compare IDPTC vs experts.",
  };
}

/**
 * Predicate: row is an IDP eligible for the top-200 IDP Buy/Sell
 * sections.  Requires:
 *   - assetClass === "idp"
 *   - IDPTC ranked the player at or above 200
 *   - row is not quarantined
 *
 * The IDPTC-rank-based limit (rather than our blended consensus rank)
 * matches user expectation: "limit to the top 200 by IDPTC".
 */
export function isIdpInTopByIdptc(row, limit = 200) {
  if (!row || row.assetClass !== "idp") return false;
  if (row.quarantined) return false;
  const ranks =
    (row.effectiveSourceRanks &&
    Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row.sourceRanks) || {};
  const idptcRank = Number(ranks[IDP_RETAIL_KEY]);
  if (!Number.isFinite(idptcRank) || idptcRank < 1) return false;
  return idptcRank <= limit;
}

// Exposed for parity testing only — `IDP_CONSENSUS_KEYS` is a
// hand-maintained mirror of the source registry and drifted once
// (omitting `dlfRookieIdp`, naming a nonexistent "FootballGuys IDP").
// `__tests__/idp-consensus-keys-parity.test.js` derives the expected
// set from RANKING_SOURCES so a future divergence fails loudly instead
// of quietly biasing the IDP consensus mean.
export const __testables = { IDP_CONSENSUS_KEYS, IDP_RETAIL_KEY };
