"""Use Team Context — one shared mode for every trade surface (V1-41 / C3-CTX-01).

Owner decision #842, binding spec
``docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md`` §3-§5.
Before this module the toggle did not exist anywhere in the repository.

What the mode is
================
**ON (``teamContext``, the default)** — evaluation and generation may consume
real selected-team / opponent context: roster ownership, Team Strength and
Weakness, the meaningful roster core, age-value / young core, competitive
posture, playoff / bye / championship probability and post-trade
counterfactuals, season timing, pick ownership and forecast, positional need,
surplus, depth, promotion / displacement, and approved user constraints.

**OFF (``assetOnly``)** — a clearly labelled Asset-Only analysis.  No
team-specific evidence reaches the verdict or the ranking.

The distinction that is easiest to get backwards
================================================
**OFF removes TEAM context, not LEAGUE-FORMAT valuation.**  The selected
league's TEP / Superflex / IDP / scoring / roster configuration still shapes
canonical asset value, because that is a property of the league's rules and not
of anybody's roster.  An Asset-Only analysis in a Superflex TE-premium league is
still a Superflex TE-premium analysis.  So OFF may still consume canonical
league-format-aware player and pick value, package and Value Adjustment math,
external-market corroboration, asset-level uncertainty, age as an *intrinsic*
descriptor, real trade comps and liquidity, source confidence and coverage, and
hard user constraints.

Three rules, all structurally testable
======================================
1. **OFF must not consume team context in the verdict.**  Not "should not" —
   the partition below is the definition, and the accompanying test proves it by
   making every team-context owner RAISE and requiring a verdict anyway.  Same
   non-influence proof #914 used for `C2-EXP-01`.
2. **Never silently fall back ON → OFF.**  A missing dimension while ON degrades
   EXPLICITLY: it is named in ``degraded`` with a reason, the mode stays ON, and
   the surface says which dimensions were not included.  Silently switching
   modes would publish an Asset-Only verdict under a team-aware label, which is
   the failure the spec names.
3. **A dimension is either team context or it is not**, and that is decided
   here rather than at each call site.  ``ALL_DIMENSIONS`` is exhaustive by
   construction and :func:`admits` refuses an unknown name rather than guessing
   — an unclassified dimension defaulting to "admissible" is how team evidence
   leaks into an Asset-Only verdict.

This module decides ADMISSIBILITY.  It computes no value, reads no roster, and
never resolves a league; a caller asks whether a dimension may be consumed and
records what it could not get.  Pure, no I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = [
    "ALL_DIMENSIONS",
    "ASSET_ONLY_DIMENSIONS",
    "CONTEXT_OFF",
    "CONTEXT_ON",
    "DEFAULT_MODE",
    "DegradedDimension",
    "TEAM_CONTEXT_DIMENSIONS",
    "TradeContextMode",
    "UnknownDimension",
    "admits",
    "resolve_context_mode",
]

CONTEXT_ON = "teamContext"
CONTEXT_OFF = "assetOnly"

#: #842: ON by default.  A caller that says nothing gets the full analysis.
DEFAULT_MODE = CONTEXT_ON

#: Evidence OFF must not consume in the verdict or the ranking (spec §3 OFF).
TEAM_CONTEXT_DIMENSIONS: frozenset[str] = frozenset(
    {
        "rosterFit",
        "positionalNeed",
        "teamStrength",
        "teamWeakness",
        "meaningfulCore",
        "teamAgeValue",
        "youngCore",
        "competitivePosture",
        "playoffOdds",
        "championshipOdds",
        "byeOdds",
        "seasonWindowStrategy",
        "ownPickStrategy",
        "opponentPosture",
        "rosterCapacity",
        "promotionDisplacement",
    }
)

#: Evidence OFF may still consume (spec §3 "May still use").
#:
#: ``leagueFormatValuation`` is on this side deliberately and is the entry most
#: likely to be moved by mistake: TEP / Superflex / IDP / scoring shape the
#: canonical value of an ASSET, which is not team context.
ASSET_ONLY_DIMENSIONS: frozenset[str] = frozenset(
    {
        "canonicalAssetValue",
        "leagueFormatValuation",
        "packageValueAdjustment",
        "externalMarket",
        "assetUncertainty",
        "intrinsicAge",
        "pickValue",
        "tradeComps",
        "liquidity",
        "sourceConfidence",
        "userConstraints",
    }
)

ALL_DIMENSIONS: frozenset[str] = TEAM_CONTEXT_DIMENSIONS | ASSET_ONLY_DIMENSIONS

assert not (
    TEAM_CONTEXT_DIMENSIONS & ASSET_ONLY_DIMENSIONS
), "a dimension cannot be both team context and asset-only"


class UnknownDimension(KeyError):
    """A dimension nobody classified.

    Raised rather than defaulted.  Defaulting to admissible leaks team evidence
    into an Asset-Only verdict; defaulting to inadmissible silently drops
    asset-only evidence from the team-aware one.  Neither failure announces
    itself, so the unclassified name is refused at the boundary instead.
    """


@dataclass(frozen=True)
class DegradedDimension:
    """A dimension the mode ALLOWS but the data could not supply."""

    dimension: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "reason": self.reason}


@dataclass(frozen=True)
class TradeContextMode:
    """The resolved mode for one request, plus what it could not get."""

    mode: str = DEFAULT_MODE
    degraded: tuple[DegradedDimension, ...] = field(default_factory=tuple)

    @property
    def team_context(self) -> bool:
        return self.mode == CONTEXT_ON

    def admits(self, dimension: str) -> bool:
        """May this mode consume ``dimension`` in the verdict?"""
        return admits(self.mode, dimension)

    def available(self, dimension: str) -> bool:
        """Admissible AND actually supplied.

        The two questions are separate on purpose: "OFF, so not consulted" and
        "ON, but the snapshot was missing" are different sentences and a surface
        that collapses them cannot explain itself.
        """
        return self.admits(dimension) and dimension not in {d.dimension for d in self.degraded}

    def degrade(self, dimension: str, reason: str) -> TradeContextMode:
        """Record that an ALLOWED dimension was unavailable.  Mode is unchanged.

        This is the whole of rule 2.  Falling back to ``assetOnly`` here would
        publish an Asset-Only verdict under a team-aware label.
        """
        if dimension not in ALL_DIMENSIONS:
            raise UnknownDimension(dimension)
        if not self.admits(dimension):
            # Not degraded — deliberately not consulted.  Recording it would
            # read as "we wanted this and could not get it".
            return self
        if any(d.dimension == dimension for d in self.degraded):
            return self
        return TradeContextMode(
            mode=self.mode,
            degraded=tuple(
                sorted(
                    [*self.degraded, DegradedDimension(dimension, reason)],
                    key=lambda d: d.dimension,
                )
            ),
        )

    def excluded_dimensions(self) -> tuple[str, ...]:
        """What this mode did not consult, so a surface can label the panels.

        Spec §4: "If team-context panels are visible while OFF, they must be
        marked `not included in this verdict`."
        """
        return tuple(sorted(d for d in ALL_DIMENSIONS if not self.admits(d)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "teamContext": self.team_context,
            "label": "Team Context" if self.team_context else "Asset-Only Analysis",
            "degraded": [d.to_dict() for d in self.degraded],
            "excludedDimensions": list(self.excluded_dimensions()),
            # Named so nothing downstream has to infer it: OFF removes team
            # context, and never the league's own scoring rules.
            "leagueFormatValuationIncluded": True,
        }


def admits(mode: str, dimension: str) -> bool:
    """May ``mode`` consume ``dimension``?  Raises on an unclassified name."""
    if dimension not in ALL_DIMENSIONS:
        raise UnknownDimension(dimension)
    if mode == CONTEXT_ON:
        return True
    return dimension in ASSET_ONLY_DIMENSIONS


def resolve_context_mode(
    body: Mapping[str, Any] | None = None,
    query: Mapping[str, Any] | None = None,
) -> TradeContextMode:
    """Which mode this request asked for.  Body first, then query, then ON.

    Same precedence ``_requested_valuation_mode`` uses, so a POST engine and a
    GET surface ask the same way.  **Anything unrecognised resolves to ON**, not
    to an error and not to OFF: the default is the complete analysis, and a typo
    must not silently downgrade a user to Asset-Only under a label that does not
    say so.
    """
    raw = ""
    for source, keys in (
        (body, ("useTeamContext", "teamContext", "contextMode")),
        (query, ("useTeamContext", "teamContext", "contextMode")),
    ):
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            if key in source and source[key] is not None:
                raw = str(source[key]).strip()
                break
        if raw:
            break

    if raw.lower() in {"false", "0", "off", "no", CONTEXT_OFF.lower(), "asset_only", "asset-only"}:
        return TradeContextMode(mode=CONTEXT_OFF)
    return TradeContextMode(mode=CONTEXT_ON)


def assert_asset_only(mode: TradeContextMode, dimensions: Iterable[str]) -> None:
    """Raise if any of ``dimensions`` is inadmissible under ``mode``.

    For call sites that consume a batch of evidence: cheaper to state the whole
    set once than to guard each read, and it fails loudly rather than quietly
    including something it should not.
    """
    bad = sorted(d for d in dimensions if not admits(mode.mode, d))
    if bad:
        raise ValueError(f"{mode.mode} may not consume team-context evidence: {', '.join(bad)}")
