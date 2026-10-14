// Display helpers for Golden Upgrades (C7-GOLD-01).
//
// Pure: every number and verdict comes from POST /api/trade/golden-upgrades.
// Nothing here qualifies, ranks or re-prices an upgrade.  Unknown values
// render as an explicit unknown, never as a zero.

import { UNKNOWN, fmtInt, fmtSignedPct } from "@/lib/best-offers";

export { UNKNOWN };

/** One row per upgrade, in the server's order (strongest inversion first). */
export function goldenRows(result) {
  return (result?.upgrades || []).map((u, i) => {
    const lineup = u?.lineupImpact;
    let lineupText = null;
    if (lineup && lineup.available && Number.isFinite(lineup.ourDelta)) {
      const d = lineup.ourDelta;
      lineupText = `Starting lineup ${d > 0 ? "+" : ""}${d.toFixed(1)} pts (rest of season)`;
    } else if (lineup && lineup.available === false) {
      lineupText = "Lineup impact unavailable";
    }
    return {
      key: `${u?.owned?.name}->${u?.target?.name}@${u?.opponent}#${i}`,
      owned: u?.owned || {},
      target: u?.target || {},
      opponent: u?.opponent || UNKNOWN,
      market: u?.market || u?.owned?.market || UNKNOWN,
      boardGain: fmtSignedPct(u?.boardGainPct),
      marketInversion: Number.isFinite(u?.marketInversionPct)
        ? `${u.marketInversionPct.toFixed(1)}%`
        : UNKNOWN,
      ownedLine: `${fmtInt(u?.owned?.boardValue)} board · ${fmtInt(u?.owned?.marketValue)} market`,
      targetLine: `${fmtInt(u?.target?.boardValue)} board · ${fmtInt(u?.target?.marketValue)} market`,
      lineupText,
      why: u?.why || "",
    };
  });
}

const REASON_TEXT = {
  no_priced_outgoing_assets:
    "None of your players carries a market value in this scan.",
  all_outgoing_assets_constrained:
    "Every player you could send is protected or excluded for this league.",
  lock_conflicts_with_protection:
    "A locked player is also protected or excluded, so he cannot be upgraded.",
  locked_player_unavailable: "A locked player is not on your tradeable roster.",
  locked_players_exceed_package_size:
    "A Golden Upgrade is one player for one player — lock at most one.",
  no_inversion_meets_the_thresholds:
    "No same-position swap has our board preferring their player while their market prefers yours by the minimum margins.",
};

export function noResultText(result) {
  return REASON_TEXT[result?.noResultReason] || null;
}
