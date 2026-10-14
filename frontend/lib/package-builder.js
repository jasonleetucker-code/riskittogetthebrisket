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
    maxAssetsPerSide: maxSide,
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
  target_not_on_opponent:
    "That asset belongs to a different team than the one chosen.",
  target_ambiguous:
    "More than one team holds an asset by that name — choose the team.",
  target_unpriced:
    "That asset is rostered, but our board does not price it, so no package can be valued around it.",
  no_external_acceptance:
    "No package that is fair for you is even or better for them on an approved calculator that prices every asset.",
};

export function noResultText(result) {
  return result?.noResultDetail || REASON_TEXT[result?.noResultReason] || null;
}

const ERROR_TEXT = {
  unknown_team: "Choose your team first.",
  unknown_opponent: "Choose a different team to trade with.",
  invalid_target: "That player or pick name is not valid.",
  invalid_outgoing: "Choose at most 60 assets to offer.",
  invalid_return_positions: "One of the selected positions is not supported.",
  invalid_numbers: "Package size must be between 1 and 3.",
  invalid_evidence: "Choose which evidence the packages need.",
  invalid_refinement: "A player cannot be both locked and excluded.",
};

/** A readable message for a 4xx/5xx code; the code itself is never shown alone. */
export function requestErrorText(code) {
  return ERROR_TEXT[code] || "The package builder could not run. Try again.";
}

/** The "do they accept" line: the server's own wording when nothing qualifies. */
export function externalLine(pkg, fmtPct) {
  const ext = pkg?.external;
  if (ext) return `${ext.label}: them ${fmtPct(ext.opponentMarginPct)}`;
  return (
    pkg?.whyTheyMayAccept ||
    "No approved calculator prices every asset and grades it even for them."
  );
}
