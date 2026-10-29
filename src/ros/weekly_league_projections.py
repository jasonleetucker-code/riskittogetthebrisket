"""League-scored WEEKLY projected points for every player — one owner.

One question, one owner: *for (league, season, week), what is each NFL
player's projected fantasy score under THIS league's exact scoring card,
where did it come from, and what does it not cover?*  Consumers (the IDP
streaming solver, the Waiver Advisor, an API) read
:func:`load_weekly_projections`; none fetches, rescores or combines a weekly
source itself.

Reused, not forked
------------------
=====================================  ==================================================
concern                                owner consumed
=====================================  ==================================================
RotoWire-via-Sleeper weekly rows        :mod:`src.ros.sleeper_weekly_projections`
FPTrack weekly rows (coverage filler)   :mod:`src.ros.fptrack_weekly_projections`
keyed-provider mapping + rescoring      :mod:`src.ros.keyed_weekly_projections`
exact league scoring                    :func:`src.league_intel.scorer.score_stat_line`
league scoring card + its evidence      :mod:`src.api.league_registry` snapshot
cross-family combination                :func:`src.ros.projection_ensemble.combine_ensemble`
independence / ancestry                 :mod:`src.ros.projection_source_census`
first-down bonus imputation (ours)      :func:`src.nfl_data.first_down_rate.imputed_sleeper_first_down_bonus`
bye weeks                               :func:`src.ros.game_day_week.bye_teams_for_week`
NFL schedule                            :func:`src.nfl_data.ingest.fetch_schedules`
identity (FPTrack only)                 :mod:`src.identity` directory index + CANONICAL_V2
=====================================  ==================================================

States — missing is never zero
------------------------------
* ``projected`` — at least one live source projected the player this week;
  ``weeklyPoints`` is the league-scored number.
* ``bye`` — ``0.0``, ONLY when the NFL schedule proves the player's team has
  no game this week (:func:`bye_teams_for_week` over a schedule that has the
  week).  An unavailable schedule never yields a bye.
* ``injured_out`` — ``0.0``, ONLY when no provider projected the player AND
  the host (Sleeper) lists him ``Out`` / ``IR`` / ``PUP`` / ``Sus`` AND the
  requested week is the caller-stated current week (a designation describes
  now, not a future week).  Same posture as Game Day's "host-declared Out is
  definitive" rule (:mod:`src.ros.game_day_week`).
* ``unprojected`` — ``None`` with a reason: no live source, the week is not
  published yet, the provider shipped a placeholder, no NFL team on file, …

Independence — no double counting
---------------------------------
Sources are tried in :data:`SOURCE_PRECEDENCE`.  A source whose census
ancestry overlaps a source already contributing for that player
(:func:`projection_source_census.ancestry_overlaps` — same family, or a
declared constituent) does NOT vote; it is listed in ``excludedSources``.
FPTrack declares RotoWire as a constituent, so today it only fills players
RotoWire did not project.  With two or more INDEPENDENT families the
combination is the ensemble owner's ``equal_family_mean``; with one it is
labelled ``single_family_passthrough`` — never presented as a consensus.

Caching
-------
Fetches are cached per ``(source, season, week)`` for
:data:`FETCH_TTL_SECONDS`; results are cached on ``(scoring fingerprint,
season, week, each source's fetch version, schedule signature, current week,
positions)`` — the scoring IDENTITY, never the ``scoringProfile`` label.

**Seasonal intelligence lane only.**  Nothing here reads or writes
``rankDerivedValue`` or any dynasty value, rank, vote or weight.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from src.ros import projection_source_census as census
from src.utils.name_clean import normalize_position

__all__ = [
    "COMBINE_ENSEMBLE",
    "COMBINE_PASSTHROUGH",
    "FETCH_TTL_SECONDS",
    "INJURED_OUT_STATUSES",
    "SOURCE_PRECEDENCE",
    "STATE_BYE",
    "STATE_INJURED_OUT",
    "STATE_PROJECTED",
    "STATE_UNPROJECTED",
    "LeagueScoredWeeklyProjection",
    "ProjectionCoverage",
    "SourceContribution",
    "SourceState",
    "WeeklyProjectionSet",
    "clear_caches",
    "load_weekly_projection_horizon",
    "load_weekly_projections",
]

STATE_PROJECTED = "projected"
STATE_BYE = "bye"
STATE_UNPROJECTED = "unprojected"
STATE_INJURED_OUT = "injured_out"

COMBINE_PASSTHROUGH = "single_family_passthrough"
COMBINE_ENSEMBLE = "equal_family_mean"

SLEEPER_SOURCE = "sleeperWeeklyProjections"
FPTRACK_SOURCE = "fptrackWeeklyProjections"
#: Precedence order: the first source of an ancestry group keeps the vote.
SOURCE_PRECEDENCE: tuple[str, ...] = (SLEEPER_SOURCE, FPTRACK_SOURCE)

#: Host injury designations that mean "will not play THIS week".
INJURED_OUT_STATUSES: frozenset[str] = frozenset({"Out", "IR", "PUP", "Sus"})

FETCH_TTL_SECONDS = 900.0
_RESULT_CACHE_SIZE = 32

_IDP = frozenset({"DL", "LB", "DB"})
_KNOWN_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")


# ── Public contract ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceContribution:
    """One source's league-scored number for one player."""

    source_key: str
    family: str
    provider_model: str
    fetched_at: str | None
    updated_at: str | None
    #: The provider line under the league card (excludes our imputation).
    weekly_points: float
    #: OUR first-down imputation added for this source (0.0 when none).
    imputed_points: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceKey": self.source_key,
            "family": self.family,
            "providerModel": self.provider_model,
            "fetchedAt": self.fetched_at,
            "updatedAt": self.updated_at,
            "weeklyPoints": self.weekly_points,
            "imputedPoints": self.imputed_points,
        }


