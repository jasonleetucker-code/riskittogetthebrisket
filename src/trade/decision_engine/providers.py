"""Local provider Protocols and explicit "unavailable" stubs (batch 1).

BATCH-1 ISOLATION RULE: this package imports no sibling League Intelligence
package (``src.bestball``, ``src.league_valuation``, the scoring provider).  Each
Protocol below is a STRUCTURAL mirror of the provider's published ``to_dict``
shape (camelCase mappings), so the batch-2 adapters can be type-checked
against them and parity-tested against the providers' committed fixtures.

Until a provider is merged and wired, :func:`stub_providers` answers every call
with ``state: "unavailable"`` plus a reason and NO numbers -- never a
fabricated zero, mean or probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

NOT_MERGED = "provider_not_merged_batch1"


@runtime_checkable
class ScoringProvider(Protocol):
    """Mirror of ``src.league_intel.projection_provider.ScoringProvider``:
    PredictiveSummary-shaped mappings (mean, median, sd, quantiles, pZero,
    basis, n, paramSetId, state, reason)."""

    def weekly_summary(self, player_id: str, season: int, week: int) -> Mapping[str, Any]: ...

    def season_summary(self, player_id: str, season: int) -> Mapping[str, Any]: ...

    def observation(
        self, player_id: str, season: int, week: int | None
    ) -> Mapping[str, Any] | None: ...


@runtime_checkable
class BestBallProvider(Protocol):
    """Mirror of ``src.bestball.provider.BestBallProvider``: TeamLineupDelta-,
    MarginalBestBallUtility- and TeamHorizonExpectation-shaped mappings."""

    def two_sided_lineup_deltas(
        self, team_ids: Sequence[str], **kwargs: Any
    ) -> Mapping[str, Mapping[str, Any]]: ...

    def marginal(self, player_id: str, **kwargs: Any) -> Mapping[str, Any]: ...

    def team_horizon(self, team_id: str, **kwargs: Any) -> Mapping[str, Any]: ...


@runtime_checkable
class CompetitiveProvider(Protocol):
    """Mirror of ``src.bestball.provider.CompetitiveProvider``:
    CompetitiveOutcome-shaped mappings keyed by owner id."""

    def championship_delta(
        self,
        owner_ids: Sequence[str],
        lineup_deltas: Mapping[str, Any],
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Mapping[str, Any]]: ...


@runtime_checkable
class ValuationProvider(Protocol):
    """Mirror of ``src.league_valuation.provider.ValuationProvider``:
    LeagueFairValue-shaped mappings.  A NON-VOTING diagnostic for the decision
    engine (lineage: descendant of ``bdvm_fundamental``)."""

    def fair_value_for(self, asset_key: str) -> Mapping[str, Any]: ...

    def board_pins(self) -> Mapping[str, Any]: ...


def unavailable(reason: str, **identity: str) -> dict[str, Any]:
    """The one shape a stub answers: identity keys, a state and a reason."""
    return {**identity, "state": "unavailable", "reason": reason}


class UnavailableScoringProvider:
    def __init__(self, reason: str = NOT_MERGED) -> None:
        self.reason = reason

    def weekly_summary(self, player_id: str, season: int, week: int) -> Mapping[str, Any]:
        return unavailable(self.reason, playerId=player_id)

    def season_summary(self, player_id: str, season: int) -> Mapping[str, Any]:
        return unavailable(self.reason, playerId=player_id)

    def observation(self, player_id: str, season: int, week: int | None) -> None:
        return None


class UnavailableBestBallProvider:
    def __init__(self, reason: str = NOT_MERGED) -> None:
        self.reason = reason

    def two_sided_lineup_deltas(
        self, team_ids: Sequence[str], **kwargs: Any
    ) -> Mapping[str, Mapping[str, Any]]:
        return {t: unavailable(self.reason, ownerId=t) for t in team_ids}

    def marginal(self, player_id: str, **kwargs: Any) -> Mapping[str, Any]:
        return unavailable(self.reason, playerId=player_id)

    def team_horizon(self, team_id: str, **kwargs: Any) -> Mapping[str, Any]:
        return unavailable(self.reason, ownerId=team_id)


class UnavailableCompetitiveProvider:
    def __init__(self, reason: str = NOT_MERGED) -> None:
        self.reason = reason

    def championship_delta(
        self,
        owner_ids: Sequence[str],
        lineup_deltas: Mapping[str, Any],
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Mapping[str, Any]]:
        return {o: unavailable(self.reason, ownerId=o) for o in owner_ids}


class UnavailableValuationProvider:
    def __init__(self, reason: str = "fair_value_artifact_not_built") -> None:
        self.reason = reason

    def fair_value_for(self, asset_key: str) -> Mapping[str, Any]:
        return unavailable(self.reason, assetKey=asset_key)

    def board_pins(self) -> Mapping[str, Any]:
        return unavailable(self.reason)


@dataclass(frozen=True)
class Providers:
    scoring: ScoringProvider
    bestball: BestBallProvider
    competitive: CompetitiveProvider
    valuation: ValuationProvider


def stub_providers(reason: str = NOT_MERGED) -> Providers:
    """Every provider answering ``unavailable`` with ``reason`` -- no numbers."""
    return Providers(
        scoring=UnavailableScoringProvider(reason),
        bestball=UnavailableBestBallProvider(reason),
        competitive=UnavailableCompetitiveProvider(reason),
        valuation=UnavailableValuationProvider(),
    )
