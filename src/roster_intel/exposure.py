"""Value-weighted NFL-franchise exposure (C2-EXP-01, CE-06).

*"Show value-weighted NFL franchise exposure Before → After, e.g.
``MIN 18.2% → 22.4%``. It is informational, not an automatic trade
penalty."* — ``docs/OWNER_PRODUCT_BACKLOG_SPEC.md`` §1.6.

Descriptive only, and that is enforced rather than promised
=========================================================

This module emits **no flag, no verdict, no penalty and no
recommendation**.  Not "emits one that consumers may ignore" — emits
none, asserted structurally over the payload keys the same way
``simulation.py`` is.

That is also how the spec's handcuff carve-out is discharged.  *"Intentional
starting-QB + primary-backup handcuffs are purposeful exposure and should not
be flagged as accidental concentration"* is a guard against a flag; the honest
way to satisfy it is not to write a heuristic that guesses intent, but not to
flag.  Same-franchise same-position pairs ARE reported, as descriptive
context under ``handcuff_pairs``, with no claim about why they are there.

The owner's Minnesota overlay is a DIFFERENT owner: it is user- and
league-scoped, applies to the outgoing side of generated packages only, and
lives in ``docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md``.
Nothing here knows about it, and nothing here should.

Two scopes, named separately
============================

Exposure over the **meaningful core** answers "how concentrated is the part of
this roster that plays"; over the **full roster** it answers "how concentrated
is the capital".  They differ materially — measured on the live board, one
team's top franchise is 17.8% of its core and 16.4% of its roster — so both are
published under their own names rather than one being quietly chosen.

``FA`` is not a franchise
=========================

25 of 660 rostered players on the live board carry ``FA`` — genuine unsigned
NFL free agents — which ties the largest single franchise by HEADCOUNT (HOU,
also 25).  Only 6 of those 25 are priced, so by VALUE it is small: 0.58% of a
roster on average, 4.8% at the worst, and present on 2 of 12 teams.  Both
numbers are worth knowing, and neither makes ``FA`` a team.

Counting it as a 33rd franchise would report "your biggest exposure is FA",
which is not an exposure to a team at all; it is the *absence* of one, and it
is a different risk — an unsigned player's fantasy outlook depends on a
signing that has not happened.  It gets its own bucket with
``is_franchise=False``, and the concentration statistics are computed over
franchises only.

Missing is never zero
=====================

A player the board did not price carries no weight and is reported in
``unpriced_ids`` — never counted at 0, which would silently shrink every share's
denominator's honesty rather than the denominator itself.  A priced player whose
NFL team is unknown goes to ``unknown_team_ids``, not to a bucket.  Picks have no
NFL team and never enter: they are excluded by the pool builder, not bucketed as
"unknown".

Pure computation.  No I/O, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.roster_intel.core import MeaningfulCore

__all__ = [
    "NON_FRANCHISE_TOKENS",
    "ExposureChange",
    "FranchiseExposure",
    "NflExposure",
    "build_nfl_exposure",
    "exposure_change",
    "exposure_from_core",
    "nfl_team_by_player",
    "simulation_exposure_change",
]

#: Tokens the contract's ``team`` field uses that are not NFL franchises.
#: ``FA`` is an unsigned player; treating it as a team would report the
#: absence of a franchise as the largest exposure to one.
NON_FRANCHISE_TOKENS = frozenset({"FA", "FA*", "NONE", "UNK", "UNKNOWN", ""})


@dataclass(frozen=True)
class FranchiseExposure:
    """One bucket's share of the priced value in scope."""

    team: str
    is_franchise: bool
    value: float
    #: Percent of ``priced_value``, 0-100.
    share: float
    player_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "isFranchise": self.is_franchise,
            "value": round(self.value, 2),
            "share": round(self.share, 3),
            "playerIds": list(self.player_ids),
        }