@dataclass(frozen=True)
class ProjectionCoverage:
    """Which league-paid categories the projection speaks to.

    ``leaguePaidKeys`` = paid keys relevant to the player's position: those
    the provider projects for that position plus those it leaves uncovered.
    ``coverageShare`` is a KEY-COUNT share (not point-weighted), ``None``
    when nothing is relevant."""

    league_paid_keys: tuple[str, ...]
    covered_keys: tuple[str, ...]
    uncovered_keys: tuple[str, ...]
    coverage_share: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaguePaidKeys": list(self.league_paid_keys),
            "coveredKeys": list(self.covered_keys),
            "uncoveredKeys": list(self.uncovered_keys),
            "coverageShare": self.coverage_share,
        }


@dataclass(frozen=True)
class LeagueScoredWeeklyProjection:
    player_id: str
    name: str | None
    position: str | None
    team: str | None
    season: int
    week: int
    #: ``None`` unless ``state`` is projected / bye / injured_out.
    weekly_points: float | None
    state: str
    reason: str
    sources: tuple[SourceContribution, ...] = ()
    combine_method: str | None = None
    coverage: ProjectionCoverage | None = None
    opponent: str | None = None
    game_id: str | None = None
    injury_status: str | None = None
    imputed_points: float = 0.0
    imputed_keys: tuple[str, ...] = ()
    family_count: int = 0
    disagreement_spread: float | None = None
    #: Sources that projected the player but were not allowed to vote
    #: (ancestry overlap with a source already contributing).
    excluded_sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.name,
            "position": self.position,
            "team": self.team,
            "season": self.season,
            "week": self.week,
            "weeklyPoints": self.weekly_points,
            "state": self.state,
            "reason": self.reason,
            "sources": [s.to_dict() for s in self.sources],
            "combineMethod": self.combine_method,
            "coverage": self.coverage.to_dict() if self.coverage else None,
            "opponent": self.opponent,
            "gameId": self.game_id,
            "injuryStatus": self.injury_status,
            "imputedPoints": self.imputed_points,
            "imputedKeys": list(self.imputed_keys),
            "familyCount": self.family_count,
            "disagreementSpread": self.disagreement_spread,
            "excludedSources": list(self.excluded_sources),
        }


@dataclass(frozen=True)
class SourceState:
    source_key: str
    family: str | None
    #: ``live`` | ``unavailable``.
    state: str
    reason: str
    fetched_at: str | None = None
    observation_count: int = 0
    refused: Mapping[str, int] = field(default_factory=dict)
    unmapped_provider_fields: Mapping[str, int] = field(default_factory=dict)
    unresolved_count: int = 0
    placeholder_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceKey": self.source_key,
            "family": self.family,
            "state": self.state,
            "reason": self.reason,
            "fetchedAt": self.fetched_at,
            "observationCount": self.observation_count,
            "refused": dict(self.refused),
            "unmappedProviderFields": dict(self.unmapped_provider_fields),
            "unresolvedCount": self.unresolved_count,
            "placeholderFields": list(self.placeholder_fields),
        }


