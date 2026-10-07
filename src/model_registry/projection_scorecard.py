"""AL-3b — the projection scorecard (report-only, champion vs constituents).

What it answers: how far were the projections Calculator held BEFORE kickoff from
what the players then did, scored under the league's EXACT card? It re-derives
nothing — every projected number comes from the projection owners and every
realized number from the realized-points owner:

* **WEEKLY** — the pregame Sleeper weekly projections Game Day archived
  (``src.ros.game_day_live.build_pregame_projection_archive`` /
  ``pregame_projections.json.gz``), re-selected through the canonical
  ``sleeper_weekly_projections.lock_baseline_at_kickoff`` (the temporal guard:
  a row observed after its game's kickoff is never selectable) and scored with
  ``sleeper_weekly_projections.build_weekly_observations``. Realized points are
  Sleeper's own weekly stat dump scored by
  ``src.nfl_data.realized_points.compute_weekly_points(source="sleeper")``;
  per-stat realized values are ``realized_points.host_stat_line``.
* **SEASON** (``PRESEASON_FULL_SEASON``) — immutable BDVM snapshots
  (``data/bdvm/projections/``) rescored per record with
  ``projection_observations.rescore_projection_record`` (→ ``resolve_fpg``), the
  equal-family CHAMPION from ``projection_ensemble.combine_ensemble``.
  Realized per-game points are ``src.bdvm.actuals.weekly_points_from_rows``
  (nflverse, the BDVM actuals owner, keyed by the same normalized name), over
  only the weeks whose FIRST kickoff is after the snapshot's ``asOf``.

Rules (each pinned by ``tests/model_registry/test_projection_scorecard.py``):

* **Temporal guard.** Weekly: only a projection observed at or before its own
  game's kickoff (the canonical lock rule) and a realized dump fetched after the
  week's LAST kickoff. Season: only weeks that kicked off strictly after the
  snapshot ``asOf`` (a date-only ``asOf`` is bounded conservatively at the END of
  that UTC day).
* **Missing is never zero.** A projected player with no realized row, or a row
  that says he did not play (``gp`` = 0), is NOT scored as 0 points — he is
  counted (``outcomeMissing`` / ``didNotPlay``). Inside a PRESENT host stat line
  an absent stat is zero events: the host publishes only nonzero events
  (``realized_points.sleeper_stat_line_from_row`` documents the convention).
* **Duplicates are deduped**: a second archive for the same week, a repeated
  (source, player) in one snapshot.
* **Model versions are separate cohorts**: the provider model (``company`` on a
  weekly row) and the snapshot vintage (``asOf``) are cohort keys, never pooled.
* **Small samples are flagged**: a cohort with fewer than :data:`MIN_N` scored
  players is ``insufficient_sample`` with no metric; no interval is presented as
  significance.
* **One family is reported as one family.** The weekly archive holds one
  provider family today, so its champion IS its sole constituent and the
  scorecard says so (``championEqualsSoleConstituent``) instead of inventing a
  comparison.
* **Deterministic**: no wall clock; identical inputs give byte-identical output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.bdvm.projections import ProjectionRecord
from src.dfs.metrics import SMALL_SAMPLE, point_forecast
from src.history.store import has_time_component
from src.model_registry.evaluation_receipt import (
    VERDICT_INCONCLUSIVE,
    CohortResult,
    Estimate,
    EvaluationReceipt,
    cohort_result,
)
from src.model_registry.learning_receipt import (
    ROLE_INPUT,
    ROLE_OUTCOME,
    LearningReceipt,
    NotApplicable,
    ReceiptError,
    StoreRef,
    Unobserved,
    canonical_json,
    model_version_id,
    parse_instant,
    sha256_text,
)
from src.nfl_data.realized_points import compute_weekly_points, host_stat_line
from src.ros.projection_ensemble import _DEFAULT_ROS_FULL_SEASON_SOURCES, combine_ensemble
from src.ros.projection_observations import (
    ProjectionObservationError,
    rescore_projection_record,
)
from src.ros.sleeper_weekly_projections import (
    WeeklyProjectionError,
    build_weekly_observations,
    lock_baseline_at_kickoff,
)

SCHEMA = "projection-scorecard/v1"
PRODUCER = "projection_scorecard"
FAMILY = "projection_ensemble"
HORIZON_WEEKLY = "WEEKLY"
HORIZON_SEASON = "PRESEASON_FULL_SEASON"
STAT_POINTS = "leaguePoints"
CHAMPION = "equal_family_champion"
CHAMPION_METHOD = "equal_family_mean"
ALL_POSITIONS = "ALL"

WEEKLY_STORE = "game_day_pregame_projections"
WEEKLY_REALIZED_STORE = "sleeper_weekly_stats"
SEASON_STORE = "bdvm_projection_snapshot"
SEASON_REALIZED_STORE = "nflverse_weekly_stats"

#: Minimum scored players for a cohort to carry a metric. The repo's existing
#: declared small-sample rule (``src.dfs.metrics.SMALL_SAMPLE``). PRIOR.
MIN_N: int = SMALL_SAMPLE

WEEKLY_RULE = (
    "per player, the last observation at or before his own game's kickoff "
    "(sleeper_weekly_projections.lock_baseline_at_kickoff); realized from a stat dump fetched "
    "after the week's last kickoff"
)
SEASON_RULE = (
    "a snapshot is scored only on weeks whose first kickoff is strictly after its asOf "
    "(date-only asOf bounded at the end of that UTC day)"
)


# ── inputs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeeklyArchive:
    """One NFL week's pregame projection archive payload, as stored or built."""

    season: int
    week: int
    payload: Mapping[str, Any]
    source_key: str


