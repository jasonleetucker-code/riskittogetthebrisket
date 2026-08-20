"""Roster capacity and forced drops — the canonical owner for trade evaluation.

What this answers
─────────────────
"If this trade happens, does the roster still fit — and if not, who has to
go and what are they worth?"

Nothing in the trade surface could answer that before 2026-08-18.
``src/api/trade_simulator.py`` accepted ``roster_settings`` and used it only to
reach ``team_impact`` for starter slots and positional need; ``suggestions.py``,
``finder.py`` and ``angle.py`` proposed 2-for-1s with no notion of a roster cap
at all.  The single legality check in the whole repo lives in
``roster_intel/packages.py::_check_legality`` and is ``/api/gameplan``-only.

That is not an edge case in this league.  Measured on the 2026-08-18 board,
``dynasty_main`` carries a 58-man cap and its twelve rosters hold
``[45, 46, 53, 55, 56, 57, 58, 58, 58, 58, 58, 58]`` — **six teams are already
at the cap**.  For half the league every 2-for-1 costs a release, and until now
the released value was presented as free.

Reporting, not rejecting
────────────────────────
``_check_legality`` REFUSES an over-cap package, and that is right for a
package *generator* deciding what to put on a Pareto frontier.  It is wrong for
a simulator answering a question the user typed in, and wrong for a suggestion
list that would silently shorten.  Both consume the same counting rule; the
difference is what they do with the answer.  This module only ever *reports*.

Consumed, never rebuilt
───────────────────────
Every primitive here already existed, built for Perfect Draft:

* ``src/draft/displacement.py`` — ``build_cut_ladder``, ``effective_cut_cost``,
  ``waiver_values_by_position``, ``RosterAsset``.  The cut ladder is
  lineup-validated by the exact solver: a player is only droppable if releasing
  him does not reduce how many starting slots the roster can fill.
* ``src/draft/context.py`` — ``build_roster_assets`` (the roster ↔ board join),
  ``_index_contract_rows``.
* ``src/ros/lineup.py`` — ``load_league_starter_slots``.  No slot table lives
  here; that owner is canonical (C2-U1).

One cut ladder, two consumers: ``/api/draft/roster-context`` and this.

Three things that are load-bearing
──────────────────────────────────
**Draft picks do not occupy roster spots.**  Verified on the live contract
rather than assumed: ``rosterSize`` is 58, the largest roster holds exactly 58
*players*, and the same teams hold 10-23 picks besides.  So capacity counts
players and ignores picks entirely, and a pick-for-player trade is NOT
capacity-neutral.

**An unresolved player still occupies a spot.**  Counts come from the roster
and the request, never from what the board managed to price — dropping an
unjoinable name would understate roster pressure, which is the direction that
hides a forced drop.  Their *value* is a separate question and is reported as
missing.

**An unknown cap is UNKNOWN, never unlimited.**  A league with no
``rosterSize`` yields ``rosterLimit: None`` and ``overLimitAfter: None`` with a
note.  Coercing it to "no limit" would make every trade look free, which is the
optimistic-default failure the coercion gate exists to catch.

Taxi membership is UNKNOWN here, and unknown is not zero
───────────────────────────────────────────────────────
Sleeper's ``players`` array is the WHOLE roster — taxi and reserve players are
members of it as well as of their own arrays (``src/sharp/roster_collect.py``
documents this, and reads ``taxi`` / ``reserve`` to LABEL those same ids).  The
canonical contract's ``sleeper.teams[]`` block carries ``players`` /
``playerIds`` and **not** ``taxi``, so from here we can count the roster but
cannot tell which of its members occupy taxi slots.

That matters in the direction opposite to the one this module first claimed.
Counting every listed player against the active cap does not understate open
spots — it **overstates roster pressure**, and in a taxi league it can invent
forced drops that the league would not require.  ``dynasty_new`` carries 5 taxi
slots against a 24-man roster, so the error is up to five players wide.

Neither guess is available:

* assuming taxi occupancy 0 overstates pressure (the old behaviour);
* assuming full taxi relief understates it and would hide real forced drops.

So the answer is BRACKETED rather than guessed.  With ``taxiSize`` slots and
unknown membership, active occupancy lies in
``[size - min(taxiSize, size), size]``, ``overLimitAfter`` is published as a
MIN/MAX pair, ``certainty`` is ``"partial"``, and ``requiresDrops`` is ``None``
when the range straddles zero.  ``forcedDrops`` then carries the worst case and
says so via ``forcedDropsAreUpperBound``.

A league with ``taxiSize == 0`` — ``dynasty_main`` — is unaffected: the range
collapses and ``certainty`` is ``"exact"``.

Making this exact needs ``taxi`` on the contract's team block, which is the
contract owner's surface, not this module's.  Recorded rather than reached for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from src.draft.context import _league_scarcity, _norm, build_roster_assets, index_contract_rows
from src.draft.displacement import (
    RosterAsset,
    waiver_values_by_position,
)
from src.roster_intel import pool_cut_ladder, simulate_roster_change
from src.ros.lineup import RosterPlayer

__all__ = [
    "CapacityContext",
    "ForcedDrop",
    "RosterCapacity",
    "assess_roster_capacity",
    "build_capacity_context",
    "league_roster_limit",
    "league_taxi_size",
]


# ── League caps — ONE resolver ───────────────────────────────────────
#
# ``draft/context._roster_size_for`` and ``api/gameplan._roster_limit`` both
# read ``rosterSettings.rosterSize`` behind their own try/except.  Two answers
# to "what is this league's roster cap" is one too many; both now delegate here.


def _roster_settings_for(league_key: str | None) -> Mapping[str, Any] | None:
    try:
        from src.api.league_registry import (  # noqa: PLC0415
            get_default_league,
            get_league_by_key,
        )

        cfg = get_league_by_key(league_key) if league_key else get_default_league()
    except Exception:  # noqa: BLE001 — registry problems must not break a caller
        return None
    if cfg is None:
        return None
    settings = getattr(cfg, "roster_settings", None)
    return settings if isinstance(settings, Mapping) else None


def league_roster_limit(
    league_key: str | None,
    roster_settings: Mapping[str, Any] | None = None,
) -> int | None:
    """The league's roster-size cap, or ``None`` when it is unknown.

    ``None`` means UNKNOWN.  It does not mean unlimited, and no caller may
    treat it as such.

    ``roster_settings`` wins over the registry when supplied — the caller
    already holding the league's settings (``simulate_trade`` does) should not
    make the resolver go and look them up again, and a test must be able to
    state a league shape without a live registry.
    """
    settings = roster_settings if isinstance(roster_settings, Mapping) else None
    if settings is None:
        settings = _roster_settings_for(league_key)
    if not settings:
        return None
    raw = settings.get("rosterSize")
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return None
    return size if size > 0 else None


def league_taxi_size(
    league_key: str | None,
    roster_settings: Mapping[str, Any] | None = None,
) -> int:
    """Taxi-squad size, or 0.  See the module docstring: NOT modelled."""
    settings = roster_settings if isinstance(roster_settings, Mapping) else None
    if settings is None:
        settings = _roster_settings_for(league_key)
    if not settings:
        return 0
    raw = settings.get("taxiSize")
    # An ABSENT taxi setting means the league has no taxi squad — that is the
    # registry's convention, and both live leagues state the key explicitly.
    # Written out rather than coerced with ``or 0`` so it is a decision rather
    # than a default: the number only ever drives a note, because taxi relief
    # is not modelled at all.
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


# ── Result types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ForcedDrop:
    """One player the roster must release for this trade to be legal."""

    player_id: str
    name: str
    position: str
    #: ``rankDerivedValue``.  ``None`` when the board declined to price him —
    #: reported, NEVER counted as zero.
    value: float | None
    #: Effective Cut Cost: value over replacement at his position, scarcity
    #: adjusted.  The honest "what does releasing him actually cost".
    effective_cut_cost: float
    #: ``"board"`` or ``"assumedWaiver"`` (unranked players sit at waiver level
    #: by definition).
    value_basis: str
    #: 1-based ladder position; rung 1 goes first.
    rung: int
    #: What releasing him ACTUALLY costs this roster: ``base x scarcity``.
    #:
    #: ``effective_cut_cost`` above is ``max(0, base - waiver) x scarcity`` and
    #: is **0 for every player at or below waiver level** — which, on a roster
    #: that is full, is exactly the tail the ladder selects. Measured on the
    #: 2026-08-18 board: all twelve ``dynasty_main`` rosters produce forced
    #: drops whose ECC is 0.0, so ``forced_drop_cut_cost`` summed to 0.0 while
    #: ``forced_drop_value`` was 3,964 on the same trade.
    #:
    #: ECC is not wrong — it answers "what do I lose versus the wire", and
    #: Bobby Wagner (1,312) really is below the LB waiver level (1,740). It is
    #: the wrong QUESTION here: the vacated spot is consumed by the incoming
    #: player, so there is no wire pickup to net against. Charging value over
    #: replacement gives credit for a replacement you cannot sign.
    #:
    #: Perfect Draft hit this first and CLAUDE.md records its answer —
    #: "releaseCost = baseValue x scarcityMultiplier ... ECC itself is unchanged
    #: for its other consumers". This consumes that same rule rather than
    #: inventing a third notion of what a cut costs.
    release_cost: float = 0.0
    #: Waiver level at his position, and the scarcity multiplier applied.
    #: Published so the two costs above can be reconciled by a reader.
    waiver_value: float = 0.0
    scarcity_multiplier: float = 1.0
    #: True when this player ARRIVED in the trade being evaluated.  Not hidden:
    #: "this trade forces you to release the player you just acquired" is a
    #: real signal, and suppressing it would make the cheapest legal path
    #: invisible.
    acquired_in_trade: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.name,
            "position": self.position,
            "value": None if self.value is None else round(self.value, 1),
            "effectiveCutCost": round(self.effective_cut_cost, 1),
            "releaseCost": round(self.release_cost, 1),
            "waiverValue": round(self.waiver_value, 1),
            "scarcityMultiplier": round(self.scarcity_multiplier, 4),
            "valueBasis": self.value_basis,
            "rung": self.rung,
            "acquiredInTrade": self.acquired_in_trade,
            "valueScale": "rankDerivedValue",
        }


@dataclass(frozen=True)
class RosterCapacity:
    """What a trade does to a roster's legality."""

    roster_limit: int | None
    taxi_size: int
    size_before: int
    size_after: int
    incoming: int
    outgoing: int
    open_spots_before: int | None
    open_spots_after: int | None
    #: How many players over the cap.  ``None`` when the cap is unknown, and
    #: also ``None`` when taxi membership is unknown and the bracket straddles
    #: — see ``over_limit_after_min`` / ``_max``.  A point estimate here is a
    #: claim of certainty and must never be published without one.
    over_limit_before: int | None
    over_limit_after: int | None
    #: ``"exact"`` when active occupancy is known, ``"partial"`` when taxi
    #: membership is invisible and the answer is a range.
    certainty: str = "exact"
    #: How many of the ``outgoing`` names the roster does NOT hold.  Normally
    #: 0.  Reachable — Angle lets a user select any player on the BOARD, not
    #: only one they own — and published rather than corrected away, because
    #: "you cannot trade him, he is not yours" is the caller's answer to give,
    #: not this module's to swallow.  The COUNTS below already exclude these,
    #: so a name the roster never had cannot free a spot.
    outgoing_not_on_roster: int = 0
    #: Bounds on ``over_limit_after``.  Equal to it when ``certainty`` is
    #: ``"exact"``.
    over_limit_after_min: int | None = None
    over_limit_after_max: int | None = None
    #: True when every forced drop tied on effective cut cost, so the cut
    #: ladder's rung order carried no priority and the drops below are ordered
    #: by ``release_cost`` instead.  See the note in ``assess_roster_capacity``.
    rung_order_was_tied: bool = False
    #: Bounds on how many roster members could be sitting on taxi slots.
    taxi_occupied_min: int = 0
    taxi_occupied_max: int = 0
    forced_drops: list[ForcedDrop] = field(default_factory=list)
    #: Total ``rankDerivedValue`` released.  ``None`` when the cap is unknown;
    #: excludes unpriced players, whose count is published separately so the
    #: total is never quietly understated by treating missing as zero.
    forced_drop_value: float | None = None
    forced_drop_cut_cost: float | None = None
    #: Sum of ``ForcedDrop.release_cost`` — the honest "what does this trade
    #: cost me in releases". See ``ForcedDrop.release_cost`` for why
    #: ``forced_drop_cut_cost`` beside it is structurally 0 on a full roster.
    forced_drop_release_cost: float | None = None
    unpriced_forced_drops: int = 0
    #: True when the cut ladder ran out before the roster reached legal size —
    #: "no legal path modelled" and "no drops needed" render identically and
    #: mean opposite things.
    ladder_exhausted: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def requires_drops(self) -> bool | None:
        """True / False / **None when unknown**.

        ``None`` is reachable and load-bearing: with unknown taxi membership a
        roster can be over the cap or not depending on how many of its members
        sit on taxi, and collapsing that to ``False`` hides real forced drops
        while collapsing it to ``True`` invents them.
        """
        if self.over_limit_after is not None:
            return bool(self.over_limit_after)
        if self.roster_limit is None:
            return None
        lo, hi = self.over_limit_after_min, self.over_limit_after_max
        if lo is None or hi is None:
            return None
        if hi == 0:
            return False  # legal under every taxi assignment
        if lo > 0:
            return True  # over the cap under every taxi assignment; only the
            # COUNT is uncertain, and that distinction is the point of the
            # bracket — "how many" being unknown does not make "whether"
            # unknown.
        return None  # the range straddles zero — genuinely unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "rosterLimit": self.roster_limit,
            "taxiSize": self.taxi_size,
            "sizeBefore": self.size_before,
            "sizeAfter": self.size_after,
            "incoming": self.incoming,
            "outgoing": self.outgoing,
            "outgoingNotOnRoster": self.outgoing_not_on_roster,
            "openSpotsBefore": self.open_spots_before,
            "openSpotsAfter": self.open_spots_after,
            "overLimitBefore": self.over_limit_before,
            "overLimitAfter": self.over_limit_after,
            "overLimitAfterMin": self.over_limit_after_min,
            "overLimitAfterMax": self.over_limit_after_max,
            "certainty": self.certainty,
            "requiresDrops": self.requires_drops,
            "taxiOccupiedMin": self.taxi_occupied_min,
            "taxiOccupiedMax": self.taxi_occupied_max,
            "forcedDrops": [d.to_dict() for d in self.forced_drops],
            # True when the drops below are the WORST case of a range rather
            # than a determined set.  A caller that renders them as required
            # without reading this is overstating what is known.
            "forcedDropsAreUpperBound": self.certainty != "exact",
            "rungOrderWasTied": self.rung_order_was_tied,
            "forcedDropValue": (
                None if self.forced_drop_value is None else round(self.forced_drop_value, 1)
            ),
            "forcedDropCutCost": (
                None if self.forced_drop_cut_cost is None else round(self.forced_drop_cut_cost, 1)
            ),
            "forcedDropReleaseCost": (
                None
                if self.forced_drop_release_cost is None
                else round(self.forced_drop_release_cost, 1)
            ),
            "unpricedForcedDrops": self.unpriced_forced_drops,
            "ladderExhausted": self.ladder_exhausted,
            "notes": list(self.notes),
            "valueScale": "rankDerivedValue",
        }


