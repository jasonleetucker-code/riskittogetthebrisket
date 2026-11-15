/**
 * Manager Intelligence Batch D — seeding the trade tools from a scouted
 * roster (C6-MGR-02).
 *
 * Pure helpers.  Nothing here values anything: every value is the canonical
 * board's, published by GET /api/manager-intel/league
 * (`src/intel/manager_league.py`), and the calculator re-values every seeded
 * asset itself on the same board under the ACTIVE package model.  These
 * helpers only decide what can travel and build links through the existing
 * restore mechanisms:
 *
 *   - Trade Calculator / Analyze Trade — `/trade?share=…`, the calculator's
 *     own share format (`lib/trade-share.js`, encoder injected so this module
 *     stays free of the trade import graph);
 *   - Package Builder — `/arbitrage?tool=builder&…` (`lib/package-builder.js`
 *     owns that query format).
 *
 * An asset the board does not name AND price is UNRESOLVED: it is listed
 * with its reason and never seeded, so the calculator can never show it at
 * 0.  Unknown pick ownership is unknown, never "no picks".
 *
 * League scoping (CLAUDE.md "Rankings vs. league context"): Analyze Trade and
 * the Package Builder run against the site's loaded league rosters, so they
 * are offered only when the backend says this league IS that league
 * (`tradeTools.leagueScoped`).  Owned picks keep their canonical id
 * (`src/identity/picks.py`) only then; elsewhere a pick travels as the
 * generic board row it was valued from, and only the calculator is offered.
 */

import { builderSeedHref } from "@/lib/package-builder";
import {
  describePickOwnershipReason,
  pickOwnershipUnavailableReason,
} from "@/lib/pick-ownership";

/** Why an asset could not be seeded, for display. */
const UNRESOLVED_REASONS = {
  board_unavailable: "the canonical board is not loaded",
  not_on_board: "not on the canonical board",
  unpriced_by_board: "the canonical board does not price him",
  no_board_name: "the canonical board has no row for him",
  pick_already_used: "pick already used",
  draft_status_unknown: "draft status unknown",
  no_board_row_for_ref: "no canonical board value for this pick",
  outside_board_grammar: "pick outside the board",
  pick_unparseable: "unreadable pick",
  row_present_but_unpriced: "the canonical board does not price it",
  alias_target_missing: "no canonical board value for this pick",
};

export function unresolvedReasonText(reason) {
  return UNRESOLVED_REASONS[reason] || (reason ? String(reason) : "unresolved");
}

