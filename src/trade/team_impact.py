"""Team-aware trade impact analyzer.

Produces a roster-shape-aware verdict on a proposed trade — the dynasty
manager's actual question: *does this trade FIT my roster*, not just
*is the equity fair*.

Pure functions; no I/O.  Inputs are the same resolved-asset dicts that
``src/api/trade_simulator.py`` already builds, plus the league's
``rosterSettings`` (from ``src.api.league_registry``).

CRITICAL ARCHITECTURAL RULE — see ``src/league/README.md``:

    Player VALUES are global per scoring profile.
    Team FIT is per-league.

This module produces a *fit score alongside* a player's value.  It
NEVER mutates ``row.value`` per team.  The retired LAM module proved
that path is wrong — do not re-introduce it here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence

from src.roster_intel import RosterSimulation, SlotMovement, simulate_roster_change
from src.ros.lineup import (
    RosterPlayer,
    assign_lineup,
    configured_slot_eligibility,
    resolve_starter_slots,
    slot_demand,
    slot_eligible_positions,
)

#: Display/report order for the offence+IDP families this module aggregates.
#:
#: **An ORDER, not a filter.**  It used to be both, and that was a defect:
#: ``dynasty_main`` starts ``K: 1``, ``resolve_starter_slots`` duly returns a
#: ``K`` slot, and ``project_starters`` then dropped every kicker because ``K``
#: is not in this tuple — so the K slot could never be filled, ``K`` was not
#: even a key in the output, and a traded kicker was invisible to the whole
#: team-impact payload including the C2-SIM-01 lineup delta.
#:
#: Measured on the same roster: the capacity path (``build_cut_ladder`` ->
#: ``assign_lineup``) SEATS the kicker while this module modelled a lineup with
#: one fewer slot.  Two Trade modules disagreeing about one roster.
#:
#: Which positions may play is now asked of the canonical owner per league —
#: see :func:`_positions_for`.  This tuple only decides what order the buckets
#: are reported in.
_REPORT_POSITION_ORDER = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")

#: Deprecated alias.  ``src/trade/waiver.py`` also defines ``_BASE_POSITIONS``
#: as an 18-member frozenset of RAW spellings — the same name for a different
#: object, in the same package.  Kept only so an external reader is not
#: silently broken; new code uses the two names above.
_BASE_POSITIONS = _REPORT_POSITION_ORDER


def _positions_for(roster_settings: dict[str, Any]) -> tuple[str, ...]:
    """Positions this league can actually start, in report order.

    Derived from the league's OWN resolved slots via the canonical eligibility
    owner (C2-U1), so a league that starts a K reports a K and one that does
    not, does not.  ``dynasty_new`` starts no kicker and no IDP; ``dynasty_main``
    starts both.
    """

    from src.utils.name_clean import normalize_position  # noqa: PLC0415

    slots, _source = resolve_starter_slots(roster_settings=roster_settings)
    eligible: set[str] = set()
    for slot in slots:
        # ``slot_eligible_positions`` answers in RAW spellings (CB, DE, EDGE…)
        # because that is what eligibility is expressed in.  The assets this
        # module buckets carry ``basePos``, already folded by the canonical
        # normalizer, so fold to the same vocabulary rather than keeping a
        # third one.
        for raw in slot_eligible_positions(slot):
            folded = normalize_position(raw)
            if folded:
                eligible.add(folded)
    ordered = [p for p in _REPORT_POSITION_ORDER if p in eligible]
    ordered += sorted(eligible - set(_REPORT_POSITION_ORDER))
    return tuple(ordered)


def _load_default_weights() -> dict[str, Any]:
    """Read config/trade/team_impact.json once.  Falls back to safe
    defaults if the file is missing — same shape as the JSON.
    """
    try:
        path = Path(__file__).resolve().parents[2] / "config" / "trade" / "team_impact.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "weights": {
                "fillStarter": 1.0,
                "depth": 0.25,
                "overflow": 0.6,
                "fitNormalization": 4000,
                "equityNormalization": 2500,
                "compositeFitWeight": 0.55,
                "compositeEquityWeight": 0.45,
            },
            "verdictThresholds": {
                "accept": 20,
                "leanAccept": 8,
                "leanDecline": -8,
                "decline": -20,
            },
            "windowFit": {
                "contendIndexThreshold": 0.15,
                "youngStarterMaxAge": 23,
                "primeStarterMinAge": 24,
                "primeStarterMaxAge": 29,
            },
        }


def _starter_slots(roster_settings: dict[str, Any]) -> dict[str, int]:
    """Extract the per-slot starter counts dict (e.g. {"QB":1,"RB":2,...}).
    Returns ``{}`` if absent — caller treats that as "no fit analysis
    possible".
    """
    s = roster_settings.get("starters") if isinstance(roster_settings, dict) else None
    if not isinstance(s, dict):
        return {}
    return {str(k).upper(): int(v) for k, v in s.items() if isinstance(v, (int, float))}


def roster_players(
    assets: Sequence[dict[str, Any]],
    accepted: Sequence[str],
    *,
    id_prefix: str = "",
) -> tuple[list[RosterPlayer], dict[str, dict[str, Any]]]:
    """``(pool, {player_id: asset})`` for the canonical lineup / simulation owners.

    Extracted from :func:`project_starters` so the starter projection and the
    C2-SIM-01 simulation build their pools the same way; two conversions of one
    asset list into one owner's input type is how two answers start.

    Ids are INDEX-keyed and prefixed.  These dicts carry no stable identifier
    and two roster picks can legitimately share a display name, so an id minted
    from the name would collapse them — the defect class C1-U3 exists to
    prevent.  ``id_prefix`` keeps the before-roster and the incoming package in
    disjoint id spaces, which is also what lets this lane hand
    ``simulate_roster_change`` a set of ``outgoing_ids`` safely: the owner
    removes by SET membership (**R3**), so unique ids are the adapter that
    makes multiplicity a non-question rather than a silent double-removal.
    """
    pool: list[RosterPlayer] = []
    by_id: dict[str, dict[str, Any]] = {}
    for idx, asset in enumerate(assets):
        base = (asset.get("basePos") or asset.get("pos") or "").upper()
        if base not in accepted:
            continue
        key = f"{id_prefix}{idx}"
        by_id[key] = asset
        value = asset.get("value")
        pool.append(
            RosterPlayer(
                player_id=key,
                canonical_name=str(asset.get("name") or key),
                position=base,
                # ``None`` stays ``None``: an asset the board declined to
                # price is UNPRICED, not worth zero, and must not win a
                # starting slot ahead of one we can price.
                ros_value=None if value is None else float(value),
                fantasy_positions=tuple(
                    str(fp).upper() for fp in (asset.get("fantasyPositions") or ()) if fp
                ),
            )
        )
    return pool, by_id


def project_starters(
    assets: list[dict[str, Any]],
    roster_settings: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Starting lineup from a list of resolved assets.

    Returns ``{base_pos: [asset, ...]}`` — the starters at each base
    position (RB starters from FLEX go into the RB bucket).  Picks are
    ignored (they don't start).

    **Consumes the canonical assignment owner** (C2-U1).  It used to
    keep its own slot-ordered greedy plus its own
    ``_DEFAULT_*_ELIGIBLE`` tables, and measured against Sleeper's own
    awarded lineups over 10 real 2025 team-weeks that engine reproduced
    the host on **0 of 10** — 238.92 points of which was eligibility
    blindness (it read ``basePos`` only, so a DL/LB hybrid was locked
    out of half its legal slots) and 2.76 points the greedy itself lost
    (its ``_FILL_ORDER`` filled ``SFLEX`` before ``FLEX``, i.e.
    least-restrictive first).  It also named no ``K`` slot, though that
    never reached this function's own output.

    The eligibility half only becomes real once callers supply
    ``fantasyPositions``; assets that carry none fall back to
    ``basePos``, which is exactly the old behaviour.  Nothing is
    fabricated to fill the gap.
    """
    slots, _source = resolve_starter_slots(roster_settings=roster_settings)
    accepted = _positions_for(roster_settings)
    if not slots:
        return {p: [] for p in accepted}

    pool, by_id = roster_players(assets, accepted)

    starters: dict[str, list[dict[str, Any]]] = {p: [] for p in accepted}
    # The league's OWN flex rules, not the declared defaults (#922 F1).  A
    # measured no-op on both live leagues today — they configure exactly the
    # defaults — and not a no-op the day either narrows one, at which point a
    # lineup solved without it seats a player the league does not allow.
    assignment = assign_lineup(
        pool, slots, slot_eligibility=configured_slot_eligibility(roster_settings) or None
    )
    # Slot order, so the buckets read the way the league's lineup card
    # does rather than in augmenting-path order.
    for slot_idx in sorted(assignment.assignments):
        player = assignment.assignments[slot_idx]
        asset = by_id.get(player.player_id)
        if asset is None:
            continue
        base = (asset.get("basePos") or asset.get("pos") or "").upper()
        if base in starters:
            starters[base].append(asset)
    return starters