@dataclass(frozen=True)
class NflExposure:
    """Value-weighted franchise exposure over one named population."""

    scope: str
    buckets: tuple[FranchiseExposure, ...]
    priced_value: float
    unpriced_ids: frozenset[str] = frozenset()
    unknown_team_ids: frozenset[str] = frozenset()
    handcuff_pairs: tuple[tuple[str, str, str], ...] = ()

    @property
    def franchises(self) -> tuple[FranchiseExposure, ...]:
        return tuple(b for b in self.buckets if b.is_franchise)

    @property
    def top_franchise_share(self) -> float | None:
        """Largest single-FRANCHISE share, or ``None`` when nothing is priced.

        ``None`` rather than ``0.0``: a roster with no priced players has an
        unmeasured concentration, not a concentration of zero.
        """
        franchises = self.franchises
        return max((b.share for b in franchises), default=None) if franchises else None

    @property
    def franchise_hhi(self) -> float | None:
        """Herfindahl index over franchise shares, on 0-10000.

        A descriptive spread statistic with a standard definition, published
        because "one 25% team" and "five 5% teams" are different rosters and a
        single top share cannot tell them apart.  It carries no threshold and
        no verdict; what counts as concentrated is a judgement this module does
        not make.
        """
        franchises = self.franchises
        if not franchises:
            return None
        return sum(b.share * b.share for b in franchises)

    def share_of(self, team: str) -> float:
        """This team's share, or ``0.0`` — which here is a real answer.

        A franchise you own nobody from genuinely is 0% of your value; that is
        not a missing measurement.  Unpriced and unknown-team players are the
        missing cases and they live in their own sets.
        """
        key = str(team).strip().upper()
        for bucket in self.buckets:
            if bucket.team == key:
                return bucket.share
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "buckets": [b.to_dict() for b in self.buckets],
            "pricedValue": round(self.priced_value, 2),
            "topFranchiseShare": (
                None if self.top_franchise_share is None else round(self.top_franchise_share, 3)
            ),
            "franchiseHHI": (None if self.franchise_hhi is None else round(self.franchise_hhi, 1)),
            "unpricedIds": sorted(self.unpriced_ids),
            "unknownTeamIds": sorted(self.unknown_team_ids),
            "handcuffPairs": [
                {"team": t, "position": pos, "playerIds": list(ids)}
                for t, pos, ids in _grouped_handcuffs(self.handcuff_pairs)
            ],
        }


def _grouped_handcuffs(
    pairs: Sequence[tuple[str, str, str]],
) -> list[tuple[str, str, tuple[str, ...]]]:
    """``(team, position, ids)`` rows from flat ``(team, position, id)`` triples."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for team, position, player_id in pairs:
        grouped.setdefault((team, position), []).append(player_id)
    return [(t, p, tuple(sorted(ids))) for (t, p), ids in sorted(grouped.items())]


def _normalize_team(raw: Any) -> str | None:
    """``"phi "`` → ``"PHI"``; anything empty → ``None`` (UNKNOWN, not a bucket)."""
    token = str(raw or "").strip().upper()
    return token or None


def nfl_team_by_player(contract: Mapping[str, Any] | None) -> dict[str, str]:
    """``{playerName: nflTeam}`` from the canonical board.

    Keyed the same way :func:`src.api.data_contract.contract_roster_pools`
    keys players (``canonicalName`` first, falling back to ``displayName``),
    so a caller joining this against a ``RosterPlayer``/``CoreMember``
    population cannot silently miss every row — a join key that disagrees
    with the pools fails completely rather than partially, which is what
    made the original bug (this function's predecessor keyed by
    ``playerId``, matching nothing) invisible until a live board was run.

    An empty ``team`` is left OUT rather than stored as ``""`` — callers
    read absence as UNKNOWN. ``"FA"`` (an unsigned free agent) IS a real,
    resolved value here, not a missing one — see :data:`NON_FRANCHISE_TOKENS`
    for the caller-side rule that a resolved-but-non-franchise team must not
    be bucketed as if it were one of the 32 NFL teams.

    Moved here from ``src/api/roster_intelligence.py`` (2026-09) so a second
    consumer (Team Assignment's NFL affinity model) does not need to keep a
    private duplicate of this join — one owner for "which NFL team is this
    canonical player on".
    """
    out: dict[str, str] = {}
    if not isinstance(contract, Mapping):
        return out
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        team = str(row.get("team") or "").strip()
        if not team:
            continue
        for key in (row.get("canonicalName"), row.get("displayName")):
            if key:
                out.setdefault(str(key), team)
    return out


def build_nfl_exposure(
    player_ids: Iterable[str],
    *,
    teams: Mapping[str, Any],
    values: Mapping[str, float | None],
    positions: Mapping[str, str] | None = None,
    scope: str = "meaningful_core",
) -> NflExposure:
    """Value-weighted franchise exposure over ``player_ids``.

    Args:
        player_ids: the population in scope, keyed the way ``teams`` /
            ``values`` are keyed.  The caller chooses the population — the
            meaningful core, the full roster, one trade side — and names it in
            ``scope``, because a share is meaningless without its denominator.
        teams: ``{playerId: nflTeam}``.  A missing or empty entry is UNKNOWN.
        values: ``{playerId: rankDerivedValue | None}``.  ``None`` is unpriced.
        positions: optional, only used to report handcuff pairs.
    """
    priced: dict[str, float] = {}
    unpriced: set[str] = set()
    unknown_team: set[str] = set()
    by_team: dict[str, list[str]] = {}

    for raw_id in player_ids:
        player_id = str(raw_id)
        value = values.get(player_id)
        if not isinstance(value, (int, float)):
            unpriced.add(player_id)
            continue
        team = _normalize_team(teams.get(player_id))
        if team is None:
            # Priced but unplaceable.  Counted nowhere rather than bucketed as
            # a franchise called "UNKNOWN", which would then hold a share.
            unknown_team.add(player_id)
            continue
        priced[player_id] = float(value)
        by_team.setdefault(team, []).append(player_id)

    total = sum(priced.values())
    buckets: list[FranchiseExposure] = []
    for team, ids in by_team.items():
        value = sum(priced[i] for i in ids)
        buckets.append(
            FranchiseExposure(
                team=team,
                is_franchise=team not in NON_FRANCHISE_TOKENS,
                value=value,
                share=(100.0 * value / total) if total > 0 else 0.0,
                player_ids=tuple(sorted(ids)),
            )
        )
    # Largest first, then alphabetically — deterministic under any input order.
    buckets.sort(key=lambda b: (-b.share, b.team))

    handcuffs: list[tuple[str, str, str]] = []
    if positions:
        for team, ids in sorted(by_team.items()):
            if team in NON_FRANCHISE_TOKENS:
                continue
            by_position: dict[str, list[str]] = {}
            for player_id in ids:
                position = str(positions.get(player_id) or "").strip().upper()
                if position:
                    by_position.setdefault(position, []).append(player_id)
            for position, group in by_position.items():
                if len(group) > 1:
                    handcuffs.extend((team, position, pid) for pid in sorted(group))

    return NflExposure(
        scope=str(scope),
        buckets=tuple(buckets),
        priced_value=total,
        unpriced_ids=frozenset(unpriced),
        unknown_team_ids=frozenset(unknown_team),
        handcuff_pairs=tuple(handcuffs),
    )


def exposure_from_core(
    core: MeaningfulCore,
    *,
    teams: Mapping[str, Any],
    values: Mapping[str, float | None] | None = None,
    scope: str = "meaningful_core",
) -> NflExposure:
    """Exposure over a meaningful core, using the core's own values.

    The core already carries each member's canonical value and position, so
    passing ``values`` is optional — and when it is omitted this cannot
    disagree with Team Strength about what a member is worth.
    """
    member_values = {m.player_id: m.value for m in core.members}
    if values:
        member_values.update({k: v for k, v in values.items() if k in member_values})
    return build_nfl_exposure(
        [m.player_id for m in core.members],
        teams=teams,
        values=member_values,
        positions={m.player_id: m.position for m in core.members},
        scope=scope,
    )


@dataclass(frozen=True)
class ExposureChange:
    """One franchise's before → after share."""

    team: str
    is_franchise: bool
    share_before: float
    share_after: float

    @property
    def delta(self) -> float:
        return self.share_after - self.share_before

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "isFranchise": self.is_franchise,
            "shareBefore": round(self.share_before, 3),
            "shareAfter": round(self.share_after, 3),
            "delta": round(self.delta, 3),
        }


