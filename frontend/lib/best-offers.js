// Display helpers for Best Trade to Send Each Team (C7-BEST-TRADE).
//
// Pure: every number and verdict comes from POST /api/trade/best-offers.
// Nothing here qualifies, ranks or re-prices a trade.  Unknown values render
// as an explicit unknown, never as a zero.

export const UNKNOWN = "—";

export function fmtInt(v) {
  return Number.isFinite(v) ? Math.round(v).toLocaleString("en-US") : UNKNOWN;
}

export function fmtSignedInt(v) {
  if (!Number.isFinite(v)) return UNKNOWN;
  const n = Math.round(v);
  return `${n > 0 ? "+" : ""}${n.toLocaleString("en-US")}`;
}

export function fmtSignedPct(v) {
  if (!Number.isFinite(v)) return UNKNOWN;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function assetNames(assets) {
  return (assets || []).map((a) => a?.name).filter(Boolean);
}

/** One line a manager scans: what goes, what comes, and the two verdicts. */
export function summarizeCard(card) {
  const offer = card?.offer || null;
  if (!offer) {
    return {
      team: card?.team || "",
      qualified: false,
      label: card?.noResultLabel || "No qualifying trade found",
      detail: card?.noResultDetail || null,
    };
  }
  const ext = offer.external || {};
  return {
    team: card.team,
    qualified: true,
    send: assetNames(offer.send),
    receive: assetNames(offer.receive),
    packageSize: offer.packageSize || null,
    ourGap: Number.isFinite(offer?.canonical?.vaAdjustedGap)
      ? offer.canonical.vaAdjustedGap
      : null,
    ourMagnitude: offer?.canonical?.magnitude || null,
    calculator: ext.label || null,
    theirMarginPct: Number.isFinite(ext.opponentMarginPct)
      ? ext.opponentMarginPct
      : null,
    theirResult: ext.result || null,
    confidence: offer.confidence || null,
    score: Number.isFinite(offer.score) ? offer.score : null,
  };
}

/** Replace one opponent's card in a full result (single-card regeneration). */
export function mergeCards(result, fresh) {
  if (!result) return fresh;
  const byTeam = new Map((fresh?.opponents || []).map((o) => [o.team, o]));
  return {
    ...result,
    opponents: (result.opponents || []).map((o) => byTeam.get(o.team) || o),
  };
}

export function lineupLine(lineup) {
  if (!lineup) return null;
  if (!lineup.available) return "Lineup impact unavailable";
  const us = Number(lineup.ourDelta);
  const them = Number(lineup.theirDelta);
  if (!Number.isFinite(us) || !Number.isFinite(them)) return null;
  const s = (v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
  return `Starting lineup (rest of season): you ${s(us)}, them ${s(them)} pts`;
}

export function concentrationLine(offer) {
  const shared = offer?.outgoingAlsoOfferedTo || {};
  const entries = Object.entries(shared).filter(([, n]) => Number(n) > 0);
  if (!entries.length) return null;
  return entries
    .map(
      ([name, n]) =>
        `${name} also headlines ${n} other offer${n === 1 ? "" : "s"}`,
    )
    .join("; ");
}
