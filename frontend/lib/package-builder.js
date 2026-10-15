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

/**
 * The builder's views (directive Part 3).  Each is a preset over the SAME
 * server request — no mode has its own generator:
 *
 *   acquire — a desired incoming asset (``target``); its holder is implied.
 *   sell    — one asset to move (``outgoing = [it]``); the best package with
 *             EACH plausible buyer (``perOpponent``).
 *   improve — one position you want back (``returnPositions = [it]``), best
 *             package per team (``perOpponent``); the roster-aware rerank keeps
 *             a trade that opens a bigger hole elsewhere from ranking first.
 *   custom  — every control, as before.
 */
export const BUILDER_MODES = [
  { value: "acquire", label: "Acquire a player" },
  { value: "sell", label: "Sell a player" },
  { value: "improve", label: "Improve a position" },
  { value: "custom", label: "Custom" },
];

export const IMPROVE_POSITIONS = PACKAGE_POSITIONS.filter((p) => p !== "PICKS");

/**
 * The request fields one mode sends, and whether it has what it needs.
 * ``missing`` names the one required choice when ``ready`` is false.
 */
export function modeRequestFields(mode, state) {
  const s = state || {};
  if (mode === "acquire") {
    const target = String(s.target ?? "").trim();
    return {
      target,
      opponent: s.opponent || "",
      outgoing: s.outgoing || [],
      positions: [],
      perOpponent: false,
      ready: Boolean(target),
      missing: target ? null : "Choose the player or pick you want.",
    };
  }
  if (mode === "sell") {
    const asset = String(s.sellAsset ?? "").trim();
    return {
      target: "",
      opponent: "",
      outgoing: asset ? [asset] : [],
      positions: s.positions || [],
      perOpponent: true,
      ready: Boolean(asset),
      missing: asset ? null : "Choose the player you want to sell.",
    };
  }
  if (mode === "improve") {
    const pos = IMPROVE_POSITIONS.includes(s.improvePosition)
      ? s.improvePosition
      : "";
    return {
      target: "",
      opponent: "",
      outgoing: s.outgoing || [],
      positions: pos ? [pos] : [],
      perOpponent: true,
      ready: Boolean(pos),
      missing: pos ? null : "Choose the position to improve.",
    };
  }
  return {
    target: String(s.target ?? "").trim(),
    opponent: s.opponent || "",
    outgoing: s.outgoing || [],
    positions: s.positions || [],
    perOpponent: false,
    ready: true,
    missing: null,
  };
}

/** "3 teams have an offer" / "5 packages found", from the server's grouping. */
export function resultCountText(result) {
  const n = (result?.packages || []).length;
  if (result?.grouping === "best_per_opponent") {
    const searched = result?.opponentsSearched;
    return `${n} team${n === 1 ? "" : "s"} ${n === 1 ? "has" : "have"} an offer${
      typeof searched === "number" ? ` (of ${searched} searched)` : ""
    }.`;
  }
  const opp = result?.request?.opponent;
  return `${n} package${n === 1 ? "" : "s"} found${opp ? ` with ${opp}` : ""}.`;
}

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
  perOpponent,
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
  if (perOpponent) body.perOpponent = true;
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
