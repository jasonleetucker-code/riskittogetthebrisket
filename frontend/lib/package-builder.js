// Request shaping and display text for the Package Builder (C7-PKGB-01).
//
// Pure: the server validates and applies every constraint during generation
// (src/trade/package_builder.py).  Nothing here filters or ranks packages.

import { toRequest } from "@/lib/trade-refinement";

export const PACKAGE_POSITIONS = [
  "QB",
  "RB",
  "WR",
  "TE",
  "DL",
  "LB",
  "DB",
  "PICKS",
];

export function togglePosition(list, pos) {
  return list.includes(pos) ? list.filter((p) => p !== pos) : [...list, pos];
}

/** The POST body; empty choices are omitted (the server reads absence as "any"). */
export function buildRequest({
  myTeam,
  leagueKey,
  target,
  opponent,
  outgoing,
  positions,
  maxSide,
  allowPicks,
  evidence,
  useTeamContext,
  refinement,
}) {
  const body = {
    myTeam,
    maxPlayersPerSide: maxSide,
    allowPicks: Boolean(allowPicks),
    evidence: evidence === "external" ? "external" : "any",
    useTeamContext: useTeamContext !== false,
    refinement: toRequest(refinement),
  };
  if (leagueKey) body.leagueKey = leagueKey;
  const t = String(target ?? "").trim();
  if (t) body.target = t;
  if (opponent) body.opponent = opponent;
  if (outgoing?.length) body.outgoing = [...outgoing];
  if (positions?.length) body.returnPositions = [...positions];
  return body;
}

const REASON_TEXT = {
  no_priced_outgoing_assets:
    "None of the players you offered carries a market value.",
  all_outgoing_assets_constrained:
    "Every asset you offered is protected or excluded.",
  lock_conflicts_with_protection:
    "A locked player is also protected or excluded.",
  locked_player_unavailable:
    "A locked player is not among the assets you offered.",
  target_not_found: "That player or pick is not on another team's roster.",
  target_on_your_roster: "You already own that asset.",
  target_is_a_pick_but_picks_are_off:
    "That is a draft pick — allow draft picks to build for it.",
  no_return_assets_in_selected_positions:
    "No opponent has a priced asset at the positions you selected.",
  package_size_cannot_hold_requirements:
    "Your locks do not fit inside the maximum package size.",
  no_candidate_packages: "No package of an allowed shape could be built.",
  no_plausible_package: "Every package failed the plausibility gates.",
  no_fair_package:
    "Every package that fits your request loses for you on our board.",
  no_external_acceptance:
    "No package that is fair for you is even or better for them on an approved calculator that prices every asset.",
};

export function noResultText(result) {
  return result?.noResultDetail || REASON_TEXT[result?.noResultReason] || null;
}
