/**
 * second-opinions-rows — assemble one Second Opinions row per vendor for a
 * trade, and word the independent / modeled tallies.
 *
 * Extracted from `components/trade/TradeSourceBreakdown.jsx` (TC-B /
 * TCM-K03) so the per-source table AND the immediate one-glance tally beside
 * the meter read the SAME rows: one assembly, never two.  The opinion
 * semantics (resolution, states, the even band, the one-vote-per-family
 * tally) stay owned by `lib/second-opinions.js`; this file only groups the
 * registry by vendor and calls that owner.
 */

import { RANKING_SOURCES, SOURCE_VENDOR_LABELS, vendorForSource } from "./dynasty-data.js";
import {
  evaluateAlternateOpinion,
  evaluateOpinion,
  resolveOpinionAsset,
  tallyOpinions,
} from "./second-opinions.js";
import { tradeRoutes, valueAdjustmentFromSideArrays } from "./trade-logic.js";

/**
 * One row per vendor: `{key, family, label, displayName, signal, opinion}`.
 * Empty when no side holds an asset.  `sides` are BARE (`{label, assets}`):
 * a manual override changes the user's headline, never what a source sees.
 *
 * `opts.compareModelId` (owner directive 2026-10-19): also evaluate each row
 * under that package model — the SAME per-asset resolutions, a second whole-
 * package evaluation — and attach it as `row.comparison`.  `row.opinion` (and
 * so every tally) is identical whether or not it is asked for.
 */
export function buildOpinionRows(sides, opts = {}) {
  const compareModelId = opts.compareModelId || null;
  const compareAdjust = compareModelId
    ? (sideValues) => valueAdjustmentFromSideArrays(sideValues, { modelId: compareModelId })
    : null;
  const assetsBySide = (sides || []).map((s) => s?.assets || []);
  if (!assetsBySide.some((a) => a.length > 0)) return [];
  // 3+ teams: the package adjustment is per team, in that team's own
  // perspective, so it needs each line's destination (spec
  // docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1).  Two sides route implicitly.
  const routes = assetsBySide.length > 2 ? tradeRoutes(sides) : null;
  const activeAdjust = routes
    ? (sideValues) => valueAdjustmentFromSideArrays(sideValues, { routes })
    : valueAdjustmentFromSideArrays;
  const vendorOrder = [];
  const vendorSubs = new Map();
  for (const src of RANKING_SOURCES) {
    const vendor = vendorForSource(src.key);
    if (!vendorSubs.has(vendor)) {
      vendorSubs.set(vendor, []);
      vendorOrder.push(vendor);
    }
    vendorSubs.get(vendor).push(src);
  }
  return vendorOrder.map((vendor) => {
    const subs = vendorSubs.get(vendor);
    const mainSubs = subs.filter((s) => !s.needsRookieTranslation);
    const rookieSubs = subs.filter((s) => s.needsRookieTranslation);
    const resolutionsBySide = assetsBySide.map((assets) =>
      assets.map((row) => ({
        name: row?.name || "Unknown asset",
        ...resolveOpinionAsset({ row, mainSubs, rookieSubs }),
      })),
    );
    const opinion = evaluateOpinion(resolutionsBySide, activeAdjust);
    const primary = subs[0];
    const comparison = compareAdjust
      ? {
          modelId: compareModelId,
          ...evaluateAlternateOpinion(resolutionsBySide, opinion, compareAdjust),
        }
      : undefined;
    return {
      key: vendor,
      family: primary.correlationGroup || vendor,
      label: SOURCE_VENDOR_LABELS[vendor] || primary.columnLabel || primary.displayName || vendor,
      displayName: SOURCE_VENDOR_LABELS[vendor]
        ? subs.map((s) => s.displayName || s.key).join(" + ")
        : primary.displayName || primary.key,
      signal: subs.every((s) => s.isRankSignal === false)
        ? "vendor value"
        : "translated rank (modeled)",
      opinion,
      ...(comparison ? { comparison } : {}),
    };
  });
}

/** The tally for a trade's rows (thin pass-through to the owner). */
export function opinionTally(rows, sideCount) {
  return tallyOpinions(rows, sideCount);
}

/** "Side A 5 · Side B 3 · Even 1 · Split 1" for one tally half. */
export function opinionTallyText(t, sideLabels) {
  return [
    ...sideLabels.map((lbl, i) => `Side ${lbl} ${t.wins[i]}`),
    t.even ? `Even ${t.even}` : null,
    t.split ? `Split ${t.split}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Plain coverage words for the immediate tally line: how many independent
 * families priced every piece, out of how many priced anything, and how many
 * source rows are incomplete.  Counts only — no winner.
 */
export function opinionCoverageText(tally) {
  const ind = tally?.independent || { families: 0, eligible: 0 };
  const counts = tally?.counts || {};
  const parts = [`${ind.families} of ${ind.eligible} source families priced every piece`];
  if (counts.incomplete) {
    parts.push(`${counts.incomplete} source${counts.incomplete === 1 ? "" : "s"} incomplete`);
  }
  // Decision 9: an excluded source is named as unavailable -- never a vote,
  // never "even", never folded into the coverage it could not give.
  if (counts.unavailable) {
    parts.push(`${counts.unavailable} source${counts.unavailable === 1 ? "" : "s"} unavailable`);
  }
  return parts.join(" · ");
}