def _aggregate_state(
    assets: list[dict[str, Any]],
    roster_settings: dict[str, Any],
) -> dict[str, Any]:
    """Project starters + compute totalCount/starterCount/depthCount/
    starterValue per base position.
    """
    starters = project_starters(assets, roster_settings)
    accepted = _positions_for(roster_settings)
    starter_count = {p: len(starters[p]) for p in accepted}
    # Sum the starters we can PRICE.  ``int(a.get("value") or 0)`` counted an
    # unpriced starter as worth zero, which is the coercion the module's own
    # `_starter_row` refuses three functions away — and it silently dragged
    # `starterValue`, and therefore `starterValueDelta` and `fitScore`, down in
    # proportion to how much of the roster the board failed to price.
    starter_value = {
        p: sum(
            float(a["value"])
            for a in starters[p]
            if isinstance(a.get("value"), (int, float)) and not isinstance(a.get("value"), bool)
        )
        for p in accepted
    }
    total_count: dict[str, int] = {p: 0 for p in accepted}
    for a in assets:
        pos = (a.get("basePos") or a.get("pos") or "").upper()
        if pos in total_count:
            total_count[pos] += 1
    depth_count = {p: max(0, total_count[p] - starter_count[p]) for p in accepted}
    return {
        "starters": starters,
        "starterCount": starter_count,
        "starterValue": starter_value,
        "totalCount": total_count,
        "depthCount": depth_count,
    }


