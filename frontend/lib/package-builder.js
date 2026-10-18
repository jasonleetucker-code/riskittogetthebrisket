// Request shaping and display text for the Package Builder (C7-PKGB-01).
//
// Pure: the server validates and applies every constraint during generation
// (src/trade/package_builder.py).  Nothing here filters or ranks packages.

import { toRequest } from "@/lib/trade-refinement";
import { discoveryRequest } from "@/lib/trade-discovery";

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
  sending = "both",
  receiving = "both",
  discovery = null,
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
  // Owner directive 2026-10-18: independent Sending / Receiving sides, applied
  // by the server to the two pools BEFORE enumeration.  "both" is omitted so a
  // default request is byte-identical to the legacy one.
  if (sending && sending !== "both") body.sending = sending;
  if (receiving && receiving !== "both") body.receiving = receiving;
  if (discovery) body.discovery = discoveryRequest(discovery);
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
  return_positions_outside_receiving:
    "The positions you want back are all outside Receiving.",
  selected_outgoing_outside_sending:
    "Every player you selected to offer is outside Sending.",
  no_outgoing_in_sending: "None of your offerable players is in the Sending group.",
  locked_player_outside_sending:
    "A locked player is outside Sending. Unlock him or widen Sending.",
  target_outside_receiving:
    "The player you want is outside Receiving. Widen Receiving to build for him.",
  target_outside_target_quality:
    "The player you want is outside Target Quality. Broaden it to build for him.",
  no_return_assets_in_receiving:
    "No opponent has a priced player in the Receiving group.",
  no_target_meets_quality:
    "No opponent player you could receive meets Target Quality.",
  no_package_within_target_quality:
    "No package of an allowed shape brings back a player inside Target Quality.",
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
  invalid_sides: "Sending and Receiving must each be Offense, Defense or Both.",
  invalid_discovery: "One of the discovery filters is not supported.",
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

// ── Seeding the builder from a link (Manager Intelligence Batch D) ──────
//
// ``/arbitrage?tool=builder&league=<leagueKey>&opponent=<ownerUserId>
// [&target=<board name>]`` opens the Package Builder with that team chosen as
// the counterparty (and, with a target, in "Acquire a player").  The opponent
// travels as the team's permanent Sleeper owner id, never its display name, and
// is resolved against the loaded league's teams by the view — a seed for a
// league or owner the page does not hold applies nothing and says so.

export const BUILDER_SEED_TOOL = "builder";
const SEED_OWNER_RE = /^\d{1,24}$/;
const SEED_LEAGUE_RE = /^[a-z][a-z0-9_-]{0,63}$/;
const SEED_TARGET_MAX = 64;

/** The builder seed link, or null when the owner id is not a valid one. */
export function builderSeedHref({ leagueKey, opponentOwner, target } = {}) {
  const owner = String(opponentOwner ?? "");
  const league = String(leagueKey ?? "");
  if (!SEED_OWNER_RE.test(owner) || !SEED_LEAGUE_RE.test(league)) return null;
  const params = new URLSearchParams({
    tool: BUILDER_SEED_TOOL,
    league,
    opponent: owner,
  });
  const t = String(target ?? "").trim();
  if (t && t.length <= SEED_TARGET_MAX) params.set("target", t);
  return `/arbitrage?${params.toString()}`;
}

/**
 * The seed a ``/arbitrage`` URL carries, or null.  Untrusted input: anything
 * malformed is dropped rather than half-applied.
 */
export function parseBuilderSeed(search) {
  if (typeof search !== "string" || !search) return null;
  let params;
  try {
    params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  } catch {
    return null;
  }
  if (params.get("tool") !== BUILDER_SEED_TOOL) return null;
  const owner = params.get("opponent") || "";
  const league = params.get("league") || "";
  if (!SEED_OWNER_RE.test(owner) || !SEED_LEAGUE_RE.test(league)) {
    return { opponentOwner: "", leagueKey: "", target: "" };
  }
  const t = String(params.get("target") || "").trim();
  return {
    opponentOwner: owner,
    leagueKey: league,
    target: t && t.length <= SEED_TARGET_MAX ? t : "",
  };
}

/**
 * The counterparty team a seed names in the loaded league: the team whose
 * owner id matches, unless that is the user's own team.  "" when unresolved.
 */
export function seedOpponentTeam(seed, teams, myTeam) {
  const owner = seed?.opponentOwner;
  if (!owner) return "";
  const team = (teams || []).find((t) => String(t?.ownerId ?? "") === owner);
  return team && team.name && team.name !== myTeam ? team.name : "";
}

/** Why a seed could not be applied (a sentence), or "" when it applied. */
export function seedProblemText(seed, { teams, myTeam, leagueKey } = {}) {
  if (!seed || !(teams || []).length) return "";
  if (!seed.opponentOwner) return "The link's team could not be read, so nothing was pre-filled.";
  if (seedOpponentTeam(seed, teams, myTeam)) return "";
  if (seed.leagueKey && leagueKey && seed.leagueKey !== leagueKey)
    return "That team is in a different league from the one selected. Switch leagues to build packages with it.";
  const own = (teams || []).find((t) => String(t?.ownerId ?? "") === seed.opponentOwner);
  if (own && own.name === myTeam) return "That team is your own, so it cannot be the counterparty.";
  return "That manager has no team in the selected league, so nothing was pre-filled.";
}
