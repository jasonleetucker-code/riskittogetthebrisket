// Shared player/contract fixtures for component + logic tests.
//
// Mirrors the backend-stamped contract shape (see backend
// tests/test_trade_suggestions.py `_row`/`_contract`) and the inline
// `withStamps` helper in dynasty-data.test.js, centralised so component
// tests don't each re-invent a player object.

export function makePlayer(overrides = {}) {
  const name = overrides.name || "Josh Allen";
  const value = overrides.rankDerivedValue ?? 9200;
  const rank = overrides.canonicalConsensusRank ?? 1;
  return {
    name,
    displayName: name,
    canonicalName: name,
    position: overrides.position || "QB",
    pos: overrides.pos || overrides.position || "QB",
    team: overrides.team || "BUF",
    assetClass: overrides.assetClass || "offense",
    rookie: overrides.rookie ?? false,
    canonicalConsensusRank: rank,
    rankDerivedValue: value,
    sourceCount: overrides.sourceCount ?? 6,
    sourceRanks: overrides.sourceRanks || { ktc: rank, fantasycalc: rank },
    canonicalSiteValues: overrides.canonicalSiteValues || {
      ktc: value,
      fantasycalc: value + 50,
    },
    values: overrides.values || {
      rawComposite: value,
      finalAdjusted: value,
      overall: value,
    },
    ...overrides,
  };
}

export function makeContract(players = [makePlayer()]) {
  const arr = players.map((p) => (p && p.name ? p : makePlayer(p)));
  return {
    playersArray: arr,
    players: Object.fromEntries(arr.map((p) => [p.name, p])),
  };
}
