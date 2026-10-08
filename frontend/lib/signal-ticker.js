/**
 * signal-ticker — PRESENTATION rules for the homepage Buy/Sell ticker
 * (C6-SIG-02, issue #784, inventory 4.3).
 *
 * The one owner of Buy/Sell is the C6-SIG-01 reconciler
 * (`GET /api/signals/reconciled`, `src/signals/reconciler.py`).  This module
 * decides nothing about a player's verdict.  It only applies the owner's
 * presentation rule the reconciler deliberately leaves to its consumer:
 *
 *   * BUY items may be global — any player the reconciler publishes in state
 *     `directional_buy_only`;
 *   * SELL items ONLY for players on the SELECTED team's roster, where
 *     membership is the reconciler's own `roster.playerKeys` (one identity
 *     join, server-side — never a name match in the browser), and only when
 *     the payload's resolved team IS the selected team;
 *   * a `conflict` is shown as a conflict, never as its BUY or SELL half — and
 *     only for a rostered player, because its SELL half is a sell call;
 *   * a `withheld` player never appears;
 *   * no team selected → no SELL items, stated rather than implied;
 *   * picks are never SELL items (#784).
 *
 * No score, threshold, blend or vote count is computed here.  Lineage text is
 * read from the payload's own `agreement` / `conflict` blocks.  Order is the
 * contract's backend-stamped `canonicalConsensusRank` (rank-less sinks), the
 * same stamp `buildRows` orders by — a display order, not a ranking.
 */

export const RECONCILED_STATES = Object.freeze({
  WITHHELD: "withheld",
  CONFLICT: "conflict",
  BUY_ONLY: "directional_buy_only",
  SELL_ONLY: "directional_sell_only",
  NONE: "no_directional_signal",
});

/** Why the SELL lane is (or is not) showing — one stated reason. */
export const SELL_SCOPE = Object.freeze({
  ROSTER: "roster",
  NO_TEAM: "no_team",
  TEAM_NOT_FOUND: "team_not_found",
  TEAM_MISMATCH: "team_mismatch",
  ROSTER_UNAVAILABLE: "roster_unavailable",
});

// Display words for the reconciler's own `domain` field.  Labels only; an
// unknown domain renders verbatim rather than being mapped to a guess.
const DOMAIN_LABELS = {
  market_momentum: "Momentum",
  fundamental: "Fundamentals",
  consensus: "Consensus Edge",
  sharp: "Sharp",
};

export function domainLabel(domain) {
  return DOMAIN_LABELS[domain] || String(domain || "unknown");
}

function sameTeam(payloadTeam, selectedTeam) {
  if (!payloadTeam || !selectedTeam) return false;
  const a = String(payloadTeam.ownerId || "");
  const b = String(selectedTeam.ownerId || "");
  if (a && b) return a === b;
  // Neither side carries an owner id: the request was made by name.
  if (!a && !b) {
    const na = String(payloadTeam.name || "").trim().toLowerCase();
    const nb = String(selectedTeam.name || "").trim().toLowerCase();
    return Boolean(na) && na === nb;
  }
  return false;
}

/** The SELL scope for this payload + selection, with the roster set. */
export function sellScopeFor(payload, selectedTeam) {
  if (!selectedTeam) return { state: SELL_SCOPE.NO_TEAM, rosterKeys: null };
  if (payload?.teamResolution?.reason === "team_not_found") {
    return { state: SELL_SCOPE.TEAM_NOT_FOUND, rosterKeys: null };
  }
  // Never another team's roster: the payload must be FOR the selected team.
  if (!sameTeam(payload?.team, selectedTeam)) {
    return { state: SELL_SCOPE.TEAM_MISMATCH, rosterKeys: null };
  }
  const keys = payload?.roster?.playerKeys;
  if (!Array.isArray(keys)) return { state: SELL_SCOPE.ROSTER_UNAVAILABLE, rosterKeys: null };
  return { state: SELL_SCOPE.ROSTER, rosterKeys: new Set(keys) };
}

/**
 * Lineage, read off the payload.  `count` is how many kept (deduplicated)
 * verdicts point this way; `independent` is the reconciler's own flag
 * (`null` for a single verdict — independence of one opinion is not a
 * question).  Collapsed restatements are reported, not counted.
 */
export function lineageFor(player, kind) {
  if (kind === "conflict") {
    const c = player?.conflict || {};
    const shared = Array.isArray(c.sharedAncestry) ? c.sharedAncestry : [];
    return {
      kind,
      buyCount: Array.isArray(c.buy) ? c.buy.length : 0,
      sellCount: Array.isArray(c.sell) ? c.sell.length : 0,
      sharedAncestry: shared,
      independent: shared.length === 0,
      domains: [...(c.buy || []), ...(c.sell || [])].map((s) => s.domain),
      collapsed: Array.isArray(player?.collapsed) ? player.collapsed.length : 0,
    };
  }
  const dir = kind === "sell" ? "sell" : "buy";
  const agreement = player?.agreement?.[dir] || null;
  const signals = (player?.signals || []).filter((s) => s?.direction === dir);
  return {
    kind,
    count: agreement ? agreement.emitters.length : signals.length,
    independent: agreement ? agreement.independent === true : null,
    sharedAncestry: agreement ? agreement.sharedAncestry || [] : [],
    domains: signals.map((s) => s.domain),
    collapsed: Array.isArray(player?.collapsed) ? player.collapsed.length : 0,
  };
}

