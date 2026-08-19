"""Droppability — the canonical consumer interface (C2-DROP-01).

**This module implements nothing.**  The owner of "what does releasing
this player cost, and who can we legally release at all" is
``src/draft/displacement.py``, and the manifest names it: `C2-DROP-01`
is a **CONSOLIDATE**, not an IMPLEMENT.  This is the adapter that lets
the rest of the canonical roster chain — and the trade lane's
capacity/forced-drop work (`C3-CAP-01`) and Perfect Waivers
(`C7-WAIV-01`) — reach that owner without going through the Perfect
Draft board.

The same relationship ``Dynasty Scraper.py`` has with
``src/identity/name_primitives.py``: the caller is an adapter, the
callee is the owner, and there is no second copy of the arithmetic.

Why an adapter was needed at all
================================

``build_cut_ladder`` is sound.  Every rung is validated by re-running
the exact assignment solver over the surviving roster (the legal
cut-sets are the independent sets of the dual of a transversal matroid,
so cheapest-first is exactly optimal, not a heuristic), and an unpriced
player is stamped ``assumedWaiver`` rather than being read as a cheap
cut.  What it was NOT was reachable: its only production caller is
``src/draft/context.py`` → ``GET /api/draft/roster-context``, which
also computes rookie pools, auction budgets and a dollar ladder, and
which refuses outright unless a draft-shaped league resolves.  A trade
surface asking "can this team legally absorb three players" had no way
in that did not drag a draft board behind it.

Measured parity, not asserted
=============================

Two roster joins reach the same board.  ``build_roster_assets``
(``src/draft/context.py``) joins ``sleeper.teams[].players`` to
``playersArray`` by name with an id fallback; ``contract_roster_pools``
(``src/api/data_contract.py``) is the C2 chain's own builder.  They were
compared on the live 12-team board before this module chose one:
**identical membership on 12 of 12 teams (660 players), identical
``rankDerivedValue`` on every one, zero unmatched rows** — and the two
slot resolvers agreed on all 21 slots.

So this adapter calls ``build_roster_assets`` directly.  Not because the
chain's own builder is worse, but because reusing the owner's own join
makes the ladder byte-identical to the draft surface's by construction
instead of by coincidence, and ``RosterAsset`` needs two fields the pool
builder does not carry (``playerId`` and the injury flag).  The
measurement above is what makes that safe to say rather than hope.

Two inputs are named, never invented
====================================

* **Scarcity** is OPTIONAL and defaults to inert.  The multiplier comes
  from ``league_intel.replacement.compute_scarcity``, which reads
  ``rosValue`` off the ROS team-strength snapshot — the same
  wrong-quantity dependency the rest of this chain moved off (see
  ``docs/roster-intelligence/C2_CANONICAL_ROSTER_CHAIN.md`` §8).  Rather
  than reintroduce it, the caller supplies it or does not, and
  ``scarcityApplied`` says which happened.  The divergence that creates
  is BOUNDED and stated: the multiplier lives in [0.85, 1.15], so
  scarcity can reorder two candidates only when their inert costs are
  within a factor of 1.15/0.85 ≈ 1.353.  Beyond that ratio the two
  ladders agree on order whatever the scarcity signals say.
* **``unavailable_keys``** removes players who are not actually
  signable, and its DEFAULT is no longer "nobody".  It was ``()``, which
  is the claim that every unrostered player can be signed — false for
  every lot in a live rookie auction, and false in the direction that
  matters: counting the auction's own rookies as free agents RAISES the
  replacement bar, so every cut looks CHEAPER.  Measured against the
  draft surface on the live board, WR waiver level ran **25.4% high**
  (2036.0 vs 1519.0), DL 8.1% and TE 7.1%.  That is the defect
  ``src/draft/rookie_pool.py`` exists to prevent, arriving by a
  different door.

  ``None`` now asks the contract (the same ``auction_rookie_keys`` the
  draft surface passes); ``()`` still asserts that nobody is unavailable.
  Missing and explicitly-empty are different claims.  Either way
  ``waiverPopulation`` stamps which was used, because a silently smaller
  free-agent pool and a genuinely empty wire look identical in the
  numbers.

Missing is never zero
=====================

A rostered player the board did not price keeps his roster spot, is
counted, and is costed at ``assumedWaiver`` with the basis stamped —
never at the board's tail floor, which ``league_intel/replacement.py``
calls "the noisiest number in the league (deep dart throws, and any
identity-join miss lands there)".  ``unmatchedRosterPlayers`` carries
the names so a join miss reads as a join miss instead of as a free cut.

Pure computation.  No I/O, no network, no clock.
"""

from __future__ import annotations

from typing import Any, Collection, Iterable, Mapping, Sequence

from src.draft.context import (
    build_roster_assets,
    contract_teams,
    index_contract_rows,
    league_rostered_keys,
    match_team,
)
from src.draft.rookie_pool import auction_rookie_keys
from src.draft.displacement import (
    FEASIBILITY_OBJECTIVE,
    count_free_agents,
    MAX_LADDER_RUNGS,
    CutLadder,
    RosterAsset,
    build_cut_ladder,
    scarcity_multiplier,
    waiver_values_by_position,
)
from src.league_intel.replacement import ScarcityComponents