function isValue(v) {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * Every asset on one scouted roster, in the order the page lists them
 * (players by board value, then held picks), each marked resolved or not.
 *
 * ``{ key, kind, label, detail, value, seedName, assetId, resolved, reason }``
 */
export function rosterSeedAssets(manager, tradeTools) {
  const scoped = tradeTools?.leagueScoped === true;
  const out = [];
  for (const p of manager?.roster?.players || []) {
    const priced = isValue(p.value);
    const named = typeof p.boardName === "string" && p.boardName.trim() !== "";
    const resolved = priced && named;
    out.push({
      key: `player:${p.playerId}`,
      kind: "player",
      label: p.name || `Player ${p.playerId}`,
      detail: p.position || "",
      value: priced ? p.value : null,
      seedName: resolved ? p.boardName : null,
      assetId: null,
      playerId: p.playerId,
      resolved,
      reason: resolved
        ? null
        : !priced
          ? p.valueReason || "unpriced_by_board"
          : "no_board_name",
    });
  }
  const picks = manager?.draftCapital?.picks;
  if (Array.isArray(picks)) {
    picks.forEach((pick, i) => {
      const priced = isValue(pick.value);
      const named =
        typeof pick.boardRowName === "string" &&
        pick.boardRowName.trim() !== "";
      const resolved = priced && named;
      out.push({
        key: `pick:${pick.pickId || `${pick.label}:${i}`}`,
        kind: "pick",
        label: pick.label || "Unknown pick",
        detail: pick.own
          ? "Own"
          : `From ${pick.originOwnerName || `roster ${pick.originRosterId}`}`,
        value: priced ? pick.value : null,
        seedName: resolved ? pick.boardRowName : null,
        // The canonical owned-pick id travels only into the league the site
        // has loaded; anywhere else it names an asset the calculator cannot
        // hold, so the pick goes as its generic board row instead.
        assetId: resolved && scoped && pick.pickId ? String(pick.pickId) : null,
        resolved,
        reason: resolved ? null : pick.valueReason || "no_board_row_for_ref",
      });
    });
  }
  return out;
}

/** Why this roster's picks are not listed (a sentence), or "" when they are. */
export function seedPicksNote(manager) {
  const capital = manager?.draftCapital;
  if (!capital) return "Draft picks were not read for this roster.";
  if (capital.available === false)
    return "Picks are read for the current season only, so none are listed.";
  const reason = pickOwnershipUnavailableReason(capital);
  if (reason) return describePickOwnershipReason(reason);
  return "";
}

/** The resolved assets whose keys are selected, in list order. */
export function selectedSeedAssets(assets, selectedKeys) {
  const keys =
    selectedKeys instanceof Set ? selectedKeys : new Set(selectedKeys || []);
  return (assets || []).filter((a) => a.resolved && keys.has(a.key));
}

/** Keys of every resolved asset ("Select all priced"). */
export function resolvedSeedKeys(assets) {
  return (assets || []).filter((a) => a.resolved).map((a) => a.key);
}

/**
 * The calculator trade for a seed: side A is the user's (empty — they add
 * what they would send), side B lists what the scouted manager SENDS (the
 * calculator's convention), with each owned pick's canonical id aligned.
 * ``packageModel`` is the receipt id the backend stamped, so the calculator
 * can say when its own active model differs.
 */
export function calculatorSeedTrade({
  manager,
  assets,
  selectedKeys,
  tradeTools,
}) {
  const chosen = selectedSeedAssets(assets, selectedKeys);
  const side = {
    name:
      manager?.displayName ||
      (manager?.rosterId != null ? `Roster ${manager.rosterId}` : "Them"),
    players: chosen.map((a) => a.seedName),
  };
  if (chosen.some((a) => a.assetId))
    side.assetIds = chosen.map((a) => a.assetId || null);
  const trade = { sides: [{ name: "You", players: [] }, side] };
  const modelId = tradeTools?.packageModel?.id;
  if (typeof modelId === "string" && modelId) trade.packageModel = modelId;
  return trade;
}

/**
 * ``/trade?share=…`` for the seed, or null when nothing resolved is selected.
 * ``encode`` is ``lib/trade-share``'s ``encodeTrade``.
 */
export function calculatorSeedHref(input, encode) {
  if (typeof encode !== "function") return null;
  const trade = calculatorSeedTrade(input);
  if (!trade.sides[1].players.length) return null;
  try {
    return `/trade?share=${encode(trade)}`;
  } catch {
    return null;
  }
}

/** May the league-scoped tools (Analyze Trade, Package Builder) be offered? */
export function leagueScopedToolsAvailable(tradeTools) {
  return tradeTools?.leagueScoped === true && Boolean(tradeTools?.leagueKey);
}

/** Why only the calculator is offered (a sentence), or "" when all tools are. */
export function tradeToolsScopeNote(tradeTools) {
  if (leagueScopedToolsAvailable(tradeTools)) return "";
  if (tradeTools?.reason === "league_rosters_not_loaded")
    return "This league's rosters are not loaded on the site right now, so only the Trade Calculator can be seeded.";
  return "This is not one of the site's leagues, so only the Trade Calculator can be seeded — picks travel as generic picks on the canonical board.";
}

/**
 * The Package Builder link for this roster, or null when the league-scoped
 * tools are not available or the roster has no current owner.  Exactly one
 * selected player becomes the builder's target ("Acquire a player");
 * otherwise only the opponent is seeded.
 */
export function packageBuilderSeedHref({
  manager,
  assets,
  selectedKeys,
  tradeTools,
}) {
  if (!leagueScopedToolsAvailable(tradeTools)) return null;
  const chosen = selectedSeedAssets(assets, selectedKeys);
  const players = chosen.filter((a) => a.kind === "player");
  return builderSeedHref({
    leagueKey: tradeTools.leagueKey,
    opponentOwner: manager?.ownerUserId,
    target:
      chosen.length === 1 && players.length === 1 ? players[0].seedName : "",
  });
}
