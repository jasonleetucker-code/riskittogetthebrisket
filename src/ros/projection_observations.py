"""C5-PROJ-B — canonical projection-stat schema + exact-league rescoring.

Second sub-unit of the multi-source projection ensemble (`C5-U1`), per
`docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md` §4/§5. Builds directly on
`C5-PROJ-A`'s finding (`docs/projections/C5_PROJ_A_SOURCE_CAPABILITY_CENSUS.md`):
two real `PROJECTION_MODEL` sources already exist — inside `src.bdvm`, not
this package — with a working schema (`ProjectionRecord`) and a working
exact-league rescorer (`ProjectionRecord.resolve_fpg`).

**This module does not reimplement either.** It wraps `ProjectionRecord`
into the seasonal ensemble's own observation contract (plan §4's field
list) and calls `resolve_fpg` for the rescoring step — "ONE CONCEPT, ONE
CANONICAL OWNER" applied to the projection *schema and scoring* layer,
exactly as `C5-PROJ-A` recommended. What this module adds that
`ProjectionRecord` does not carry: `evidenceClass`, `horizon`,
`accessPosture` and `providerFamily` — fields the DYNASTY-fundamental
BDVM engine has no reason to track, but the seasonal ensemble's
independence/lineage rules (plan §6) cannot function without. Those four
come from `C5-PROJ-A`'s census (`src.ros.projection_source_census`), never
invented here — a `ProjectionObservation` cannot exist for a source the
census does not know about.

**Native provider totals are diagnostic only** (plan §4: "preserve the
native total as a diagnostic"). `ProjectionObservation.native_fpg` and
`native_scoring_native` are carried for display/audit; every consumer
that blends or ranks projections must read `league_scored_fpg`.

**Proxy rows are excluded from ensemble use by default.**
`ProjectionRecord.is_proxy=True` marks BDVM's own reconstructed-baseline
rows — a Brisket-internal estimate, not a vendor's real projection, and
therefore not a `PROJECTION_MODEL` observation for the ensemble's
independence-counting purposes (plan §6: "count independent model
families"). `rescore_projection_record` refuses (returns ``None``) on a
proxy row unless the caller explicitly opts in with
``include_proxy=True`` — and even then the resulting observation is
stamped ``is_proxy=True`` so nothing downstream can mistake it for real
vendor evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.bdvm.projections import ProjectionRecord, latest_snapshot_path, load_snapshot
from src.ros import projection_source_census as census


@dataclass(frozen=True)
class ProjectionObservation:
    """The seasonal ensemble's canonical projection-stat contract (plan §4).

    Deliberately NOT a dynasty value or ranking of any kind — this is
    seasonal evidence, kept on the redraft/ROS side of the source-domain
    boundary (`docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md`). Nothing in this
    module writes `rankDerivedValue` or any of its aliases; see
    `tests/api/test_canonical_ownership_protections.py::test_no_seasonal_lane_module_assigns_a_canonical_alias`,
    which already scans every module under `src/ros/`, including this one.
    """

    census_source_key: str
    provider_family: str
    evidence_class: str
    horizon: str
    access_posture: str

    player_key: str
    position: str
    season: int
    as_of: str
    games: float

    #: Under the CALLER's exact league scoring — the number every
    #: ensemble/consensus/blend consumer must read.
    league_scored_fpg: float
    #: Whether `league_scored_fpg` already reflects league-native scoring
    #: without a rescore step (True when the source's own points already
    #: matched, per `ProjectionRecord.resolve_fpg`'s own contract).
    league_scored_is_native: bool

    #: Diagnostic only — the source's own reported per-game figure,
    #: BEFORE any league rescoring. Never feed this into a blend.
    native_fpg: float | None
    native_is_scoring_native: bool

    stat_line_available: bool
    proj_high: float | None
    proj_low: float | None
    is_proxy: bool


class ProjectionObservationError(ValueError):
    """Raised when a record cannot be wrapped — e.g. the census has no
    entry for its source, which would silently invent an evidence class
    otherwise."""


def rescore_projection_record(
    record: ProjectionRecord,
    *,
    scoring_settings: Mapping[str, Any],
    census_source_key: str,
    include_proxy: bool = False,
) -> ProjectionObservation | None:
    """Wrap one `ProjectionRecord` into the ensemble's observation
    contract, rescoring it through the caller's exact league scoring.

    Returns ``None`` (a refusal, not an error) when ``record.is_proxy`` is
    True and ``include_proxy`` is False — the default posture, since a
    caller building real ensemble evidence should not have to remember to
    filter proxies out themselves.

    Raises :class:`ProjectionObservationError` when ``census_source_key``
    has no entry in the `C5-PROJ-A` census — this is a caller/config bug
    (the fetcher-to-census mapping drifted), not a missing-data state, and
    should surface loudly rather than silently degrade to an unlabelled
    observation.
    """
    if record.is_proxy and not include_proxy:
        return None

    entry = census.get_source(census_source_key)
    if entry is None:
        raise ProjectionObservationError(
            f"{census_source_key!r} is not in the C5-PROJ-A source census "
            "(config/projections/source_capability_census.json) — every "
            "projection observation must be traceable to a censused "
            "source. Add it to the census before wiring a new fetcher."
        )
    if entry["evidenceClass"] not in ("PROJECTION_MODEL", "DFS_PROJECTION", "BETTING_MARKET"):
        raise ProjectionObservationError(
            f"{census_source_key!r} is censused as {entry['evidenceClass']!r}, "
            "not a projection evidence class — rescoring a RANKINGS_ONLY "
            "source would manufacture projection evidence the source "
            "never published."
        )
    horizons = entry.get("horizons") or []
    if len(horizons) != 1:
        # ProjectionRecord carries no horizon field of its own (every
        # BDVM snapshot today is a full-season projection), so this
        # wrapper can only infer the horizon when the census names
        # exactly one candidate. A source later censused for multiple
        # horizons (e.g. a real weekly + a real ROS product) needs a
        # horizon-aware ProjectionRecord source, or an explicit horizon
        # argument here — failing closed rather than guessing which one
        # a given snapshot actually is.
        raise ProjectionObservationError(
            f"{census_source_key!r} is censused with {len(horizons)} horizon(s) "
            f"{horizons!r}; this wrapper can only infer a horizon for a "
            "single-horizon source. Pass the horizon explicitly once a "
            "multi-horizon source needs this path."
        )

    league_scored_fpg, league_native = record.resolve_fpg(scoring_settings)

    native_fpg: float | None
    if record.fpg is not None:
        native_fpg = float(record.fpg)
    elif record.fpts is not None and record.games > 0:
        native_fpg = float(record.fpts) / record.games
    else:
        # Source published only a raw stat line, no native point total.
        native_fpg = None

    return ProjectionObservation(
        census_source_key=census_source_key,
        provider_family=str(entry["providerFamily"]),
        evidence_class=str(entry["evidenceClass"]),
        horizon=str(horizons[0]),
        access_posture=str(entry["accessPosture"]),
        player_key=record.player_key,
        position=record.position,
        season=record.season,
        as_of=record.as_of,
        games=record.games,
        league_scored_fpg=league_scored_fpg,
        league_scored_is_native=league_native,
        native_fpg=native_fpg,
        native_is_scoring_native=record.scoring_native,
        stat_line_available=record.stat_line is not None,
        proj_high=record.proj_high,
        proj_low=record.proj_low,
        is_proxy=record.is_proxy,
    )


@dataclass(frozen=True)
class LoadResult:
    """Outcome of loading + rescoring one source's snapshot. Mirrors
    BDVM's own ``status: "no_projection_snapshot"`` refusal shape
    (`src/bdvm/service.py`) rather than inventing a second one — a
    missing snapshot is reported, never silently treated as zero
    observations available."""

    status: str  # "ok" | "no_snapshot" | "no_census_entry"
    census_source_key: str
    observations: tuple[ProjectionObservation, ...] = ()
    proxy_rows_excluded: int = 0
    reason: str = ""


def load_and_rescore_source(
    census_source_key: str,
    *,
    season: int,
    scoring_settings: Mapping[str, Any],
    base_dir: Path | None = None,
) -> LoadResult:
    """Load one census-registered LIVE source's latest BDVM snapshot and
    rescore every non-proxy record in it through the caller's league
    scoring.

    Only meaningful for sources whose `C5-PROJ-A` census entry names a
    real `existingModule` (today: `clayProjections`, `idpShowProjections`)
    — this function does not fetch or parse anything itself, it reads the
    snapshot the existing BDVM fetcher already wrote.
    """
    entry = census.get_source(census_source_key)
    if entry is None:
        return LoadResult(
            status="no_census_entry",
            census_source_key=census_source_key,
            reason=f"{census_source_key!r} is not in the C5-PROJ-A source census",
        )

    path = latest_snapshot_path(season, base_dir=base_dir)
    if path is None:
        return LoadResult(
            status="no_snapshot",
            census_source_key=census_source_key,
            reason=f"no BDVM projection snapshot found for season {season}",
        )

    _as_of, all_records = load_snapshot(path)
    source_records = [r for r in all_records if r.source == census_source_key]

    observations: list[ProjectionObservation] = []
    proxy_excluded = 0
    for record in source_records:
        obs = rescore_projection_record(
            record,
            scoring_settings=scoring_settings,
            census_source_key=census_source_key,
        )
        if obs is None:
            proxy_excluded += 1
            continue
        observations.append(obs)

    return LoadResult(
        status="ok",
        census_source_key=census_source_key,
        observations=tuple(observations),
        proxy_rows_excluded=proxy_excluded,
    )