@dataclass(frozen=True)
class CapacityContext:
    """Everything that is constant for one (team, board) pair.

    Built once and reused across many candidate trades, because the expensive
    part — joining the roster to the board, measuring waiver level across the
    league, resolving starter slots — does not depend on which trade is being
    evaluated.  The cut LADDER does, so it is rebuilt per assessment.
    """

    league_key: str | None
    roster_limit: int | None
    taxi_size: int
    #: Whether we can tell WHICH roster members occupy taxi slots.  False
    #: whenever the source we were handed carries no taxi membership, which is
    #: every contract-shaped caller today.  Never assume a value for it.
    taxi_membership_known: bool
    #: Normalised names/ids of the roster members on taxi, when known.  Empty
    #: and meaningless unless ``taxi_membership_known``.
    taxi_member_keys: frozenset[str]
    roster_player_names: tuple[str, ...]
    assets_by_key: Mapping[str, RosterAsset]
    starter_slots: tuple[str, ...]
    waiver_values: Mapping[str, float]
    scarcity: Mapping[str, Any] | None
    by_name: Mapping[str, Mapping[str, Any]]
    by_id: Mapping[str, Mapping[str, Any]]
    #: The league's CONFIGURED flex rule, resolved once from the contract by
    #: ``data_contract.contract_slot_eligibility`` — the same helper the
    #: lineup stamp, ``/api/roster/intelligence`` and ``team_droppability``
    #: use.  ``None`` means nothing configured, NOT nothing eligible.
    slot_eligibility: Mapping[str, Any] | None = None
    notes: tuple[str, ...] = ()


