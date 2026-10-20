"""The ONE derived-evidence lineage registry (League Intelligence Stage E).

B10 (``src/api/data_contract.py::_RANKING_SOURCES`` ``correlation_group``)
answers "which RANKING SOURCES are one provider's opinion".  This registry
answers the next question up: "which DERIVED quantities -- a canonical board
value, a package Value Adjustment, a league-scored projection, a best-ball
lineup delta, a playoff simulation, a fair-value challenger -- are
descendants of the same body of evidence", so a decision that reads several of
them counts that evidence ONCE (CLAUDE.md, "Signal independence").

It owns exactly three things:

* :data:`GROUPS` -- the correlation groups of derived evidence, their members
  and whether a member of the group may vote in a decision at all.  The B10
  families a group descends from are REFERENCED by their B10 id strings, never
  redefined here (``tests/evidence_lineage`` pins that every id resolves
  against ``config/sources/source_lineage.json`` through B10).
* :data:`PARTIAL_OVERLAPS` -- pairs of DIFFERENT groups that share a named
  component no validated method can remove from either.  Both may vote, but
  their agreement is never corroboration.
* :func:`assert_voting_terms_valid` -- the mechanical lineage rule: at most one
  voting term per group, no vote from a non-voting group, and the agreement
  cap any declared partial overlap imposes.  It RAISES on violation; a
  decision that double counts is a defect, not a degraded answer.

The registry computes no value and imports nothing from ``src``: the decision
engine (``src/trade/decision_engine``) and the league fair-value challenger
(``src/league_valuation``) both read it, and neither may keep a second copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

REGISTRY_VERSION = "evidence_lineage_v1"


class LineageViolation(ValueError):
    """A set of voting terms breaks the lineage rule (double counting)."""


@dataclass(frozen=True)
class CorrelationGroup:
    """One body of derived evidence.

    ``descends_from_source_families`` are B10 family ids (``correlation_group``
    values, or a singleton source key), referenced and never redefined.
    ``selection_dependencies`` names what a non-voting group's SELECTION reads
    (posture selects the strategy row from inputs that share the projection /
    ``rosValue`` lineage), so a reader can see why it may not also vote.
    """

    id: str
    descends_from_source_families: tuple[str, ...]
    members: tuple[str, ...]
    voting: bool
    selection_dependencies: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "descendsFromSourceFamilies": list(self.descends_from_source_families),
            "members": list(self.members),
            "voting": self.voting,
            "selectionDependencies": list(self.selection_dependencies),
            "note": self.note,
        }


#: The B10 families whose votes make up the canonical board (the voting
#: correlation groups of ``_RANKING_SOURCES`` on 2026-10-19).  A new voting
#: family joining the board is a lineage change: add it here in the same PR.
_CANONICAL_BOARD_FAMILIES: tuple[str, ...] = (
    "dlf",
    "draftSharks",
    "dynastyDaddySf",
    "dynastyNerdsSfTep",
    "fantasyCalc",
    "fantasyPros",
    "flockFantasy",
    "idpShow",
    "idpTradeCalc",
    "ktcCrowd",
    "ktcTrades",
    "otcffbSf",
    "pfkDynasty",
    "yahooBoone",
)

CANONICAL_MARKET = "canonical_market"
LEAGUE_SCORED_PROJECTION = "league_scored_projection"
TEAM_STRATEGY_CONTEXT = "team_strategy_context"
MANAGER_CONTEXT = "manager_context"
MARKET_COMPARABLES = "market_comparables"

_GROUPS: tuple[CorrelationGroup, ...] = (
    CorrelationGroup(
        id=CANONICAL_MARKET,
        descends_from_source_families=_CANONICAL_BOARD_FAMILIES,
        members=("rank_derived_value", "package_va"),
        voting=True,
        note=(
            "rankDerivedValue and the active package Value Adjustment.  VA is a "
            "transform of the same asset values, not a separate family."
        ),
    ),
    CorrelationGroup(
        id=LEAGUE_SCORED_PROJECTION,
        descends_from_source_families=(),
        members=(
            "projection_snapshot",
            "bdvm_fundamental",
            "ros_ensemble",
            "bestball_lineup_delta",
            "bestball_marginal",
            "bestball_horizon",
            "playoff_presim",
            "league_fair_value",
        ),
        voting=True,
        note=(
            "Every quantity built from league-scored projections.  Exactly one "
            "member may vote per team decision; league_fair_value is a "
            "descendant of bdvm_fundamental and is never a decision vote."
        ),
    ),
    CorrelationGroup(
        id=TEAM_STRATEGY_CONTEXT,
        descends_from_source_families=(),
        members=("posture",),
        voting=False,
        selection_dependencies=(LEAGUE_SCORED_PROJECTION, "rosValue"),
        note="Competitive posture selects the strategy row only: never a vote, never a confidence axis.",
    ),
    CorrelationGroup(
        id=MANAGER_CONTEXT,
        descends_from_source_families=(),
        members=("manager_tendency",),
        voting=False,
        note="Manager tendencies may inform only the counterparty acceptance note.",
    ),
    CorrelationGroup(
        id=MARKET_COMPARABLES,
        descends_from_source_families=(),
        members=("comparable_trades",),
        voting=False,
        note="Comparable trades are context, never a vote.",
    ),
)

GROUPS: Mapping[str, CorrelationGroup] = MappingProxyType({g.id: g for g in _GROUPS})

#: Declared partial overlaps between DIFFERENT groups.  The dynasty market
#: value already prices near-term production and no validated method removes
#: the current-season component from it, so market and league-scored
#: projection may both vote but their agreement never corroborates.
PARTIAL_OVERLAPS: Mapping[frozenset[str], str] = MappingProxyType(
    {frozenset({CANONICAL_MARKET, LEAGUE_SCORED_PROJECTION}): "current_season_production"}
)

#: The confidence label a partial overlap caps the agreement axis at.
OVERLAP_AGREEMENT_CAP = "medium"

_MEMBER_TO_GROUP: Mapping[str, str] = MappingProxyType(
    {member: g.id for g in _GROUPS for member in g.members}
)


def _check_registry() -> None:
    seen: dict[str, str] = {}
    for g in _GROUPS:
        for m in g.members:
            if m in seen:
                raise RuntimeError(f"lineage member {m!r} declared in {seen[m]} and {g.id}")
            seen[m] = g.id
    for pair in PARTIAL_OVERLAPS:
        if len(pair) != 2 or not pair <= set(GROUPS):
            raise RuntimeError(f"partial overlap {sorted(pair)} must name two declared groups")


_check_registry()


def group_of(member: str) -> str:
    """The group a derived-evidence member belongs to.

    Raises ``KeyError`` for an undeclared member: an unregistered quantity has
    no proven independence, so it cannot be admitted by default.
    """
    try:
        return _MEMBER_TO_GROUP[member]
    except KeyError:
        raise KeyError(f"undeclared lineage member {member!r}") from None


@dataclass(frozen=True)
class LineageVerdict:
    """What :func:`assert_voting_terms_valid` proved about a set of terms."""

    voting_groups: tuple[str, ...]
    partial_overlaps: tuple[str, ...]
    agreement_cap: str | None
    voting_members: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "registryVersion": REGISTRY_VERSION,
            "votingGroups": list(self.voting_groups),
            "votingMembers": list(self.voting_members),
            "partialOverlaps": list(self.partial_overlaps),
            "agreementCap": self.agreement_cap,
        }


def _field(term: Mapping[str, Any], snake: str, camel: str) -> Any:
    return term[snake] if snake in term else term.get(camel)


def assert_voting_terms_valid(terms: Sequence[Mapping[str, Any]]) -> LineageVerdict:
    """Validate the terms of ONE team decision against the lineage rule.

    Each term is a mapping carrying ``lineage_member`` (or ``lineageMember``)
    and ``counted_as_vote`` (or ``countedAsVote``).  Every term, voting or not,
    must name a declared member.  Raises :class:`LineageViolation` when:

    * a member is undeclared;
    * a voting term comes from a ``voting=False`` group;
    * two voting terms come from one group.
    """
    by_group: dict[str, list[str]] = {}
    for term in terms:
        member = _field(term, "lineage_member", "lineageMember")
        if not isinstance(member, str):
            raise LineageViolation(f"term without a lineage member: {dict(term)!r}")
        try:
            gid = group_of(member)
        except KeyError as exc:
            raise LineageViolation(str(exc)) from exc
        if _field(term, "counted_as_vote", "countedAsVote") is not True:
            continue
        if not GROUPS[gid].voting:
            raise LineageViolation(f"{member!r} votes, but group {gid!r} is non-voting")
        by_group.setdefault(gid, []).append(member)
    for gid, members in by_group.items():
        if len(members) > 1:
            raise LineageViolation(
                f"group {gid!r} has {len(members)} voting terms ({', '.join(members)}); "
                "at most one is allowed"
            )
    voting = tuple(sorted(by_group))
    overlaps = tuple(sorted(name for pair, name in PARTIAL_OVERLAPS.items() if pair <= set(voting)))
    return LineageVerdict(
        voting_groups=voting,
        partial_overlaps=overlaps,
        agreement_cap=OVERLAP_AGREEMENT_CAP if overlaps else None,
        voting_members=tuple(sorted(m for ms in by_group.values() for m in ms)),
    )


def registry_snapshot() -> dict[str, Any]:
    """The whole registry as data, for receipts."""
    return {
        "registryVersion": REGISTRY_VERSION,
        "groups": [g.to_dict() for g in _GROUPS],
        "partialOverlaps": [
            {"groups": sorted(pair), "component": name} for pair, name in PARTIAL_OVERLAPS.items()
        ],
    }