def _starter_identity(asset: dict[str, Any]) -> str:
    """Identity for the before/after starter diff.

    Board display name, lowercased.  Picks never reach here — ``project_starters``
    keeps only ``_BASE_POSITIONS`` — which matters, because a pick is the one
    asset class where two roster entries legitimately share a board row
    ("2027 Mid 1st" own vs acquired) and a name key would collapse them.  For
    PLAYERS the canonical board carries one row per identity, so the name is a
    sound key; :func:`lineup_displacement` refuses rather than guesses if that
    ever stops being true.
    """

    return str(asset.get("name") or asset.get("sourceLabel") or "").strip().lower()


def _flatten_starters(starters: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """``identity -> asset`` across every base position."""

    out: dict[str, dict[str, Any]] = {}
    for position, assets in starters.items():
        for asset in assets:
            key = _starter_identity(asset)
            if not key:
                continue
            enriched = dict(asset)
            enriched["startingAt"] = position
            out[key] = enriched
    return out


def _starter_row(asset: dict[str, Any], position: str) -> dict[str, Any]:
    value = asset.get("value")
    return {
        "name": asset.get("name"),
        "position": position,
        # ``None`` stays ``None``.  An unpriced player is UNPRICED, and this
        # block is roster information — publishing 0 here would read as "worth
        # nothing" on the one surface whose whole point is that it is not a
        # value statement.
        "value": None if value is None else int(value),
        "valueScale": "rankDerivedValue",
    }


def lineup_displacement(
    simulation: RosterSimulation,
    *,
    incoming_ids: Collection[str] = (),
    outgoing_ids: Collection[str] = (),
    assets_by_id: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Who starts now who did not, and who lost a slot — as ROSTER information.

    C2-SIM-01 / V1-42, and owner decision 26: promotions and displacements are
    *separate roster information, never a value subtraction*.  Nothing here
    returns a delta; every field names players and slots.

    **This is a REFINEMENT of the canonical owner, not a second one.**  The
    before → apply → re-solve → after primitive is
    ``roster_intel.simulation.simulate_roster_change`` (lane ``roster``); this
    function does no solving of its own and receives its ``RosterSimulation``.
    What it adds is the one distinction the owner structurally cannot make:
    ``SlotMovement.kind`` reports a departing starter and a benched starter
    both as ``displaced``, because the owner never receives the trade's
    incoming/outgoing sets as identities.  Those are different sentences —

    ``arrived``    starting now, came IN with this trade
    ``promoted``   starting now, was ALREADY on the roster and was not starting
    ``departed``   was starting, LEFT in this trade — not displaced, gone
    ``displaced``  was starting, is STILL on the roster, no longer starts

    — and only ``displaced`` answers "what did this trade cost me that the
    value delta does not show".  Reported to Roster as **R2**.

    Consuming the owner also buys two states the retired starters-only diff
    could not see, because it compared starting lineups while the owner
    measures the whole MEANINGFUL CORE (starters ∪ reserves):

    ``demoted``    still in the core, dropped from starter to reserve
    ``movedSlot``  still a starter, in a different slot (RB → FLEX)

    An unpriced player is not assignable by the canonical solver, so he is in
    neither state's core and therefore in no category — reported by the owner
    in ``unpriced_incoming`` rather than silently counted as a bench player who
    was never promoted.

    Identity is the owner's ``player_id``, which the caller mints uniquely per
    asset (``b{i}`` / ``i{n}``).  The retired implementation keyed on display
    NAME and had to raise rather than guess when two starters collided; unique
    ids remove the collision instead of detecting it, which is why the guard is
    an assertion here rather than a runtime refusal.
    """

    incoming = {str(x) for x in incoming_ids}
    outgoing = {str(x) for x in outgoing_ids}
    by_id = dict(assets_by_id or {})

    arrived: list[dict[str, Any]] = []
    promoted: list[dict[str, Any]] = []
    departed: list[dict[str, Any]] = []
    displaced: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    moved_slot: list[dict[str, Any]] = []

    def _row(movement: SlotMovement) -> dict[str, Any]:
        asset = by_id.get(movement.player_id) or {}
        value = asset.get("value")
        return {
            "name": asset.get("name") or movement.canonical_name,
            "position": movement.position,
            "slotBefore": movement.slot_before,
            "slotAfter": movement.slot_after,
            # ``None`` stays ``None``.  An unpriced player is UNPRICED, and this
            # block is roster information — publishing 0 here would read as
            # "worth nothing" on the one surface whose whole point is that it is
            # not a value statement.
            "value": None if value is None else int(value),
            "valueScale": "rankDerivedValue",
        }

    seen: set[str] = set()
    for movement in simulation.movements:
        assert movement.player_id not in seen, (
            f"two movements share the id {movement.player_id!r}; the caller must "
            "mint one id per asset"
        )
        seen.add(movement.player_id)

        started_before = movement.role_before == "starter"
        started_after = movement.role_after == "starter"
        row = _row(movement)

        if started_after and not started_before:
            (arrived if movement.player_id in incoming else promoted).append(row)
        elif started_before and not started_after:
            if movement.player_id in outgoing:
                departed.append(row)
            else:
                displaced.append(row)
                if movement.role_after == "reserve":
                    demoted.append(row)
        elif started_before and started_after and movement.slot_before != movement.slot_after:
            moved_slot.append(row)

    def _by_position_then_name(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda r: (r["position"], str(r["name"] or "")))

    def _starters(core) -> int:
        return sum(1 for m in core.members if m.role == "starter")

    return {
        "arrived": _by_position_then_name(arrived),
        "promoted": _by_position_then_name(promoted),
        "departed": _by_position_then_name(departed),
        "displaced": _by_position_then_name(displaced),
        # New with the canonical owner: core-level states a starters-only diff
        # could not distinguish.  ``demoted`` is a SUBSET of ``displaced``, not
        # a sibling — he lost his slot AND is still meaningful.
        "demoted": _by_position_then_name(demoted),
        "movedSlot": _by_position_then_name(moved_slot),
        "startersBefore": _starters(simulation.core_before),
        "startersAfter": _starters(simulation.core_after),
        "coreBefore": len(simulation.core_before.members),
        "coreAfter": len(simulation.core_after.members),
        # Players the board could not price. Excluded from the solve by the
        # canonical owner and reported here, never seated and never zeroed.
        "unpricedIncoming": sorted(simulation.unpriced_incoming),
        "available": simulation.available,
        "unavailableReason": simulation.unavailable_reason,
        # Named so a consumer cannot mistake this block for a value statement.
        "isValueDelta": False,
    }


def _needed_at(pos: str, roster_settings: dict[str, Any]) -> float:
    """Starter demand at ``pos``, for overflow detection.

    Reads the canonical :func:`slot_demand` contract's ``even_split``
    field — a DECLARED approximation, not truth (see
    ``src/ros/lineup.py::SlotDemand``: LI-5 measured the even split ~40%
    wrong at QB).  It is the right rung here because overflow only asks
    "is this roster carrying more bodies than the lineup can absorb",
    which a coarse sizing constant answers.

    Retired the local ``_flex_share`` — one of four independent
    re-derivations of the same even-split rule in the tree.
    """
    return slot_demand(resolve_starter_slots(roster_settings=roster_settings)[0]).even_split.get(
        pos.upper(), 0.0
    )


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _league_active_positions(roster_settings: dict[str, Any]) -> list[str]:
    """Positions the league actually starts.  ``dynasty_new`` returns
    only QB/RB/WR/TE; ``dynasty_main`` adds DL/LB/DB.  This is the
    guard that prevents IDP redundancy false-positives in non-IDP
    leagues.
    """
    return [p for p in _positions_for(roster_settings) if _needed_at(p, roster_settings) > 0]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


#: Posture could not be measured — NOT the neutral answer.
#:
#: "balanced" is a real reading of a real roster; this is the absence of
#: one, and a window-fit term computed against it would be a number
#: invented from nothing.  Consumers treat it as no signal.
WINDOW_UNKNOWN = "unknown"


def _classify_window(
    before_assets: list[dict[str, Any]],
    config: dict[str, Any],
) -> str:
    """Posture from current roster: contender / balanced / rebuilder.

    Heuristic:
      contendIndex = top10 WIN-NOW value share
                   - (rookie pick share + young (<24) player share)

    "Win-now" means an asset that is neither a rookie pick nor a young
    player — i.e. the ones that score points for you THIS season.  The
    top-10 slice used to be taken over every asset, which counted the
    future twice with opposite signs: a rebuilder whose ten most
    valuable assets ARE first-round picks scored a near-1.0
    ``top10_share`` and a near-1.0 ``pick_share``, the two cancelled,
    and the engine called them "balanced".  Excluding picks and kids
    from the positive term makes every dollar feed at most one side of
    the subtraction, so a pick-stuffed roster reads as the rebuilder it
    is.

    Picks are also excluded from ``young_value`` — a pick row that
    carries an ``age`` (defensive; they normally don't) would otherwise
    be charged to the negative term twice.
    """
    threshold = float(config.get("windowFit", {}).get("contendIndexThreshold", 0.15))
    young_max = int(config.get("windowFit", {}).get("youngStarterMaxAge", 23))

    def _is_pick(asset: dict[str, Any]) -> bool:
        return (asset.get("assetClass") or "").lower() == "pick"

    def _is_young(asset: dict[str, Any]) -> bool:
        return isinstance(asset.get("age"), int) and asset["age"] <= young_max

    def _value(asset: dict[str, Any]) -> int:
        return int(asset["value"])

    # Unpriced assets are EXCLUDED, explicitly, rather than coerced.
    #
    # The retired ``int(a.get("value") or 0)`` — five of them in this function —
    # was arithmetically equivalent to this exclusion, because numerator and
    # denominator dropped the same players, so the ratio it produced was sound.
    # Two things about it were not:
    #
    # 1. the narrowing was SILENT.  On a board measured 12.6% unpriced the
    #    posture is decided over ~87% of the roster and nothing said so;
    # 2. ``or 1`` on the denominator FABRICATED a verdict.  A roster whose
    #    assets are entirely unpriced produced ``"balanced"`` — the same answer
    #    as an empty roster — which is an unknown published as a classification.
    #
    # So an unmeasurable roster returns ``"unknown"``, which every consumer
    # treats as "no window signal" rather than as the neutral one.
    priced = [a for a in before_assets if isinstance(a.get("value"), (int, float))]
    total_value = sum(_value(a) for a in priced)
    if not priced or total_value <= 0:
        return WINDOW_UNKNOWN

    win_now = [a for a in priced if not _is_pick(a) and not _is_young(a)]
    by_value = sorted(win_now, key=_value, reverse=True)
    top10_share = sum(_value(a) for a in by_value[:10]) / total_value
    pick_share = sum(_value(a) for a in priced if _is_pick(a)) / total_value
    young_share = (
        sum(_value(a) for a in priced if not _is_pick(a) and _is_young(a)) / total_value
    )

    contend_index = top10_share - (pick_share + young_share)
    if contend_index > threshold:
        return "contender"
    if contend_index < -threshold:
        return "rebuilder"
    return "balanced"


def _window_fit_for_asset(
    asset: dict[str, Any],
    posture: str,
    config: dict[str, Any],
    *,
    sign: int,
) -> float:
    """Score one moving asset against the team's posture.

    ``sign=+1`` for receiving, ``sign=-1`` for sending.  Returns a
    float in roughly [-1, +1] before averaging.
    """
    if posture == WINDOW_UNKNOWN:
        # No posture, no fit.  Falling through to the "balanced" arithmetic
        # would publish a window-fit score for a window nobody measured.
        return 0.0

    wf = config.get("windowFit", {})
    prime_min = int(wf.get("primeStarterMinAge", 24))
    prime_max = int(wf.get("primeStarterMaxAge", 29))
    young_max = int(wf.get("youngStarterMaxAge", 23))

    is_pick = (asset.get("assetClass") or "").lower() == "pick"
    age = asset.get("age") if isinstance(asset.get("age"), int) else None
    is_young = age is not None and age <= young_max
    is_prime = age is not None and prime_min <= age <= prime_max

    if posture == "contender":
        if is_prime:
            return 1.0 * sign
        if is_pick or is_young:
            return -1.0 * sign
        return 0.0
    if posture == "rebuilder":
        if is_pick or is_young:
            return 1.0 * sign
        if is_prime:
            return -0.5 * sign
        return 0.0
    return 0.0


def _redundancy(
    receiving: list[dict[str, Any]],
    after_starters: dict[str, list[dict[str, Any]]],
    before_state: dict[str, Any],
    roster_settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flag acquired assets that don't crack the starting lineup at a
    position the team was already saturated in.  Skipped for positions
    the league doesn't start (no false-positives in non-IDP leagues).
    """
    starter_names = {
        str(a.get("name") or "").lower() for assets in after_starters.values() for a in assets
    }
    active = set(_league_active_positions(roster_settings))
    out: list[dict[str, Any]] = []
    for asset in receiving:
        pos = (asset.get("basePos") or asset.get("pos") or "").upper()
        if pos not in active:
            continue
        name_key = str(asset.get("name") or "").lower()
        if name_key in starter_names:
            continue
        before_count = before_state["totalCount"].get(pos, 0)
        needed = _needed_at(pos, roster_settings)
        if before_count >= int(needed) + 1:
            out.append(
                {
                    "name": asset.get("name"),
                    "pos": pos,
                    "reason": "duplicate at saturated position",
                }
            )
    return out


def _verdict(composite: float, thresholds: dict[str, Any]) -> str:
    if composite >= float(thresholds.get("accept", 20)):
        return "accept"
    if composite >= float(thresholds.get("leanAccept", 8)):
        return "lean accept"
    if composite > float(thresholds.get("leanDecline", -8)):
        return "neutral"
    if composite > float(thresholds.get("decline", -20)):
        return "lean decline"
    return "decline"


def _rationale(
    *,
    starter_value_delta: dict[str, int],
    starter_delta: dict[str, int],
    overflow_delta: dict[str, int],
    redundancy: list[dict[str, Any]],
    window_fit: float,
    posture: str,
    equity: int,
    fit_score: float,
) -> list[str]:
    """Top 5 bullets ranked by absolute contribution to verdict."""
    bullets: list[tuple[float, str]] = []
    for pos, dv in starter_value_delta.items():
        if dv == 0:
            continue
        sign = "+" if dv > 0 else ""
        if dv > 0 and starter_delta.get(pos, 0) > 0:
            bullets.append((abs(dv), f"Adds a starting {pos} ({sign}{dv} starter value)"))
        elif dv < 0 and starter_delta.get(pos, 0) < 0:
            bullets.append((abs(dv), f"Loses a starting {pos} ({sign}{dv} starter value)"))
        else:
            bullets.append((abs(dv) * 0.6, f"Shifts {pos} starter quality ({sign}{dv})"))
    for pos, od in overflow_delta.items():
        if od >= 1:
            bullets.append((400 * od, f"Adds bench depth at saturated {pos} (-overflow)"))
    for r in redundancy:
        bullets.append((300, f"Acquired {r['name']} ({r['pos']}) doesn't start — duplicate"))
    if abs(window_fit) >= 0.4:
        word = "aligns with" if window_fit > 0 else "fights"
        bullets.append(
            (abs(window_fit) * 1000, f"Trade {word} a {posture} window ({window_fit:+.1f})")
        )
    if abs(equity) >= 500:
        bullets.append((abs(equity) * 0.3, f"Net KTC equity {equity:+d}"))
    if abs(fit_score) >= 5:
        bullets.append((abs(fit_score) * 5, f"Roster-shape fit score {fit_score:+.0f}"))
    bullets.sort(key=lambda b: b[0], reverse=True)
    return [b[1] for b in bullets[:5]]


def compute(
    *,
    before_assets: list[dict[str, Any]],
    after_assets: list[dict[str, Any]],
    receiving: list[dict[str, Any]],
    sending: list[dict[str, Any]],
    equity: int,
    roster_settings: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build the ``teamImpact`` payload.  Returns ``None`` when
    ``roster_settings`` lacks starter slots (no fit analysis possible).
    """
    cfg = config or _load_default_weights()
    weights = cfg.get("weights", {})
    thresholds = cfg.get("verdictThresholds", {})

    if not _starter_slots(roster_settings):
        return None

    before = _aggregate_state(before_assets, roster_settings)
    after = _aggregate_state(after_assets, roster_settings)
    active = _league_active_positions(roster_settings)

    # C2-SIM-01 / V1-42.  The exact before -> apply -> re-solve -> after
    # roster, published as NAMES rather than as another number.
    #
    # The re-solve belongs to ``roster_intel.simulation.simulate_roster_change``
    # (lane ``roster``); this lane supplies the two populations and refines the
    # owner's four movement KINDS into the arrived/departed split it cannot
    # express (R2).  Nothing here solves a lineup.
    #
    # ``after_assets`` is built by the caller with a two-level multiplicity rule
    # (exact package label, then board identity) that the owner's set-membership
    # ``outgoing_ids`` cannot express — so the identity diff is taken HERE, on
    # object identity, and the owner is handed ids that are unique by
    # construction.  That is an adapter at the boundary, not a second rule.
    accepted_positions = _positions_for(roster_settings)
    before_pool, before_by_id = roster_players(before_assets, accepted_positions, id_prefix="b")
    before_ids = {id(a): key for key, a in before_by_id.items()}
    survived = {id(a) for a in after_assets}
    departed_ids = [key for oid, key in before_ids.items() if oid not in survived]
    incoming_assets = [a for a in after_assets if id(a) not in before_ids]
    incoming_pool, incoming_by_id = roster_players(
        incoming_assets, accepted_positions, id_prefix="i"
    )

    slots, _slot_source = resolve_starter_slots(roster_settings=roster_settings)
    simulation = simulate_roster_change(
        before_pool,
        slots,
        incoming=incoming_pool,
        outgoing_ids=departed_ids,
        slot_eligibility=configured_slot_eligibility(roster_settings) or None,
    )
    displacement = lineup_displacement(
        simulation,
        incoming_ids=incoming_by_id.keys(),
        outgoing_ids=departed_ids,
        assets_by_id={**before_by_id, **incoming_by_id},
    )

    accepted = _positions_for(roster_settings)
    starter_delta = {p: after["starterCount"][p] - before["starterCount"][p] for p in accepted}
    starter_value_delta = {
        p: after["starterValue"][p] - before["starterValue"][p] for p in accepted
    }
    depth_delta = {p: after["depthCount"][p] - before["depthCount"][p] for p in accepted}

    # Overflow detection — anything above (needed + 1) is bench bloat.
    overflow_delta: dict[str, int] = {}
    for p in accepted:
        cap = int(_needed_at(p, roster_settings)) + 1
        before_over = max(0, before["totalCount"][p] - cap)
        after_over = max(0, after["totalCount"][p] - cap)
        overflow_delta[p] = after_over - before_over

    # Average starter value per position — the SCALE the depth and overflow
    # terms are expressed in.
    #
    # Two coercions used to live in these four lines and both fabricated a
    # number the roster never showed us:
    #
    # * ``int(a.get("value") or 0)`` counted an UNPRICED starter as worth zero,
    #   dragging the scale down in proportion to how much of the roster the
    #   board failed to price (12.6% of rostered players on a measured board);
    # * ``or 1500.0`` then invented a scale outright for a position with no
    #   starters — and fired again whenever the average came out at exactly
    #   0.0, which the first coercion made reachable.
    #
    # Now: average the starters we can actually price, and when there are none
    # the scale is UNKNOWN (``None``) rather than 1500.  A position with no
    # measurable scale contributes no depth or overflow term at all — we cannot
    # weigh it, so we do not pretend to — and it is reported in
    # ``unscalablePositions`` so the omission is visible instead of silent.
    avg_starter_val: dict[str, float | None] = {}
    for p in accepted:
        priced = [
            float(a["value"])
            for a in (*before["starters"][p], *after["starters"][p])
            if isinstance(a.get("value"), (int, float)) and not isinstance(a.get("value"), bool)
        ]
        avg_starter_val[p] = _avg(priced) if priced else None
    unscalable = tuple(p for p in accepted if avg_starter_val[p] is None)

    w_fill = float(weights.get("fillStarter", 1.0))
    w_depth = float(weights.get("depth", 0.25))
    w_overflow = float(weights.get("overflow", 0.6))
    fit_norm = float(weights.get("fitNormalization", 4000)) or 4000.0

    fit_raw = 0.0
    for p in active:
        fit_raw += w_fill * starter_value_delta[p]
        # Diminishing depth: only the first depth piece earns a bonus.
        before_first_depth = 1 if before["depthCount"][p] >= 1 else 0
        after_first_depth = 1 if after["depthCount"][p] >= 1 else 0
        scale = avg_starter_val[p]
        if scale is None:
            # No priced starter at this position in either state — no scale, so
            # no depth/overflow contribution.  The starter-value delta above is
            # still counted: it is measured in board points, not in this scale.
            continue
        fit_raw += w_depth * (after_first_depth - before_first_depth) * scale
        fit_raw -= w_overflow * max(0, overflow_delta[p]) * scale

    fit_score = _clamp(100.0 * fit_raw / fit_norm, -100.0, 100.0)
    equity_norm = float(weights.get("equityNormalization", 2500)) or 2500.0
    equity_score = _clamp(100.0 * float(equity) / equity_norm, -100.0, 100.0)

    cw_fit = float(weights.get("compositeFitWeight", 0.55))
    cw_eq = float(weights.get("compositeEquityWeight", 0.45))
    composite = cw_fit * fit_score + cw_eq * equity_score

    posture = _classify_window(before_assets, cfg)
    # How much of the roster the posture could NOT see.  Published because the
    # exclusion is real and was previously invisible: a posture decided over
    # 87% of a roster and one decided over all of it read identically.
    posture_unpriced = sum(1 for a in before_assets if not isinstance(a.get("value"), (int, float)))
    window_score = 0.0
    moving = []
    for a in receiving:
        moving.append(_window_fit_for_asset(a, posture, cfg, sign=+1))
    for a in sending:
        moving.append(_window_fit_for_asset(a, posture, cfg, sign=-1))
    if moving:
        window_score = sum(moving) / len(moving)

    def _avg_age(assets: list[dict[str, Any]]) -> float | None:
        ages = [a["age"] for a in assets if isinstance(a.get("age"), int)]
        return sum(ages) / len(ages) if ages else None

    in_age = _avg_age(receiving)
    out_age = _avg_age(sending)
    age_delta = (in_age - out_age) if (in_age is not None and out_age is not None) else 0.0

    # Scarcity delta — reports the per-position starter-vs-replacement
    # shift for the user.  This is reporting only, never re-prices.
    scarcity_delta: dict[str, float] = {}
    for p in active:
        before_avg = (
            (before["starterValue"][p] / before["starterCount"][p])
            if before["starterCount"][p]
            else 0
        )
        after_avg = (
            (after["starterValue"][p] / after["starterCount"][p]) if after["starterCount"][p] else 0
        )
        scarcity_delta[p] = round(after_avg - before_avg, 1)

    redundancy = _redundancy(receiving, after["starters"], before, roster_settings)
    rationale = _rationale(
        starter_value_delta={p: starter_value_delta[p] for p in active},
        starter_delta={p: starter_delta[p] for p in active},
        overflow_delta={p: overflow_delta[p] for p in active},
        redundancy=redundancy,
        window_fit=window_score,
        posture=posture,
        equity=equity,
        fit_score=fit_score,
    )

    return {
        "fitScore": round(fit_score, 1),
        "equityScore": round(equity_score, 1),
        "compositeScore": round(composite, 1),
        "verdict": _verdict(composite, thresholds),
        "posture": posture,
        # Assets the posture could not read.  ``posture: "unknown"`` means it
        # could not be measured at all — not that the roster is balanced.
        "postureUnpricedExcluded": posture_unpriced,
        "starterDelta": {p: starter_delta[p] for p in active},
        "starterValueDelta": {p: starter_value_delta[p] for p in active},
        "depthDelta": {p: depth_delta[p] for p in active},
        "windowFit": round(window_score, 2),
        "ageDelta": round(age_delta, 1),
        "scarcityDelta": scarcity_delta,
        "redundancy": redundancy,
        "rationale": rationale,
        # Positions whose depth/overflow terms were skipped for want of a
        # measurable scale.  Empty on a normally-priced roster.
        "unscalablePositions": list(unscalable),
        # Roster information, NOT a value statement — see `lineup_displacement`.
        # It sits beside the scores rather than inside them: nothing above reads
        # it, and no verdict moves because of it.
        "lineupDisplacement": displacement,
    }