def _asset_key(asset: RosterAsset) -> str:
    return _norm(asset.player_id) or _norm(asset.name)


def build_capacity_context(
    contract: Mapping[str, Any] | None,
    league_key: str | None,
    team: Mapping[str, Any] | None,
    *,
    roster_settings: Mapping[str, Any] | None = None,
) -> CapacityContext:
    """Assemble the per-(team, board) constants.

    Degrades rather than raises.  A capacity answer with no cut ladder is still
    worth having — the counts are the load-bearing part — so a missing board,
    missing starter slots or missing scarcity each produce a note, not an
    exception.
    """
    notes: list[str] = []
    roster_limit = league_roster_limit(league_key, roster_settings)
    taxi_size = league_taxi_size(league_key, roster_settings)
    if roster_limit is None:
        notes.append("league roster size is not configured — capacity is UNKNOWN, not unlimited")
    # Taxi membership: present only if the caller handed us a roster that
    # carries it.  The canonical contract's team block does not.
    taxi_members = team.get("taxi") if isinstance(team, Mapping) else None
    taxi_membership_known = isinstance(taxi_members, (list, tuple))
    taxi_member_keys = frozenset(_norm(m) for m in (taxi_members or ()) if _norm(m))
    if taxi_size and not taxi_membership_known:
        notes.append(
            f"league carries {taxi_size} taxi slot(s) and this source does not say which "
            "roster members occupy them — Sleeper lists taxi players inside `players`, so "
            "active occupancy is a RANGE and the capacity conclusion is partial"
        )

    team = team if isinstance(team, Mapping) else {}
    names = tuple(str(n) for n in (team.get("players") or []) if str(n or "").strip())

    by_id, by_name = index_contract_rows(contract)
    assets: list[RosterAsset] = []
    unmatched: list[str] = []
    if team:
        assets, unmatched = build_roster_assets(team, by_name, by_id)
    if unmatched:
        notes.append(
            f"{len(unmatched)} rostered player(s) did not join to the board — they still "
            "occupy a roster spot and are still cut candidates, but their value is unknown"
        )

    # League-wide rostered set: a player on ANY roster is not a waiver option.
    rostered_keys: set[str] = set()
    sleeper = contract.get("sleeper") if isinstance(contract, Mapping) else None
    teams = (sleeper or {}).get("teams") if isinstance(sleeper, Mapping) else None
    for t in teams if isinstance(teams, list) else []:
        if not isinstance(t, Mapping):
            continue
        for pid in t.get("playerIds") or []:
            if _norm(pid):
                rostered_keys.add(_norm(pid))
        for nm in t.get("players") or []:
            if _norm(nm):
                rostered_keys.add(_norm(nm))

    # NOTE: no auction-rookie exclusion here.  That belongs to Perfect Draft,
    # where the rookies being priced are the lots in the very auction being
    # optimized.  A trade in August is not bidding against them.
    waiver_values = waiver_values_by_position(contract, rostered_keys)
    if not waiver_values:
        notes.append("no waiver-level values available — cut costs fall back to raw board value")

    # Slot rules have ONE owner (C2-U1); nothing here derives them.  Prefer the
    # caller's own league settings when it has them, exactly as
    # ``resolve_starter_slots``' truth ladder does, and fall back to the
    # registry lookup.
    from src.ros.lineup import flatten_starter_slots, load_league_starter_slots  # noqa: PLC0415

    starter_slots: tuple[str, ...] = ()
    try:
        if isinstance(roster_settings, Mapping) and roster_settings.get("starters"):
            starter_slots = tuple(flatten_starter_slots(roster_settings.get("starters")))
        if not starter_slots:
            starter_slots = tuple(load_league_starter_slots(league_key))
    except Exception as exc:  # noqa: BLE001 — a missing slot config must not raise
        starter_slots = ()
        notes.append(f"starter slots unavailable ({type(exc).__name__}) — cut ladder unguarded")
    if not starter_slots:
        notes.append(
            "no starter slots resolved for this league — the cut ladder is not "
            "lineup-guarded, so a forced drop may be a player the lineup needs"
        )

    # C2-U1 / #922 F1: one answer to "who can fill this slot" per league.
    # Without this the cut ladder would score a custom-flex league against
    # built-in defaults while ``optimalLineup`` used the configured ones.
    from src.api.data_contract import contract_slot_eligibility  # noqa: PLC0415

    try:
        slot_eligibility = contract_slot_eligibility(contract) or None
    except Exception:  # noqa: BLE001 — an optional rule must not fail capacity
        slot_eligibility = None

    scarcity, scarcity_note = _league_scarcity(league_key, contract)
    if scarcity_note:
        notes.append(scarcity_note)

    return CapacityContext(
        league_key=league_key,
        roster_limit=roster_limit,
        taxi_size=taxi_size,
        taxi_membership_known=taxi_membership_known,
        taxi_member_keys=taxi_member_keys,
        roster_player_names=names,
        assets_by_key={_asset_key(a): a for a in assets},
        starter_slots=starter_slots,
        waiver_values=waiver_values,
        scarcity=scarcity,
        slot_eligibility=slot_eligibility,
        by_name=by_name,
        by_id=by_id,
        notes=tuple(notes),
    )


