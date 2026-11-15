// Canonical market-arbitrage helpers.
//
// This module answers a different question from source disagreement:
// "How far is OUR canonical value from the public transaction market a trade
// partner is likely to consult?"
//
// Offense -> KTC MARKET: KTC's published Crowd+Trades SF/TE++ value
//            (ktcCrowdTradesSfTep) — the one canonical market owner
//            (src/sources/ktc_market.py), benchmark-only, never a model input
// IDP     -> IDP Trade Calculator (idpTradeCalc)
//
// No ranking or valuation math is recreated here. `ourValue` is read from the
// backend-authored canonical board value already materialized on the row, and
// public values are read from backend-authored canonicalSiteValues. Missing
// public values remain missing; they are never coerced to zero.

import { playerScopeGroup, qualityLimit } from "@/lib/trade-discovery";

export const ARBITRAGE_MIN_EDGE = 0.05;
export const ARBITRAGE_STRONG_EDGE = 0.15;
export const ARBITRAGE_INTERNAL_MARGIN = 0.10;
export const ARBITRAGE_PUBLIC_FRIENDLY_PREMIUM = 0.05;

const PUBLIC_MARKETS = {
  offense: { key: "ktcCrowdTradesSfTep", label: "KTC" },
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

/**
 * Player-level arbitrage rows, filtered and sorted.
 *
 * Owner directive 2026-10-18 adds, all over BACKEND-STAMPED fields (no value
 * or rank is recomputed here):
 *   targetQuality  "top100" | "top250" | "top500" | "all" — canonical overall
 *                  rank (canonicalConsensusRank, never the display ordinal);
 *                  an unranked row is outside every narrowed level
 *   minValue       minimum canonical value (rankDerivedValue)
 *   scope          "both" | "offense" | "defense" — via the shared vocabulary;
 *                  a missing/ambiguous position is excluded from both narrowed
 *                  modes (never treated as offense)
 *   sort           "percentage" (legacy default) | "absolute" | "rank"
 * A row with no public market price stays out (missing is never zero).
 */
export function buildArbitrageRows(rows, {
  action = "all",
  assetClass = "all",
  minEdge = ARBITRAGE_MIN_EDGE,
  search = "",
  targetQuality = "all",
  minValue = null,
  scope = "both",
  sort = "percentage",
} = {}) {
  const needle = String(search || "").trim().toLowerCase();
  const limit = qualityLimit(targetQuality);
  const floor = Number(minValue);
  const hasFloor = Number.isFinite(floor) && floor > 0;
  const rankOf = (row) => {
    const r = Number(row?.canonicalConsensusRank);
    return Number.isInteger(r) && r > 0 ? r : null;
  };
  return (rows || [])
    .map((row) => ({ row, edge: arbitrageDescriptor(row) }))
    .filter(({ row, edge }) => {
      if (!edge) return false;
      if (edge.magnitude < minEdge) return false;
      if (assetClass !== "all" && row.assetClass !== assetClass) return false;
      if (scope !== "both" && playerScopeGroup(row.pos) !== scope) return false;
      if (limit !== null) {
        const r = rankOf(row);
        if (r === null || r > limit) return false;
      }
      if (hasFloor && edge.ourValue < floor) return false;
      if (action === "buy" && !["buy", "strong_buy"].includes(edge.action)) return false;
      if (action === "sell" && !["sell", "strong_sell"].includes(edge.action)) return false;
      if (action === "winwin" && !edge.winWin) return false;
      if (needle && !String(row.name || "").toLowerCase().includes(needle)) return false;
      return true;
    })
    .sort((a, b) => {
      const ra = rankOf(a.row) ?? Infinity;
      const rb = rankOf(b.row) ?? Infinity;
      if (sort === "rank") {
        if (ra !== rb) return ra - rb;
        return b.edge.magnitude - a.edge.magnitude;
      }
      if (sort === "absolute") {
        const da = Math.abs(a.edge.edgePoints);
        const db = Math.abs(b.edge.edgePoints);
        if (db !== da) return db - da;
        return ra - rb;
      }
      if (b.edge.magnitude !== a.edge.magnitude) return b.edge.magnitude - a.edge.magnitude;
      return (a.row.rank ?? Infinity) - (b.row.rank ?? Infinity);
    });
}


// ── Roster capacity, as words (Wave B / C3-CAP-01) ───────────────────────
// Labels only: every count and cost is the backend's (src/trade/roster_capacity).

/** One line describing what a trade does to a roster's legality. */
export function rosterCapacityLine(capacity) {
  if (!capacity || typeof capacity !== "object") return null;
  if (capacity.unavailable) return "roster capacity unavailable";
  const drops = Array.isArray(capacity.forcedDrops) ? capacity.forcedDrops : [];
  if (capacity.requiresDrops === null || capacity.requiresDrops === undefined) {
    return capacity.rosterLimit == null
      ? "roster limit unknown"
      : "may need a release (taxi occupancy unknown)";
  }
  if (!capacity.requiresDrops) return "fits — no release needed";
  const names = drops.map((d) => d.name).filter(Boolean);
  const upper = capacity.forcedDropsAreUpperBound ? " at most" : "";
  const who = names.length ? `: ${names.join(", ")}` : "";
  return `must release${upper} ${drops.length}${who}`;
}