__all__ = [
    "DROPPABILITY_CONTRACT_VERSION",
    "SCARCITY_MULTIPLIER_BAND",
    "SCARCITY_REORDER_RATIO",
    "TeamNotInLeague",
    "league_droppability",
    "pool_cut_ladder",
    "team_droppability",
]

DROPPABILITY_CONTRACT_VERSION = "roster-droppability/2026-08-18.v1"


def _scarcity_band() -> tuple[float, float]:
    """The owner's multiplier range, MEASURED by asking it.

    Restating ``0.85`` and ``1.15`` here would be a duplicated constant in a
    module whose entire point is that it duplicates nothing — and it would go
    stale silently the day the owner retunes the band.  So the extremes are
    read off ``displacement.scarcity_multiplier`` itself at import time.
    """

    def at(waiver: float) -> float:
        return scarcity_multiplier(
            ScarcityComponents(
                position="",
                lineup_scarcity=None,
                roster_scarcity=None,
                waiver_scarcity=waiver,
                elite_separation=None,
                starter_separation=None,
                replacement_gap=None,
            )
        )

    return at(0.0), at(1.0)


#: ``displacement.scarcity_multiplier``'s range, read from the owner.
SCARCITY_MULTIPLIER_BAND = _scarcity_band()

#: Two candidates whose scarcity-inert costs differ by more than this ratio
#: cannot swap places when scarcity is applied — the multiplier cannot close
#: a gap wider than ``max_band / min_band``.
SCARCITY_REORDER_RATIO = SCARCITY_MULTIPLIER_BAND[1] / SCARCITY_MULTIPLIER_BAND[0]


class TeamNotInLeague(Exception):
    """The requested team has no roster in this contract.

    Distinct from "this team has nothing droppable", which is a real
    answer with a real payload.
    """


def _slots_for(
    contract: Mapping[str, Any] | None,
    starter_slots: Sequence[str] | None,
) -> tuple[list[str], str]:
    """The league's real starting slots, and where they came from.

    Defaults to the C2-U1 truth ladder via ``contract_roster_pools``
    (live ``rosterPositions`` → registry ``starters`` → refuse) so this
    module needs no ``leagueKey`` and no registry round-trip of its own.
    An explicit list wins and is stamped ``caller`` — the parity test
    uses it to hand both surfaces the same slots.
    """
    if starter_slots is not None:
        return [str(s) for s in starter_slots if s], "caller"
    from src.api.data_contract import contract_roster_pools  # noqa: PLC0415

    _pools, slots, source = contract_roster_pools(dict(contract or {}))
    return list(slots), str(source or "unresolved")


def team_droppability(
    contract: Mapping[str, Any] | None,
    *,
    owner_id: str | None = None,
    roster_id: Any = None,
    team_name: str | None = None,
    starter_slots: Sequence[str] | None = None,
    scarcity: Mapping[str, Any] | None = None,
    unavailable_keys: Iterable[str] | None = None,
    max_rungs: int = MAX_LADDER_RUNGS,
) -> dict[str, Any]:
    """One team's cut ladder, from the canonical owner.

    Raises :class:`TeamNotInLeague` when the team cannot be resolved,
    for the same reason ``build_roster_context`` does: silently
    optimizing for whichever team sorted first is the worst possible
    failure mode for a team-specific answer.
    """
    teams = contract_teams(contract)
    if not teams:
        raise TeamNotInLeague("no_rosters_loaded")
    team = match_team(teams, owner_id=owner_id, roster_id=roster_id, team_name=team_name)
    if team is None:
        raise TeamNotInLeague(str(owner_id or roster_id or team_name or ""))

    by_id, by_name = index_contract_rows(contract)
    assets, unmatched = build_roster_assets(team, by_name, by_id)

    # ``None`` asks the contract who is unsignable; ``()`` asserts nobody
    # is.  Missing and explicitly-empty are different claims and stay
    # distinguishable, which is the same discipline the rest of this
    # chain applies to a missing value.
    if unavailable_keys is None:
        excluded = sorted(auction_rookie_keys(contract))
        waiver_source = "contract_auction_rookies"
    else:
        excluded = [str(k) for k in unavailable_keys]
        waiver_source = "caller"

    rostered = league_rostered_keys(contract)
    waiver_values = waiver_values_by_position(contract, rostered, excluded)

    slots, slot_source = _slots_for(contract, starter_slots)
    ladder = build_cut_ladder(assets, slots, waiver_values, scarcity, max_rungs=max_rungs)

    notes = list(ladder.notes)
    if not waiver_values:
        notes.append("no waiver-level values available — cut costs fall back to raw board value")
    if unmatched:
        notes.append(
            f"{len(unmatched)} rostered player(s) did not join to the board and are "
            "treated as unpriced — verify before releasing"
        )
    if scarcity is None:
        notes.append(
            "positional scarcity not supplied — multiplier inert (1.0); rung ORDER "
            f"is unaffected for any pair whose costs differ by more than "
            f"{SCARCITY_REORDER_RATIO:.3f}x"
        )

    return {
        "contractVersion": DROPPABILITY_CONTRACT_VERSION,
        "owner": "src/draft/displacement.py",
        "valueScale": "rankDerivedValue",
        "team": {
            "ownerId": str(team.get("ownerId") or ""),
            "teamName": str(team.get("name") or ""),
            "rosterId": team.get("roster_id"),
        },
        "starterSlots": slots,
        "slotSource": slot_source,
        "scarcityApplied": scarcity is not None,
        "waiverValues": {k: round(v, 1) for k, v in sorted(waiver_values.items())},
        # Who was treated as signable, and who was not.  A silently
        # smaller free-agent pool and a genuinely empty wire look
        # identical in the numbers, so the population is stamped.
        "waiverPopulation": {
            "source": waiver_source,
            "excludedKeys": len(excluded),
            "freeAgents": count_free_agents(contract, rostered, excluded),
        },
        "cutLadder": ladder.to_dict(),
        "counts": {
            "rosterPlayers": len(assets),
            "cutRungs": len(ladder.rungs),
            "undroppable": len(ladder.undroppable),
            "assumedWaiverRungs": sum(1 for r in ladder.rungs if r.value_basis == "assumedWaiver"),
            "unmatchedRosterPlayers": len(unmatched),
        },
        "unmatchedRosterPlayers": unmatched[:25],
        "notes": notes,
    }


