// ── Edge Detection Engine ────────────────────────────────────────────
// Ported from Static/js/runtime/20-data-and-calculator.js
// Computes buy/sell/hold signals by comparing each player's composite
// model rank percentile against an external market curve.

import { classifyPos, normalizePos } from "./dynasty-data";

const MIN_EDGE_PCT = 15;
const IDP_CONF_FLOOR_WITH_IDP_TC = 0.50;

function clamp(n, lo, hi) {
  if (!Number.isFinite(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}

function rankToPercentile(rank, total) {
  if (!Number.isFinite(rank) || !Number.isFinite(total) || total <= 0) return 0;
  if (total <= 1) return 1;
  return 1 - (rank - 1) / (total - 1);
}

function projectPercentileToCurve(sortedDesc, percentile) {
  const vals = (Array.isArray(sortedDesc) ? sortedDesc : [])
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v) && v > 0);
  if (!vals.length) return null;
  if (vals.length === 1) return vals[0];
  const pct = clamp(Number(percentile), 0, 1);
  const idx = (1 - pct) * (vals.length - 1);
  const lo = Math.max(0, Math.min(vals.length - 1, Math.floor(idx)));
  const hi = Math.max(0, Math.min(vals.length - 1, Math.ceil(idx)));
  if (lo === hi) return vals[lo];
  const t = idx - lo;
  return vals[lo] + (vals[hi] - vals[lo]) * t;
}

function rankMapFromSorted(items, valueKey) {
  const map = new Map();
  let prev = null;
  let prevRank = 0;
  items.forEach((item, idx) => {
    const v = Number(item?.[valueKey]);
    const same = prev !== null && Number.isFinite(v) && Number.isFinite(prev) && v === prev;
    const rank = same ? prevRank : idx + 1;
    map.set(item.name, rank);
    prev = v;
    prevRank = rank;
  });
  return map;
}

function marketSourceForClass(assetClass) {
  if (assetClass === "idp") return { key: "idpTradeCalc", label: "IDP TC" };
  return { key: "ktc", label: "KTC" };
}

function confidenceLabel(score) {
  if (score >= 0.72) return "HIGH";
  if (score >= 0.52) return "MED";
  return "LOW";
}

function computeEdgeConfidence(row, curveSize, comparable) {
  const ac = row.assetClass || "offense";
  const expected = ac === "idp" ? 3 : ac === "pick" ? 2 : 8;
  const siteNorm = clamp((Number(row.siteCount) || 0) / Math.max(1, expected), 0, 1);
  const curveNorm = clamp((curveSize - 20) / 180, 0, 1);
  const comparableBonus = comparable ? 0.2 : 0;
  const hasIdpTC =
    ac === "idp" &&
    row.marketKey === "idpTradeCalc" &&
    Number.isFinite(row.actualExternal) &&
    row.actualExternal > 0;
  let score = 0.45 * siteNorm + 0.35 * curveNorm + comparableBonus;
  if (!comparable) score -= 0.1;
  score = clamp(score, 0, 1);
  if (hasIdpTC) score = Math.max(score, IDP_CONF_FLOOR_WITH_IDP_TC);
  return {
    score,
    label: confidenceLabel(score),
    high: score >= 0.72 && (comparable || hasIdpTC),
  };
}

/**
 * Build edge projection data from dynasty-data rows.
 * Returns array of edge rows with signal, edgePct, valueEdge, etc.
 */
