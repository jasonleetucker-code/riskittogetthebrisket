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
from src.bdvm.source_vocabulary import record_coverage
from src.nfl_data.synthetic_splits import RECEPTION_BAND_KEYS, synthetic_band_keys
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

    # ── Additive scoring detail (optional; defaults keep every existing
    # construction site and serializer byte-identical). ──────────────
    #: ``(scoring_key, raw_stat, rate, awarded_points)`` per game, from the
    #: ONE scoring call that produced ``league_scored_fpg`` — the canonical
    #: scorer's own components, never a second scoring pass.  For a
    #: stat-line record they sum, in order, to ``league_scored_fpg``
    #: exactly.  Empty when the source supplied points rather than a stat
    #: line (nothing was scored here) and for constructions that predate it.
    scoring_components: tuple[tuple[str, float, float, float], ...] = ()
    #: Nonzero card rules this observation's points do NOT include because
    #: the source did not project them — their contribution is UNKNOWN,
    #: never zero.  For BDVM-snapshot records this is the canonical
    #: per-record coverage (``src.bdvm.source_vocabulary.record_coverage``),
    #: fed the engine's own unscored keys from the same scoring call.
    uncovered_paid_keys: tuple[str, ...] = ()
    #: Card keys whose projected value is an IMPUTED split rather than
    #: provider evidence (today: the provider's fixed reception-band split,
    #: :mod:`src.nfl_data.synthetic_splits`).  A label only — the points
    #: are still in ``league_scored_fpg``; nothing here changes a number.
    synthetic_components: tuple[str, ...] = ()
    #: ``"complete"`` / ``"partial"`` / ``"unverifiable"`` from the same
    #: coverage owner, so an empty ``uncovered_paid_keys`` on a record whose
    #: coverage could not be checked (source-scored points) never reads as
    #: complete.  ``None`` when not computed.
    coverage_status: str | None = None


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

    # ONE scoring call: the total, the engine's unscored keys and the
    # per-key components all come from this resolution.
    resolved = record.resolve_fpg_breakdown(scoring_settings)
    league_scored_fpg, league_native = resolved.fpg, resolved.scoring_native
    coverage = record_coverage(record, scoring_settings, engine_unscored=resolved.unscored)
    uncovered, coverage_status = _with_unreadable_rates(
        tuple(coverage.unscored_keys), coverage.status, scoring_settings
    )
    synthetic = _synthetic_components(record, resolved.components)

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
        scoring_components=resolved.components,
        uncovered_paid_keys=uncovered,
        synthetic_components=synthetic,
        coverage_status=coverage_status,
    )


def _with_unreadable_rates(
    uncovered: tuple[str, ...], status: str, scoring_settings: Mapping[str, Any]
) -> tuple[tuple[str, ...], str]:
    """Add card keys whose RATE is unreadable to the uncovered list.

    The realized engine coerces a non-numeric rate to 0 and the coverage
    owner skips it, so an unreadable rate would otherwise vanish.  An
    unknown rate is not a zero rate: it is named here, and a ``complete``
    coverage verdict drops to ``partial``.  Additive — a card whose rates
    all parse is untouched.
    """
    unreadable: list[str] = []
    for key, raw in (scoring_settings or {}).items():
        if isinstance(raw, bool):
            unreadable.append(str(key))
            continue
        try:
            rate = float(raw)
        except (TypeError, ValueError):
            unreadable.append(str(key))
            continue
        if rate != rate:  # NaN
            unreadable.append(str(key))
    if not unreadable:
        return uncovered, status
    merged = tuple(sorted(set(uncovered) | set(unreadable)))
    return merged, ("partial" if status == "complete" else status)


def _synthetic_components(
    record: ProjectionRecord, components: tuple[tuple[str, float, float, float], ...]
) -> tuple[str, ...]:
    """Band keys that are the provider's fixed split, on either key view.

    Checked on the record's own stat line (a Sleeper-keyed source) and on
    the scored per-game components (the Sleeper-keyed view the scorer saw).
    The two are checked separately rather than merged — they may be on
    different bases (season vs per game); a share test is basis-free
    within one view.
    """
    found: set[str] = set()
    if record.stat_line:
        found.update(synthetic_band_keys(record.stat_line))
    if components:
        found.update(synthetic_band_keys({key: raw for key, raw, _rate, _pts in components}))
    return tuple(k for k in RECEPTION_BAND_KEYS if k in found)


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