def _resolve_incoming(
    name: str,
    by_name: Mapping[str, Mapping[str, Any]],
) -> RosterAsset:
    """An acquired player as the displacement model sees him.

    Unresolvable names still become assets: they occupy a spot on the
    post-trade roster whether or not the board knows who they are.
    """
    row = by_name.get(_norm(name))
    if row is None:
        return RosterAsset(player_id=_norm(name), name=name, position="", board_value=None)
    value = row.get("rankDerivedValue")
    fantasy = row.get("fantasyPositions")
    # ``ros_value`` drives LINEUP FEASIBILITY only, never cost arithmetic
    # (``src/draft/displacement.RosterAsset``).  A missing one is left to the
    # dataclass default rather than coerced here: ``src/ros/lineup.py`` draws a
    # hard line between 0.0 ("assignable, contributes nothing") and unknown,
    # and manufacturing a 0.0 from an absent field is the coercion C2-U1
    # removed from the lineup owner.
    ros = row.get("rosValue")
    extra = {"ros_value": float(ros)} if isinstance(ros, (int, float)) else {}
    return RosterAsset(
        player_id=str(row.get("playerId") or name),
        name=str(row.get("displayName") or row.get("canonicalName") or name),
        position=str(row.get("position") or "").strip().upper(),
        board_value=float(value) if isinstance(value, (int, float)) and value > 0 else None,
        fantasy_positions=tuple(fantasy) if isinstance(fantasy, (list, tuple)) else (),
        injured=bool(row.get("injured")),
        **extra,
    )