@dataclass(frozen=True)
class WeeklyProjectionSet:
    league_key: str
    season: int
    week: int
    as_of: str
    scoring_fingerprint: str | None
    #: ``fresh`` | ``stale`` | ``missing`` (registry) | ``caller_supplied``.
    scoring_evidence_state: str
    #: Set when nothing could be scored at all (e.g. no scoring card).
    refusal: str | None
    source_states: tuple[SourceState, ...]
    players: Mapping[str, LeagueScoredWeeklyProjection]
    #: ``ok`` | ``unavailable`` — whether the schedule covers this week.
    schedule_state: str
    bye_teams: tuple[str, ...]
    current_week: int | None
    cache_key: str

    def get(self, player_id: str) -> LeagueScoredWeeklyProjection | None:
        return self.players.get(str(player_id))

    def by_position(self, *positions: str) -> list[LeagueScoredWeeklyProjection]:
        wanted = {normalize_position(p) for p in positions}
        return [p for p in self.players.values() if p.position in wanted]

    def counts(self) -> dict[str, dict[str, int]]:
        """``{position: {state: n}}``."""
        out: dict[str, dict[str, int]] = {}
        for p in self.players.values():
            bucket = out.setdefault(p.position or "?", {})
            bucket[p.state] = bucket.get(p.state, 0) + 1
        return out

    def to_dict(self, *, include_players: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "leagueKey": self.league_key,
            "season": self.season,
            "week": self.week,
            "asOf": self.as_of,
            "scoringFingerprint": self.scoring_fingerprint,
            "scoringEvidenceState": self.scoring_evidence_state,
            "refusal": self.refusal,
            "sourceStates": [s.to_dict() for s in self.source_states],
            "scheduleState": self.schedule_state,
            "byeTeams": list(self.bye_teams),
            "currentWeek": self.current_week,
            "cacheKey": self.cache_key,
            "counts": self.counts(),
        }
        if include_players:
            out["players"] = {pid: p.to_dict() for pid, p in sorted(self.players.items())}
        return out


# ── Caches ───────────────────────────────────────────────────────────

_lock = threading.Lock()
_fetch_cache: dict[tuple[str, int, int], tuple[float, Any]] = {}
_result_cache: OrderedDict[str, WeeklyProjectionSet] = OrderedDict()


def clear_caches() -> None:
    with _lock:
        _fetch_cache.clear()
        _result_cache.clear()


def _default_fetch(source_key: str, season: int, week: int) -> Any:
    if source_key == SLEEPER_SOURCE:
        from src.ros.sleeper_weekly_projections import fetch_weekly_projection_rows

        return fetch_weekly_projection_rows(int(season), int(week))
    if source_key == FPTRACK_SOURCE:
        from src.ros.fptrack_weekly_projections import fetch_weekly_projection_payload

        return fetch_weekly_projection_payload(int(season), int(week))
    raise KeyError(f"no fetcher for weekly source {source_key!r}")


def _cached_fetch(source_key: str, season: int, week: int, now_ts: float) -> Any:
    key = (source_key, int(season), int(week))
    with _lock:
        hit = _fetch_cache.get(key)
        if hit is not None and 0 <= now_ts - hit[0] < FETCH_TTL_SECONDS:
            return hit[1]
    result = _default_fetch(source_key, season, week)
    if getattr(result, "status", None) == "ok":
        # Only a successful fetch is held; a failure is retried next call.
        with _lock:
            _fetch_cache[key] = (now_ts, result)
    return result


# ── Helpers ──────────────────────────────────────────────────────────


def _rate(scoring: Mapping[str, Any], key: str) -> float:
    """The card's rate for ``key``.  An absent or non-numeric rule pays
    nothing, which is what the exact scorer does with it too."""
    raw = scoring.get(key)
    if raw is None or isinstance(raw, bool):
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _family(source_key: str) -> str | None:
    entry = census.get_source(source_key)
    return str(entry["providerFamily"]) if entry else None


def _team(code: Any) -> str | None:
    team = str(code or "").strip().upper()
    if not team:
        return None
    return "LAR" if team == "LA" else team