/** Short, honest lineage text for a ticker slot. */
export function lineageText(lineage) {
  if (!lineage) return "";
  if (lineage.kind === "conflict") {
    const head = `${lineage.buyCount} buy vs ${lineage.sellCount} sell`;
    return lineage.independent ? `${head} · independent` : `${head} · shared lineage`;
  }
  if (lineage.count <= 1) {
    const [domain] = lineage.domains;
    return `1 signal · ${domainLabel(domain)}`;
  }
  return lineage.independent
    ? `${lineage.count} independent signals`
    : `${lineage.count} signals · shared lineage`;
}

function rankOf(player) {
  const r = player?.board?.canonicalConsensusRank;
  return Number.isInteger(r) && r > 0 ? r : null;
}

function byBoardRank(a, b) {
  const ra = rankOf(a.player);
  const rb = rankOf(b.player);
  if (ra != null && rb != null && ra !== rb) return ra - rb;
  if (ra != null && rb == null) return -1;
  if (ra == null && rb != null) return 1;
  return String(a.name).localeCompare(String(b.name));
}

function itemFor(player, kind) {
  return {
    kind,
    key: `${kind}:${player.playerKey}`,
    playerKey: player.playerKey,
    name: player.displayName || player.playerKey,
    position: player?.board?.position || null,
    lineage: lineageFor(player, kind),
    player,
  };
}

/**
 * Select the ticker's verdict items.
 *
 * Returns `{ items, sellScope, counts }`.  Roster items (SELL, CONFLICT) come
 * first — they are the few that concern the selected team — then BUYs, each
 * group in board-rank order, BUYs capped at `buyLimit`.
 */
export function selectTickerVerdicts(payload, { selectedTeam = null, buyLimit = 20 } = {}) {
  const players = Array.isArray(payload?.players) ? payload.players : [];
  const scope = sellScopeFor(payload, selectedTeam);
  const counts = {
    buy: 0,
    sell: 0,
    conflict: 0,
    withheld: 0,
    sellOffRoster: 0,
    conflictOffRoster: 0,
  };
  const buys = [];
  const rosterItems = [];
  for (const player of players) {
    if (!player || !player.playerKey) continue;
    const onRoster = scope.rosterKeys ? scope.rosterKeys.has(player.playerKey) : false;
    const isPick = player?.board?.assetClass === "pick";
    switch (player.state) {
      case RECONCILED_STATES.WITHHELD:
        counts.withheld += 1;
        break;
      case RECONCILED_STATES.BUY_ONLY:
        counts.buy += 1;
        buys.push(itemFor(player, "buy"));
        break;
      case RECONCILED_STATES.SELL_ONLY:
        if (onRoster && !isPick) {
          counts.sell += 1;
          rosterItems.push(itemFor(player, "sell"));
        } else {
          counts.sellOffRoster += 1;
        }
        break;
      case RECONCILED_STATES.CONFLICT:
        if (onRoster && !isPick) {
          counts.conflict += 1;
          rosterItems.push(itemFor(player, "conflict"));
        } else {
          counts.conflictOffRoster += 1;
        }
        break;
      default:
        break;
    }
  }
  rosterItems.sort(byBoardRank);
  buys.sort(byBoardRank);
  const shownBuys = buys.slice(0, Math.max(0, buyLimit));
  return {
    items: [...rosterItems, ...shownBuys],
    sellScope: scope.state,
    counts: { ...counts, buyShown: shownBuys.length },
  };
}

/** Collected emitters that did not run, from the payload's own registry. */
export function unobservedEmitters(payload) {
  const emitters = Array.isArray(payload?.emitters) ? payload.emitters : [];
  return emitters.filter((e) => e?.disposition === "collected" && e?.state === "unobserved");
}

/** One sentence for the SELL scope, so "no sells" is never ambiguous. */
export function sellScopeText(sellScope, teamName) {
  switch (sellScope) {
    case SELL_SCOPE.ROSTER:
      return teamName ? `Sells: ${teamName} only` : "Sells: your roster only";
    case SELL_SCOPE.NO_TEAM:
      return "Sells hidden: no team selected";
    case SELL_SCOPE.TEAM_NOT_FOUND:
      return "Sells hidden: team not found";
    case SELL_SCOPE.TEAM_MISMATCH:
      return "Sells hidden: loading your roster";
    case SELL_SCOPE.ROSTER_UNAVAILABLE:
    default:
      return "Sells hidden: roster unavailable";
  }
}