def exposure_change(before: NflExposure, after: NflExposure) -> dict[str, Any]:
    """``MIN 18.2% → 22.4%`` for every franchise either side touches.

    The union of both sides, so a franchise you exited (share → 0.0) is as
    visible as one you entered.  Reporting only the after side would make an
    exit invisible, which is the direction a diversification story is most
    likely to be told badly.

    Emits no verdict.  A share moving is a fact; whether it is good is a trade
    judgement built on top, and this module deliberately cannot express one.
    """
    teams = {b.team: b.is_franchise for b in before.buckets}
    teams.update({b.team: b.is_franchise for b in after.buckets})
    rows = [
        ExposureChange(
            team=team,
            is_franchise=is_franchise,
            share_before=before.share_of(team),
            share_after=after.share_of(team),
        )
        for team, is_franchise in teams.items()
    ]
    rows.sort(key=lambda r: (-abs(r.delta), r.team))
    return {
        "before": before.to_dict(),
        "after": after.to_dict(),
        "changes": [r.to_dict() for r in rows],
        "moved": [r.to_dict() for r in rows if abs(r.delta) > 1e-9],
    }


def simulation_exposure_change(
    simulation: Any,
    *,
    teams: Mapping[str, Any],
    scope: str = "meaningful_core",
) -> dict[str, Any]:
    """Before → after exposure for a :class:`~src.roster_intel.simulation.RosterSimulation`.

    **The dependency arrow points this way on purpose.**  Exposure reads a
    simulation; the simulation knows nothing about exposure and imports nothing
    from here.  That is what makes "descriptive only, must not influence the
    trade grade" a structural property rather than a promise — there is no edge
    along which it could influence anything, and a test asserts the import graph
    stays that way.

    Typed loosely (``Any``) for the same reason: importing ``RosterSimulation``
    for an annotation would create the very edge the separation exists to avoid.
    """
    return exposure_change(
        exposure_from_core(simulation.core_before, teams=teams, scope=scope),
        exposure_from_core(simulation.core_after, teams=teams, scope=scope),
    )