def _resolve_scoring(
    league_key: str, scoring_settings: Mapping[str, Any] | None
) -> tuple[Mapping[str, Any] | None, str, str | None]:
    """``(card, evidence state, refusal)``."""
    if scoring_settings is not None:
        return scoring_settings, "caller_supplied", None
    from src.api import league_registry as reg  # noqa: PLC0415

    cfg = reg.get_league_by_key(league_key)
    if cfg is None:
        return None, "missing", f"unknown_league:{league_key}"
    card = reg.scoring_settings_for_league(cfg)
    state = reg.scoring_evidence_state(cfg)
    if not card:
        return None, state, "scoring_card_unavailable"
    return card, state, None


def _default_schedule_rows(season: int) -> list[Mapping[str, Any]]:
    """The cached nflverse schedule — the request path never fetches."""
    try:
        from src.nfl_data import ingest  # noqa: PLC0415

        return list(ingest.fetch_schedules([int(season)], cache_only=True) or [])
    except Exception:  # noqa: BLE001 — absence of schedule evidence, never a bye
        return []


def _schedule(rows: Iterable[Mapping[str, Any]], season: int, week: int) -> tuple[str, frozenset]:
    from src.ros.game_day_week import bye_teams_for_week  # noqa: PLC0415

    rows = list(rows or ())
    has_week = False
    for row in rows:
        try:
            if (
                int(row.get("season")) == int(season)
                and int(row.get("week")) == int(week)
                and row.get("game_type") == "REG"
            ):
                has_week = True
                break
        except (TypeError, ValueError):
            continue
    if not has_week:
        return "unavailable", frozenset()
    return "ok", bye_teams_for_week(rows, season=int(season), week=int(week))


@dataclass
class _Meta:
    name: str | None = None
    position: str | None = None
    positions: tuple[str, ...] = ()
    team: str | None = None
    injury_status: str | None = None
    game_id: str | None = None
    opponent: str | None = None


def _sleeper_meta(rows: Iterable[Any]) -> dict[str, _Meta]:
    """Every player Sleeper listed (placeholders included)."""
    out: dict[str, _Meta] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pid = str(row.get("player_id") or "").strip()
        if not pid:
            continue
        player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
        raw_positions = player.get("fantasy_positions") or [player.get("position")]
        positions = tuple(
            dict.fromkeys(
                p for p in (normalize_position(x) for x in raw_positions) if p in _KNOWN_POSITIONS
            )
        )
        name = " ".join(
            str(x) for x in (player.get("first_name"), player.get("last_name")) if x
        ).strip()
        out[pid] = _Meta(
            name=name or None,
            position=positions[0] if positions else None,
            positions=positions,
            team=_team(row.get("team") or player.get("team")),
            injury_status=(str(player["injury_status"]) if player.get("injury_status") else None),
            game_id=(str(row["game_id"]) if row.get("game_id") else None),
            opponent=(str(row["opponent"]) if row.get("opponent") else None),
        )
    return out


