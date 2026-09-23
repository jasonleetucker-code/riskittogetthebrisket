// ── Display helpers ──────────────────────────────────────────────────────────
// Shared presentational logic for badge CSS classes and label formatting.
// Used by rankings, edge, and finder pages.  Pure functions, no React.
//
// Tests: frontend/__tests__/display-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import { MARKET_GAP_MIN_VALUE_RATIO } from "./thresholds.js";

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
 * "Market gap" is OUR MODEL VALUE against canonical KTC MARKET (KTC's
 * published Crowd+Trades value, normalized onto the board scale) — owner
 * directive 2026-09-23, backend owner `src/sources/ktc_market.py`.  It is
 * read from backend stamps (`ktcMarket`, `marketGapDirection`,
 * `marketGapValueRatio`); nothing here recomputes it.
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
 *   - "retail_higher"    KTC Market prices the asset above our model
 *   - "consensus_higher" our model prices the asset above KTC Market
 *   - "aligned"          within the display threshold
 *   - "retail_only"      only KTC Market prices it (our model does not)
 *   - "consensus_only"   our model prices it, KTC Market does not
 *   - "unranked"         neither side is available
 *
 * The legacy `marketGapLabel` behavior (returning a raw string or null)
 * is preserved in `marketGapLabelLegacy` for back-compat with tests.
 */
// ── Model vs KTC Market: read, never recomputed (owner directive 2026-09-23) ──
//
// The market gap used to be rebuilt HERE from per-source value stamps —
// "retail" (KTC + Fantasy Navigator) against "consensus" (every other source)
// — a second, client-side market definition.  The owner ruled there is ONE
// market: canonical KTC MARKET (KTC's published Crowd+Trades), owned by the
// backend (`src/sources/ktc_market.py`), compared against OUR model value.
// The backend stamps `row.ktcMarket`, `marketGapDirection` and
// `marketGapValueRatio`; these helpers only format them.

const MARKET_LABEL = "KTC Market";

// ── IDPTC-vs-IDP-experts helpers (NOT the market) ──────────────────────
//
// Used ONLY by `idpMarketEdge` below — an explicitly NAMED alternate
// comparison ("IDPTC vs IDP-expert consensus", labelled with IDPTC on every
// surface).  It is not "the market": KTC Market prices no defenders, so an
// IDP row has no market benchmark and `marketEdge` says so.  Kept because
// the name travels with the number.
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

function relativeValueGap(retailValues, consensusValues) {
  const mean = (xs) => xs.reduce((s, v) => s + v, 0) / xs.length;
  const r = mean(retailValues);
  const c = mean(consensusValues);
  const scale = (r + c) / 2;
  if (!(scale > 0)) return null;
  return { ratio: (r - c) / scale, retailMean: r, consensusMean: c };
}

function _positive(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function _modelValue(row) {
  return _positive(row?.values?.full ?? row?.rankDerivedValue);
}

function _hasMarket(row) {
  const market = row?.ktcMarket;
  return !!market && market.available === true && _positive(market.normalizedValue) !== null;
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
  const model = _modelValue(row);
  const hasMarket = _hasMarket(row);
  if (!row || (model === null && !hasMarket)) {
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title: "Neither our model nor KTC Market prices this asset.",
    };
  }
  if (!hasMarket) {
    return {
      label: "no KTC market",
      css: "edge-none",
      kind: "consensus_only",
      title: `${MARKET_LABEL} does not price this asset, so there is no market to compare our model value against.`,
    };
  }
  if (model === null) {
    return {
      label: "KTC only",
      css: "edge-none",
      kind: "retail_only",
      title: `Only ${MARKET_LABEL} prices this asset — our model does not, so there is nothing to compare.`,
    };
  }
  const ratio = marketGapRatioOf(row);
  const direction = String(row?.marketGapDirection || "none");
  if (ratio === null) {
    return {
      label: "unpriced",
      css: "edge-none",
      kind: "unranked",
      title: "This payload carries no model-vs-market gap, so it cannot be measured.",
    };
  }
  const pct = pctText(ratio);
  if (ratio < MARKET_GAP_MIN_VALUE_RATIO || direction === "none") {
    return {
      label: "aligned",
      css: "edge-aligned",
      kind: "aligned",
      title: `Our model and ${MARKET_LABEL} value this asset within ${Math.round(MARKET_GAP_MIN_VALUE_RATIO * 100)}% of each other (actual difference: ${pct}).`,
    };
  }
  if (direction === "retail_premium") {
    return {
      label: `${MARKET_LABEL} higher by ${pct}`,
      css: "edge-retail",
      kind: "retail_higher",
      title: `${MARKET_LABEL} values this asset ~${pct} above our model.`,
    };
  }
  return {
    label: `Model higher by ${pct}`,
    css: "edge-consensus",
    kind: "consensus_higher",
    title: `Our model values this asset ~${pct} above ${MARKET_LABEL}.`,
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
      title: `${edge.title} Model > KTC Market → the market is undervaluing.`,
    };
  }
  if (edge.kind === "retail_higher") {
    return {
      label: "SELL",
      css: "edge-sell",
      kind: "sell",
      title: `${edge.title} KTC Market > model → the market is overvaluing.`,
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
      "Insufficient coverage to compare our model against KTC Market.",
  };
}

/**
 * Legacy string-only market gap label.  Retained for tests and any
 * consumer that still expects the old `"KTC +N"` / `"Consensus +N"` /
 * `null` contract.  New code should prefer `marketEdge()` which
 * returns an explicit structured object.
 */
export function marketGapLabel(row) {
  const edge = marketEdge(row);
  const ratio = marketGapRatioOf(row);
  if (ratio === null) return null;
  if (edge.kind === "retail_higher") return `${MARKET_LABEL} +${pctText(ratio)}`;
  if (edge.kind === "consensus_higher") return `Model +${pctText(ratio)}`;
  return null;
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