export function buildEdgeProjection(rows) {
  // Build edge rows from the dynasty-data rows
  const edgeRows = [];
  for (const r of rows) {
    if (!r.pos || r.pos === "?" || r.pos === "K") continue;
    const modelValue = r.values?.full || 0;
    if (modelValue <= 0) continue;

    const assetClass = r.assetClass || classifyPos(r.pos);
    const market = marketSourceForClass(assetClass);
    const extRaw = Number(r.canonicalSites?.[market.key]);
    const actualExternal = Number.isFinite(extRaw) && extRaw > 0 ? Math.round(extRaw) : null;

    // Count IDP sources for IDP players
    const idpKeys = ["idpTradeCalc", "pffIdp", "fantasyProsIdp", "draftSharksIdp", "dlfIdp", "dlfRidp"];
    const idpSiteCount = assetClass === "idp"
      ? idpKeys.reduce((n, k) => {
          const v = Number(r.canonicalSites?.[k]);
          return n + (Number.isFinite(v) && v > 0 ? 1 : 0);
        }, 0)
      : r.siteCount || 0;

    edgeRows.push({
      name: r.name,
      pos: r.pos,
      assetClass,
      marketKey: market.key,
      marketLabel: market.label,
      modelValue: Math.round(modelValue),
      actualExternal,
      siteCount: idpSiteCount,
      row: r, // keep ref for popup
    });
  }

  // Split into universes
  const universes = {
    offense: edgeRows.filter((r) => r.assetClass === "offense"),
    idp: edgeRows.filter((r) => r.assetClass === "idp"),
    pick: edgeRows.filter((r) => r.assetClass === "pick"),
  };
  const minCurveSizes = { offense: 40, idp: 30, pick: 24 };

  for (const [klass, universe] of Object.entries(universes)) {
    // Model rank (all players in class)
    const modelSorted = [...universe].sort((a, b) => b.modelValue - a.modelValue || a.name.localeCompare(b.name));
    const modelRankAll = rankMapFromSorted(modelSorted, "modelValue");
    const modelTotal = modelSorted.length;

    // External-covered subset
    const externalSorted = universe
      .filter((r) => Number.isFinite(r.actualExternal) && r.actualExternal > 0)
      .sort((a, b) => b.actualExternal - a.actualExternal || a.name.localeCompare(b.name));

    const modelComparableSorted = [...externalSorted].sort((a, b) => b.modelValue - a.modelValue || a.name.localeCompare(b.name));
    const modelRankComparable = rankMapFromSorted(modelComparableSorted, "modelValue");
    const modelComparableTotal = modelComparableSorted.length;
    const externalRank = rankMapFromSorted(externalSorted, "actualExternal");
    const externalCurve = externalSorted.map((r) => r.actualExternal);

    const curveTooSmall = externalCurve.length < (minCurveSizes[klass] || 20);

    for (const row of universe) {
      const mRankComparable = modelRankComparable.get(row.name) || null;
      const mRankAll = modelRankAll.get(row.name) || modelTotal;
      const mRank = mRankComparable || mRankAll;
      const mPct = rankToPercentile(mRank, mRankComparable ? modelComparableTotal : modelTotal);
      const projRaw = curveTooSmall ? null : projectPercentileToCurve(externalCurve, mPct);
      const projected = Number.isFinite(projRaw) && projRaw > 0 ? Math.round(projRaw) : null;
      const eRank = externalRank.get(row.name) || null;

      const comparable =
        !curveTooSmall &&
        Number.isFinite(row.actualExternal) &&
        row.actualExternal > 0 &&
        Number.isFinite(projected) &&
        projected > 0;

      const valueEdge = comparable ? projected - row.actualExternal : null;
      const edgePct = comparable ? (valueEdge / row.actualExternal) * 100 : null;
      const rankEdge = comparable && eRank ? eRank - mRank : null;
      const conf = computeEdgeConfidence(row, externalCurve.length, comparable);

      const absPct = Math.abs(Number(edgePct) || 0);
      const absVal = Math.abs(Number(valueEdge) || 0);
      const valThreshold = Math.max(120, (Number(row.actualExternal) || 0) * 0.04);
      let signal = "HOLD";
      if (comparable && conf.score >= 0.45 && absPct >= MIN_EDGE_PCT && absVal >= valThreshold) {
        signal = valueEdge > 0 ? "BUY" : "SELL";
      }

      row.modelRank = mRank;
      row.externalRank = eRank;
      row.projected = projected;
      row.valueEdge = valueEdge;
      row.edgePct = edgePct;
      row.rankEdge = rankEdge;
      row.signal = signal;
      row.confidenceScore = conf.score;
      row.confidenceLabel = conf.label;
      row.comparable = comparable;
    }
  }

  return edgeRows;
}