def _directory_from_sleeper_rows(rows: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """A Sleeper-directory-shaped map built from the projection rows' own
    player objects — the identity fallback when no directory dump is cached."""
    directory: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("player_id"):
            continue
        player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
        directory[str(row["player_id"])] = {
            "first_name": player.get("first_name"),
            "last_name": player.get("last_name"),
            "position": player.get("position"),
            "fantasy_positions": player.get("fantasy_positions"),
            "team": row.get("team") or player.get("team"),
            "active": bool(row.get("team") or player.get("team")),
            # Absent stays absent; the index treats a missing value itself.
            "years_exp": player.get("years_exp"),
        }
    return directory


@dataclass
class _SourceRun:
    state: SourceState
    observations: list[Any] = field(default_factory=list)
    #: ``{position: frozenset(stat keys)}`` the provider published.
    vocabulary: Mapping[str, Sequence[str]] = field(default_factory=dict)


def _run_sleeper(
    result: Any, *, season: int, week: int, scoring: Mapping[str, Any], family: str | None
) -> _SourceRun:
    from src.ros.sleeper_weekly_projections import (  # noqa: PLC0415
        WeeklyProjectionError,
        build_weekly_observations,
    )

    status = getattr(result, "status", None)
    if status != "ok":
        reason = f"{status or 'no_fetch'}: {getattr(result, 'reason', '')}".strip()
        return _SourceRun(SourceState(SLEEPER_SOURCE, family, "unavailable", reason))
    try:
        batch = build_weekly_observations(
            result.rows,
            season=season,
            week=week,
            observed_at=result.observed_at,
            scoring_settings=scoring,
        )
    except WeeklyProjectionError as exc:
        return _SourceRun(
            SourceState(SLEEPER_SOURCE, family, "unavailable", f"scoring_unusable: {exc}")
        )
    n = len(batch.observations)
    state = SourceState(
        SLEEPER_SOURCE,
        family,
        "live" if n else "unavailable",
        "ok" if n else "not_published: every row was a placeholder",
        fetched_at=batch.observed_at,
        observation_count=n,
        refused=dict(batch.refused),
    )
    return _SourceRun(state, list(batch.observations), batch.provider_vocabulary)


def _run_fptrack(
    result: Any,
    *,
    season: int,
    week: int,
    scoring: Mapping[str, Any],
    family: str | None,
    identity_index: Any,
) -> _SourceRun:
    from src.ros.fptrack_weekly_projections import build_weekly_observations  # noqa: PLC0415
    from src.ros.fptrack_weekly_projections import exact_identity_resolver
    from src.ros.sleeper_weekly_projections import WeeklyProjectionError  # noqa: PLC0415

    status = getattr(result, "status", None)
    if status != "ok":
        reason = f"{status or 'no_fetch'}: {getattr(result, 'reason', '')}".strip()
        return _SourceRun(SourceState(FPTRACK_SOURCE, family, "unavailable", reason))
    if identity_index is None:
        return _SourceRun(
            SourceState(FPTRACK_SOURCE, family, "unavailable", "identity_directory_unavailable")
        )
    try:
        mapped, parsed = build_weekly_observations(
            result.payload,
            season=season,
            week=week,
            observed_at=result.observed_at,
            scoring_settings=scoring,
            resolve_player=exact_identity_resolver(identity_index),
        )
    except WeeklyProjectionError as exc:
        return _SourceRun(SourceState(FPTRACK_SOURCE, family, "unavailable", f"unusable: {exc}"))
    batch = mapped.batch
    n = len(batch.observations)
    reason = "ok"
    if not n:
        reason = (
            "not_published: empty player list"
            if not parsed.rows
            else f"no_observations: refused {dict(batch.refused)}"
        )
    state = SourceState(
        FPTRACK_SOURCE,
        family,
        "live" if n else "unavailable",
        reason,
        fetched_at=batch.observed_at,
        observation_count=n,
        refused=dict(batch.refused),
        unmapped_provider_fields=dict(mapped.unmapped_provider_fields),
        unresolved_count=len(mapped.unresolved_players),
        placeholder_fields=tuple(
            f"{scope}:{f}"
            for scope, fields in parsed.placeholder_zero_fields.items()
            for f in fields
        ),
    )
    return _SourceRun(state, list(batch.observations), batch.provider_vocabulary)


def _version(source_key: str, result: Any) -> tuple[str, str, str, int]:
    rows = getattr(result, "rows", None)
    payload = getattr(result, "payload", None)
    size = len(rows) if rows is not None else len((payload or {}).get("players") or [])
    return (
        source_key,
        str(getattr(result, "status", None)),
        str(getattr(result, "observed_at", None)),
        size,
    )


def _ensemble(pid: str, chosen: Sequence[tuple[Any, float, float]]) -> tuple[float, float | None]:
    """``(combined points, spread)`` for >= 2 independent families."""
    from src.ros.projection_ensemble import combine_ensemble  # noqa: PLC0415
    from src.ros.projection_observations import ProjectionObservation  # noqa: PLC0415

    rows = []
    for obs, points, _imputed in chosen:
        entry = census.get_source(obs.census_source_key) or {}
        rows.append(
            ProjectionObservation(
                census_source_key=obs.census_source_key,
                provider_family=obs.provider_family,
                evidence_class=str(entry.get("evidenceClass") or "PROJECTION_MODEL"),
                horizon="WEEKLY",
                access_posture=str(entry.get("accessPosture") or ""),
                player_key=f"player:{pid}",
                position=obs.position,
                season=obs.season,
                # Metadata only: the provider stamp when stated, else fetch.
                as_of=obs.provider_updated_at or obs.observed_at,
                games=1.0,
                league_scored_fpg=points,
                league_scored_is_native=False,
                native_fpg=None,
                native_is_scoring_native=False,
                stat_line_available=True,
                proj_high=None,
                proj_low=None,
                is_proxy=False,
            )
        )
    combined = combine_ensemble(rows, method=COMBINE_ENSEMBLE)
    return combined.combined_league_scored_fpg, combined.disagreement_spread


def _coverage(
    chosen: Sequence[Any],
    vocab_by_source: Mapping[str, Mapping[str, Sequence[str]]],
    paid: frozenset[str],
    imputed_keys: frozenset[str],
) -> ProjectionCoverage:
    covered: set[str] = set()
    uncovered: set[str] = set()
    for obs in chosen:
        vocab = vocab_by_source.get(obs.census_source_key, {})
        for pos in obs.fantasy_positions or (obs.position,):
            covered |= set(vocab.get(pos, ())) & paid
        uncovered |= set(obs.uncovered_scoring_keys)
    covered |= imputed_keys & paid
    uncovered -= covered
    relevant = covered | uncovered
    share = (len(covered) / len(relevant)) if relevant else None
    return ProjectionCoverage(
        league_paid_keys=tuple(sorted(relevant)),
        covered_keys=tuple(sorted(covered)),
        uncovered_keys=tuple(sorted(uncovered)),
        coverage_share=share,
    )


def _refused_set(
    league_key: str,
    season: int,
    week: int,
    as_of: str,
    evidence: str,
    refusal: str | None,
    current_week: int | None,
) -> WeeklyProjectionSet:
    """Nothing could be scored: no players, the refusal named."""
    return WeeklyProjectionSet(
        league_key=league_key,
        season=season,
        week=week,
        as_of=as_of,
        scoring_fingerprint=None,
        scoring_evidence_state=evidence,
        refusal=refusal,
        source_states=(),
        players=MappingProxyType({}),
        schedule_state="unavailable",
        bye_teams=(),
        current_week=current_week,
        cache_key="",
    )


# ── Entry points ─────────────────────────────────────────────────────


def load_weekly_projections(
    league_key: str,
    season: int,
    week: int,
    *,
    now: datetime | None = None,
    fetch: Callable[[str, int, int], Any] | None = None,
    positions: Iterable[str] | None = None,
    scoring_settings: Mapping[str, Any] | None = None,
    schedule_rows: Iterable[Mapping[str, Any]] | None = None,
    current_week: int | None = None,
    identity_index: Any = None,
    sources: Sequence[str] = SOURCE_PRECEDENCE,
    use_cache: bool = True,
) -> WeeklyProjectionSet:
    """League-scored weekly projections for every player in ``week``.

    ``fetch(source_key, season, week)`` returns that source's raw fetch
    result (injected in tests; the default fetches with a TTL cache and the
    sources' own flags).  ``scoring_settings`` overrides the registry card
    (then ``scoringEvidenceState`` is ``caller_supplied``).
    ``schedule_rows`` overrides the cached nflverse schedule.
    ``current_week`` enables the ``injured_out`` state for that week only.
    ``identity_index`` (a ``SleeperDirectoryIndex``) is used to resolve
    FPTrack rows; default: the cached directory, else one built from the
    Sleeper projection rows themselves.
    """
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    as_of = clock.astimezone(timezone.utc).isoformat()
    season, week = int(season), int(week)
    wanted = frozenset(normalize_position(p) for p in positions) if positions is not None else None
    scoring, evidence, refusal = _resolve_scoring(league_key, scoring_settings)
    if scoring is None:
        return _refused_set(league_key, season, week, as_of, evidence, refusal, current_week)
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    fingerprint = scoring_fingerprint(scoring)
    if fingerprint is None:
        return _refused_set(
            league_key, season, week, as_of, evidence, "scoring_card_unusable", current_week
        )

    now_ts = clock.timestamp()
    results: dict[str, Any] = {}
    for key in sources:
        if fetch is not None:
            results[key] = fetch(key, season, week)
        else:
            results[key] = _cached_fetch(key, season, week, now_ts)

    rows = list(schedule_rows) if schedule_rows is not None else _default_schedule_rows(season)
    schedule_state, bye_teams = _schedule(rows, season, week)

    signature = repr(
        (
            fingerprint,
            season,
            week,
            tuple(_version(k, results[k]) for k in sources),
            schedule_state,
            tuple(sorted(bye_teams)),
            current_week,
            tuple(sorted(wanted)) if wanted is not None else None,
            league_key,
        )
    )
    cache_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]
    if use_cache:
        with _lock:
            hit = _result_cache.get(cache_key)
            if hit is not None:
                _result_cache.move_to_end(cache_key)
                return hit

    built = _build(
        league_key=league_key,
        season=season,
        week=week,
        as_of=as_of,
        scoring=scoring,
        fingerprint=fingerprint,
        evidence=evidence,
        results=results,
        sources=sources,
        schedule_state=schedule_state,
        bye_teams=bye_teams,
        current_week=current_week,
        identity_index=identity_index,
        wanted=wanted,
        cache_key=cache_key,
    )
    if use_cache:
        with _lock:
            _result_cache[cache_key] = built
            while len(_result_cache) > _RESULT_CACHE_SIZE:
                _result_cache.popitem(last=False)
    return built


