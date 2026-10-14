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

/**
 * Re-derive "this player also headlines N other offers" over the cards the
 * page actually holds.  The server counts within one request, so after a
 * single-card regeneration its counts describe a set that no longer exists.
 * Counting only — no offer is re-ranked or re-priced.
 */
export function recomputeConcentration(result) {
  if (!result) return result;
  const usage = new Map();
  for (const card of result.opponents || []) {
    for (const a of card?.offer?.send || []) {
      usage.set(a.name, usage.has(a.name) ? usage.get(a.name) + 1 : 1);
    }
  }
  const opponents = (result.opponents || []).map((card) => {
    if (!card?.offer) return card;
    const also = {};
    for (const a of card.offer.send || []) {
      const n = usage.get(a.name);
      if (n > 1) also[a.name] = n - 1;
    }
    return { ...card, offer: { ...card.offer, outgoingAlsoOfferedTo: also } };
  });
  const outgoingConcentration = Object.fromEntries(
    [...usage.entries()]
      .filter(([, n]) => n > 1)
      .sort(([a], [b]) => a.localeCompare(b)),
  );
  return { ...result, opponents, outgoingConcentration };
}

/** Server order: qualified offers by score, then no-result cards by team. */
function serverOrder(a, b) {
  const qa = a?.offer ? 0 : 1;
  const qb = b?.offer ? 0 : 1;
  if (qa !== qb) return qa - qb;
  if (!qa) {
    const sa = Number.isFinite(a.offer.score) ? a.offer.score : -Infinity;
    const sb = Number.isFinite(b.offer.score) ? b.offer.score : -Infinity;
    if (sa !== sb) return sb - sa;
  }
  return String(a?.team || "").localeCompare(String(b?.team || ""));
}

/**
 * Replace one opponent's card in a full result (single-card regeneration),
 * keeping "best opportunity first" true for the cards the page now holds.
 */
export function mergeCards(result, fresh) {
  if (!result) return fresh;
  const byTeam = new Map((fresh?.opponents || []).map((o) => [o.team, o]));
  return recomputeConcentration({
    ...result,
    opponents: (result.opponents || [])
      .map((o) => byTeam.get(o.team) || o)
      .sort(serverOrder),
  });
}

/**
 * One line per approved calculator — a contrary COMPLETE verdict is shown,
 * never hidden behind the one that qualified.  The opponent may well check
 * the calculator that grades it a loss.
 */
export function verdictLines(offer) {
  return (offer?.externalAll || []).map((v) => {
    let text;
    if (v.coverage === "complete") {
      const result = v.result ? ` (${v.result} for them)` : "";
      text = `${v.label}: them ${fmtSignedPct(v.opponentMarginPct)}${result}`;
    } else if (v.coverage === "withheld") {
      text = `${v.label}: withheld as stale`;
    } else {
      text = `${v.label}: does not price every asset`;
    }
    return {
      calculator: v.calculator,
      text,
      qualifies: Boolean(v.qualifies),
      contrary: v.coverage === "complete" && v.result === "loss",
    };
  });
}

const FACTOR_LABELS = {
  mutualBalance: "Mutual balance",
  canonicalEdge: "Canonical edge",
  externalComfort: "Opponent comfort (external)",
  calculatorDivergence: "Board vs calculator disagreement (cost)",
  contraryCalculator: "Another calculator grades it a loss for them (cost)",
  lineupImpact: "Lineup impact",
  ourNeedFit: "Fits your needs",
  theirNeedFit: "Fits their needs",
  simplicity: "Simplicity",
  confidence: "Evidence confidence",
  forcedDropCost: "Forced release cost (cost)",
};

/** The declared-prior factors behind one offer, for the "how it ranked" list. */
export function factorRows(offer) {
  const factors = offer?.rankingFactors || {};
  const imputed = offer?.rankingImputations || {};
  return Object.keys(FACTOR_LABELS)
    .filter((k) => k in factors)
    .map((k) => {
      const v = factors[k];
      const known = Number.isFinite(v);
      const stand = Number.isFinite(imputed[k]) ? imputed[k] : null;
      return {
        key: k,
        label: FACTOR_LABELS[k],
        value: known ? v.toFixed(2) : UNKNOWN,
        note:
          !known && stand !== null
            ? `unknown — ranked as ${stand.toFixed(2)}, the worst known among the top offers`
            : !known
              ? "not available"
              : null,
      };
    });
}

/** A DOM id from a team name (team names carry spaces and punctuation). */
export function domId(prefix, name) {
  const slug = String(name ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  let h = 0;
  for (const ch of String(name ?? "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `${prefix}-${slug || "x"}-${h.toString(36)}`;
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