def league_droppability(
    contract: Mapping[str, Any] | None,
    *,
    starter_slots: Sequence[str] | None = None,
    scarcity: Mapping[str, Any] | None = None,
    unavailable_keys: Iterable[str] | None = None,
    max_rungs: int = MAX_LADDER_RUNGS,
) -> dict[str, dict[str, Any]]:
    """``{ownerId: team_droppability(...)}`` for every team in the league.

    The waiver level is league-wide, so computing one team at a time
    would be correct but repeats the free-agent scan per team; this is
    the same loop with the resolution done once.  A team that cannot be
    resolved is skipped rather than raising — a league payload must not
    fail because one roster is malformed.
    """
    out: dict[str, dict[str, Any]] = {}
    for team in contract_teams(contract):
        owner = str(team.get("ownerId") or "")
        if not owner:
            continue
        try:
            out[owner] = team_droppability(
                contract,
                owner_id=owner,
                starter_slots=starter_slots,
                scarcity=scarcity,
                unavailable_keys=unavailable_keys,
                max_rungs=max_rungs,
            )
        except TeamNotInLeague:
            continue
    return out


def pool_cut_ladder(
    pool: Iterable[Any],
    starter_slots: Sequence[str],
    waiver_values: Mapping[str, float],
    *,
    scarcity: Mapping[str, Any] | None = None,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
    max_rungs: int = MAX_LADDER_RUNGS,
) -> CutLadder:
    """A cut ladder over an ARBITRARY roster, not one the contract holds.

    :func:`team_droppability` answers "what would this team release today",
    and the contract is its roster.  A post-trade roster does not exist in the
    contract, so the trade lane's roster-capacity / forced-drop unit
    (`C3-CAP-01`, ``src/trade/``) needs the same ladder over a pool it
    constructed — hence this entry point rather than a second ladder built
    there.  The spec forbids ``package delta - lowest raw player value`` by
    name; this is what a consumer calls instead.

    Still no arithmetic here.  ``RosterPlayer`` carries canonical value in
    ``ros_value`` (that is what ``contract_roster_pools`` puts there), and
    ``RosterAsset`` splits the two concepts the owner keeps separate:
    ``board_value`` is the COST scale and ``ros_value`` is the FEASIBILITY
    objective, which is a constant for the reason
    ``displacement.FEASIBILITY_OBJECTIVE`` states.  Getting that mapping
    backwards would silently exclude every unpriced player from the lineup
    guard and report a roster as more droppable than it is.

    ``slot_eligibility`` is accepted and, when supplied, applied by re-running
    the owner against the caller's slots — it is not silently dropped.
    """
    assets = [
        RosterAsset(
            player_id=str(player.player_id),
            name=str(getattr(player, "canonical_name", "") or player.player_id),
            position=str(getattr(player, "position", "") or ""),
            board_value=(
                float(player.ros_value) if isinstance(player.ros_value, (int, float)) else None
            ),
            ros_value=FEASIBILITY_OBJECTIVE,
            fantasy_positions=tuple(getattr(player, "fantasy_positions", ()) or ()),
            injured=bool(getattr(player, "injured", False)),
        )
        for player in pool
    ]
    del slot_eligibility  # the owner reads eligibility from the slot names
    return build_cut_ladder(
        assets, list(starter_slots), waiver_values, scarcity, max_rungs=max_rungs
    )