def load_weekly_projection_horizon(
    league_key: str, season: int, weeks: Iterable[int], **kwargs: Any
) -> dict[int, WeeklyProjectionSet]:
    """One :class:`WeeklyProjectionSet` per week (current, next weeks,
    playoff weeks).  A week no provider has published yet comes back with
    every player ``unprojected`` (reason ``week_not_published``)."""
    return {int(w): load_weekly_projections(league_key, season, int(w), **kwargs) for w in weeks}


def _build(
    *,
    league_key: str,
    season: int,
    week: int,
    as_of: str,
    scoring: Mapping[str, Any],
    fingerprint: str,
    evidence: str,
    results: Mapping[str, Any],
    sources: Sequence[str],
    schedule_state: str,
    bye_teams: frozenset,
    current_week: int | None,
    identity_index: Any,
    wanted: frozenset[str] | None,
    cache_key: str,
) -> WeeklyProjectionSet:
    from src.nfl_data.first_down_rate import (  # noqa: PLC0415
        SLEEPER_PROJECTED_FD_KEYS,
        imputed_sleeper_first_down_bonus,
    )

    sleeper_result = results.get(SLEEPER_SOURCE)
    sleeper_rows = (
        list(getattr(sleeper_result, "rows", ()) or ())
        if getattr(sleeper_result, "status", None) == "ok"
        else []
    )
    meta = _sleeper_meta(sleeper_rows)

    runs: dict[str, _SourceRun] = {}
    for key in sources:
        family = _family(key)
        if key == SLEEPER_SOURCE:
            runs[key] = _run_sleeper(
                results[key], season=season, week=week, scoring=scoring, family=family
            )
        elif key == FPTRACK_SOURCE:
            index = identity_index
            if index is None and getattr(results[key], "status", None) == "ok":
                index = _default_identity_index(sleeper_rows)
            runs[key] = _run_fptrack(
                results[key],
                season=season,
                week=week,
                scoring=scoring,
                family=family,
                identity_index=index,
            )
            if index is not None:
                for obs in runs[key].observations:
                    if obs.sleeper_player_id not in meta:
                        cand = getattr(index, "by_sleeper_id", {}).get(obs.sleeper_player_id)
                        meta[obs.sleeper_player_id] = _Meta(
                            name=getattr(cand, "display_name", None),
                            position=obs.position,
                            positions=obs.fantasy_positions,
                            team=_team(obs.team),
                            opponent=obs.opponent,
                        )
        else:
            raise KeyError(f"no adapter for weekly source {key!r}")

    paid = frozenset(k for k in scoring if _rate(scoring, k) != 0.0)
    paid_fd = [k for k in SLEEPER_PROJECTED_FD_KEYS if k in paid]
    vocab_by_source = {k: r.vocabulary for k, r in runs.items()}
    by_player: dict[str, list[Any]] = {}
    for key in sources:
        for obs in runs[key].observations:
            by_player.setdefault(obs.sleeper_player_id, []).append(obs)
            meta.setdefault(
                obs.sleeper_player_id,
                _Meta(position=obs.position, positions=obs.fantasy_positions, team=_team(obs.team)),
            )

    live = [k for k in sources if runs[k].state.state == "live"]
    all_unpublished = bool(sources) and all(
        runs[k].state.reason.startswith("not_published") for k in sources
    )

    players: dict[str, LeagueScoredWeeklyProjection] = {}
    for pid, m in meta.items():
        if wanted is not None and not (set(m.positions or (m.position,)) & wanted):
            continue
        base = dict(
            player_id=pid,
            name=m.name,
            position=m.position,
            team=m.team,
            season=season,
            week=week,
            opponent=m.opponent,
            game_id=m.game_id,
            injury_status=m.injury_status,
        )
        chosen: list[tuple[Any, float, float]] = []
        imputed_keys: set[str] = set()
        excluded: list[str] = []
        refused_fd = False
        for obs in by_player.get(pid, ()):
            if any(census.ancestry_overlaps([c.census_source_key, obs.census_source_key])
                   for c, _p, _i in chosen):  # fmt: skip
                excluded.append(obs.census_source_key)
                continue
            if paid_fd and any(k in obs.stat_line for k in paid_fd):
                # The provider's *_fd keys are yardage/10, not first downs
                # (first_down_rate.SLEEPER_PROJECTED_FD_KEYS) — same refusal
                # as Game Day's weekly adapter.
                refused_fd = True
                continue
            imputed = imputed_sleeper_first_down_bonus(obs.stat_line, obs.position, scoring)
            imp_pts = imputed[2] if imputed else 0.0
            if imputed:
                imputed_keys.add(imputed[0])
            chosen.append((obs, obs.league_scored_points + imp_pts, imp_pts))

        if chosen:
            contributions = tuple(
                SourceContribution(
                    source_key=obs.census_source_key,
                    family=obs.provider_family,
                    provider_model=obs.model_company,
                    fetched_at=obs.observed_at,
                    updated_at=obs.provider_updated_at,
                    weekly_points=obs.league_scored_points,
                    imputed_points=imp,
                )
                for obs, _pts, imp in chosen
            )
            if len(chosen) >= 2:
                points, spread = _ensemble(pid, chosen)
                method = COMBINE_ENSEMBLE
            else:
                points, spread = chosen[0][1], None
                method = COMBINE_PASSTHROUGH
            reason = "ok"
            if schedule_state == "ok" and m.team in bye_teams:
                reason = "schedule_lists_team_on_bye_but_provider_projects"
            first = chosen[0][0]
            players[pid] = LeagueScoredWeeklyProjection(
                **{
                    **base,
                    "opponent": base["opponent"] or first.opponent,
                    "team": base["team"] or _team(first.team),
                },
                weekly_points=points,
                state=STATE_PROJECTED,
                reason=reason,
                sources=contributions,
                combine_method=method,
                coverage=_coverage(
                    [c[0] for c in chosen], vocab_by_source, paid, frozenset(imputed_keys)
                ),
                imputed_points=sum(c[2] for c in chosen) / len(chosen),
                imputed_keys=tuple(sorted(imputed_keys)),
                family_count=len({c[0].provider_family for c in chosen}),
                disagreement_spread=spread,
                excluded_sources=tuple(excluded),
            )
            continue

        if refused_fd:
            state, points, reason = STATE_UNPROJECTED, None, "provider_first_down_keys_refused"
        elif not m.team:
            state, points, reason = STATE_UNPROJECTED, None, "no_nfl_team_on_file"
        elif schedule_state == "ok" and m.team in bye_teams:
            state, points, reason = STATE_BYE, 0.0, "bye"
        elif (
            m.injury_status in INJURED_OUT_STATUSES
            and current_week is not None
            and int(current_week) == week
        ):
            state, points = STATE_INJURED_OUT, 0.0
            reason = f"host_injury_status:{m.injury_status}"
        else:
            state, points = STATE_UNPROJECTED, None
            if not live:
                reason = (
                    "week_not_published"
                    if all_unpublished
                    else "no_live_source: "
                    + "; ".join(f"{k}={runs[k].state.reason}" for k in sources)
                )
            else:
                reason = "provider_published_no_projection"
            if schedule_state != "ok":
                reason += "; schedule_unavailable"
        players[pid] = LeagueScoredWeeklyProjection(
            **base, weekly_points=points, state=state, reason=reason
        )

    return WeeklyProjectionSet(
        league_key=league_key,
        season=season,
        week=week,
        as_of=as_of,
        scoring_fingerprint=fingerprint,
        scoring_evidence_state=evidence,
        refusal=None,
        source_states=tuple(runs[k].state for k in sources),
        players=MappingProxyType(dict(sorted(players.items()))),
        schedule_state=schedule_state,
        bye_teams=tuple(sorted(bye_teams)),
        current_week=current_week,
        cache_key=cache_key,
    )


def _default_identity_index(sleeper_rows: Sequence[Any]) -> Any:
    try:
        from src.identity.directory_cache import get_default_sleeper_index  # noqa: PLC0415

        index = get_default_sleeper_index()
    except Exception:  # noqa: BLE001 — an unreadable directory is "unavailable"
        index = None
    if index is not None:
        return index
    if not sleeper_rows:
        return None
    from src.identity.resolution import build_sleeper_index  # noqa: PLC0415

    return build_sleeper_index(_directory_from_sleeper_rows(sleeper_rows))