@dataclass(frozen=True)
class RealizedWeek:
    """Sleeper's weekly stat dump for one week and when WE fetched it."""

    season: int
    week: int
    fetched_at: datetime
    #: sleeper player id -> the host's raw stat line
    stats: Mapping[str, Mapping[str, Any]]
    source_key: str


@dataclass(frozen=True)
class SeasonSnapshot:
    as_of: str
    records: Sequence[ProjectionRecord]
    source_key: str


@dataclass(frozen=True)
class RealizedSeason:
    season: int
    #: when the realized rows were read
    known_at: datetime
    #: normalized player key -> [(week, league points)] (bdvm.actuals output)
    points: Mapping[str, Sequence[tuple[int, float]]]
    #: week -> its first kickoff instant
    week_first_kickoff: Mapping[int, datetime]
    source_key: str


@dataclass(frozen=True)
class Pair:
    horizon: str
    provider: str
    model: str
    position: str
    stat: str
    player: str
    projected: float
    actual: float
    as_known_at: datetime
    target_at: datetime
    realized_at: datetime
    realized_revision: str
    families: int = 1


@dataclass
class ScorecardResult:
    league_key: str
    summary: dict[str, Any]
    pairs: list[Pair] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _LockRow:
    """The four attributes ``lock_baseline_at_kickoff`` reads."""

    sleeper_player_id: str
    game_id: str
    observed_at: str
    provider_updated_at: str | None
    row: Mapping[str, Any]


# ── helpers ──────────────────────────────────────────────────────────────────


def _instant(value: Any) -> datetime | None:
    try:
        return parse_instant(value, what="instant")
    except (ReceiptError, ValueError, TypeError):
        return None