def _outgoing_held(
    context: CapacityContext,
    outgoing: Sequence[str],
) -> tuple[int, list[str]]:
    """How many outgoing names the roster actually holds, and which it does not.

    Matched by MULTIPLICITY, the same rule ``_surviving_keys`` and the roster
    rebuild use.  Before this existed ``size_after`` subtracted ``len(outgoing)``
    flat while both of those removed only what was there, so the two definitions
    of the post-trade roster disagreed whenever a caller named a player the
    roster did not hold — and they disagreed in the direction that HIDES roster
    pressure, reporting a spot freed that never existed.
    """

    held = Counter(_norm(n) for n in context.roster_player_names)
    asked = Counter(_norm(n) for n in outgoing)
    matched = sum(min(held[key], count) for key, count in asked.items())
    # DISTINCT names for the note — asking to send the same player twice when
    # the roster holds one copy is one shortfall, not two names.  The COUNT is
    # ``len(outgoing) - matched``, which is what the caller publishes.
    short = {key for key, count in asked.items() if count > held[key]}
    seen: set[str] = set()
    absent: list[str] = []
    for name in outgoing:
        key = _norm(name)
        if key in short and key not in seen:
            seen.add(key)
            absent.append(name)
    return matched, absent


def _surviving_keys(
    context: CapacityContext,
    incoming: Sequence[str],
    outgoing: Sequence[str],
) -> set[str]:
    """Normalised keys of the roster AFTER the trade.

    Removal is by MULTIPLICITY, matching the roster rebuild below and the rule
    ``simulate_trade`` had to learn for picks: two entries sharing a key are
    two assets, and trading one removes one.
    """
    pending = {_norm(n) for n in outgoing}
    keys: set[str] = set()
    for name in context.roster_player_names:
        key = _norm(name)
        if key in pending:
            pending.discard(key)
            continue
        keys.add(key)
    keys.update(_norm(n) for n in incoming)
    return keys


