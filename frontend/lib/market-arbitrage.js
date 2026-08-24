// Canonical market-arbitrage helpers.
//
// This module answers a different question from source disagreement:
// "How far is OUR canonical value from the public transaction market a trade
// partner is likely to consult?"
//
// Offense -> KeepTradeCut SF/TEP (ktcSfTep)
// IDP     -> IDP Trade Calculator (idpTradeCalc)
//
// No ranking or valuation math is recreated here. `ourValue` is read from the
// backend-authored canonical board value already materialized on the row, and
// public values are read from backend-authored canonicalSiteValues. Missing
// public values remain missing; they are never coerced to zero.

export const ARBITRAGE_MIN_EDGE = 0.05;
export const ARBITRAGE_STRONG_EDGE = 0.15;
export const ARBITRAGE_INTERNAL_MARGIN = 0.10;
export const ARBITRAGE_PUBLIC_FRIENDLY_PREMIUM = 0.05;

const PUBLIC_MARKETS = {
  offense: { key: "ktcSfTep", label: "KTC" },
  idp: { key: "idpTradeCalc", label: "IDP Trade Calculator" },
};

function finitePositive(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function publicMarketFor(row) {
  return PUBLIC_MARKETS[row?.assetClass] || null;
}

export function canonicalValueOf(row) {
  return finitePositive(row?.values?.full ?? row?.rankDerivedValue);
}

export function publicMarketValueOf(row) {
  const market = publicMarketFor(row);
  if (!market) return null;
  const sites = row?.canonicalSites;
  if (!sites || typeof sites !== "object") return null;
  return finitePositive(sites[market.key]);
}

export function arbitrageDescriptor(row) {
  if (!row || row.quarantined) return null;
  const market = publicMarketFor(row);
  if (!market) return null;

  const ourValue = canonicalValueOf(row);
  const marketValue = publicMarketValueOf(row);
  if (ourValue === null || marketValue === null) return null;

  const edgePoints = ourValue - marketValue;
  const edgeRatio = edgePoints / marketValue;
  const magnitude = Math.abs(edgeRatio);

  let action = "hold";
  if (edgeRatio >= ARBITRAGE_STRONG_EDGE) action = "strong_buy";
  else if (edgeRatio >= ARBITRAGE_MIN_EDGE) action = "buy";
  else if (edgeRatio <= -ARBITRAGE_STRONG_EDGE) action = "strong_sell";
  else if (edgeRatio <= -ARBITRAGE_MIN_EDGE) action = "sell";

  // A trade-partner-friendly budget: pay 5% above the public market while
  // retaining at least a 10% internal edge.  If our edge is not wide enough to
  // satisfy both conditions, this is null rather than pretending there is a
  // win-win construction.
  const publicFriendlyTarget = marketValue * (1 + ARBITRAGE_PUBLIC_FRIENDLY_PREMIUM);
  const internalEdgeCeiling = ourValue / (1 + ARBITRAGE_INTERNAL_MARGIN);
  const publicFriendlyOfferCeiling = Math.floor(
    Math.min(publicFriendlyTarget, internalEdgeCeiling),
  );
  const publicWinRatio = publicFriendlyOfferCeiling / marketValue - 1;
  const internalWinRatio = ourValue / publicFriendlyOfferCeiling - 1;
  const winWin =
    edgeRatio > 0 &&
    publicWinRatio >= 0.03 &&
    internalWinRatio >= ARBITRAGE_INTERNAL_MARGIN;

  return {
    action,
    marketKey: market.key,
    marketLabel: market.label,
    ourValue,
    marketValue,
    edgePoints,
    edgeRatio,
    magnitude,
    winWin,
    publicFriendlyOfferCeiling: winWin ? publicFriendlyOfferCeiling : null,
    publicWinRatio: winWin ? publicWinRatio : null,
    internalWinRatio: winWin ? internalWinRatio : null,
  };
}

export function buildArbitrageRows(rows, {
  action = "all",
  assetClass = "all",
  minEdge = ARBITRAGE_MIN_EDGE,
  search = "",
} = {}) {
  const needle = String(search || "").trim().toLowerCase();
  return (rows || [])
    .map((row) => ({ row, edge: arbitrageDescriptor(row) }))
    .filter(({ row, edge }) => {
      if (!edge) return false;
      if (edge.magnitude < minEdge) return false;
      if (assetClass !== "all" && row.assetClass !== assetClass) return false;
      if (action === "buy" && !["buy", "strong_buy"].includes(edge.action)) return false;
      if (action === "sell" && !["sell", "strong_sell"].includes(edge.action)) return false;
      if (action === "winwin" && !edge.winWin) return false;
      if (needle && !String(row.name || "").toLowerCase().includes(needle)) return false;
      return true;
    })
    .sort((a, b) => {
      if (b.edge.magnitude !== a.edge.magnitude) return b.edge.magnitude - a.edge.magnitude;
      return (a.row.rank ?? Infinity) - (b.row.rank ?? Infinity);
    });
}
