"""Package Builder — C7-PKGB-01 (owner inventory row 2.6, backlog spec §2.2).

The user describes the trade they want — a desired incoming player or pick,
which of their assets may go, which positions may come back, how big the
package may be, whether picks are allowed — and the builder returns the best
packages that satisfy it.

A CONSUMER, never a second package algorithm:

* candidates come from the finder's own enumeration (``finder.generate_packages``
  over the canonical substrate, C3-TOPO-01 topology: player counts within one,
  picks not counted);
* every user constraint is applied DURING generation, never as a post-filter:
  return positions and the outgoing selection shape the two pools before the
  enumeration runs, the desired incoming asset rides the substrate's
  ``required_receive`` seam, LOCK rides ``required_send``, and saved
  protections / EXCLUDE are the constraint owner's outgoing policy;
* the canonical verdict is the calculator's own (``analyze_trade.equity_verdict``);
* external checks are the market owner's (``cross_market.external_package_verdicts``,
  native whole-package coverage only);
* ranking is Best Offers' declared prior (``config/trade/best_offers_prior.json``,
  ``PRIOR_UNVALIDATED``) and its roster-aware rerank (``best_offers.rerank_head``)
  — one ranking rule for every generated-trade surface.

Two evidence settings, both stated on every response:

* ``external`` — the opponent must be even or better on an approved calculator
  that natively prices every asset (the Best Offers rule);
* ``any`` — packages that are fair or better for you on the canonical
  calculator, external verdicts shown but not required.

A package that LOSES for you on the canonical calculator is never returned in
either setting.  Recommendation only: nothing is sent.

Sending / Receiving (owner directive 2026-10-18, ``src/trade/discovery``):
each side is independently Offense / Defense (IDP) / Both, applied to the two
pools BEFORE enumeration — all nine combinations, every mode.  Picks are never
offense or defense (``allow_picks`` governs them).  Broad ∩ specific is the
intersection with the return positions; an incompatible pair is explained.  A
locked or explicitly selected player outside Sending, or a requested target
outside Receiving or Target Quality, is REPORTED — never silently dropped and
never overridden.  Target Quality rides the substrate's receive anchor (at
least one incoming player); it is waived, and the response says so, only when
the request can bring back no player at all (a pick target, pick-only return
positions).  ``discovery.sort`` orders by the shared discovery orderings.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from src.league_intel.cross_market import best_qualifying_verdict, external_package_verdicts
from src.trade import best_offers as bo
from src.trade import discovery as disc
from src.trade import finder
from src.trade.analyze_trade import equity_verdict

__all__ = [
    "EVIDENCE_LEVELS",
    "PACKAGE_BUILDER_VERSION",
    "POSITION_FAMILIES",
    "build_packages",
    "normalize_return_positions",
]

PACKAGE_BUILDER_VERSION = "package-builder.2026-10-14.v1"

#: The return-position vocabulary the owner spec names (DL covers EDGE).
POSITION_FAMILIES = ("QB", "RB", "WR", "TE", "DL", "LB", "DB", "PICKS")
_ALIASES = {"EDGE": "DL", "DE": "DL", "DT": "DL", "CB": "DB", "S": "DB", "PICK": "PICKS"}

EVIDENCE_LEVELS = ("external", "any")
#: Assets (players AND picks) on either side — the substrate's largest shape is
#: 3-for-2 / 2-for-3.  Applied as a SHAPE limit before enumeration.
MAX_PACKAGE_ASSETS = 3
#: Emission budget per finder shape group per opponent.  Pools are ranked by
#: value, so a budget-cut search keeps the most valuable combinations; the cut
#: is reported (``searchTruncated``), never silent.  Measured worst case before
#: the budget (no target, no positions, picks on, size 3): 318k packages, 28 s.
SEARCH_BUDGET_PER_SHAPE_GROUP = 2500

_NO_RESULT_TEXT = {
    "no_priced_outgoing_assets": "None of the players you offered carries a market value.",
    "all_outgoing_assets_constrained": (
        "Every asset you offered is protected or excluded for this league."
    ),
    "lock_conflicts_with_protection": (
        "A locked player is also protected or excluded, so no package can include him."
    ),
    "locked_player_unavailable": "A locked player is not among the assets you offered.",
    "target_not_found": "The player or pick you want is not on another team's roster.",
    "target_not_on_opponent": "The asset you want belongs to a different team than the one chosen.",
    "target_ambiguous": "More than one team holds an asset by that name — choose the team.",
    "target_unpriced": (
        "The asset you want is rostered but our board does not price it, so no package can "
        "be valued around it."
    ),
    "target_on_your_roster": "You already own the asset you asked for.",
    "target_is_a_pick_but_picks_are_off": (
        "The asset you want is a draft pick; allow draft picks to build for it."
    ),
    "no_return_assets_in_selected_positions": (
        "No opponent has a priced asset at the positions you selected."
    ),
    "package_size_cannot_hold_requirements": (
        "Your locks and the asset you want do not fit inside the maximum package size."
    ),
    "no_candidate_packages": "No package of an allowed shape could be built.",
    "no_plausible_package": "Every package failed the plausibility gates.",
    "no_fair_package": "Every package that fits your request loses for you on our board.",
    "no_external_acceptance": (
        "No package that is fair for you is even or better for them on an approved "
        "calculator that prices every asset."
    ),
    # Sending / Receiving / Target Quality (owner directive 2026-10-18).
    "return_positions_outside_receiving": (
        "The positions you want back are all outside Receiving. Choose a position in that "
        "group or widen Receiving."
    ),
    "selected_outgoing_outside_sending": (
        "Every player you selected to offer is outside Sending. Widen Sending or choose "
        "players in that group."
    ),
    "no_outgoing_in_sending": "None of your offerable players is in the Sending group.",
    "locked_player_outside_sending": (
        "A locked player is outside Sending, so no package can include him. Unlock him or "
        "widen Sending."
    ),
    "target_outside_receiving": (
        "The player you want is outside Receiving. Widen Receiving to build for him."
    ),
    "target_outside_target_quality": (
        "The player you want is outside Target Quality. Broaden Target Quality to build for him."
    ),
    "no_return_assets_in_receiving": "No opponent has a priced player in the Receiving group.",
    "no_target_meets_quality": (
        "No opponent player you could receive meets Target Quality. Broaden it to search deeper."
    ),
    "no_package_within_target_quality": (
        "No package of an allowed shape brings back a player inside Target Quality."
    ),
}

_PLAYER_FAMILIES = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")


def normalize_return_positions(raw: Any) -> tuple[frozenset[str] | None, list[str]]:
    """``(families | None, unknown)`` — ``None`` means "any position"."""
    if raw is None:
        return None, []
    if not isinstance(raw, (list, tuple, set)):
        return None, ["<not a list>"]
    out: set[str] = set()
    unknown: list[str] = []
    for item in raw:
        key = str(item or "").strip().upper()
        key = _ALIASES.get(key, key)
        if key in POSITION_FAMILIES:
            out.add(key)
        elif key:
            unknown.append(str(item))
    return (frozenset(out) if out else None), unknown


def _family(asset: Any) -> str:
    if asset.is_pick:
        return "PICKS"
    pos = str(asset.position or "").upper()
    return _ALIASES.get(pos, pos)


def _norm(name: Any) -> str:
    return str(name or "").strip().casefold()


def _match(assets: Sequence[Any], wanted: str) -> Any | None:
    """An asset by its own name or canonical pick id — never by a shared board
    row (a generic "2029 Round 1" row is every team's pick, not one asset)."""
    w = _norm(wanted)
    for a in assets:
        if w and w in {_norm(a.name), _norm(a.asset_id)}:
            return a
    return None


def _raw_roster_has(team: Mapping[str, Any] | None, wanted: str) -> bool:
    """Whether the ROSTER lists the name at all, priced or not."""
    w = _norm(wanted)
    return any(_norm(n) == w for n in (team or {}).get("players") or [])


def _no_result(reason: str, *, constrained: bool = False) -> dict[str, Any]:
    return {
        "packages": [],
        "noResultReason": reason,
        "noResultLabel": (
            "No package found under current constraints" if constrained else "No package found"
        ),
        "noResultDetail": _NO_RESULT_TEXT.get(reason),
    }


def build_packages(
    players: dict[str, Any],
    my_team: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    contract: Mapping[str, Any],
    target: str | None = None,
    opponent: str | None = None,
    outgoing: Sequence[str] | None = None,
    return_positions: frozenset[str] | None = None,
    max_assets_per_side: int = MAX_PACKAGE_ASSETS,
    allow_picks: bool = False,
    evidence: str = "any",
    constraints: Any | None = None,
    use_team_context: bool = True,
    needs_by_owner: Mapping[str, set[str]] | None = None,
    lineup_delta: Callable[..., dict[str, Any] | None] | None = None,
    capacity_for: Callable[[str, list[Any], list[Any]], tuple[Any, float | None]] | None = None,
    pick_forecasts: Mapping[int, Any] | None = None,
    limit: int = 10,
    prior: Mapping[str, Any] | None = None,
    per_opponent: bool = False,
    send_scope: str = "both",
    receive_scope: str = "both",
    discovery: disc.DiscoveryFilters | None = None,
) -> dict[str, Any]:
    """The best packages satisfying one user request, best first.

    ``per_opponent`` keeps only each opponent's best package — the "Sell a
    player" / "Improve a position" views, which ask WHO the plausible
    partners are rather than for many variants with one team.  The choice is
    made on the same pre-rerank order the head uses, then the roster-aware
    rerank runs over those per-opponent bests exactly as it does over the head.
    """
    from src.trade.constraints import (  # noqa: PLC0415
        blocked_outgoing,
        outgoing_eligibility,
        resolve_locked_outgoing,
    )

    if evidence not in EVIDENCE_LEVELS:
        raise ValueError(f"evidence must be one of {EVIDENCE_LEVELS}")
    max_side = max(1, min(int(max_assets_per_side), MAX_PACKAGE_ASSETS))
    prior = dict(prior or bo.load_ranking_prior())
    weights = prior["weights"]
    top_k = int((prior.get("search") or {}).get("lineupRerankTopK", 5))
    use_ctx = bool(use_team_context)

    board_values = finder.board_values_from_contract(contract)
    positions = finder.positions_from_contract(contract)
    # The whole priced board, not the finder's top-N market cut: a user who
    # names a target is asking about that asset whatever its market rank.
    pool = finder.build_asset_pool(
        players, market_top_n=0, board_values=board_values, positions=positions
    )
    pool_by_name = {a.name: a for a in pool}
    index = bo._row_index(contract)
    owner_of = {str(t.get("name") or ""): str(t.get("ownerId") or "") for t in sleeper_teams}
    team_by_name = {str(t.get("name") or ""): t for t in sleeper_teams}

    request = {
        "target": target or None,
        "opponent": opponent or None,
        "outgoing": list(outgoing) if outgoing else None,
        "returnPositions": sorted(return_positions) if return_positions else None,
        "maxAssetsPerSide": max_side,
        "allowPicks": bool(allow_picks),
        "evidence": evidence,
        "perOpponent": bool(per_opponent),
        "sending": send_scope,
        "receiving": receive_scope,
    }
    base: dict[str, Any] = {
        "version": PACKAGE_BUILDER_VERSION,
        "myTeam": my_team,
        "action": "recommend_only",
        "request": request,
        "rankingMethod": {
            "id": prior.get("id"),
            "status": prior.get("status"),
            "configPath": "config/trade/best_offers_prior.json",
        },
        "rules": {
            "canonical": "never a loss for you (VA-adjusted canonical calculator)",
            "external": (
                "opponent even or better on a whole-package-covered approved calculator"
                if evidence == "external"
                else "shown, not required"
            ),
            "topology": "abs(players sent - players received) <= 1; picks not counted",
            "packageSize": "at most maxAssetsPerSide assets (players and picks) on either side",
            "picks": (
                "only when the user allows them; a user-requested pick may balance a package"
                if allow_picks
                else "excluded"
            ),
            "constraintsAppliedDuringGeneration": True,
        },
        "teamContext": {"applied": use_ctx},
    }
    if send_scope not in disc.SCOPES or receive_scope not in disc.SCOPES:
        raise ValueError(f"sending/receiving must be one of {disc.SCOPES}")
    cindex = disc.CanonicalIndex(contract)
    disc_report = disc.DiscoveryReport()
    sides: dict[str, Any] = {
        "sending": send_scope,
        "receiving": receive_scope,
        "appliedDuringGeneration": True,
        "picks": "never offense or defense; governed by allowPicks",
    }
    base["sides"] = sides
    if discovery is not None:
        prior_i = disc.load_impact_prior()
        base["discovery"] = {
            "version": disc.DISCOVERY_VERSION,
            "filters": discovery.to_dict(),
            "impactPrior": {
                "id": prior_i.get("id"),
                "status": prior_i.get("status"),
                "configPath": "config/trade/discovery_impact_prior.json",
            },
            "broaderQualityLevels": disc.broader_quality_levels(discovery.quality),
        }
    # Broad ∩ specific: the return positions intersected with Receiving.
    if receive_scope != "both" and return_positions:
        kept = frozenset(
            f for f in return_positions if f == "PICKS" or disc.player_group(f) == receive_scope
        )
        dropped = sorted(return_positions - kept)
        if dropped:
            sides["returnPositionsOutsideReceiving"] = dropped
        if not kept:
            return {
                **base,
                **_no_result("return_positions_outside_receiving"),
                "noResultDetail": (
                    f"{', '.join(dropped)} {'is' if len(dropped) == 1 else 'are'} outside "
                    f"Receiving ({receive_scope.title()}). Choose a "
                    f"{receive_scope} position or widen Receiving."
                ),
            }
        return_positions = kept
        request["returnPositions"] = sorted(kept)
    if my_team not in team_by_name:
        return {**base, "error": "my_team_unresolved", "packages": []}
    if opponent and (opponent not in team_by_name or opponent == my_team):
        return {**base, "error": "unknown_opponent", "packages": []}

    unfiltered = {a.name: a for a in pool}
    my_owner = owner_of.get(my_team, "")

    # ── outgoing pool (the user's selection, then the constraint owner) ────
    my_players_all = finder.resolve_roster(my_team, sleeper_teams, pool_by_name)
    my_picks_all, _ = finder.owned_pick_assets(
        team_by_name[my_team], contract, players, pool_by_name, pick_forecasts, unfiltered
    )
    my_players = my_players_all
    not_on_roster: list[str] = []
    if outgoing:
        # The selection names PLAYERS; picks are governed by ``allow_picks``.
        chosen = []
        for name in outgoing:
            a = _match(my_players_all, name) or _match(my_picks_all, name)
            if a is None:
                not_on_roster.append(str(name))
            elif a not in chosen and not a.is_pick:
                chosen.append(a)
        my_players = chosen
    if not_on_roster:
        base["outgoingNotOnRoster"] = not_on_roster
    # A LOCK is resolved on the unscoped roster so a locked player outside
    # Sending is reported by name rather than read as "not on your roster".
    unscoped = [*my_players, *(my_picks_all if allow_picks else [])]
    if send_scope != "both" and constraints is not None and unscoped:
        pre_lock = resolve_locked_outgoing(unscoped, constraints)
        outside = sorted(
            a.name
            for a in (pre_lock.required if pre_lock.satisfiable else ())
            if not a.is_pick and disc.player_group(a.position) != send_scope
        )
        if outside:
            return {
                **base,
                "lockedOutgoing": pre_lock.to_dict(),
                **_no_result("locked_player_outside_sending", constrained=True),
                "noResultDetail": (
                    f"{', '.join(outside)} {'is' if len(outside) == 1 else 'are'} locked but "
                    f"outside Sending ({send_scope.title()}). Unlock or widen Sending."
                ),
            }
    if send_scope != "both":
        in_scope = [a for a in my_players if disc.player_group(a.position) == send_scope]
        outside = [a for a in my_players if a not in in_scope]
        sides["excludedBySending"] = len(outside)
        if outgoing:
            # An explicit selection that conflicts is REPORTED, never silently
            # traded and never silently forgotten.
            conflicts = sorted(a.name for a in outside)
            if conflicts:
                sides["selectedOutgoingOutsideSending"] = conflicts
            if not in_scope:
                return {
                    **base,
                    **_no_result("selected_outgoing_outside_sending"),
                    "noResultDetail": (
                        f"{', '.join(conflicts)} {'is' if len(conflicts) == 1 else 'are'} "
                        f"outside Sending ({send_scope.title()})."
                    ),
                }
        elif not in_scope and not (allow_picks and my_picks_all):
            return {**base, **_no_result("no_outgoing_in_sending")}
        my_players = in_scope
    my_roster = [*my_players, *(my_picks_all if allow_picks else [])]
    if not my_roster:
        return {**base, **_no_result("no_priced_outgoing_assets")}
    blocked = blocked_outgoing(my_roster, constraints)
    if len(blocked) >= len(my_roster):
        return {**base, **_no_result("all_outgoing_assets_constrained", constrained=True)}
    lock = resolve_locked_outgoing(my_roster, constraints)
    if not lock.satisfiable:
        return {
            **base,
            "lockedOutgoing": lock.to_dict(),
            **_no_result(lock.no_result_reason, constrained=True),
        }
    policy = outgoing_eligibility(my_roster, constraints)

    # ── the desired incoming asset ────────────────────────────────────────
    target_asset = None
    if target:
        if (
            _match(my_players_all, target) is not None
            or _match(my_picks_all, target) is not None
            or _raw_roster_has(team_by_name[my_team], target)
        ):
            return {**base, **_no_result("target_on_your_roster")}
        holders: list[tuple[str, Any]] = []
        unpriced_holders: list[str] = []
        for name, team in team_by_name.items():
            if name == my_team:
                continue
            hit = _match(finder.resolve_roster(name, sleeper_teams, pool_by_name), target)
            if hit is None:
                picks, _ = finder.owned_pick_assets(
                    team, contract, players, pool_by_name, pick_forecasts, unfiltered
                )
                hit = _match(picks, target)
            if hit is not None:
                holders.append((name, hit))
            elif _raw_roster_has(team, target):
                unpriced_holders.append(name)
        if opponent:
            elsewhere = [n for n, _a in holders if n != opponent]
            holders = [(n, a) for n, a in holders if n == opponent]
            if not holders and elsewhere:
                return {
                    **base,
                    "targetHolders": sorted(elsewhere),
                    **_no_result("target_not_on_opponent"),
                }
            unpriced_holders = [n for n in unpriced_holders if n == opponent]
        if not holders:
            if unpriced_holders:
                return {
                    **base,
                    "targetHolders": sorted(unpriced_holders),
                    **_no_result("target_unpriced"),
                }
            return {**base, **_no_result("target_not_found")}
        if len(holders) > 1:
            return {
                **base,
                "targetHolders": sorted(n for n, _a in holders),
                **_no_result("target_ambiguous"),
            }
        opponent, target_asset = holders[0]
        if target_asset.is_pick and not allow_picks:
            return {**base, **_no_result("target_is_a_pick_but_picks_are_off")}
        request["opponent"] = opponent
        if not target_asset.is_pick:
            group = disc.player_group(target_asset.position)
            if receive_scope != "both" and group != receive_scope:
                return {
                    **base,
                    **_no_result("target_outside_receiving"),
                    "noResultDetail": (
                        f"{target_asset.name} ({target_asset.position or 'position unknown'}) is "
                        f"outside Receiving ({receive_scope.title()}). Widen Receiving to build "
                        "for him."
                    ),
                }
            if discovery is not None and discovery.quality_active:
                ok, why = disc.incoming_quality(target_asset, discovery, cindex)
                if not ok:
                    rank = cindex.rank(target_asset)
                    fits = next(
                        (
                            lvl
                            for lvl, lim in disc.QUALITY_LEVELS.items()
                            if lim is None or (rank is not None and rank <= lim)
                        ),
                        "all",
                    )
                    return {
                        **base,
                        **_no_result("target_outside_target_quality"),
                        "targetRank": rank,
                        "suggestedTargetQuality": fits if why != "below_min_value" else None,
                        "noResultDetail": (
                            f"{target_asset.name} is "
                            + (
                                f"ranked #{rank}"
                                if rank is not None
                                else "unranked on the canonical board"
                            )
                            + (
                                f", below the minimum incoming value of "
                                f"{discovery.min_incoming_value:,}"
                                if why == "below_min_value"
                                else ", outside the current Target Quality"
                            )
                            + ". Broaden Target Quality to build for him."
                        ),
                    }
    if len(lock.required) > max_side:
        return {**base, **_no_result("package_size_cannot_hold_requirements", constrained=True)}

    opponents = [opponent] if opponent else [n for n in team_by_name if n and n != my_team]
    # Target Quality: waived — and said so — only when the request can bring
    # back no player at all.
    quality_waived = None
    if discovery is not None and discovery.quality_active:
        if target_asset is not None and target_asset.is_pick:
            quality_waived = "target_is_a_pick"
        elif return_positions is not None and return_positions <= frozenset({"PICKS"}):
            quality_waived = "pick_only_return_positions"
    if quality_waived and "discovery" in base:
        base["discovery"]["qualityWaived"] = quality_waived
    anchor = (
        disc.quality_anchor(discovery, cindex)
        if discovery is not None and quality_waived is None
        else None
    )
    scope_filters = disc.DiscoveryFilters(
        quality=(discovery.quality if discovery is not None else "all"),
        min_incoming_value=(discovery.min_incoming_value if discovery is not None else None),
        scope=receive_scope,
    )
    our_needs = (needs_by_owner or {}).get(my_owner) if use_ctx and needs_by_owner else None

    # ── generate per opponent, constraints inside the enumeration ─────────
    diag = bo._new_diag()
    diag["rejectedBy"]["no_fair_package"] = diag["rejectedBy"].pop("no_canonical_win")
    any_return_pool = False
    truncated = False
    needs_by_opp: dict[str, set[str] | None] = {}
    found: list[tuple[str, bo.BestOfferCandidate]] = []
    enumeration: dict[str, Any] = {}
    for opp in opponents:
        opp_roster = finder.resolve_roster(opp, sleeper_teams, pool_by_name)
        if allow_picks and (return_positions is None or "PICKS" in return_positions):
            opp_picks, _ = finder.owned_pick_assets(
                team_by_name.get(opp), contract, players, pool_by_name, pick_forecasts, unfiltered
            )
            opp_roster = [*opp_roster, *opp_picks]
        owned = {a.name for a in my_roster}
        opp_pool = [
            a
            for a in opp_roster
            if a.name not in owned
            and a is not target_asset
            and (allow_picks or not a.is_pick)
            and (return_positions is None or _family(a) in return_positions)
        ]
        # Receiving, BEFORE enumeration (picks pass; their own controls rule).
        opp_pool = disc.filter_incoming(opp_pool, scope_filters, cindex, disc_report)
        if not opp_pool and target_asset is None:
            continue
        any_return_pool = True
        their_needs = (needs_by_owner or {}).get(owner_of.get(opp, "")) if use_ctx else None
        needs_by_opp[opp] = their_needs
        score = _scorer(index, prior, our_needs, their_needs, diag, evidence, contract)
        cands, report = finder.generate_packages(
            my_roster,
            opp_pool,
            policy,
            equal_count_only=False,
            **({"required_send": list(lock.required)} if lock.required else {}),
            **({"required_receive": [target_asset]} if target_asset is not None else {}),
            score=score,
            max_per_side=max_side,
            max_packages=SEARCH_BUDGET_PER_SHAPE_GROUP,
            **({"receive_anchor": anchor} if anchor is not None else {}),
        )
        disc_report.anchor_rejected += disc.anchor_rejections(report)
        enumeration[opp] = report
        truncated = truncated or any(
            isinstance(g, dict) and g.get("budgetExhausted") for g in report.values()
        )
        found.extend((opp, c) for c in cands)

    if discovery is not None:
        base["discovery"]["report"] = disc_report.to_dict()
    sides["report"] = disc_report.to_dict()
    if not any_return_pool:
        if receive_scope != "both" and disc_report.targets_considered == 0:
            return {**base, **_no_result("no_return_assets_in_receiving")}
        return {**base, **_no_result("no_return_assets_in_selected_positions")}

    seen: dict[tuple, tuple[str, bo.BestOfferCandidate]] = {}
    for opp, c in found:
        key = (opp, c.package_key())
        if key not in seen or c.arbitrage_score > seen[key][1].arbitrage_score:
            seen[key] = (opp, c)
    opp_of = {id(c): opp for opp, c in seen.values()}
    cands = [c for _opp, c in seen.values()]
    if not cands:
        reason = _reason(diag, evidence)
        if anchor is not None and reason == "no_candidate_packages":
            reason = (
                "no_target_meets_quality"
                if disc_report.targets_meeting_quality == 0 and target_asset is None
                else "no_package_within_target_quality"
            )
        out = {
            **base,
            **_no_result(reason, constrained=bool(blocked or lock.required)),
        }
        out["diagnostics"] = {**diag, "enumeration": enumeration}
        if truncated:
            out["searchTruncated"] = True
        return out

    def _order(c: bo.BestOfferCandidate) -> tuple:
        return (-c.arbitrage_score, c.has_pick, opp_of[id(c)], c.package_key())

    # An unknown disagreement cost (no calculator prices the whole package)
    # ranks as the worst KNOWN one across every candidate, never as free.
    bo.score_head(cands, weights, factors=("calculatorDivergence",))
    cands.sort(key=_order)
    if per_opponent:
        head = []
        seen_opp: set[str] = set()
        for c in cands:
            if opp_of[id(c)] not in seen_opp:
                seen_opp.add(opp_of[id(c)])
                head.append(c)
    else:
        head = cands[: max(top_k, limit)]
    if use_ctx:
        # Roster consequences per opponent pairing; ONE set of stand-ins over
        # the merged head, so every opponent's candidates are charged alike.
        by_opp: dict[str, list[bo.BestOfferCandidate]] = {}
        for c in head:
            by_opp.setdefault(opp_of[id(c)], []).append(c)
        for opp, group in by_opp.items():
            bo.annotate_roster_factors(
                group,
                lineup_delta=lineup_delta,
                capacity_for=capacity_for,
                my_owner=my_owner,
                opp_owner=owner_of.get(opp, ""),
                opp=opp,
            )
    bo.score_head(head, weights, factors=(*bo._RERANK_FACTORS, "calculatorDivergence"))
    head.sort(key=_order)
    if discovery is not None and discovery.sort is not None:
        head = _order_by_discovery(
            cands,
            head,
            sort=discovery.sort,
            filters=discovery,
            index=cindex,
            our_needs=our_needs,
            use_ctx=use_ctx,
            opp_of=opp_of,
            per_opponent=per_opponent,
            keep=max(top_k, limit),
            annotate=lambda group, opp: bo.annotate_roster_factors(
                group,
                lineup_delta=lineup_delta,
                capacity_for=capacity_for,
                my_owner=my_owner,
                opp_owner=owner_of.get(opp, ""),
                opp=opp,
            ),
        )

    packages = []
    for c in head[: max(1, int(limit))]:
        opp = opp_of[id(c)]
        offer = bo._offer_dict(c, our_needs, needs_by_opp.get(opp), None, prior)
        offer["opponent"] = opp
        offer["externalQualifies"] = bool(c.external is not None and c.external.qualifies)
        if c.discovery is not None:
            offer["discovery"] = c.discovery
            offer["whyItMatters"] = c.discovery.get("whyItMatters")
        packages.append(offer)
    out = {**base, "packages": packages, "diagnostics": {**diag, "enumeration": enumeration}}
    if per_opponent:
        out["grouping"] = "best_per_opponent"
        out["opponentsWithOffers"] = len(head)
        out["opponentsSearched"] = len(opponents)
    if truncated:
        out["searchTruncated"] = True
    return out


def _order_by_discovery(
    cands: list[bo.BestOfferCandidate],
    head: list[bo.BestOfferCandidate],
    *,
    sort: str,
    filters: disc.DiscoveryFilters,
    index: disc.CanonicalIndex,
    our_needs: set[str] | None,
    use_ctx: bool,
    opp_of: Mapping[int, str],
    per_opponent: bool,
    keep: int,
    annotate: Callable[[list[bo.BestOfferCandidate], str], None],
) -> list[bo.BestOfferCandidate]:
    """Re-select and order the head by the shared discovery orderings.

    Every qualifying candidate is scored on what is free to read; the kept
    head (per opponent, or the top ``keep``) then gains the roster reads the
    builder already owns — lineup delta and forced-release cost — and is
    ordered under the SAME sort.  The Best Offers prior score stays computed
    and published.
    """
    prior = disc.load_impact_prior()

    def _metrics(c: bo.BestOfferCandidate) -> dict[str, Any]:
        fit_lineup = disc.lineup_fit(c.lineup, prior)
        fit_need = disc.need_fit(c.receive, our_needs) if use_ctx else None
        return disc.candidate_metrics(
            c.give,
            c.receive,
            index=index,
            prior=prior,
            filters=filters,
            roster_fit=fit_lineup if fit_lineup is not None else fit_need,
            roster_fit_basis=(
                "lineup"
                if fit_lineup is not None
                else ("team_weakness" if fit_need is not None else None)
            ),
            counterparty=c.factors.get("externalComfort"),
            counterparty_basis="Best Offers externalComfort (qualifying calculator)",
            forced_drop=c.factors.get("forcedDropCost"),
            lineup=c.lineup,
        )

    def _key(c: bo.BestOfferCandidate) -> tuple:
        return disc.sort_key(sort, c.discovery or {}, (c.has_pick, opp_of[id(c)], c.package_key()))

    for c in cands:
        c.discovery = _metrics(c)
    disc.score_impact([c.discovery for c in cands], prior)
    ordered = sorted(cands, key=_key)
    if per_opponent:
        new_head, seen = [], set()
        for c in ordered:
            if opp_of[id(c)] not in seen:
                seen.add(opp_of[id(c)])
                new_head.append(c)
    else:
        new_head = ordered[: max(1, keep)]
    if use_ctx:
        fresh = [c for c in new_head if c not in head]
        by_opp: dict[str, list[bo.BestOfferCandidate]] = {}
        for c in fresh:
            by_opp.setdefault(opp_of[id(c)], []).append(c)
        for opp, group in by_opp.items():
            annotate(group, opp)
        for c in new_head:
            c.discovery = _metrics(c)
        disc.score_impact([c.discovery for c in new_head], prior)
    new_head.sort(key=_key)
    for c in new_head:
        c.discovery["whyItMatters"] = disc.why_it_matters(
            c.discovery, need_positions=our_needs or ()
        )
        c.discovery.pop("lineupImpact", None)
    return new_head


def _reason(diag: Mapping[str, Any], evidence: str) -> str:
    if diag["enumerated"] == 0:
        return "no_candidate_packages"
    if diag["plausible"] == 0:
        return "no_plausible_package"
    if diag["canonicalWins"] == 0:
        return "no_fair_package"
    return "no_external_acceptance"


def _scorer(
    index: Mapping[str, list[Mapping[str, Any]]],
    prior: Mapping[str, Any],
    our_needs: set[str] | None,
    their_needs: set[str] | None,
    diag: dict[str, Any],
    evidence: str,
    contract: Mapping[str, Any],
) -> Callable[[list[Any], list[Any]], bo.BestOfferCandidate | None]:
    """Judge one enumerated package against the user's request.

    ``diag["canonicalWins"]`` counts packages that are FAIR OR BETTER for the
    user here (the builder accepts an even canonical result; Best Offers does
    not) — named in the response rules.
    """
    weights = prior["weights"]
    pick_provenance = (contract or {}).get("pickAnchorsProvenance")
    memo: dict[tuple, bo.BestOfferCandidate | None] = {}

    def score(give: list[Any], receive: list[Any]) -> bo.BestOfferCandidate | None:
        key = (
            tuple(sorted((a.asset_id or a.name) for a in give)),
            tuple(sorted((a.asset_id or a.name) for a in receive)),
        )
        if key not in memo:
            memo[key] = _judge(give, receive)
        return memo[key]

    def _judge(give: list[Any], receive: list[Any]) -> bo.BestOfferCandidate | None:
        diag["enumerated"] += 1
        ok, flags = finder.plausibility_check(give, receive)
        if not ok:
            diag["rejectedBy"]["no_plausible_package"] += 1
            return None
        diag["plausible"] += 1
        equity = equity_verdict(
            [float(a.model_value) for a in give], [float(a.model_value) for a in receive]
        )
        if equity["direction"] == "opposes":
            diag["rejectedBy"]["no_fair_package"] += 1
            return None
        diag["canonicalWins"] += 1
        give_rows = [bo._row_for(a, index) for a in give]
        recv_rows = [bo._row_for(a, index) for a in receive]
        verdicts = external_package_verdicts(give_rows, recv_rows, pick_provenance=pick_provenance)
        best = best_qualifying_verdict(verdicts)
        if any(v.coverage == "complete" for v in verdicts):
            diag["covered"] += 1
        if best is None and evidence == "external":
            if any(v.coverage == "complete" for v in verdicts):
                reason = "opponent_not_even_on_any_calculator"
            elif any(v.coverage == "withheld" for v in verdicts):
                reason = "external_provider_withheld"
            else:
                reason = "no_whole_package_coverage"
            diag["rejectedBy"][reason] += 1
            return None
        if best is not None:
            diag["qualified"] += 1
        factors = bo._factors(
            give,
            receive,
            equity,
            best,
            prior,
            our_needs,
            their_needs,
            rows=[*give_rows, *recv_rows],
            pick_provenance=pick_provenance,
            verdicts=verdicts,
        )
        return bo.BestOfferCandidate(
            give=list(give),
            receive=list(receive),
            equity=equity,
            external=best,
            external_all=verdicts,
            factors=factors,
            arbitrage_score=bo._score(factors, weights),
            flags=list(flags),
        )

    return score