def _as_roster_players(assets: Iterable[RosterAsset]) -> list[RosterPlayer]:
    """``RosterAsset`` -> the canonical owners' input type.

    ``board_value`` (``rankDerivedValue``) becomes ``ros_value``, which is what
    ``contract_roster_pools`` puts there and what every ``roster_intel`` entry
    point reads.  ``None`` stays ``None``: the owner excludes an unpriced player
    from the solve and REPORTS him, a third state that is neither 0.0 nor
    silent omission.
    """
    return [
        RosterPlayer(
            player_id=a.player_id,
            canonical_name=a.name,
            position=a.position,
            ros_value=a.board_value,
            injured=a.injured,
            bye=a.bye,
            fantasy_positions=a.fantasy_positions,
        )
        for a in assets
    ]


def simulate_final_legal_roster(
    context: CapacityContext,
    capacity: RosterCapacity,
    *,
    incoming_players: Sequence[str] = (),
    outgoing_players: Sequence[str] = (),
) -> dict[str, Any]:
    """Roster intelligence for the FINAL LEGAL roster, cleanup included.

    ``C3-CAP-01`` names the sequence and this is its last two steps:

        before -> apply -> capacity/overage -> required legal cleanup ->
        **apply optimal cleanup -> rerun roster intelligence** -> evaluate

    :func:`assess_roster_capacity` stops at "overage".  It reports WHO must go;
    it cannot say what the roster looks like once they have, because roster
    effects are set-dependent — that is C2-SIM-01's premise, and it applies to
    the cleanup exactly as it applies to the trade.  Releasing the cheapest
    legal body can still vacate a FLEX seat and promote a player the trade never
    mentioned.

    The re-solve belongs to ``roster_intel.simulation.simulate_roster_change``.
    Nothing here solves a lineup, computes a strength, or picks a cut.
    """
    if not context.starter_slots:
        return {
            "available": False,
            "unavailableReason": "starter_slots_unresolved",
            "notes": ["the league's starting slots did not resolve, so no lineup can be solved"],
        }

    before_assets = [
        context.assets_by_key.get(_norm(name)) or _resolve_incoming(name, context.by_name)
        for name in context.roster_player_names
    ]
    before_pool = _as_roster_players(before_assets)
    on_roster = {p.player_id for p in before_pool}

    incoming_assets = [_resolve_incoming(n, context.by_name) for n in incoming_players]
    incoming_pool = _as_roster_players(incoming_assets)

    # The cleanup IS the capacity answer's own forced drops — not a second
    # selection.  A drop the trade acquired leaves from the INCOMING side
    # instead, because he was never on the before-roster to leave it.
    drop_ids = {d.player_id for d in capacity.forced_drops}
    acquired_drop_ids = {d.player_id for d in capacity.forced_drops if d.acquired_in_trade}
    incoming_pool = [p for p in incoming_pool if p.player_id not in acquired_drop_ids]

    outgoing_ids = sorted(
        {
            a.player_id
            for a in (
                context.assets_by_key.get(_norm(n)) or _resolve_incoming(n, context.by_name)
                for n in outgoing_players
            )
        }
        | (drop_ids - acquired_drop_ids)
    )

    simulation = simulate_roster_change(
        before_pool,
        list(context.starter_slots),
        incoming=incoming_pool,
        outgoing_ids=[i for i in outgoing_ids if i in on_roster],
        slot_eligibility=context.slot_eligibility,
    )

    notes: list[str] = []
    if capacity.certainty != "exact":
        notes.append(
            "the forced drops this was solved against are an UPPER BOUND "
            f"({capacity.certainty} capacity certainty), so the final roster is one "
            "of a range rather than a determined set"
        )

    payload = simulation.to_dict()
    payload["cleanupApplied"] = [d.to_dict() for d in capacity.forced_drops]
    payload["cleanupIsUpperBound"] = capacity.certainty != "exact"
    payload["notes"] = notes
    # Named for the same reason ``isValueDelta`` is: this block reports what the
    # roster IS afterwards, and grades nothing.
    payload["isVerdict"] = False
    return payload