def as_of_bound(value: Any) -> tuple[datetime, bool] | None:
    """``(instant, exact)``: a proven instant, or the END of a date-only day (not exact)."""
    text = str(value or "").strip()
    if not text:
        return None
    if has_time_component(text.replace("Z", "+00:00")):
        at = _instant(text)
        return None if at is None else (at, True)
    try:
        day = datetime.fromisoformat(text[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return day + timedelta(days=1) - timedelta(microseconds=1), False


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _bump(counter: dict[str, int], key: str, by: int = 1) -> None:
    counter[key] = counter.get(key, 0) + by


def _played(stats: Mapping[str, Any]) -> bool:
    gp = _num(stats.get("gp"))
    return not (gp is not None and gp <= 0)


def _paid(scoring: Mapping[str, Any], key: str) -> bool:
    rate = _num(scoring.get(key))
    return rate is not None and rate != 0.0


def _token(text: str) -> str:
    out = "".join("_" if (c == ":" or c.isspace()) else c for c in str(text))
    return out or "unrecorded"


# ── WEEKLY ───────────────────────────────────────────────────────────────────


def _weekly_pairs(
    archives: Sequence[WeeklyArchive],
    realized: Sequence[RealizedWeek],
    scoring: Mapping[str, Any],
) -> tuple[list[Pair], list[dict[str, Any]], dict[str, Any]]:
    pairs: list[Pair] = []
    weeks_out: list[dict[str, Any]] = []
    lineage: dict[str, Any] = {}
    realized_by_week: dict[tuple[int, int], RealizedWeek] = {}
    for rw in realized:
        key = (int(rw.season), int(rw.week))
        prev = realized_by_week.get(key)
        # The latest fetch is the corrected one; ties keep the first given.
        if prev is None or rw.fetched_at > prev.fetched_at:
            realized_by_week[key] = rw
    seen: set[tuple[int, int]] = set()
    for arch in sorted(archives, key=lambda a: (int(a.season), int(a.week), a.source_key)):
        season, week = int(arch.season), int(arch.week)
        census: dict[str, int] = {}
        row_out: dict[str, Any] = {"season": season, "week": week, "source": arch.source_key}
        if (season, week) in seen:
            _bump(census, "duplicate_week_archive")
            weeks_out.append({**row_out, "census": census, "state": "duplicate_skipped"})
            continue
        seen.add((season, week))
        payload = arch.payload or {}
        players = payload.get("players") or {}
        _bump(census, "timing_unverified_excluded", len(payload.get("timingUnverified") or {}))
        _bump(
            census, "no_pre_kickoff_observation", len(payload.get("noPreKickoffObservation") or ())
        )
        lock_rows: list[_LockRow] = []
        kickoffs: dict[str, str] = {}
        for pid, entry in sorted(players.items()):
            row = (entry or {}).get("row") or {}
            observed = _instant((entry or {}).get("observedAt"))
            kick = _instant((entry or {}).get("kickoffAt"))
            gid = row.get("game_id")
            if observed is None or kick is None or not gid:
                _bump(census, "unproven_instant_or_game")
                continue
            kickoffs.setdefault(str(gid), kick.isoformat())
            lock_rows.append(
                _LockRow(
                    sleeper_player_id=str(pid),
                    game_id=str(gid),
                    observed_at=observed.isoformat(),
                    provider_updated_at=None,
                    row=row,
                )
            )
        lock = lock_baseline_at_kickoff(lock_rows, kickoffs)
        _bump(census, "post_kickoff_excluded", lock.post_kickoff_observations_ignored)
        selected = {pid: e for pid, e in lock.baselines.items()}
        by_observed: dict[str, list[Mapping[str, Any]]] = {}
        for pid, entry in selected.items():
            by_observed.setdefault(entry.observation.observed_at, []).append(entry.observation.row)
        observations = []
        for observed_at in sorted(by_observed):
            try:
                batch = build_weekly_observations(
                    by_observed[observed_at],
                    season=season,
                    week=week,
                    observed_at=observed_at,
                    scoring_settings=dict(scoring),
                )
            except WeeklyProjectionError as exc:
                weeks_out.append({**row_out, "state": "scoring_refused", "reason": str(exc)})
                observations = None
                break
            for reason, n in batch.refused.items():
                _bump(census, f"refused:{reason}", n)
            observations.extend(batch.observations)
        if observations is None:
            continue
        max_kick = max((_instant(k) for k in kickoffs.values()), default=None)
        rw = realized_by_week.get((season, week))
        row_out["projected"] = len(observations)
        lineage[f"{season}-w{week}"] = {
            "archive": arch.source_key,
            "selectedSha256": sha256_text(
                canonical_json(
                    sorted(
                        [o.sleeper_player_id, o.observed_at, o.league_scored_points]
                        for o in observations
                    )
                )
            ),
        }
        if rw is None:
            weeks_out.append({**row_out, "census": census, "state": "realized_unavailable"})
            continue
        if max_kick is None or rw.fetched_at < max_kick:
            weeks_out.append(
                {**row_out, "census": census, "state": "realized_fetched_before_last_kickoff"}
            )
            continue
        revision = sha256_text(canonical_json({str(k): dict(v) for k, v in rw.stats.items()}))[:16]
        lineage[f"{season}-w{week}"]["realized"] = {"source": rw.source_key, "sha256": revision}
        scored = 0
        for obs in observations:
            stats = rw.stats.get(obs.sleeper_player_id)
            if not isinstance(stats, Mapping) or not stats:
                _bump(census, "outcome_missing")
                continue
            if not _played(stats):
                _bump(census, "did_not_play")
                continue
            rp = compute_weekly_points(
                {**dict(stats), "player_id": obs.sleeper_player_id, "season": season, "week": week},
                dict(scoring),
                source="sleeper",
            )
            if rp is None:
                _bump(census, "outcome_unscoreable")
                continue
            if obs.uncovered_scoring_keys:
                _bump(census, "projection_uncovered_keys")
            if rp.unscored:
                _bump(census, "realized_partial")
            kick = _instant(obs_kickoff(selected, obs.sleeper_player_id))
            base = dict(
                horizon=HORIZON_WEEKLY,
                provider=obs.census_source_key,
                model=str(obs.model_company),
                position=obs.position,
                player=f"{season}-w{week}:{obs.sleeper_player_id}",
                as_known_at=_instant(obs.observed_at),
                target_at=kick or max_kick,
                realized_at=rw.fetched_at,
                realized_revision=revision,
            )
            pairs.append(
                Pair(
                    stat=STAT_POINTS,
                    projected=float(obs.league_scored_points),
                    actual=float(rp.fantasy_points),
                    **base,
                )
            )
            line = host_stat_line(dict(stats))
            for key, value in sorted(obs.stat_line.items()):
                if not _paid(scoring, key):
                    continue
                pairs.append(
                    Pair(
                        stat=key,
                        projected=float(value),
                        actual=float(line.get(key, 0.0)),
                        **base,
                    )
                )
            scored += 1
        weeks_out.append({**row_out, "census": census, "state": "scored", "scored": scored})
    return pairs, weeks_out, lineage


def obs_kickoff(selected: Mapping[str, Any], pid: str) -> str | None:
    entry = selected.get(pid)
    return None if entry is None else entry.kickoff_at


# ── SEASON ───────────────────────────────────────────────────────────────────


def _season_pairs(
    snapshots: Sequence[SeasonSnapshot],
    realized: RealizedSeason | None,
    scoring: Mapping[str, Any],
    sources: Sequence[str],
) -> tuple[list[Pair], list[dict[str, Any]], dict[str, Any]]:
    pairs: list[Pair] = []
    out: list[dict[str, Any]] = []
    lineage: dict[str, Any] = {}
    seen: set[str] = set()
    for snap in sorted(snapshots, key=lambda s: (str(s.as_of), s.source_key)):
        census: dict[str, int] = {}
        row: dict[str, Any] = {"asOf": snap.as_of, "source": snap.source_key}
        bound = as_of_bound(snap.as_of)
        if bound is None:
            out.append({**row, "state": "as_of_unproven"})
            continue
        if snap.source_key in seen:
            out.append({**row, "state": "duplicate_skipped"})
            continue
        seen.add(snap.source_key)
        as_of_at, exact = bound
        row["asOfExact"] = exact
        by_player: dict[str, list[Any]] = {}
        dedupe: set[tuple[str, str]] = set()
        for record in snap.records:
            if record.source not in sources:
                _bump(census, "source_not_in_ensemble")
                continue
            key = (record.source, record.player_key)
            if key in dedupe:
                _bump(census, "duplicate_record")
                continue
            dedupe.add(key)
            try:
                obs = rescore_projection_record(
                    record, scoring_settings=dict(scoring), census_source_key=record.source
                )
            except ProjectionObservationError:
                _bump(census, "census_refused")
                continue
            if obs is None:
                _bump(census, "proxy_excluded")
                continue
            if obs.horizon != HORIZON_SEASON:
                _bump(census, "other_horizon")
                continue
            by_player.setdefault(obs.player_key, []).append(obs)
        lineage[snap.source_key] = sha256_text(
            canonical_json(
                sorted(
                    [o.census_source_key, o.player_key, o.league_scored_fpg]
                    for rows in by_player.values()
                    for o in rows
                )
            )
        )
        if realized is None:
            out.append({**row, "census": census, "state": "realized_unavailable"})
            continue
        weeks = sorted(
            w
            for w, k in realized.week_first_kickoff.items()
            if k > as_of_at and k < realized.known_at
        )
        row["eligibleWeeks"] = weeks
        if not weeks:
            out.append({**row, "census": census, "state": "no_week_after_as_of"})
            continue
        last_kick = max(realized.week_first_kickoff[w] for w in weeks)
        families = set()
        revision = sha256_text(
            canonical_json({k: [list(x) for x in v] for k, v in sorted(realized.points.items())})
        )[:16]
        model = f"asOf={str(snap.as_of)[:10]}"
        scored = 0
        for player_key in sorted(by_player):
            rows = by_player[player_key]
            played = [pts for (w, pts) in realized.points.get(player_key, ()) if w in weeks]
            if not played:
                _bump(census, "outcome_missing")
                continue
            actual = sum(played) / len(played)
            champion = combine_ensemble(rows, method=CHAMPION_METHOD)
            families.add(champion.family_count)
            base = dict(
                horizon=HORIZON_SEASON,
                position=rows[0].position,
                stat=STAT_POINTS,
                player=player_key,
                actual=float(actual),
                as_known_at=as_of_at,
                target_at=last_kick,
                realized_at=realized.known_at,
                realized_revision=revision,
            )
            pairs.append(
                Pair(
                    provider=CHAMPION,
                    model=f"{model}|{champion.combination_method}",
                    projected=float(champion.combined_league_scored_fpg),
                    families=champion.family_count,
                    **base,
                )
            )
            for obs in sorted(rows, key=lambda o: o.census_source_key):
                pairs.append(
                    Pair(
                        provider=obs.census_source_key,
                        model=model,
                        projected=float(obs.league_scored_fpg),
                        families=champion.family_count,
                        **base,
                    )
                )
            scored += 1
        out.append(
            {
                **row,
                "census": census,
                "state": "scored",
                "scored": scored,
                "familyCounts": sorted(families),
            }
        )
    return pairs, out, lineage


# ── evaluation ───────────────────────────────────────────────────────────────


def _cohort_metrics(pairs: Sequence[Pair]) -> dict[str, Any] | None:
    if len(pairs) < MIN_N:
        return None
    return point_forecast([(p.projected, p.actual) for p in pairs])


def _cohort_key(p: Pair) -> tuple[str, str, str]:
    return (p.horizon, p.provider, p.model)


def _summarize_cohorts(pairs: Sequence[Pair]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str], list[Pair]] = {}
    for p in pairs:
        groups.setdefault((*_cohort_key(p), p.position, p.stat), []).append(p)
        if p.stat == STAT_POINTS:
            groups.setdefault((*_cohort_key(p), ALL_POSITIONS, p.stat), []).append(p)
    out = []
    for (horizon, provider, model, position, stat), rows in sorted(groups.items()):
        metrics = _cohort_metrics(rows)
        out.append(
            {
                "horizon": horizon,
                "provider": provider,
                "model": model,
                "position": position,
                "stat": stat,
                "n": len(rows),
                "status": "ok" if metrics is not None else "insufficient_sample",
                "metrics": metrics,
            }
        )
    return out


def _paired_comparison(pairs: Sequence[Pair]) -> list[dict[str, Any]]:
    """Champion vs each constituent on the SAME players, per snapshot vintage, only
    for players more than one family covered."""
    by_model: dict[str, dict[str, dict[str, Pair]]] = {}
    for p in pairs:
        if p.horizon != HORIZON_SEASON or p.stat != STAT_POINTS or p.families < 2:
            continue
        vintage = p.model.split("|")[0]
        by_model.setdefault(vintage, {}).setdefault(p.player, {})[p.provider] = p
    out = []
    for vintage, players in sorted(by_model.items()):
        providers = sorted({k for row in players.values() for k in row} - {CHAMPION})
        for provider in providers:
            common = [row for row in players.values() if CHAMPION in row and provider in row]
            common.sort(key=lambda r: r[CHAMPION].player)
            n = len(common)
            entry: dict[str, Any] = {
                "vintage": vintage,
                "constituent": provider,
                "n": n,
                "status": "ok" if n >= MIN_N else "insufficient_sample",
            }
            if n >= MIN_N:
                champ = point_forecast(
                    [(r[CHAMPION].projected, r[CHAMPION].actual) for r in common]
                )
                const = point_forecast(
                    [(r[provider].projected, r[provider].actual) for r in common]
                )
                entry["championMae"] = champ["mae"] if champ else None
                entry["constituentMae"] = const["mae"] if const else None
            out.append(entry)
    return out


def evaluate(
    *,
    league_key: str,
    scoring: Mapping[str, Any],
    scoring_fingerprint: str | None,
    weekly_archives: Sequence[WeeklyArchive] = (),
    realized_weeks: Sequence[RealizedWeek] = (),
    season_snapshots: Sequence[SeasonSnapshot] = (),
    realized_season: RealizedSeason | None = None,
    season_sources: Sequence[str] = _DEFAULT_ROS_FULL_SEASON_SOURCES,
) -> ScorecardResult:
    weekly, weekly_weeks, weekly_lineage = _weekly_pairs(weekly_archives, realized_weeks, scoring)
    season, season_rows, season_lineage = _season_pairs(
        season_snapshots, realized_season, scoring, season_sources
    )
    pairs = sorted(
        [*weekly, *season],
        key=lambda p: (p.horizon, p.provider, p.model, p.position, p.stat, p.player),
    )
    weekly_families = sorted({p.provider for p in weekly})
    summary = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "leagueKey": league_key,
        "reportOnly": True,
        "promotes": False,
        "scoringFingerprint": scoring_fingerprint,
        "constants": {
            "minN": MIN_N,
            "minNBasis": "src.dfs.metrics.SMALL_SAMPLE (declared small-sample rule; PRIOR)",
            "championMethod": CHAMPION_METHOD,
            "seasonSources": list(season_sources),
        },
        "pointInTimeRules": {HORIZON_WEEKLY: WEEKLY_RULE, HORIZON_SEASON: SEASON_RULE},
        "weekly": {
            "weeks": weekly_weeks,
            "providerFamiliesObserved": len(weekly_families),
            "championEqualsSoleConstituent": len(weekly_families) == 1,
            "note": (
                "no weekly projection was scored"
                if not weekly_families
                else "one provider family was scored: its equal-family champion IS that family, "
                "so no champion-vs-constituent comparison exists for WEEKLY"
                if len(weekly_families) == 1
                else f"{len(weekly_families)} provider families were scored"
            ),
        },
        "season": {
            "snapshots": season_rows,
            "pairedComparison": _paired_comparison(season),
            "note": (
                "SEASON is points-only: the realized owner (bdvm.actuals) returns weekly "
                "league points, not stat lines; per-stat scorecards are WEEKLY only"
            ),
        },
        "cohorts": _summarize_cohorts(pairs),
        "notes": [
            "a projected player with no realized row, or gp = 0, is counted and not scored",
            "weekly projections leave some league-paid keys uncovered (counted as "
            "projection_uncovered_keys): projected points are biased low by construction there",
        ],
    }
    return ScorecardResult(
        league_key=league_key,
        summary=summary,
        pairs=pairs,
        lineage={"weekly": weekly_lineage, "season": season_lineage},
    )


