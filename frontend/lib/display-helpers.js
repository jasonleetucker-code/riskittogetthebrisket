// ── Display helpers ──────────────────────────────────────────────────────────
// Shared presentational logic for badge CSS classes and label formatting.
// Used by rankings, edge, and finder pages.  Pure functions, no React.
//
// Tests: frontend/__tests__/display-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import { MARKET_GAP_MIN_DIFF, MIN_CONSENSUS_SOURCES_FOR_VERB } from "./thresholds.js";
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
 * True when the board declined to price this row.
 *
 * The canonical materializers (`_materializePlayerArrayRow` /
 * `_materializeLegacyDictRow`) both read `rankDerivedValue` as
 * `Number(...) || null`, so an unpriced row carries an explicit null
 * — never 0, never absent.  A row that does not carry the key at all
 * (a hand-built descriptor, a partial fixture) is NOT treated as
 * unpriced: absence of the field is not evidence of a refusal.
 *
 * This is the single predicate every abstaining display helper keys
 * off, so "the board could not price this" has exactly one definition
 * on the client (W07-F004).
 */
export function isUnpricedRow(row) {
  if (!row || typeof row !== "object") return false;
  if (!("rankDerivedValue" in row)) return false;
  return row.rankDerivedValue == null;
}

/**
 * Return the CSS class for a confidence badge.
 *
 * ``none`` is the backend's "no confidence could be computed" bucket
 * (``confidenceLabel: "None - unranked"``), not the bottom of the
 * scale.  It used to fall through to the same red "Low" badge as a
 * genuinely low-confidence row, which read as a graded verdict on a
 * row the pipeline never graded (W07-F004).
 */
export function confBadgeClass(bucket) {
  if (bucket === "high") return "badge badge-green";
  if (bucket === "medium") return "badge badge-amber";
  if (bucket === "low") return "badge badge-red";
  return "badge badge-muted";
}

/**
 * Return a short human label for a confidence bucket.
 *
 * See :func:`confBadgeClass` — ``none``/absent is an abstention and
 * renders as a dash, never as "Low".
 */
