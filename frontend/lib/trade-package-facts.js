/**
 * trade-package-facts — descriptive facts about the packages already on
 * /trade (TC-B2: TCM-M01 stacked value bars, TCM-M02 asset identity,
 * TCM-M04 Quick Trade Facts, TCM-M05 value dispersion;
 * docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md TC-11, TC-12,
 * TC-14, TC-15).
 *
 * PURE PRESENTATION ARITHMETIC over numbers the page already holds:
 *   - an asset's value is `effectiveValue` (lib/trade-logic) -- the same
 *     per-copy number the side totals sum, override included;
 *   - Value Adjustment is the side's `adjustment` from the page's
 *     `sideTotals` (packageAdjustPair / multiAdjustedSideTotals), never
 *     recomputed here;
 *   - ranks are the backend-stamped `canonicalConsensusRank` only (never the
 *     frontend display ordinal).
 *
 * Nothing here grades, ranks or recommends.  MISSING IS NEVER ZERO: an
 * unpriced asset is counted as a piece and named, never averaged as 0; an
 * average with no applicable member is `null`, and every average says how
 * many members it covers.
 */

import { effectiveValue } from "@/lib/trade-logic";
import { groupSideEntries, tradeEntryLabel } from "@/lib/trade-assets";

/** Distinct chart series in fixed order (components/ds/token-contract.js). */
export const IDENTITY_SERIES_LIMIT = 6;

/**
 * Presentation identity for every LINE in the trade (TC-12): a stable marker
 * number in order of first appearance (side order, then line order) and a
 * chart series.  The first IDENTITY_SERIES_LIMIT lines take the fixed series
 * --chart-1..6; later lines share the neutral "other" series and keep their
 * marker, so identity never rests on colour alone.  The same line on two
 * sides keeps one identity.  Never persisted -- it is recomputed per trade.
 * @returns {Map<string, {marker: number, series: number|null, label: string}>}
 */
export function tradeAssetIdentities(sides) {
  const out = new Map();
  for (const side of Array.isArray(sides) ? sides : []) {
    for (const g of groupSideEntries(side?.assets)) {
      if (out.has(g.key)) continue;
      const marker = out.size + 1;
      out.set(g.key, {
        marker,
        series: marker <= IDENTITY_SERIES_LIMIT ? marker : null,
        label: tradeEntryLabel(g.entry),
      });
    }
  }
  return out;
}

const isPick = (e) => e?.assetClass === "pick" || e?.pos === "PICK";

/** Per-copy value, or null when the board does not price it (and no override does). */
export function assetCopyValue(entry, valueMode) {
  const v = Number(effectiveValue(entry, valueMode, null));
  return Number.isFinite(v) && v > 0 ? v : null;
}

function mean(values) {
  return values.length ? values.reduce((s, v) => s + v, 0) / values.length : null;
}

/**
 * Quick Trade Facts for ONE side (TC-14).  Counts are per COPY: three copies
 * of a generic pick are three pieces.
 * @returns {{
 *   pieces: number, players: number, picks: number,
 *   rawPriced: number, pricedPieces: number, unpriced: string[],
 *   averageValue: number|null,
 *   averageAge: number|null, agedPlayers: number,
 *   averageRank: number|null, rankedPieces: number,
 * }}
 */
export function sidePackageFacts(assets, valueMode) {
  const list = Array.isArray(assets) ? assets : [];
  const values = [];
  const unpriced = [];
  const ages = [];
  const ranks = [];
  let players = 0;
  let picks = 0;
  for (const entry of list) {
    if (isPick(entry)) picks += 1;
    else players += 1;
    const v = assetCopyValue(entry, valueMode);
    if (v == null) {
      const name = tradeEntryLabel(entry);
      if (!unpriced.includes(name)) unpriced.push(name);
    } else {
      values.push(v);
    }
    if (!isPick(entry)) {
      const age = Number(entry?.age);
      if (Number.isFinite(age) && age > 0) ages.push(age);
    }
    const rank = Number(entry?.canonicalConsensusRank);
    if (Number.isInteger(rank) && rank > 0) ranks.push(rank);
  }
  return {
    pieces: list.length,
    players,
    picks,
    rawPriced: values.reduce((s, v) => s + v, 0),
    pricedPieces: values.length,
    unpriced,
    averageValue: mean(values),
    averageAge: mean(ages),
    agedPlayers: ages.length,
    averageRank: mean(ranks),
    rankedPieces: ranks.length,
  };
}

/**
 * How concentrated one side's priced value is (TC-15), over every priced
 * COPY.  Two standard, explainable statistics -- no threshold, no label, no
 * better/worse reading (no validated decision rule exists):
 *   - topShare:       the largest single piece's share of the side's value;
 *   - effectiveCount: (Σv)² / Σv², the inverse Herfindahl index -- "this
 *                     package behaves like N equal pieces".
 * `null` when nothing on the side is priced.
 * @returns {{topShare: number, effectiveCount: number, pricedPieces: number}|null}
 */
export function valueConcentration(assets, valueMode) {
  const values = (Array.isArray(assets) ? assets : [])
    .map((e) => assetCopyValue(e, valueMode))
    .filter((v) => v != null);
  if (!values.length) return null;
  const total = values.reduce((s, v) => s + v, 0);
  const sumSq = values.reduce((s, v) => s + v * v, 0);
  return {
    topShare: Math.max(...values) / total,
    effectiveCount: (total * total) / sumSq,
    pricedPieces: values.length,
  };
}

/**
 * The segments of one side's stacked value bar (TC-11): one per LINE (all its
 * copies), sized by raw canonical value, in line order, then the side's Value
 * Adjustment as its own segment.  Unpriced lines carry `value: null` and no
 * width -- they are listed, never drawn as 0-width "worthless" pieces.
 * @param {object[]} assets   the side's entries
 * @param {number}   adjustment  the side's VA from the page's sideTotals
 * @param {Map}      identities  tradeAssetIdentities(sides)
 */
export function sideValueSegments(assets, adjustment, valueMode, identities) {
  const segments = groupSideEntries(assets).map((g) => {
    const per = assetCopyValue(g.entry, valueMode);
    const id = identities?.get(g.key) || null;
    return {
      key: g.key,
      kind: "asset",
      label: tradeEntryLabel(g.entry),
      count: g.count,
      value: per == null ? null : per * g.count,
      marker: id?.marker ?? null,
      series: id?.series ?? null,
    };
  });
  const va = Number(adjustment);
  if (Number.isFinite(va) && va > 0) {
    segments.push({
      key: "__value_adjustment__",
      kind: "va",
      label: "Value Adjustment",
      count: 1,
      value: va,
      marker: null,
      series: null,
    });
  }
  return segments;
}