# ── receipts ─────────────────────────────────────────────────────────────────


def _estimates(pairs: Sequence[Pair]) -> dict[str, Estimate]:
    m = point_forecast([(p.projected, p.actual) for p in pairs]) or {}
    out = {k: Estimate(point=float(m[k])) for k in ("mae", "rmse", "bias") if m.get(k) is not None}
    if m.get("spearman") is not None:
        out["spearman"] = Estimate(point=float(m["spearman"]))
    return out


def _cohort(pairs: Sequence[Pair], cohort: Mapping[str, str]) -> CohortResult:
    enough = len(pairs) >= MIN_N
    return cohort_result(
        cohort,
        n=len(pairs),
        metrics=_estimates(pairs) if enough else None,
        insufficient=not enough,
        note=f"minimum {MIN_N} scored players",
    )


def receipts(
    result: ScorecardResult, *, code_sha: str, scoring_fingerprint: str | None
) -> list[LearningReceipt]:
    """One EVALUATION receipt per (horizon, provider, model). Report-only."""
    if not str(code_sha or "").strip():
        raise ReceiptError("the scorecard code revision must be stated")
    groups: dict[tuple[str, str, str], list[Pair]] = {}
    for p in result.pairs:
        groups.setdefault(_cohort_key(p), []).append(p)
    out: list[LearningReceipt] = []
    for (horizon, provider, model), rows in sorted(groups.items()):
        points = [p for p in rows if p.stat == STAT_POINTS]
        lineage = result.lineage.get("weekly" if horizon == HORIZON_WEEKLY else "season", {})
        digest = sha256_text(
            canonical_json([[p.position, p.stat, p.player, p.projected, p.actual] for p in rows])
        )
        native = f"{result.league_key}|{horizon}|{provider}|{model}|{digest}"
        is_champion = provider == CHAMPION or horizon == HORIZON_WEEKLY
        token = _token(f"{horizon.lower()}-{provider}-{model}")
        cutoff = max(p.as_known_at for p in rows)
        target_at = max(p.target_at for p in rows)
        realized_at = max(p.realized_at for p in rows)
        weekly = horizon == HORIZON_WEEKLY
        cohorts = []
        positions = sorted({p.position for p in points})
        for position in positions:
            cohorts.append(
                _cohort(
                    [p for p in points if p.position == position],
                    {"position": position, "stat": STAT_POINTS},
                )
            )
        for position, stat in sorted({(p.position, p.stat) for p in rows if p.stat != STAT_POINTS}):
            cohorts.append(
                _cohort(
                    [p for p in rows if p.position == position and p.stat == stat],
                    {"position": position, "stat": stat},
                )
            )
        families = sorted({p.families for p in points})
        ev = EvaluationReceipt(
            producer=PRODUCER,
            native_id=native,
            model_family=FAMILY,
            model_version_id=model_version_id(FAMILY, token),
            role="champion" if is_champion else "baseline",
            task=f"projection_accuracy_{horizon.lower()}",
            target=(
                "league-scored points for the week (and each league-paid stat)"
                if weekly
                else "league-scored points per game over the weeks after the snapshot asOf"
            ),
            horizon=horizon,
            cohort_keys=("position", "stat"),
            cutoff=cutoff,
            target_event_at=target_at,
            point_in_time_rule=WEEKLY_RULE if weekly else SEASON_RULE,
            feature_manifest_hash=NotApplicable(
                "a projection scorecard reads published projections, not model features"
            ),
            input_pins={
                "codeSha": str(code_sha),
                "sourceHashes": {"lineageSha256": sha256_text(canonical_json(lineage))},
                "snapshotHash": (
                    NotApplicable("a weekly archive is per-week, not a board snapshot")
                    if weekly
                    else sha256_text(canonical_json(lineage))
                ),
                "scoringFingerprint": (
                    scoring_fingerprint
                    if scoring_fingerprint
                    else Unobserved("the league scoring fingerprint could not be established")
                ),
            },
            prediction_set=StoreRef(
                store=WEEKLY_STORE if weekly else SEASON_STORE,
                key=f"{horizon}#{provider}:{model}:n={len(points)}:sha256={digest}",
                role=ROLE_INPUT,
                known_at=cutoff,
                fidelity="exact" if weekly or _all_exact(result, rows) else "partial",
                basis=(
                    "the newest pre-kickoff observedAt among the scored projections"
                    if weekly
                    else "the newest snapshot asOf (a date-only asOf bounded at its day's end)"
                ),
            ),
            outcome_set=StoreRef(
                store=WEEKLY_REALIZED_STORE if weekly else SEASON_REALIZED_STORE,
                key=f"{horizon}#realized:sha256={digest}",
                role=ROLE_OUTCOME,
                known_at=realized_at,
                fidelity="exact",
                basis="when the realized stats were read",
                revision=sha256_text(canonical_json(sorted({p.realized_revision for p in rows})))[
                    :16
                ],
            ),
            preregistration=NotApplicable(
                "report-only scorecard: no challenger and no decision rule"
            ),
            overall=_cohort(points, {"position": ALL_POSITIONS, "stat": STAT_POINTS}),
            cohorts=cohorts,
            holdout_design=("chronological",),
            proposed_verdict=VERDICT_INCONCLUSIVE,
            verdict_basis=(
                "report-only projection scorecard; no challenger and no preregistered gate, so "
                "no comparative verdict exists"
            ),
            extra={
                "schema": SCHEMA,
                "leagueKey": result.league_key,
                "provider": provider,
                "model": model,
                "familyCounts": families,
                "championEqualsSoleConstituent": weekly or families == [1],
                "minN": MIN_N,
            },
        )
        out.append(ev.to_learning_receipt())
    return out


def _all_exact(result: ScorecardResult, rows: Sequence[Pair]) -> bool:
    for snap in result.summary.get("season", {}).get("snapshots", ()):
        if snap.get("asOfExact") is False:
            return False
    return True
