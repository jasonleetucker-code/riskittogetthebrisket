"""C5-PROJ-D — ROS / full-season projection ensemble.

Fourth sub-unit of the multi-source projection ensemble (`C5-U1`), per
`docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md` §6/§9 item 4. Built out of
execution order relative to `C5-PROJ-C` (weekly ensemble) — see
`docs/projections/C5_PROJ_D_ROS_FULL_SEASON_ENSEMBLE.md` for the full
reasoning. In short: the `C5-PROJ-A` census
(`config/projections/source_capability_census.json`) has exactly two
`implementationStatus: LIVE` `PROJECTION_MODEL` sources today —
``clayProjections`` and ``idpShowProjections`` — and both are
``PRESEASON_FULL_SEASON`` horizon. Zero ``WEEKLY``-horizon sources are
live. `C5-PROJ-C` would have nothing real to combine; this unit does.

**Combines `ProjectionObservation` rows (`C5-PROJ-B`) across independent
provider families**, per plan §6: "count independent model families, not
pages... Start with simple robust family-level baselines rather than
learned weights from a tiny sample: equal-family mean; median;
trimmed/robust mean. Reliability/adaptive weighting is challenger
methodology only after sufficient leakage-safe history exists." There is
no weight parameter anywhere in this module — the closed `method` literal
below is the entire combination mechanism, so nothing can be silently
tuned later without a deliberate code change and review.

**Distinct from `src.ros.aggregate`.** That module blends *rank/ranking*
evidence into `rosValue`. This module blends *point-value projection*
evidence (`league_scored_fpg`) into a cross-family consensus. Different
inputs, different consumers, not touched here.

**Deliberately stops at the combined observation.** No downstream
consumer (Game Day, Power, Playoff, waivers, lineup, Universal Player
Profile) is wired here — that is `C5-PROJ-F`'s job. No DFS/betting-market
evidence class is handled — no live source of either class exists yet,
and the plan wants those "separately lineage-aware," never blindly
pooled. No fetcher or acquisition code is added — this module only calls
`C5-PROJ-B`'s `load_and_rescore_source`.

Deliberately NOT a dynasty value or ranking of any kind — same
source-domain-boundary posture as `ProjectionObservation`. Nothing here
writes `rankDerivedValue` or any of its aliases; the existing repo-wide
guard already scans every module under `src/ros/`, including this one
(`tests/api/test_canonical_ownership_protections.py::
test_no_seasonal_lane_module_assigns_a_canonical_alias`).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.ros import projection_source_census as census
from src.ros.projection_observations import ProjectionObservation, load_and_rescore_source

#: The three combination primitives plan §6 explicitly authorizes for a
#: multi-family panel. Anything else (a learned weight, a reliability
#: score, an adaptive coefficient) is challenger methodology gated on
#: `C5-PROJ-E`'s leakage-safe backtest history existing first — not
#: something this module accepts, even as an option.
COMBINATION_METHODS: frozenset[str] = frozenset({"equal_family_mean", "median", "trimmed_mean"})

#: Sources this unit's default entry point combines — the two, and only
#: two, PROJECTION_MODEL sources censused LIVE today. A caller wanting a
#: different source set (e.g. once a third family goes live) passes its
#: own `census_source_keys`; nothing here hardcodes the number two beyond
#: this default tuple.
_DEFAULT_ROS_FULL_SEASON_SOURCES: tuple[str, ...] = ("clayProjections", "idpShowProjections")


class ProjectionEnsembleError(ValueError):
    """Raised for a structural misuse of this module: mixing horizons or
    seasons in one combination call, an empty input, an unrecognized
    `method`, or an observation that should never reach an ensemble at
    all (a proxy row, or a non-`PROJECTION_MODEL` evidence class) —
    never silently resolved or averaged away."""


@dataclass(frozen=True)
class FamilyValue:
    """One provider family's representative value for one player, one
    season, one horizon — after within-family reduction. Today this is
    always a passthrough (`source_count == 1`): no family has more than
    one live source yet. The reduction step exists so a family that later
    gains a second product does not silently double that family's vote
    weight in the cross-family combination."""

    provider_family: str
    league_scored_fpg: float
    source_count: int
    census_source_keys: tuple[str, ...]


@dataclass(frozen=True)
class EnsembleObservation:
    """The combined, cross-family projection for one player, in one
    horizon, one season.

    Deliberately NOT a dynasty value or ranking — see module docstring.
    """

    player_key: str
    position: str
    season: int
    horizon: str

    combined_league_scored_fpg: float
    #: "equal_family_mean" | "median" | "trimmed_mean" |
    #: "single_family_passthrough". The last is FORCED whenever
    #: `family_count == 1`, regardless of what `method` the caller
    #: requested — a one-family observation is not a fabricated
    #: ensemble, and must never be labelled as one.
    combination_method: str
    family_count: int
    contributing_families: tuple[FamilyValue, ...]

    #: `None` — never `0.0` — when `family_count < 2`. Disagreement
    #: cannot be measured from a single point; coercing it to zero would
    #: read as "these families agree perfectly," which is not a claim
    #: single-source evidence can support ("missing is never zero").
    disagreement_spread: float | None
    disagreement_stddev: float | None

    as_of: str
    #: `None` when contributing families disagree on games played for
    #: this player (e.g. a different bye-week/injury-week assumption) —
    #: never silently averaged, since an averaged games count is not a
    #: number either source actually published.
    games: float | None


def _assert_single_horizon_and_season(observations: Sequence[ProjectionObservation]) -> None:
    if not observations:
        raise ProjectionEnsembleError("cannot combine an empty set of observations")
    horizons = {o.horizon for o in observations}
    seasons = {o.season for o in observations}
    if len(horizons) > 1:
        raise ProjectionEnsembleError(
            f"cannot combine observations across horizons {sorted(horizons)} in one "
            "ensemble call — plan §9 item 4: 'no weekly/ROS semantic mixing'. Call "
            "this once per horizon."
        )
    if len(seasons) > 1:
        raise ProjectionEnsembleError(
            f"cannot combine observations across seasons {sorted(seasons)} in one ensemble call."
        )


def _assert_real_projection_evidence(observations: Sequence[ProjectionObservation]) -> None:
    for obs in observations:
        if obs.is_proxy:
            raise ProjectionEnsembleError(
                f"{obs.player_key!r}/{obs.census_source_key!r}: a proxy "
                "(Brisket-internal reconstructed-baseline) observation cannot enter "
                "this ensemble — it would be presented as independent multi-vendor "
                "consensus when it is not. `load_and_rescore_source` already excludes "
                "proxy rows by default; a caller passing one in explicitly is a bug."
            )
        if obs.evidence_class != "PROJECTION_MODEL":
            raise ProjectionEnsembleError(
                f"{obs.player_key!r}/{obs.census_source_key!r}: evidence_class "
                f"{obs.evidence_class!r} is not PROJECTION_MODEL — this module only "
                "combines real projection-model evidence; DFS/betting-market "
                "evidence needs separate lineage-aware handling (plan §9 item 3), "
                "and RANKINGS_ONLY evidence is not projection evidence at all."
            )


def reduce_family(observations: Sequence[ProjectionObservation]) -> FamilyValue:
    """Reduce one provider family's observations for one player/season/
    horizon into a single representative value.

    All ``observations`` must share ``provider_family``, ``player_key``,
    ``season`` and ``horizon`` — raises :class:`ProjectionEnsembleError`
    otherwise. This should never happen if the caller groups correctly
    (see :func:`combine_ensemble`), but a silent cross-family or
    cross-horizon average here would be exactly the defect class this
    unit exists to prevent, so it is checked rather than assumed.
    """
    _assert_single_horizon_and_season(observations)
    _assert_real_projection_evidence(observations)
    families = {o.provider_family for o in observations}
    if len(families) > 1:
        raise ProjectionEnsembleError(
            f"cannot reduce observations from multiple provider families "
            f"{sorted(families)} as one family — group by provider_family first"
        )
    player_keys = {o.player_key for o in observations}
    if len(player_keys) > 1:
        raise ProjectionEnsembleError(
            f"cannot reduce observations for multiple players {sorted(player_keys)} "
            "as one family value — group by player_key first"
        )

    values = [o.league_scored_fpg for o in observations]
    representative = values[0] if len(values) == 1 else statistics.median(values)

    return FamilyValue(
        provider_family=observations[0].provider_family,
        league_scored_fpg=representative,
        source_count=len(observations),
        census_source_keys=tuple(sorted({o.census_source_key for o in observations})),
    )


def combine_ensemble(
    observations: Sequence[ProjectionObservation],
    *,
    method: str = "equal_family_mean",
) -> EnsembleObservation:
    """Combine every family's evidence for ONE player, in ONE horizon, ONE
    season, into a single :class:`EnsembleObservation`.

    ``method`` selects the cross-family combination primitive when two or
    more families contribute (plan §6's three approved baselines). It is
    ignored — and ``combination_method`` is forced to
    ``"single_family_passthrough"`` — when only one family covers this
    player, so a single-source value is never mislabelled as a consensus.
    """
    _assert_single_horizon_and_season(observations)
    _assert_real_projection_evidence(observations)
    if method not in COMBINATION_METHODS:
        raise ProjectionEnsembleError(
            f"unrecognized combination method {method!r}; must be one of "
            f"{sorted(COMBINATION_METHODS)}"
        )
    player_keys = {o.player_key for o in observations}
    if len(player_keys) > 1:
        raise ProjectionEnsembleError(
            f"cannot combine observations for multiple players {sorted(player_keys)} "
            "in one call — call this once per player"
        )

    by_family: dict[str, list[ProjectionObservation]] = {}
    for obs in observations:
        by_family.setdefault(obs.provider_family, []).append(obs)
    family_values = [reduce_family(rows) for rows in by_family.values()]
    family_values.sort(key=lambda fv: fv.provider_family)

    values = [fv.league_scored_fpg for fv in family_values]
    family_count = len(family_values)

    games_by_family = {o.games for o in observations}
    games = next(iter(games_by_family)) if len(games_by_family) == 1 else None

    as_of = max(o.as_of for o in observations)
    sample = observations[0]

    if family_count == 1:
        return EnsembleObservation(
            player_key=sample.player_key,
            position=sample.position,
            season=sample.season,
            horizon=sample.horizon,
            combined_league_scored_fpg=values[0],
            combination_method="single_family_passthrough",
            family_count=1,
            contributing_families=tuple(family_values),
            disagreement_spread=None,
            disagreement_stddev=None,
            as_of=as_of,
            games=games,
        )

    if method == "equal_family_mean":
        combined = statistics.fmean(values)
    elif method == "median":
        combined = statistics.median(values)
    else:  # "trimmed_mean"
        if family_count < 3:
            raise ProjectionEnsembleError(
                f"trimmed_mean needs at least 3 contributing families to trim both "
                f"ends and still have something left to average; got {family_count}"
            )
        trimmed = sorted(values)[1:-1]
        combined = statistics.fmean(trimmed)

    return EnsembleObservation(
        player_key=sample.player_key,
        position=sample.position,
        season=sample.season,
        horizon=sample.horizon,
        combined_league_scored_fpg=combined,
        combination_method=method,
        family_count=family_count,
        contributing_families=tuple(family_values),
        disagreement_spread=max(values) - min(values),
        disagreement_stddev=statistics.pstdev(values),
        as_of=as_of,
        games=games,
    )


@dataclass(frozen=True)
class EnsembleBuildResult:
    """Outcome of building the ensemble for one season/horizon across a
    named set of sources. Mirrors `LoadResult`'s "report the refusal,
    don't silently return an empty list" posture — a caller must be able
    to tell "zero sources had data this season" from "every source had
    data and genuinely zero players matched"."""

    season: int
    horizon: str
    ensemble: tuple[EnsembleObservation, ...]
    sources_loaded: tuple[str, ...]
    sources_unavailable: tuple[str, ...]


def build_ros_full_season_ensemble(
    *,
    season: int,
    scoring_settings: Mapping[str, Any],
    horizon: str = "PRESEASON_FULL_SEASON",
    census_source_keys: Sequence[str] = _DEFAULT_ROS_FULL_SEASON_SOURCES,
    method: str = "equal_family_mean",
    base_dir: Path | None = None,
) -> EnsembleBuildResult:
    """Load every named source's latest snapshot (via `C5-PROJ-B`'s
    `load_and_rescore_source`), filter to `horizon`, group by player, and
    combine.

    Raises :class:`ProjectionEnsembleError` if any requested
    ``census_source_keys`` entry's own census record does not publish
    ``horizon`` at all — asking this function for a horizon a named
    source never produces is a caller/config bug, not a legitimate
    "zero observations" state.
    """
    for key in census_source_keys:
        entry = census.get_source(key)
        if entry is not None and horizon not in (entry.get("horizons") or []):
            raise ProjectionEnsembleError(
                f"{key!r} is censused with horizons {entry.get('horizons')!r}, which "
                f"does not include the requested {horizon!r} — this source cannot "
                "answer this question."
            )

    sources_loaded: list[str] = []
    sources_unavailable: list[str] = []
    by_player: dict[str, list[ProjectionObservation]] = {}

    for key in census_source_keys:
        result = load_and_rescore_source(
            key, season=season, scoring_settings=scoring_settings, base_dir=base_dir
        )
        if result.status != "ok":
            sources_unavailable.append(key)
            continue
        sources_loaded.append(key)
        for obs in result.observations:
            if obs.horizon != horizon:
                continue
            by_player.setdefault(obs.player_key, []).append(obs)

    ensemble = tuple(combine_ensemble(rows, method=method) for rows in by_player.values())
    # Deterministic ordering for a caller that wants to display/iterate
    # without re-sorting — sorted by player_key, not insertion order.
    ensemble = tuple(sorted(ensemble, key=lambda e: e.player_key))

    return EnsembleBuildResult(
        season=season,
        horizon=horizon,
        ensemble=ensemble,
        sources_loaded=tuple(sources_loaded),
        sources_unavailable=tuple(sources_unavailable),
    )