export function confBadgeLabel(bucket) {
  if (bucket === "high") return "High";
  if (bucket === "medium") return "Med";
  if (bucket === "low") return "Low";
  return "—";
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
export function marketEdge(row) {
  const retailLabel = getRetailLabel();
  // The board declined to price this row, so there is no consensus to
  // compare the retail market against.  Per-source ranks can still be
  // present — Austin Ekeler carried ktcSfTep 400 / dlf 100 with every
  // backend stamp null — and computing a gap off them manufactured a
  // BUY/SELL verdict on a player the pipeline explicitly refused
  // (W07-F004).  Abstain instead, with its own `kind` so a caller can
  // tell "refused to price" from "no sources at all".
  if (isUnpricedRow(row)) {
    return {
      label: "unpriced",
      css: "edge-none",
      kind: "unpriced",
      title:
        "The board could not price this player, so there is no consensus " +
        "value to compare against the market.",
    };
  }
  // Prefer ``effectiveSourceRanks`` (post-Hampel filter on the
  // backend) when present so retail-vs-consensus edge labels stay in
  // lockstep with backend marketGapDirection / confidence /
  // anomalyFlags.  Fall back to ``sourceRanks`` for legacy payloads.
  const ranks =
    row?.effectiveSourceRanks && Object.keys(row.effectiveSourceRanks).length > 0
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

  // Evidence gate BEFORE the arithmetic: "retail versus expert consensus"
  // needs a consensus to exist.  Gates on the BACKEND's count of the
  // sources that actually formed each side, and only on that, because
  // ``getPlayerEdge`` has nothing else to gate on — counting the ranks in
  // hand here would make the two emitters disagree on any payload without
  // the stamp, which is the failure W12-F001 just closed.  No stamp =
  // unknown = no suppression.
  const consensusSources = Number(row?.marketGapConsensusSources);
  if (Number.isFinite(consensusSources) && consensusSources < MIN_CONSENSUS_SOURCES_FOR_VERB) {
    return {
      label: `${consensusSources} expert source${consensusSources === 1 ? "" : "s"}`,
      css: "edge-none",
      kind: "thin_consensus",
      consensusSources,
      title:
        `Only ${consensusSources} source besides ${retailLabel} ranked this player, ` +
        `so there is no expert consensus for the market to disagree with ` +
        `(a directional call needs ${MIN_CONSENSUS_SOURCES_FOR_VERB}).`,
    };
  }

  const retailMean = retailRanks.reduce((s, v) => s + v, 0) / retailRanks.length;
  const consensusMean =
    consensusRanks.reduce((s, v) => s + v, 0) / consensusRanks.length;
  const diff = Math.round(Math.abs(consensusMean - retailMean));

  if (diff < MARKET_GAP_MIN_DIFF) {
    return {
      label: "aligned",
      css: "edge-aligned",
      kind: "aligned",
      title: `${retailLabel} and expert consensus agree within ${MARKET_GAP_MIN_DIFF} ranks (actual difference: ${diff}).`,
    };
  }
  if (retailMean < consensusMean) {
    return {
      label: `${retailLabel} higher by ${diff}`,
      css: "edge-retail",
      kind: "retail_higher",
      title: `${retailLabel} ranks this player ~${diff} ordinal ranks above expert consensus.`,
    };
  }
  return {
    label: `Experts higher by ${diff}`,
    css: "edge-consensus",
    kind: "consensus_higher",
    title: `Expert consensus ranks this player ~${diff} ordinal ranks above ${retailLabel}.`,
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
  if (edge.kind === "thin_consensus") {
    // An explicit thin-evidence state, not the ambiguous dash: the row was
    // priced and the market was compared, there just was not enough on the
    // consensus side to call a direction.
    return {
      label: "THIN",
      css: "edge-none",
      kind: "thin_consensus",
      title: edge.title,
    };
  }
  return {
    label: "—",
    css: "edge-none",
    kind: edge.kind,
    title: edge.title || "Insufficient source coverage to compare market vs experts.",
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
    row?.effectiveSourceRanks && Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row?.sourceRanks;
  if (!ranks) return null;
  // Same abstention as ``marketEdge`` (W07-F004): no board value, no
  // gap to describe.
  if (isUnpricedRow(row)) return null;
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

  // Same evidence gate as ``marketEdge``, off the same backend stamp: one
  // expert source is not a consensus, so there is no gap to report
  // (W12-F007).
  const consensusSources = Number(row?.marketGapConsensusSources);
  if (Number.isFinite(consensusSources) && consensusSources < MIN_CONSENSUS_SOURCES_FOR_VERB) {
    return null;
  }

  const retailMean = retailRanks.reduce((s, v) => s + v, 0) / retailRanks.length;
  const consensusMean =
    consensusRanks.reduce((s, v) => s + v, 0) / consensusRanks.length;
  const diff = Math.round(Math.abs(consensusMean - retailMean));
  if (diff < MARKET_GAP_MIN_DIFF) return null;
  const higher = retailMean < consensusMean ? getRetailLabel() : "Consensus";
  return `${higher} +${diff}`;
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
// IDP sources (DLF IDP, IDP Show, FantasyPros IDP, FootballGuys IDP,
// DraftSharks IDP) as the expert consensus.

const IDP_RETAIL_KEY = "idpTradeCalc";

const IDP_CONSENSUS_KEYS = new Set([
  "dlfIdp",
  "idpShow",
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
  // Same abstention as ``marketEdge`` — an unpriced defender has no
  // consensus to compare IDPTC against (W07-F004).
  if (isUnpricedRow(row)) {
    return {
      label: "unpriced",
      css: "edge-none",
      kind: "unpriced",
      title:
        "The board could not price this player, so there is no consensus " +
        "value to compare against the IDP market.",
    };
  }
  const ranks =
    row?.effectiveSourceRanks && Object.keys(row.effectiveSourceRanks).length > 0
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

  // Evidence gate, same rule as the offense twin.  The backend's
  // ``marketGapConsensusSources`` counts the KTC-anchored split, which is
  // a different partition of the sources, so this side is counted here.
  if (consensusRanks.length < MIN_CONSENSUS_SOURCES_FOR_VERB) {
    return {
      label: `${consensusRanks.length} IDP expert source${consensusRanks.length === 1 ? "" : "s"}`,
      css: "edge-none",
      kind: "thin_consensus",
      consensusSources: consensusRanks.length,
      title:
        `Only ${consensusRanks.length} IDP-expert source ranked this player, so ` +
        `there is no consensus for IDPTC to disagree with (a directional ` +
        `call needs ${MIN_CONSENSUS_SOURCES_FOR_VERB}).`,
    };
  }

  const consensusMean =
    consensusRanks.reduce((s, v) => s + v, 0) / consensusRanks.length;
  const diff = Math.round(Math.abs(consensusMean - retailRank));

  if (diff < MARKET_GAP_MIN_DIFF) {
    return {
      label: "aligned",
      css: "edge-aligned",
      kind: "aligned",
      title: `IDPTC and IDP-expert consensus agree within ${MARKET_GAP_MIN_DIFF} ranks (actual difference: ${diff}).`,
    };
  }
  if (retailRank < consensusMean) {
    return {
      label: `IDPTC higher by ${diff}`,
      css: "edge-retail",
      kind: "retail_higher",
      title: `IDPTC ranks this player ~${diff} ordinal ranks above IDP-expert consensus.`,
    };
  }
  return {
    label: `Experts higher by ${diff}`,
    css: "edge-consensus",
    kind: "consensus_higher",
    title: `IDP-expert consensus ranks this player ~${diff} ordinal ranks above IDPTC.`,
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
  if (edge.kind === "thin_consensus") {
    return {
      label: "THIN",
      css: "edge-none",
      kind: "thin_consensus",
      title: edge.title,
    };
  }
  return {
    label: "—",
    css: "edge-none",
    kind: edge.kind,
    title: edge.title || "Insufficient IDP source coverage to compare IDPTC vs experts.",
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
    (row.effectiveSourceRanks && Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row.sourceRanks) || {};
  const idptcRank = Number(ranks[IDP_RETAIL_KEY]);
  if (!Number.isFinite(idptcRank) || idptcRank < 1) return false;
  return idptcRank <= limit;
}
