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
forced drops that the league would not require.  ``dynasty_new`` carries 3 taxi
slots against a 27-man roster (host truth, W18-F011 / V1-25 — this line used to
say 5 against 24), so the error is up to three players wide.

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
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.draft.context import _league_scarcity, _norm, build_roster_assets, index_contract_rows
from src.draft.displacement import (
    RosterAsset,
    waiver_values_by_position,
)
from src.roster_intel import pool_cut_ladder, simulate_roster_change
from src.ros.lineup import RosterPlayer
from src.trade import forced_drop_selection as fds

__all__ = [
    "CapacityContext",
    "ForcedDrop",
    "RosterCapacity",
    "assess_roster_capacity",
    "build_capacity_context",
    "league_scarcity",
    "capacity_context_for_team",
    "counterparty_capacity_block",
    "counterparty_context_resolver",
    "forced_drop_cost",
    "league_roster_limit",
    "league_taxi_size",
    "outgoing_roster_names",
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
    #: Flag ``forced_drop_cheapest_legal`` only (``None`` and unpublished when
    #: OFF): how ``release_cost`` was charged — ``release_cost`` (``base x
    #: scarcity``), ``package_credit_forgone`` (a just-acquired piece removed
    #: from the package, charged the credit the package gave it) or
    #: ``release_value`` (``base x scarcity``), ``package_credit_forgone`` (a
    #: just-acquired piece removed from the package, charged the credit the
    #: package gave it — NOT the player's value), ``release_value_uncredited``
    #: (acquired, but the package never credited it: its own ``base x
    #: scarcity`` at the ``assumedWaiver`` ceiling when unpriced) or
    #: ``release_value_no_package`` (acquired, but the caller held no package).
    charge_basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
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
        if self.charge_basis is not None:
            out["chargeBasis"] = self.charge_basis
        return out


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
    #: Flag ``forced_drop_cheapest_legal`` only — ``None`` (and nothing below
    #: published) when OFF.  The selection rule that chose ``forced_drops``.
    selection_rule: str | None = None
    #: Whether the just-acquired releases were removed from the trade's
    #: package (the caller supplied it) rather than charged their raw value.
    package_applied: bool | None = None
    #: Cost of the cheapest legal cleanup the PRE-trade roster already owes
    #: (an over-limit roster); the trade is charged only what it adds.
    pre_trade_cleanup_cost: float | None = None
    pre_trade_cleanup_exhausted: bool = False
    #: ``(player_id, value_basis)`` of that pre-trade cleanup — decides whether
    #: the MARGINAL charge rests on an ``assumedWaiver`` value (not published).
    pre_trade_cleanup_drops: tuple[tuple[str, str], ...] = ()
    #: Flag ``forced_drop_cheapest_legal`` only: whether the league produced
    #: any waiver-level values.  With none, an unpriced (``assumedWaiver``)
    #: release has a base of 0 (``displacement._waiver_value_for``), so a
    #: charge resting on one is UNDETERMINABLE, never 0 (not published; the
    #: flag-OFF path never reads it).
    waiver_values_available: bool = True
    #: Flag ``forced_drop_cheapest_legal`` only: the V5 acquired-subset search
    #: bound was exceeded and the V5-R selection with package charging ran
    #: instead (``None`` when the flag is OFF).
    search_bound_exceeded: bool | None = None
    #: Flag ``forced_drop_cheapest_legal`` and taxi-unknown (``certainty
    #: "partial"``) only: ``(cost, exhausted, assumed)`` of the cheapest legal
    #: cleanup of the GUARANTEED number of releases (``over_limit_after_min``,
    #: capped at the roster's growth), RE-SELECTED at that count.  The cheapest
    #: ``k`` drops of the worst-case cleanup are a legal ``k``-set but not
    #: necessarily the cheapest one (the lineup guard and the package step
    #: couple the choices), so they are not a guaranteed lower bound.
    taxi_bound_cleanup: tuple[float, bool, bool] | None = None

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
        } | self._selection_dict()

    def _selection_dict(self) -> dict[str, Any]:
        """The flag-ON fields; empty (so the payload is unchanged) when OFF."""
        if self.selection_rule is None:
            return {}
        cost, basis = forced_drop_cost(self)
        marginal = forced_drop_marginal(self)
        return {
            # THE charge every consumer reads (War Room objective, Trade
            # Finder re-rank, decision engine): one function, one number.
            "forcedDropCharge": None if cost is None else round(cost, 1),
            "forcedDropChargeBasis": basis,
            # The SIGNED marginal the charge is clamped from: negative when the
            # trade SPARES an over-limit roster a release it already owed
            # (e.g. sends 2, receives 1).  Published, never charged or credited
            # (``conservative_clamp``).  ``None`` when not determinable.
            "forcedDropMarginal": None if marginal is None else round(marginal, 1),
            "forcedDropSelection": {
                "rule": self.selection_rule,
                "flag": fds.FLAG,
                "packageApplied": self.package_applied,
                "searchBound": fds.MAX_PACKAGE_SUBSETS,
                "searchBoundExceeded": self.search_bound_exceeded,
                "preTradeCleanupCost": (
                    None
                    if self.pre_trade_cleanup_cost is None
                    else round(self.pre_trade_cleanup_cost, 1)
                ),
                "chargeUnit": "rankDerivedValue x scarcity (package credit for an acquired piece)",
            },
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
    #: The roster settings this context was built under, kept so a context for
    #: ANOTHER team in the same league (the counterparty) resolves the same cap
    #: and slots instead of falling back to a different source.
    roster_settings: Mapping[str, Any] | None = None
    #: The player id of each ``roster_player_names`` entry, position for
    #: position (``build_roster_assets`` emits exactly one asset per name, in
    #: order): the board row's ``playerId`` when the entry joined, else the
    #: roster's own id.  Lets an outgoing leg that carries a Sleeper id find
    #: ITS roster entry whatever display name the caller used
    #: (:func:`outgoing_roster_names`).  Empty for a context built without it.
    roster_player_ids: tuple[str, ...] = ()


def _asset_key(asset: RosterAsset) -> str:
    return _norm(asset.player_id) or _norm(asset.name)


#: ``(scarcity, note)`` as :func:`league_scarcity` returns it.
ScarcityReading = tuple[Mapping[str, Any] | None, str | None]


def league_scarcity(
    league_key: str | None,
    contract: Mapping[str, Any] | None,
) -> ScarcityReading:
    """The league's positional scarcity for capacity, or ``(None, reason)``.

    The ONE read capacity makes (``src.draft.context._league_scarcity``, which
    routes through the shared gameplan bundle).  A caller evaluating several
    teams of ONE request — the N-team engine — reads it once here and hands
    the same reading to every team's :func:`build_capacity_context`, because
    the bundle's inputs are re-loaded on every call (and can fall to the live
    team-strength fallback, TTL-cached for 120 s), so per-team reads could
    score teams of the same trade against different scarcity (R1-1).
    """
    return _league_scarcity(league_key, contract)


def build_capacity_context(
    contract: Mapping[str, Any] | None,
    league_key: str | None,
    team: Mapping[str, Any] | None,
    *,
    roster_settings: Mapping[str, Any] | None = None,
    scarcity_reading: ScarcityReading | None = None,
) -> CapacityContext:
    """Assemble the per-(team, board) constants.

    Degrades rather than raises.  A capacity answer with no cut ladder is still
    worth having — the counts are the load-bearing part — so a missing board,
    missing starter slots or missing scarcity each produce a note, not an
    exception.

    ``scarcity_reading`` is a :func:`league_scarcity` result the caller
    already holds for this league and board (one read per request); ``None``
    (the default) reads it here, exactly as before.
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

    scarcity, scarcity_note = (
        scarcity_reading if scarcity_reading is not None else league_scarcity(league_key, contract)
    )
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
        roster_settings=roster_settings if isinstance(roster_settings, Mapping) else None,
        roster_player_ids=(
            tuple(str(a.player_id) for a in assets) if len(assets) == len(names) else ()
        ),
    )


def outgoing_roster_names(
    context: CapacityContext,
    names: Sequence[str],
    ids: Sequence[str | None] | None = None,
) -> list[str]:
    """The roster's OWN name for each outgoing player (B0-b parity).

    ``ids`` runs parallel to ``names`` (``None`` for an entry without one).
    An entry whose Sleeper id matches a roster entry's id is translated to that
    entry's roster name — matched by MULTIPLICITY, each roster entry consumed
    once — so a caller that names the player differently from the Sleeper
    roster (a board display name, a suffix) still frees the spot he occupies.
    An entry with no id, or whose id is on no roster entry, keeps its name:
    name matching is the fallback only, exactly as before.  Pure.
    """
    ids = list(ids or [])
    roster_ids = list(context.roster_player_ids)
    if len(roster_ids) != len(context.roster_player_names):
        roster_ids = []
    used: set[int] = set()
    out: list[str] = []
    for i, name in enumerate(names):
        pid = ids[i] if i < len(ids) else None
        key = _norm(pid) if pid else ""
        hit = None
        if key:
            hit = next(
                (k for k, rid in enumerate(roster_ids) if k not in used and _norm(rid) == key),
                None,
            )
        if hit is None:
            out.append(str(name))
            continue
        used.add(hit)
        out.append(context.roster_player_names[hit])
    return out


def capacity_context_for_team(
    base: CapacityContext,
    contract: Mapping[str, Any] | None,
    team: Mapping[str, Any] | None,
) -> CapacityContext:
    """A context for another team in ``base``'s league — the counterparty.

    Same league key and roster settings as ``base``, so both sides of a trade
    are measured against one cap and one set of starter slots.  Nothing is
    re-derived here: it is :func:`build_capacity_context` for the other team.
    """
    return build_capacity_context(
        contract, base.league_key, team, roster_settings=base.roster_settings
    )


def counterparty_context_resolver(
    base: CapacityContext | None,
    contract: Mapping[str, Any] | None,
    sleeper_teams: Sequence[Any] | None,
) -> Callable[[str | None], CapacityContext | None]:
    """``team key -> CapacityContext`` for counterparties, memoised.

    A key matches a team's ``ownerId`` or its display ``name``.  ``None`` for
    an unknown team or a failed build — a report that cannot be made is
    reported as unavailable by the caller, never guessed.
    """
    cache: dict[str, CapacityContext | None] = {}
    teams = [t for t in (sleeper_teams or []) if isinstance(t, Mapping)]

    def resolve(key: str | None) -> CapacityContext | None:
        if base is None or not key:
            return None
        k = str(key)
        if k not in cache:
            team = next(
                (t for t in teams if k in (str(t.get("ownerId") or ""), str(t.get("name") or ""))),
                None,
            )
            try:
                cache[k] = capacity_context_for_team(base, contract, team) if team else None
            except Exception:  # noqa: BLE001 — a report never fails its caller
                cache[k] = None
        return cache[k]

    return resolve


def counterparty_capacity_block(
    context: CapacityContext | None,
    *,
    incoming_players: Sequence[str],
    outgoing_players: Sequence[str],
) -> dict[str, Any]:
    """The counterparty's capacity read, or a NAMED unavailable."""
    if context is None:
        return {
            "unavailable": "counterparty_unresolved",
            "notes": ["the counterparty's roster did not resolve"],
        }
    try:
        return assess_roster_capacity(
            context,
            incoming_players=incoming_players,
            outgoing_players=outgoing_players,
        ).to_dict()
    except Exception:  # noqa: BLE001
        return {
            "unavailable": "assessment_failed",
            "notes": ["counterparty roster capacity could not be computed"],
        }


def forced_drop_cost(capacity: RosterCapacity) -> tuple[float | None, dict[str, Any]]:
    """What the releases a trade ADDS are known to cost, on the board scale.

    Wave B (C3-CAP-01): the opportunity cost of the cleanup a trade forces,
    for a consumer that ranks on it.  Built from ``ForcedDrop.release_cost``
    (``base x scarcity`` — the same "what does releasing him cost" rule
    Perfect Draft and Analyze Trade read), never a constant.

    MARGINAL to the trade.  A roster already over the cap owes its existing
    overage whether or not it trades, so only the drops the trade adds are
    charged: ``min(over_after, net roster growth)``.  The cleanup releases the
    ladder's cheapest rungs first, so the drops the trade adds are the
    most expensive of the selected set.

    Returns ``(cost, basis)``:

    * ``None`` when it cannot be known — cap unknown, or taxi occupancy makes
      "any drop at all" undetermined.  MISSING IS NEVER ZERO: the caller must
      not read ``None`` as free.
    * ``0.0`` when the trade adds no release (legal after, or not growing).
    * otherwise the cost of the added releases.  With unknown taxi membership
      only ``over_limit_after_min`` drops are certain, so the cheapest
      guaranteed added releases are charged and the answer is a lower bound.
      Unpriced drops and an exhausted ladder likewise make it a lower bound;
      ``basis`` says so.
    """
    if capacity.selection_rule is not None:
        return _selected_forced_drop_cost(capacity)
    requires = capacity.requires_drops
    if requires is None:
        return None, {"state": "unknown", "reason": "drop_requirement_undetermined"}
    if requires is False:
        return 0.0, {"state": "none"}
    growth = max(0, capacity.size_after - capacity.size_before)
    # Ordered by what each release COSTS (name breaks ties), never by ladder
    # rung: rungs carry the ladder's ECC order, which is not release-cost order
    # across positions, and on a full roster every ECC ties at 0.0 so the rung
    # order is merely alphabetical (independent review, Wave B).
    drops = sorted(capacity.forced_drops, key=lambda d: (d.release_cost, d.name))
    lower_bound_reasons: list[str] = []
    over = (
        capacity.over_limit_after_min
        if capacity.certainty != "exact"
        else capacity.over_limit_after
    )
    if over is None:  # requires_drops proved it known; stay explicit anyway
        return None, {"state": "unknown", "reason": "overage_undetermined"}
    added = min(over, growth)
    if added == 0:
        return 0.0, {"state": "none", "reason": "trade_adds_no_release"}
    if capacity.certainty != "exact":
        # Lower bound: the cheapest that-many of the drops.
        charged = drops[:added]
        lower_bound_reasons.append("taxi_occupancy_unknown_guaranteed_drops_only")
    else:
        # The overage owed before the trade takes the cheapest releases; the
        # releases the trade ADDS are the most expensive of the selected set.
        charged = drops[max(0, len(drops) - added) :]
    if len(charged) < added:
        lower_bound_reasons.append("fewer_drops_modelled_than_added")
    priced = [d for d in charged if d.value is not None]
    if len(priced) < len(charged):
        lower_bound_reasons.append("unpriced_forced_drops_excluded")
    if capacity.ladder_exhausted:
        lower_bound_reasons.append("cut_ladder_exhausted")
    cost = float(sum(d.release_cost for d in priced))
    basis: dict[str, Any] = {
        "state": "lower_bound" if lower_bound_reasons else "exact",
        "addedReleases": added,
        "valueScale": "releaseCost (rankDerivedValue x scarcity)",
    }
    if lower_bound_reasons:
        basis["lowerBoundReasons"] = lower_bound_reasons
    return cost, basis


def forced_drop_marginal(capacity: RosterCapacity) -> float | None:
    """Flag ``forced_drop_cheapest_legal`` only: the SIGNED marginal release
    cost, ``cost(post-trade cleanup) - cost(pre-trade cleanup)``.

    Negative when the trade relieves an over-limit roster of a release it
    already owed — a roster one over that sends two and receives one is spared
    a cut.  :func:`forced_drop_cost` clamps it at 0 (``conservative_clamp``:
    relief is reported, never credited to the trade).  ``None`` unless the
    count is exact and the flag selected the drops, and ``None`` when either
    cleanup is exhausted (stops short of legal size) or rests on an unpriced
    release with no waiver table — an incomplete or undeterminable cleanup is
    never reported as an exact signed marginal.
    """
    if capacity.selection_rule is None or capacity.certainty != "exact":
        return None
    if capacity.requires_drops is None:
        return None
    owed = _pre_trade_owed(capacity)
    if owed is None:
        return None  # what the roster already owed is not known
    # An incomplete cleanup on either side is not a signed EXACT marginal:
    # the modelled drops stop short of legal size, so the difference is of
    # two different quantities (re-review finding 1a).
    if capacity.ladder_exhausted or capacity.pre_trade_cleanup_exhausted:
        return None
    if _rests_on_missing_waiver(capacity):
        return None
    total = float(sum(d.release_cost for d in capacity.forced_drops))
    return total - owed


def _pre_trade_owed(capacity: RosterCapacity) -> float | None:
    """What the PRE-trade roster already owed in releases, or ``None``.

    0 only when the roster was proven within its cap (``over_limit_before``
    <= 0: it owed no cleanup); the pre-trade cleanup cost when it was over; and
    ``None`` when the cap is unknown or the over-limit cleanup was not
    computed — an unknown is never netted as zero.
    """
    over = capacity.over_limit_before
    if over is None:
        return None
    if over <= 0:
        return 0.0
    if capacity.pre_trade_cleanup_cost is None:
        return None
    return float(capacity.pre_trade_cleanup_cost)


def _rests_on_missing_waiver(capacity: RosterCapacity) -> bool:
    """Flag-ON only: the league has no waiver-level values AND some release on
    either side of the marginal is priced at ``assumedWaiver`` — whose base is
    then 0 (``displacement._waiver_value_for``), i.e. an unpriced cut that
    would be charged nothing.  Such a charge is undeterminable, never 0."""
    if capacity.waiver_values_available:
        return False
    if any(
        d.value_basis == "assumedWaiver" and d.charge_basis != fds.CHARGE_PACKAGE
        for d in capacity.forced_drops
    ):
        return True
    return any(vb == "assumedWaiver" for _pid, vb in capacity.pre_trade_cleanup_drops)


def _selected_forced_drop_cost(capacity: RosterCapacity) -> tuple[float | None, dict[str, Any]]:
    """:func:`forced_drop_cost` under flag ``forced_drop_cheapest_legal``.

    Same vocabulary (``unknown`` / ``none`` / ``exact`` / ``lower_bound``) plus
    ``assumed`` and ``mixed_bound``, so every consumer reads it unchanged:

    * an unpriced drop is CHARGED at its ``assumedWaiver`` release cost and
      counted (``assumedWaiverDrops``) — never excluded as zero.  A charge that
      rests on such a value is NOT ``exact``: ``assumed`` (an upper bound — the
      waiver level is the unpriced player's documented ceiling) when the
      assumed drop is in the post-trade cleanup only, ``lower_bound`` (reason
      ``pre_trade_cleanup_assumed_waiver``) when only in the pre-trade cleanup
      it is netted against, ``mixed_bound`` when both;
    * marginal = ``max(0, cost(post-trade cleanup) - cost(pre-trade cleanup))``,
      so an over-limit roster is charged only what the trade adds; the signed
      value is :func:`forced_drop_marginal` and the clamp is labelled
      ``conservative_clamp`` whenever it binds;
    * an exhausted post-trade cleanup (``cut_ladder_exhausted``) is a lower
      bound even when the netted marginal is 0 — exhaustion is checked before
      the "adds no release cost" return; an exhausted PRE-trade cleanup
      understates what the roster owed, so the marginal is an upper bound
      (``upperBoundReasons: ["pre_trade_cleanup_exhausted"]``, state
      ``assumed`` or ``mixed_bound``);
    * no waiver-level values at all, with an ``assumedWaiver`` release on
      either side: ``(None, unknown / waiver_values_unavailable)`` — that
      release's base would be 0, and missing is never zero.
    """
    requires = capacity.requires_drops
    common: dict[str, Any] = {"rule": capacity.selection_rule}
    signed = forced_drop_marginal(capacity)
    if signed is not None and signed < 0:
        common["signedMarginal"] = round(signed, 1)
        common["marginalClamp"] = "conservative_clamp"
    if requires is None:
        return None, {"state": "unknown", "reason": "drop_requirement_undetermined", **common}
    if requires is False:
        return 0.0, {"state": "none", **common}
    if _rests_on_missing_waiver(capacity):
        # No waiver table: an unpriced release would be charged 0 (re-review
        # finding 3).  MISSING IS NEVER ZERO — refuse the number.
        return None, {"state": "unknown", "reason": "waiver_values_unavailable", **common}

    def _assumed(d: ForcedDrop) -> bool:
        # A just-acquired piece charged its package credit is not charged its
        # (assumed) value, so it does not make the charge assumed.
        return d.value_basis == "assumedWaiver" and d.charge_basis != fds.CHARGE_PACKAGE

    assumed = sum(1 for d in capacity.forced_drops if _assumed(d))
    credit = sum(
        d.release_cost for d in capacity.forced_drops if d.charge_basis == fds.CHARGE_PACKAGE
    )
    lower: list[str] = []
    upper_reasons: list[str] = []
    upper = False
    if capacity.certainty != "exact":
        over = capacity.over_limit_after_min
        if over is None:
            return None, {"state": "unknown", "reason": "overage_undetermined", **common}
        growth = max(0, capacity.size_after - capacity.size_before)
        added = min(over, growth)
        if added == 0:
            return 0.0, {"state": "none", "reason": "trade_adds_no_release", **common}
        lower.append("taxi_occupancy_unknown_guaranteed_drops_only")
        if capacity.taxi_bound_cleanup is not None:
            # RE-SELECTED at the guaranteed count: the cheapest legal cleanup
            # of ``added`` releases, so the lower bound is a lower bound.
            cost, bound_exhausted, upper = capacity.taxi_bound_cleanup
            if bound_exhausted:
                lower.append("fewer_drops_modelled_than_added")
        else:
            charged = sorted(capacity.forced_drops, key=lambda d: (d.release_cost, d.player_id))[
                :added
            ]
            if len(charged) < added:
                lower.append("fewer_drops_modelled_than_added")
            cost = float(sum(d.release_cost for d in charged))
            upper = any(_assumed(d) for d in charged)
    else:
        total = float(sum(d.release_cost for d in capacity.forced_drops))
        pre = _pre_trade_owed(capacity)
        if pre is None:
            return None, {"state": "unknown", "reason": "pre_trade_owed_undetermined", **common}
        cost = max(0.0, total - pre)
        # Exhaustion is checked BEFORE the zero early return: a cleanup that
        # stops short of legal size must not read as an exact zero
        # (re-review finding 1b).
        if (
            cost <= 0.0
            and not capacity.ladder_exhausted
            and not capacity.pre_trade_cleanup_exhausted
        ):
            return 0.0, {"state": "none", "reason": "trade_adds_no_release_cost", **common}
        if capacity.pre_trade_cleanup_exhausted:
            common["preTradeCleanupExhausted"] = True
            # The pre-trade cleanup stops short of what the roster owed, so
            # the netted ``pre`` understates it and the marginal is an UPPER
            # bound (re-review finding 1c).
            upper_reasons.append("pre_trade_cleanup_exhausted")
        # Does the MARGINAL rest on an assumed value?  A drop owed both
        # before and after the trade cancels out of it.
        post_a = Counter(d.player_id for d in capacity.forced_drops if _assumed(d))
        pre_a = Counter(
            pid for pid, vb in capacity.pre_trade_cleanup_drops if vb == "assumedWaiver"
        )
        upper = bool(post_a - pre_a) or bool(upper_reasons)
        if pre_a - post_a:
            lower.append("pre_trade_cleanup_assumed_waiver")
    if capacity.ladder_exhausted:
        lower.append("cut_ladder_exhausted")
    if lower and upper:
        state, bound = "mixed_bound", "mixed"
    elif lower:
        state, bound = "lower_bound", "lower"
    elif upper:
        state, bound = "assumed", "upper"
    else:
        state, bound = "exact", None
    basis: dict[str, Any] = {
        "state": state,
        "addedReleases": (
            None
            if capacity.over_limit_after_max is None or capacity.over_limit_before is None
            else max(0, capacity.over_limit_after_max - capacity.over_limit_before)
        ),
        "valueScale": (
            "releaseCost (rankDerivedValue x scarcity; package credit for an acquired piece)"
        ),
        "assumedWaiverDrops": assumed,
        "packageCreditForgone": round(credit, 1),
        **common,
    }
    if bound is not None:
        basis["bound"] = bound
    if lower:
        basis["lowerBoundReasons"] = lower
    if upper_reasons:
        basis["upperBoundReasons"] = upper_reasons
    return cost, basis


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


@dataclass(frozen=True)
class FinalLegalRoster:
    """The three rosters a trade passes through, as the ONE definition both
    roster consumers read: Team Strength (``simulate_final_legal_roster``) and
    best-ball utility (#1173, ``src.roster_intel.best_ball_utility``).

    ``landed`` is the roster the moment the trade executes; ``final`` is the
    legal roster after this capacity answer's own forced drops.  They are the
    same list whenever no cleanup is required.
    """

    before: tuple[RosterAsset, ...]
    landed: tuple[RosterAsset, ...]
    final: tuple[RosterAsset, ...]
    incoming: tuple[RosterAsset, ...]
    #: Ids leaving the BEFORE roster: the trade's outgoing players plus the
    #: forced drops that were on it (a drop the trade acquired leaves from
    #: ``incoming`` instead).
    removed_ids: tuple[str, ...]
    outgoing_ids: tuple[str, ...]
    forced_drop_ids: tuple[str, ...]
    acquired_drop_ids: tuple[str, ...]


def final_legal_roster(
    context: CapacityContext,
    capacity: RosterCapacity,
    *,
    incoming_players: Sequence[str] = (),
    outgoing_players: Sequence[str] = (),
) -> FinalLegalRoster:
    """Apply the trade, then this capacity answer's cleanup — no second selection.

    Removal is by MULTIPLICITY: two roster entries sharing an id are two
    spots, and removing one removes exactly one (the rule ``_surviving_keys``
    and ``simulate_trade`` already follow).
    """
    before = tuple(
        context.assets_by_key.get(_norm(name)) or _resolve_incoming(name, context.by_name)
        for name in context.roster_player_names
    )
    on_roster = {a.player_id for a in before}
    incoming = tuple(_resolve_incoming(n, context.by_name) for n in incoming_players)
    drop_ids = tuple(d.player_id for d in capacity.forced_drops)
    acquired_drop_ids = tuple(d.player_id for d in capacity.forced_drops if d.acquired_in_trade)
    outgoing_ids = tuple(
        a.player_id
        for a in (
            context.assets_by_key.get(_norm(n)) or _resolve_incoming(n, context.by_name)
            for n in outgoing_players
        )
        if a.player_id in on_roster
    )
    removed_ids = tuple(
        sorted(
            set(outgoing_ids) | ({i for i in drop_ids if i in on_roster} - set(acquired_drop_ids))
        )
    )

    def _without(assets: Sequence[RosterAsset], ids: Sequence[str]) -> list[RosterAsset]:
        pending = Counter(ids)
        kept: list[RosterAsset] = []
        for a in assets:
            if pending.get(a.player_id, 0) > 0:
                pending[a.player_id] -= 1
                continue
            kept.append(a)
        return kept

    landed = (*_without(before, outgoing_ids), *incoming)
    final = (
        *_without(before, removed_ids),
        *_without(incoming, acquired_drop_ids),
    )
    return FinalLegalRoster(
        before=before,
        landed=tuple(landed),
        final=tuple(final),
        incoming=incoming,
        removed_ids=removed_ids,
        outgoing_ids=outgoing_ids,
        forced_drop_ids=drop_ids,
        acquired_drop_ids=acquired_drop_ids,
    )


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

    # The cleanup IS the capacity answer's own forced drops — not a second
    # selection.  A drop the trade acquired leaves from the INCOMING side
    # instead, because he was never on the before-roster to leave it.  The
    # rosters come from ``final_legal_roster``, the one definition #1173's
    # best-ball utility reads too.
    rosters = final_legal_roster(
        context,
        capacity,
        incoming_players=incoming_players,
        outgoing_players=outgoing_players,
    )
    acquired = set(rosters.acquired_drop_ids)
    simulation = simulate_roster_change(
        _as_roster_players(rosters.before),
        list(context.starter_slots),
        incoming=[p for p in _as_roster_players(rosters.incoming) if p.player_id not in acquired],
        outgoing_ids=list(rosters.removed_ids),
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


def evaluate_final_roster_utility(
    context: CapacityContext,
    capacity: RosterCapacity,
    *,
    incoming_players: Sequence[str] = (),
    outgoing_players: Sequence[str] = (),
    season: int | None,
    scoring_settings: Mapping[str, Any] | None,
    draws: int | None = None,
    league_settings: Mapping[str, Any] | None = None,
    availability_context: Any = None,
    cache_scope: Sequence[str] | None = None,
) -> dict[str, Any]:
    """#1173 best-ball utility for the FINAL LEGAL roster (C3-CAP-01's last step).

    ``cache_scope`` is forwarded to ``evaluate_trade_utility`` so the BEFORE
    roster's simulation is reused across trades for one team (exact reuse,
    content-addressed; see ``best_ball_utility._before_side``).

    Availability (owner master package 2026-10-17, P0): when the league's
    remaining fantasy weeks resolve, every player carries his per-week
    availability from ``src.ros.availability`` and the simulation runs over
    those real weeks — a player out for all of them enters no lineup.
    ``availability_context`` is injectable for tests; by default it is
    assembled from the box's caches (no network).

    Same rosters ``simulate_final_legal_roster`` solves (``final_legal_roster``),
    evaluated by ``src.roster_intel.best_ball_utility`` on league-scored
    projections instead of canonical values.  Nothing here picks a cut: the
    cleanup is this capacity answer's own forced drops.  When taxi occupancy
    makes the drop set a RANGE (``requires_drops is None``) the post-cleanup
    roster is not determined, so only the landed roster is evaluated and the
    cleanup is reported as ``uncertain`` — never a guessed set.
    """
    from src.roster_intel import best_ball_utility as bbu  # noqa: PLC0415

    if not context.starter_slots:
        return {"available": False, "unavailableReason": "starter_slots_unresolved"}
    if season is None:
        return {
            "available": False,
            "unavailableReason": "season_unresolved",
            "notes": ["no current NFL season resolves, so no current-season projection applies"],
        }
    rosters = final_legal_roster(
        context,
        capacity,
        incoming_players=incoming_players,
        outgoing_players=outgoing_players,
    )
    all_assets = (*rosters.before, *rosters.incoming)
    ppg, basis = bbu.league_scored_ppg_by_id(
        sorted({a.player_id for a in all_assets}),
        season=season,
        scoring_settings=scoring_settings or {},
    )
    if basis.get("state") != "available":
        return {
            "available": False,
            "unavailableReason": f"projection_basis_{basis.get('reason') or 'unavailable'}",
            "basis": basis,
        }

    from src.ros import availability as av  # noqa: PLC0415

    ctx = availability_context
    if ctx is None:
        ctx = av.load_context(season=int(season), league_settings=league_settings)
    weeks = list(ctx.weeks) if ctx.weeks else None
    meta = _players_meta_for(sorted({a.player_id for a in all_assets})) if weeks else {}
    states = (
        {
            a.player_id: av.player_week_states(a.player_id, meta.get(a.player_id), ctx)
            for a in all_assets
        }
        if weeks
        else {}
    )

    def _players(assets: Sequence[RosterAsset]) -> list[bbu.UtilityPlayer]:
        return [
            bbu.UtilityPlayer(
                player_id=a.player_id,
                name=a.name,
                position=a.position,
                ppg=ppg.get(a.player_id),
                fantasy_positions=tuple(a.fantasy_positions or ()),
                availability=(
                    {w: st.state for w, st in states[a.player_id].items()}
                    if a.player_id in states
                    else None
                ),
                availability_summary=(
                    av.summarize(states[a.player_id]) if a.player_id in states else None
                ),
            )
            for a in assets
        ]

    roles: dict[str, str] = {a.player_id: "incoming" for a in rosters.incoming}
    roles.update({pid: "outgoing" for pid in rosters.outgoing_ids})
    uncertain = capacity.requires_drops is None
    cleanup_applied = bool(rosters.forced_drop_ids) and not uncertain
    if cleanup_applied:
        roles.update({pid: "forcedDrop" for pid in rosters.forced_drop_ids})
    result = bbu.evaluate_trade_utility(
        before=_players(rosters.before),
        after=_players(rosters.landed if uncertain else rosters.final),
        after_before_cleanup=_players(rosters.landed) if cleanup_applied else None,
        slots=list(context.starter_slots),
        roles=roles,
        slot_eligibility=context.slot_eligibility,
        draws=draws or bbu.DEFAULT_DRAWS,
        basis=basis,
        weeks=weeks,
        availability_basis=ctx.basis,
        cache_scope=cache_scope,
    )
    if not weeks:
        # No remaining-week calendar resolved: the legacy calendar-free
        # simulation ran, and the response says why rather than implying
        # availability was checked.
        result.setdefault("basis", {})["availability"] = {
            **dict(ctx.basis),
            "state": "not_applied",
        }
    result["cleanup"] = {
        "state": "uncertain" if uncertain else "applied" if cleanup_applied else "none",
        "forcedDropIds": list(rosters.forced_drop_ids) if cleanup_applied else [],
        # Close cut candidates stay visible rather than one drop being
        # presented as certain (the ladder's own tie flag).
        "candidatesTied": bool(capacity.rung_order_was_tied),
        "isUpperBound": capacity.certainty != "exact",
    }
    return result


def _players_meta_for(player_ids: Sequence[str]) -> dict[str, Any]:
    """Sleeper player records for availability (the same players-DB read the
    projection join uses).  An unreadable DB answers ``{}`` — every player is
    then ``unknown``, never ``available``."""
    try:
        from src.api.matchup_intel import players_meta_for_rosters  # noqa: PLC0415

        meta = players_meta_for_rosters([{"players": list(player_ids)}])
    except Exception:  # noqa: BLE001 — degraded input, surfaced as unknown
        return {}
    return meta if isinstance(meta, dict) else {}


def assess_roster_capacity(
    context: CapacityContext,
    *,
    incoming_players: Sequence[str] = (),
    outgoing_players: Sequence[str] = (),
    package: fds.PackageSides | None = None,
) -> RosterCapacity:
    """What this trade does to this roster's legality.

    ``incoming_players`` / ``outgoing_players`` are PLAYER names only — picks
    are not passed here and do not affect capacity (see the module docstring).

    Counts come from the names, not from what resolved: an unjoinable player
    still takes a spot.

    ``package`` (the trade's package from this team's side) is read only under
    flag ``forced_drop_cheapest_legal``; OFF ignores it entirely.
    """
    selecting = fds.enabled()
    rule = fds.rule_id() if selecting else None
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
            selection_rule=rule,
            search_bound_exceeded=False if selecting else None,
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
        pre_sel = (
            # Flag ``forced_drop_cheapest_legal`` only: an over-limit roster the
            # trade brings back to legal size is spared a cleanup it owed —
            # published as a signed marginal, never credited.
            _pre_trade_cleanup(context, over_before)
            if selecting and over_before > 0 and certainty == "exact"
            else None
        )
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
            selection_rule=rule,
            search_bound_exceeded=False if selecting else None,
            **_pre_trade_fields(pre_sel),
            **({"waiver_values_available": bool(context.waiver_values)} if selecting else {}),
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

    if selecting:
        return _assess_selected(
            context,
            surviving=surviving,
            incoming=incoming,
            package=package,
            notes=notes,
            counts=(size_before, size_after, len(outgoing), unheld_out, limit, open_before),
            certainty=certainty,
            taxi=(taxi_lo, taxi_hi),
            over=(over_before, over_after, over_after_min, over_after_max),
        )

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


def _assess_selected(
    context: CapacityContext,
    *,
    surviving: list[RosterAsset],
    incoming: list[str],
    package: fds.PackageSides | None,
    notes: list[str],
    counts: tuple[int, int, int, int, int, int],
    certainty: str,
    taxi: tuple[int, int],
    over: tuple[int, int | None, int, int],
) -> RosterCapacity:
    """The over-limit branch of :func:`assess_roster_capacity` under flag
    ``forced_drop_cheapest_legal``.  Counts, the taxi bracket and the notes are
    the incumbent's; only WHO is released and WHAT that is charged come from
    ``forced_drop_selection``."""
    size_before, size_after, n_outgoing, unheld_out, limit, open_before = counts
    over_before, over_after, over_after_min, over_after_max = over
    n_existing = len(surviving) - len(incoming)
    existing, arrivals = surviving[:n_existing], surviving[n_existing:]
    common: dict[str, Any] = dict(
        starter_slots=list(context.starter_slots),
        waiver_values=context.waiver_values,
        scarcity=context.scarcity,
        slot_eligibility=context.slot_eligibility,
    )
    if not context.starter_slots:
        notes.append(
            "no starter slots configured for this league — cut ladder built "
            "without a lineup-feasibility guard"
        )
    sel = fds.select_forced_drops(
        existing,
        arrivals,
        incoming,
        drops_needed=over_after_max,
        package=package,
        **common,
    )
    notes.extend(sel.notes)
    drops = [
        ForcedDrop(
            player_id=s.asset.player_id,
            name=s.asset.name,
            position=s.asset.position,
            value=s.asset.board_value,
            effective_cut_cost=s.ecc,
            release_cost=s.charge,
            waiver_value=float(s.waiver),
            scarcity_multiplier=float(s.mult),
            value_basis=s.value_basis,
            rung=i + 1,
            acquired_in_trade=s.acquired,
            charge_basis=s.charge_basis,
        )
        for i, s in enumerate(sel.drops)
    ]
    if sel.exhausted:
        notes.append(
            f"cut ladder offers {len(drops)} release(s) but {over_after_max} are needed — "
            "every remaining player is required to fill a starting slot, so no legal "
            "path back to roster size was modelled"
        )

    # What the roster owed BEFORE the trade (an over-limit roster): the trade is
    # charged only the difference (``_selected_forced_drop_cost``).
    pre_sel = (
        _pre_trade_cleanup(context, over_before)
        if over_before > 0 and certainty == "exact"
        else None
    )

    taxi_bound = None
    if certainty != "exact":
        # Taxi membership unknown: the charge is a lower bound on the releases
        # GUARANTEED under every assignment.  Re-run the selection at that
        # count (a subset of the worst-case cleanup is legal but not
        # necessarily the cheapest legal set of that size).
        added = min(over_after_min, max(0, size_after - size_before))
        if added <= 0:
            lb = None
        elif added == over_after_max and sel.mode == fds.MODE_PACKAGE_CONSISTENT:
            lb = sel
        else:
            # Always the charge-minimising (V5) selection, whichever mode is
            # served: the roster-rational set minimises ``sum c``, not the
            # charge, so its cost at a smaller count is not a lower bound.
            lb = fds.select_forced_drops(
                existing,
                arrivals,
                incoming,
                drops_needed=added,
                package=package,
                mode=fds.MODE_PACKAGE_CONSISTENT,
                **common,
            )
        if lb is not None:
            taxi_bound = (
                lb.total,
                lb.exhausted,
                any(
                    d.value_basis == "assumedWaiver" and d.charge_basis != fds.CHARGE_PACKAGE
                    for d in lb.drops
                ),
            )

    priced = [d.value for d in drops if d.value is not None]
    taxi_lo, taxi_hi = taxi
    return RosterCapacity(
        roster_limit=limit,
        taxi_size=context.taxi_size,
        size_before=size_before,
        size_after=size_after,
        incoming=len(incoming),
        outgoing=n_outgoing,
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
        # Drops are in charge order by construction; the incumbent's "rung
        # order carried no priority" condition cannot arise.
        rung_order_was_tied=False,
        unpriced_forced_drops=sum(1 for d in drops if d.value is None),
        ladder_exhausted=sel.exhausted,
        notes=notes,
        selection_rule=fds.rule_id(sel.mode),
        package_applied=sel.package_applied,
        search_bound_exceeded=sel.search_bound_exceeded,
        taxi_bound_cleanup=taxi_bound,
        waiver_values_available=bool(context.waiver_values),
        **_pre_trade_fields(pre_sel),
    )


def _pre_trade_cleanup(context: CapacityContext, over_before: int) -> fds.Selection:
    """The cheapest legal cleanup the PRE-trade roster owes on its own."""
    roster_before = [
        context.assets_by_key.get(_norm(n)) or _resolve_incoming(n, context.by_name)
        for n in context.roster_player_names
    ]
    return fds.cleanup_selection(
        roster_before,
        over_before,
        starter_slots=list(context.starter_slots),
        waiver_values=context.waiver_values,
        scarcity=context.scarcity,
        slot_eligibility=context.slot_eligibility,
    )


def _pre_trade_fields(pre: fds.Selection | None) -> dict[str, Any]:
    if pre is None:
        return {}
    return {
        "pre_trade_cleanup_cost": pre.total,
        "pre_trade_cleanup_exhausted": pre.exhausted,
        "pre_trade_cleanup_drops": tuple(
            (str(d.asset.player_id), d.value_basis) for d in pre.drops
        ),
    }


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
