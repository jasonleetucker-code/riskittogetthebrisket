// ── Display helpers ──────────────────────────────────────────────────────────
// Shared presentational logic for badge CSS classes and label formatting.
// Used by rankings, edge, and finder pages.  Pure functions, no React.
//
// Tests: frontend/__tests__/display-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import { MARKET_GAP_MIN_MAGNITUDE, MARKET_GAP_MIN_DIFF } from "./thresholds.js";
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
export function marketEdge(row) {
  const retailLabel = getRetailLabel();
  const direction = String(row?.marketGapDirection || "");
  const magnitude = Number(row?.marketGapMagnitude);
  const reason = row?.marketGapUnknown?.reason;

  // No direction. The backend now says WHY, which is the whole reason
  // this function no longer computes anything: it used to rebuild the
  // retail/consensus means locally because the contract collapsed
  // "only retail ranked him", "only the experts did" and "nobody did"
  // into one bare "none" and it needed the distinction.
  if (!direction || direction === "none" || !Number.isFinite(magnitude)) {
    if (reason === "consensus_only") {
      return {
        label: "expert only",
        css: "edge-none",
        kind: "consensus_only",
        title: `No ${retailLabel} rank for this player — only expert/consensus sources contributed.`,
      };
    }
    if (reason === "retail_only") {
      return {
        label: `${retailLabel} only`,
        css: "edge-none",
        kind: "retail_only",
        title: `No expert/consensus rank for this player — only ${retailLabel} contributed.`,
      };
    }
    if (reason === "position_sample_too_small") {
      return {
        label: "—",
        css: "edge-none",
        kind: "insufficient_basis",
        title:
          row?.marketGapUnknown?.detail ||
          "Too few players at this position to separate signal from positional basis.",
      };
    }
    // A measured tie is direction "none" WITH a finite magnitude — the
    // backend computed the gap and it came out at zero. Everything else
    // here is an absence, and the two must not render alike: "aligned"
    // is a confident statement that the market and the experts agree,
    // and an unstamped row supports no such claim. Getting this wrong
    // is the C3 defect one layer up, and the test below is what caught
    // it in this very function.
    if (direction === "none" && Number.isFinite(magnitude)) {
      return {
        label: "aligned",
        css: "edge-aligned",
        kind: "aligned",
        title: `${retailLabel} and expert consensus agree once board depth and positional basis are accounted for.`,
      };
    }
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title:
        row?.marketGapUnknown?.detail ||
        "No market gap was stamped for this player, so there is nothing to compare.",
    };
  }

  if (magnitude < MARKET_GAP_MIN_MAGNITUDE) {
    return {
      label: "aligned",
      css: "edge-aligned",
      kind: "aligned",
      title: `${retailLabel} and expert consensus agree within ${MARKET_GAP_MIN_MAGNITUDE} (actual: ${Math.round(magnitude)}).`,
    };
  }
  if (direction === "retail_premium") {
    return {
      label: `${retailLabel} higher by ${Math.round(magnitude)}`,
      css: "edge-retail",
      kind: "retail_higher",
      title: `${retailLabel} places this player ${Math.round(magnitude)} higher than expert consensus, measured in rank space and net of the positional basis.`,
    };
  }
  return {
    label: `Experts higher by ${Math.round(magnitude)}`,
    css: "edge-consensus",
    kind: "consensus_higher",
    title: `Expert consensus places this player ${Math.round(magnitude)} higher than ${retailLabel}, measured in rank space and net of the positional basis.`,
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
 *   - anything else (consensus_only / retail_only / unranked /
 *     insufficient_basis)  → "—"   (insufficient data)
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
    title: edge.title || "Insufficient source coverage to compare market vs experts.",
  };
}

/**
 * The row's market-gap magnitude, or null when it has none.
 *
 * Written as an explicit accessor rather than `?? 0` at each call site.
 * A row the backend declined to stamp has NO gap; folding that into a
 * magnitude of zero is a coercion of exactly the kind batch C3 removed,
 * and while zero happens to fall below every gate today, that is the
 * gate saving the expression rather than the expression being right.
 */
export function marketGapMagnitudeOf(row) {
  const magnitude = Number(row?.marketGapMagnitude);
  return Number.isFinite(magnitude) ? magnitude : null;
}

/** True when the row carries a gap at or above `floor`. */
export function marketGapAtLeast(row, floor) {
  const magnitude = marketGapMagnitudeOf(row);
  return magnitude !== null && magnitude >= floor;
}

/**
 * Render the market gap as a short human string, e.g. "84 (rank-space)".
 *
 * The single formatter for the gap.  It exists because the /edge rails
 * previously built their own label out of ``sourceRankSpread`` and
 * printed "Sell +45 ranks" — a source-disagreement width, described to
 * the user as the retail-vs-consensus gap.
 */
export function formatMarketGap(row) {
  const magnitude = Number(row?.marketGapMagnitude);
  if (!Number.isFinite(magnitude)) return "by an unknown amount";
  return `by ${Math.round(magnitude)}`;
}

/**
 * Legacy string-only market gap label: `"KTC +N"` / `"Consensus +N"` /
 * `null`.  Retained for consumers that still expect the string
 * contract; new code should prefer `marketEdge()`.
 *
 * N IS NO LONGER AN ORDINAL RANK DIFFERENCE.  It is the backend's
 * ``marketGapMagnitude`` in rank-space per-mille, net of positional
 * basis — see config/thresholds.json.  The old local recompute is gone
 * along with the raw-ordinal arithmetic that made "+45" mean something
 * different on every source board.
 */
export function marketGapLabel(row) {
  const direction = String(row?.marketGapDirection || "");
  const magnitude = Number(row?.marketGapMagnitude);
  if (direction !== "retail_premium" && direction !== "consensus_premium") return null;
  if (!Number.isFinite(magnitude) || magnitude < MARKET_GAP_MIN_MAGNITUDE) return null;
  const higher = direction === "retail_premium" ? getRetailLabel() : "Consensus";
  return `${higher} +${Math.round(magnitude)}`;
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

// Exposed for parity testing only — `IDP_CONSENSUS_KEYS` is a
// hand-maintained mirror of the source registry and drifted once
// (omitting `dlfRookieIdp`, naming a nonexistent "FootballGuys IDP").
// `__tests__/idp-consensus-keys-parity.test.js` derives the expected
// set from RANKING_SOURCES so a future divergence fails loudly instead
// of quietly biasing the IDP consensus mean.
export const __testables = { IDP_CONSENSUS_KEYS, IDP_RETAIL_KEY };