def assess_roster_capacity(
    context: CapacityContext,
    *,
    incoming_players: Sequence[str] = (),
    outgoing_players: Sequence[str] = (),
) -> RosterCapacity:
    """What this trade does to this roster's legality.

    ``incoming_players`` / ``outgoing_players`` are PLAYER names only — picks
    are not passed here and do not affect capacity (see the module docstring).

    Counts come from the names, not from what resolved: an unjoinable player
    still takes a spot.
    """
    incoming = [str(n) for n in incoming_players if str(n or "").strip()]
    outgoing = [str(n) for n in outgoing_players if str(n or "").strip()]
    notes = list(context.notes)

    size_before = len(context.roster_player_names)
    held_out, absent_out = _outgoing_held(context, outgoing)
    size_after = size_before - held_out + len(incoming)
    unheld_out = len(outgoing) - held_out
    if unheld_out:
        notes.append(
            f"{unheld_out} outgoing player(s) are not on this roster and free no "
            f"spot: {', '.join(absent_out[:5])}" + (" …" if len(absent_out) > 5 else "")
        )

    limit = context.roster_limit
    if limit is None:
        return RosterCapacity(
            roster_limit=None,
            taxi_size=context.taxi_size,
            size_before=size_before,
            size_after=size_after,
            incoming=len(incoming),
            outgoing=len(outgoing),
            open_spots_before=None,
            open_spots_after=None,
            over_limit_before=None,
            over_limit_after=None,
            certainty="partial",
            outgoing_not_on_roster=unheld_out,
            notes=notes,
        )

    # ── Taxi bracket ─────────────────────────────────────────────────
    # Sleeper lists taxi players inside ``players``, so ``size_*`` counts
    # them.  With membership invisible, the number occupying ACTIVE spots is
    # bracketed rather than guessed: guessing 0 overstates pressure and
    # invents forced drops, guessing full relief hides real ones.
    if context.taxi_size <= 0:
        taxi_lo = taxi_hi = 0
        certainty = "exact"
    elif context.taxi_membership_known:
        # Count the taxi members that SURVIVE the trade, capped at the number
        # of slots that exist — a source can list more than the league allows.
        surviving_keys = _surviving_keys(context, incoming, outgoing)
        occupied = len(context.taxi_member_keys & surviving_keys)
        taxi_lo = taxi_hi = min(context.taxi_size, occupied)
        certainty = "exact"
    else:
        taxi_lo = 0
        taxi_hi = min(context.taxi_size, size_after)
        certainty = "exact" if taxi_hi == 0 else "partial"

    # Worst case for the roster is the FEWEST players on taxi.
    over_after_max = max(0, (size_after - taxi_lo) - limit)
    over_after_min = max(0, (size_after - taxi_hi) - limit)
    over_before = max(0, (size_before - taxi_lo) - limit)
    over_after = over_after_max if certainty == "exact" else None
    open_before = max(0, limit - (size_before - taxi_lo))
    if over_before:
        notes.append(
            f"roster is ALREADY {over_before} over the {limit}-man limit before this "
            "trade — the drops below include getting back to legal size"
        )

    if over_after_max == 0:
        # Legal under every taxi assignment, so the bracket is moot.
        return RosterCapacity(
            roster_limit=limit,
            taxi_size=context.taxi_size,
            size_before=size_before,
            size_after=size_after,
            incoming=len(incoming),
            outgoing=len(outgoing),
            open_spots_before=open_before,
            open_spots_after=max(0, limit - (size_after - taxi_lo)),
            over_limit_before=over_before,
            over_limit_after=0,
            certainty="exact",
            outgoing_not_on_roster=unheld_out,
            over_limit_after_min=0,
            over_limit_after_max=0,
            taxi_occupied_min=taxi_lo,
            taxi_occupied_max=taxi_hi,
            forced_drop_value=0.0,
            forced_drop_cut_cost=0.0,
            notes=notes,
        )

    # ── The post-trade roster, which is what the ladder must be built on ──
    outgoing_keys = {_norm(n) for n in outgoing}
    surviving: list[RosterAsset] = []
    for name in context.roster_player_names:
        key = _norm(name)
        if key in outgoing_keys:
            outgoing_keys.discard(key)  # by multiplicity, not set membership
            continue
        asset = context.assets_by_key.get(key)
        if asset is None:
            asset = _resolve_incoming(name, context.by_name)
        surviving.append(asset)

    acquired_keys: set[str] = set()
    for name in incoming:
        asset = _resolve_incoming(name, context.by_name)
        acquired_keys.add(_asset_key(asset))
        surviving.append(asset)

    # Only as deep as this trade actually needs.  ``build_cut_ladder``
    # defaults to 30 rungs and re-solves the lineup for each one, so asking
    # for the whole ladder to read the top of it costs 39 ms where 3 ms will
    # do — measured on a real 58-man roster.  This is a bound, not an
    # approximation: rung k is identical whether the ladder stops at k or at
    # 30, because ECC is a property of the player and the greedy admits
    # cheapest-first.
    # The ladder is the canonical owner's, reached through the adapter #914 §14
    # names for C3-CAP-01 — not ``build_cut_ladder`` directly, which would be a
    # second route to one owner.  The league's configured flex rule travels with
    # it, so this ladder and ``optimalLineup`` cannot disagree about who fills a
    # slot (#922 `a03d175`).
    ladder = pool_cut_ladder(
        [
            RosterPlayer(
                player_id=a.player_id,
                canonical_name=a.name,
                position=a.position,
                ros_value=a.board_value,
                injured=a.injured,
                bye=a.bye,
                fantasy_positions=a.fantasy_positions,
            )
            for a in surviving
        ],
        list(context.starter_slots),
        context.waiver_values,
        scarcity=context.scarcity,
        slot_eligibility=context.slot_eligibility,
        max_rungs=over_after_max,
    )
    notes.extend(ladder.notes)

    drops: list[ForcedDrop] = []
    for rung in ladder.rungs[:over_after_max]:
        asset = next((a for a in surviving if a.player_id == rung.player_id), None)
        drops.append(
            ForcedDrop(
                player_id=rung.player_id,
                name=rung.name,
                position=rung.position,
                value=(asset.board_value if asset is not None else None),
                effective_cut_cost=rung.effective_cut_cost,
                release_cost=float(rung.base_value) * float(rung.scarcity_multiplier),
                waiver_value=float(rung.waiver_value),
                scarcity_multiplier=float(rung.scarcity_multiplier),
                value_basis=rung.value_basis,
                rung=rung.rung,
                acquired_in_trade=_norm(rung.player_id) in acquired_keys,
            )
        )

    # ── Ordering: the ladder's rung order is not always a priority ────────
    #
    # ``build_cut_ladder`` picks cheapest-ECC-first with a lineup guard. When
    # the ECCs TIE the greedy falls back to insertion order, which is the
    # roster's own order — alphabetical, as Sleeper returns it. Measured on the
    # 2026-08-18 board: every ECC on every forced drop is 0.0 (see
    # ``ForcedDrop.release_cost``), so on all twelve rosters the rung order was
    # purely alphabetical while ``rung: 1`` reads as "release this one first".
    # On the fullest roster that named Bobby Wagner (1,312) ahead of Jaleel
    # McLaughlin (1,205) — strictly more expensive, listed first.
    #
    # The SET is the ladder's and stays the ladder's: membership is what the
    # per-rung lineup re-solve establishes, and re-deriving it here would be a
    # second cut ladder. Only the PRESENTATION order changes, to the honest
    # cost, and ``rungOrderWasTied`` says when the ladder's own order carried
    # no information.
    tied = len({round(d.effective_cut_cost, 6) for d in drops}) <= 1 and len(drops) > 1
    if tied:
        drops = sorted(drops, key=lambda d: (d.release_cost, d.name))
        notes.append(
            "every forced drop scored the same effective cut cost, so the cut ladder's "
            "own rung order carried no priority — these are ordered by release cost instead"
        )

    exhausted = len(drops) < over_after_max
    if exhausted:
        notes.append(
            f"cut ladder offers {len(drops)} release(s) but {over_after_max} are needed — "
            "every remaining player is required to fill a starting slot, so no legal "
            "path back to roster size was modelled"
        )

    priced = [d.value for d in drops if d.value is not None]
    return RosterCapacity(
        roster_limit=limit,
        taxi_size=context.taxi_size,
        size_before=size_before,
        size_after=size_after,
        incoming=len(incoming),
        outgoing=len(outgoing),
        open_spots_before=open_before,
        open_spots_after=0 if certainty == "exact" else None,
        over_limit_before=over_before,
        over_limit_after=over_after,
        certainty=certainty,
        outgoing_not_on_roster=unheld_out,
        over_limit_after_min=over_after_min,
        over_limit_after_max=over_after_max,
        taxi_occupied_min=taxi_lo,
        taxi_occupied_max=taxi_hi,
        forced_drops=drops,
        forced_drop_value=float(sum(priced)) if priced else 0.0,
        forced_drop_cut_cost=float(sum(d.effective_cut_cost for d in drops)),
        forced_drop_release_cost=float(sum(d.release_cost for d in drops)),
        rung_order_was_tied=tied,
        unpriced_forced_drops=sum(1 for d in drops if d.value is None),
        ladder_exhausted=exhausted,
        notes=notes,
    )


def player_names_only(assets: Iterable[Any]) -> list[str]:
    """Names of the PLAYER assets on a trade side, picks excluded.

    Accepts either resolved dicts (the simulator's shape) or objects with
    ``.name`` / ``.position`` (the engines' ``PlayerAsset``).  Picks are
    identified by the board position they carry, which is how every other
    consumer in this repo tells them apart, and they are dropped because a
    pick does not occupy a roster spot.
    """
    out: list[str] = []
    for asset in assets:
        if isinstance(asset, Mapping):
            pos = str(asset.get("pos") or asset.get("position") or "")
            name = str(asset.get("name") or "")
        else:
            pos = str(getattr(asset, "position", "") or "")
            name = str(getattr(asset, "name", "") or "")
        if pos.strip().upper() == "PICK":
            continue
        name = name.strip()
        if name:
            out.append(name)
    return out
