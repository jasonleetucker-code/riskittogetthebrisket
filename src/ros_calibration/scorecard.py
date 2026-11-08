"""Standing prediction scorecard and champion-degradation review rule (MD-104).

EVALUATION ONLY.  Pure functions over plain records: this module reads nothing
from disk, writes nothing, and changes no forecast, value, flag or served
response.  ``scripts/forecast_scorecard.py`` does the I/O.

Families (each joins archived FORECASTS to realized OUTCOMES):

* ``season_playoff_odds`` / ``season_title_odds`` -- the append-only
  ``src/ros/forecast_archive.py`` records, scored per team against the host's
  playoff field / champion.
* ``game_day_win`` / ``game_day_median`` -- the Game Day generations, scored by
  the existing ``src/model_registry/game_day_calibration.py`` (its temporal
  guard, de-duplication and per-model-version cohorts are reused, not rebuilt).
* ``team_weekly_points`` -- Game Day's pre-game ``expectedFinalBestBall`` against
  the host's final score.

Rules, each pinned by ``tests/ros_calibration/test_scorecard.py``:

* **Missing is never zero.**  A family with no outcome reports ``unavailable``
  with its reason; a metric that cannot be computed is ``None`` with a reason.
* **No look-ahead.**  A forecast computed at or after its outcome was decided, or
  at or after kickoff, is excluded and counted by name.
* **Stat-correction wait.**  An outcome counts only once the configured wait has
  passed since it was last published.
* **Model versions are never pooled.**  Each version is its own row; only the
  served (most recent) version can trigger a review.
* **Same samples, named baseline.**  The served model and its baseline are scored
  on the identical samples.
* **Honest uncertainty.**  A cluster bootstrap CI on the paired difference, and a
  verdict of ``insufficient_evidence`` below the pre-declared sample floors.

The degradation rule itself is DECLARED in
``config/forecast_scorecard/degradation_rule_v1.json`` (committed before any data
was scored).  A fired rule is a REVIEW REQUEST for the owner; nothing here, or
downstream of it, promotes, demotes or alters anything.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from src.model_registry import game_day_calibration as gdc
from src.ros import forecast_archive
from src.ros_calibration import metrics as M
from src.ros_calibration import team_points as TP

SCHEMA = "forecast-scorecard/v1"

FAMILY_PLAYOFF = "season_playoff_odds"
FAMILY_TITLE = "season_title_odds"
FAMILY_GD_WIN = "game_day_win"
FAMILY_GD_MEDIAN = "game_day_median"
FAMILY_POINTS = "team_weekly_points"
FAMILIES = (FAMILY_PLAYOFF, FAMILY_TITLE, FAMILY_GD_WIN, FAMILY_GD_MEDIAN, FAMILY_POINTS)

VERDICT_INSUFFICIENT = "insufficient_evidence"
VERDICT_WORSE = "served_worse_than_baseline"
VERDICT_NOT_WORSE = "not_worse_than_baseline"
UNAVAILABLE = "unavailable"

#: 80% central interval half-width in sds (same constant ``team_points`` scores with).
Z80 = 1.2815515655446004
_EPS = 1e-12


# ── instants ─────────────────────────────────────────────────────────────────


def parse_instant(value: Any) -> datetime | None:
    """A tz-aware UTC datetime from an ISO string or datetime, else ``None``."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.astimezone(timezone.utc).isoformat()


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _digest(rows: Iterable[Any]) -> str:
    return forecast_archive.canonical_sha256(sorted(rows))[:16]


# ── config ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FamilyRule:
    family: str
    metric: str  # "brier" | "mae"
    baseline: str
    margin: float
    min_eligible: int
    min_clusters: int
    min_seasons: int
    state_basis: str | None


@dataclass(frozen=True)
class Rule:
    version: str
    wait: timedelta
    b: int
    seed: int
    consecutive: int
    families: Mapping[str, FamilyRule]


def parse_rule(config: Mapping[str, Any]) -> Rule:
    """The declared rule from its config; a malformed config raises (never a default)."""
    fams: dict[str, FamilyRule] = {}
    for name, body in (config["families"] or {}).items():
        margin = body["margin"] if "margin" in body else body["marginPoints"]
        fams[name] = FamilyRule(
            family=name,
            metric=str(body["metric"]),
            baseline=str(body["baseline"]),
            margin=float(margin),
            min_eligible=int(body["minEligible"]),
            min_clusters=int(body["minClusters"]),
            min_seasons=int(body["minSeasons"]),
            state_basis=body.get("stateBasis"),
        )
    missing = [f for f in FAMILIES if f not in fams]
    if missing:
        raise ValueError(f"degradation rule declares no families: {missing}")
    boot = config["bootstrap"]
    return Rule(
        version=str(config["ruleVersion"]),
        wait=timedelta(hours=float(config["statCorrectionWaitHours"])),
        b=int(boot["b"]),
        seed=int(boot["seed"]),
        consecutive=int(config["consecutiveEvaluations"]),
        families=fams,
    )


# ── metrics ──────────────────────────────────────────────────────────────────


def binary_metrics(ps: Sequence[float], ys: Sequence[int]) -> dict[str, Any]:
    """Brier, log loss, bias and calibration slope of probabilities against 0/1 outcomes."""
    n = len(ps)
    if n == 0:
        return {"n": 0, "state": UNAVAILABLE, "reason": "no_samples"}
    slope = M.calibration_slope(ps, ys)
    return {
        "n": n,
        "brier": sum((p - y) ** 2 for p, y in zip(ps, ys)) / n,
        "logLoss": sum(TP.log_loss(p, y) for p, y in zip(ps, ys)) / n,
        "meanPredicted": sum(ps) / n,
        "observedRate": sum(ys) / n,
        "bias": sum(ps) / n - sum(ys) / n,
        "calibrationSlope": slope,
        "calibrationSlopeReason": None if slope is not None else "no_spread_in_forecasts",
        "intervalCoverage": {
            "state": "not_applicable",
            "reason": "probability_forecast_has_no_outcome_interval",
        },
        "crps": {"state": "not_applicable", "reason": "binary_outcome_scored_by_brier"},
    }


def points_metrics(
    mus: Sequence[float], ys: Sequence[float], sds: Sequence[float | None] | None = None
) -> dict[str, Any]:
    """MAE, bias, calibration slope and, only when every sd is archived, CRPS and 80% coverage."""
    n = len(mus)
    if n == 0:
        return {"n": 0, "state": UNAVAILABLE, "reason": "no_samples"}
    slope = M.calibration_slope(mus, ys)
    out: dict[str, Any] = {
        "n": n,
        "mae": M.mae(mus, ys),
        "rmse": M.rmse(mus, ys),
        "bias": sum(m - y for m, y in zip(mus, ys)) / n,
        "calibrationSlope": slope,
        "calibrationSlopeReason": None if slope is not None else "no_spread_in_forecasts",
    }
    if sds is not None and all(s is not None and s > 0 for s in sds):
        out["crps"] = sum(TP.crps_normal(m, s, y) for m, s, y in zip(mus, sds, ys)) / n
        out["intervalCoverage"] = {
            "level": 0.8,
            "coverage": sum(1 for m, s, y in zip(mus, sds, ys) if abs(y - m) <= Z80 * s) / n,
        }
    else:
        reason = "no_predictive_distribution_archived"
        out["crps"] = {"state": UNAVAILABLE, "reason": reason}
        out["intervalCoverage"] = {"state": UNAVAILABLE, "reason": reason}
    return out


@dataclass(frozen=True)
class Sample:
    """One scored sample: forecast, baseline, outcome and the cluster it belongs to."""

    cluster: str
    season: str
    served: float
    base: float
    y: float
    sd: float | None = None


def _metric_value(samples: Sequence[Sample], metric: str, *, arm: str) -> float | None:
    if not samples:
        return None
    if arm == "served":
        xs = [s.served for s in samples]
    else:
        xs = [s.base for s in samples]
    ys = [s.y for s in samples]
    if metric == "brier":
        return sum((x - y) ** 2 for x, y in zip(xs, ys)) / len(xs)
    if metric == "mae":
        return sum(abs(x - y) for x, y in zip(xs, ys)) / len(xs)
    raise ValueError(metric)


def _delta(samples: Sequence[Sample], metric: str) -> float | None:
    a = _metric_value(samples, metric, arm="served")
    b = _metric_value(samples, metric, arm="base")
    return None if a is None or b is None else a - b


def evaluate_samples(samples: Sequence[Sample], fam: FamilyRule, rule: Rule) -> dict[str, Any]:
    """Metrics for served and baseline on the identical samples, CI and verdict."""
    n = len(samples)
    clusters = len({s.cluster for s in samples})
    seasons = len({s.season for s in samples})
    if fam.metric == "brier":
        served = binary_metrics([s.served for s in samples], [int(s.y) for s in samples])
        base = binary_metrics([s.base for s in samples], [int(s.y) for s in samples])
    else:
        sds = [s.sd for s in samples]
        served = points_metrics([s.served for s in samples], [s.y for s in samples], sds)
        base = points_metrics([s.base for s in samples], [s.y for s in samples])
    delta = _delta(samples, fam.metric)
    boot = None
    if n and clusters >= 2:
        boot = M.cluster_bootstrap(
            list(samples),
            lambda s: s.cluster,
            lambda recs: _delta(recs, fam.metric),
            b=rule.b,
            seed=rule.seed,
        )
    floors = {
        "minEligible": fam.min_eligible,
        "minClusters": fam.min_clusters,
        "minSeasons": fam.min_seasons,
    }
    shortfalls = []
    if n < fam.min_eligible:
        shortfalls.append(f"eligible {n} < {fam.min_eligible}")
    if clusters < fam.min_clusters:
        shortfalls.append(f"clusters {clusters} < {fam.min_clusters}")
    if seasons < fam.min_seasons:
        shortfalls.append(f"seasons {seasons} < {fam.min_seasons}")
    if shortfalls:
        verdict = VERDICT_INSUFFICIENT
    elif delta is not None and delta + _EPS >= fam.margin:
        verdict = VERDICT_WORSE
    else:
        verdict = VERDICT_NOT_WORSE
    return {
        "eligible": n,
        "clusters": clusters,
        "seasons": seasons,
        "served": served,
        "baseline": {"name": fam.baseline, **base},
        "metric": fam.metric,
        "delta": delta,
        "deltaMeaning": "served minus baseline; positive = served is worse (lower is better)",
        "deltaCi95": None if boot is None else boot["ci95"],
        "bootstrap": {
            "clusterBy": "see rule",
            "b": rule.b,
            "seed": rule.seed,
            "state": "ok" if boot is not None else UNAVAILABLE,
            "reason": None if boot is not None else "fewer_than_two_clusters",
        },
        "floors": floors,
        "shortfalls": shortfalls,
        "margin": fam.margin,
        "verdict": verdict,
        "sampleDigest": _digest(
            (s.cluster, round(s.served, 9), round(s.base, 9), s.y) for s in samples
        ),
    }


# ── season outcomes ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SeasonOutcome:
    """What the host decided for one league-season.  ``None`` fields are undecided."""

    league_key: str
    season: str
    playoffs_decided_at: datetime | None = None
    playoff_owner_ids: frozenset[str] | None = None
    title_decided_at: datetime | None = None
    champion_owner_id: str | None = None


def season_outcome_from_json(body: Mapping[str, Any]) -> SeasonOutcome:
    qual = body.get("playoffOwnerIds")
    return SeasonOutcome(
        league_key=str(body["leagueKey"]),
        season=str(body["season"]),
        playoffs_decided_at=parse_instant(body.get("playoffsDecidedAt")),
        playoff_owner_ids=None if qual is None else frozenset(str(x) for x in qual),
        title_decided_at=parse_instant(body.get("titleDecidedAt")),
        champion_owner_id=None
        if body.get("championOwnerId") is None
        else str(body["championOwnerId"]),
    )


def _model_version(record: Mapping[str, Any]) -> str | None:
    sha = (
        ((record.get("model") or {}).get("simParamsSha256"))
        if isinstance(record.get("model"), Mapping)
        else None
    )
    return f"sim:{str(sha)[:12]}" if sha else None


def _odds_rows(record: Mapping[str, Any], family: str) -> list[Mapping[str, Any]]:
    forecast = record.get("forecast") or {}
    key = "playoffOdds" if family == FAMILY_PLAYOFF else "championshipOdds"
    rows = forecast.get(key)
    return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []


def _odds_field(family: str) -> str:
    return "playoffOdds" if family == FAMILY_PLAYOFF else "championshipOdds"


def _season_baseline(record: Mapping[str, Any], family: str, n_rows: int) -> float | None:
    if n_rows <= 0:
        return None
    if family == FAMILY_TITLE:
        return 1.0 / n_rows
    structure = (record.get("forecast") or {}).get("playoffStructure") or {}
    teams = _num(structure.get("playoffTeams")) if isinstance(structure, Mapping) else None
    if teams is None or teams <= 0 or teams > n_rows:
        return None
    return teams / n_rows


def season_family(
    family: str,
    records: Sequence[Mapping[str, Any]],
    outcomes: Sequence[SeasonOutcome],
    rule: Rule,
    now: datetime,
) -> dict[str, Any]:
    """Score one season-level odds family across every league and model version."""
    kind = "playoff" if family == FAMILY_PLAYOFF else "championship"
    fam = rule.families[family]
    by_outcome = {(o.league_key, o.season): o for o in outcomes}
    mine = [r for r in records if r.get("kind") == kind]
    if not mine:
        return {
            "family": family,
            "state": UNAVAILABLE,
            "reason": "no_archived_forecasts",
            "rows": [],
        }
    # served version per league: the version of its most recent forecast.
    latest: dict[str, tuple[datetime, str]] = {}
    for r in mine:
        at = parse_instant(r.get("computedAt"))
        v = _model_version(r) or "unidentified"
        lg = str(r.get("leagueKey"))
        if at is not None and (lg not in latest or at > latest[lg][0]):
            latest[lg] = (at, v)

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in mine:
        lg = str(r.get("leagueKey"))
        version = _model_version(r) or "unidentified"
        g = groups.setdefault(
            (lg, version),
            {
                "forecasts": 0,
                "exclusions": Counter(),
                "cand": {},
                "codeShas": set(),
                "cards": set(),
            },
        )
        g["forecasts"] += 1
        model = r.get("model") if isinstance(r.get("model"), Mapping) else {}
        if model.get("codeSha"):
            g["codeShas"].add(str(model["codeSha"]))
        inputs = r.get("inputs") if isinstance(r.get("inputs"), Mapping) else {}
        if inputs.get("leagueSnapshotSha256"):
            g["cards"].add(str(inputs["leagueSnapshotSha256"]))
        ex = g["exclusions"]
        at = parse_instant(r.get("computedAt"))
        if at is None:
            ex["unproven_instant"] += 1
            continue
        if version == "unidentified":
            ex["model_identity_missing"] += 1
            continue
        if not inputs.get("inputsSha256"):
            ex["missing_input_hash"] += 1
            continue
        season = str(r.get("season") or "")
        cutoff = r.get("lastScoredWeek")
        if not season or not isinstance(cutoff, int):
            ex["cutoff_unproven"] += 1
            continue
        outcome = by_outcome.get((lg, season))
        decided = None
        decided_at = None
        if outcome is not None:
            if family == FAMILY_PLAYOFF:
                decided, decided_at = outcome.playoff_owner_ids, outcome.playoffs_decided_at
            else:
                decided = outcome.champion_owner_id
                decided_at = outcome.title_decided_at
        if decided is None or decided_at is None:
            ex["no_outcome_yet"] += 1
            continue
        if at >= decided_at:
            ex["forecast_after_outcome"] += 1
            continue
        if now < decided_at + rule.wait:
            ex["stat_correction_window_open"] += 1
            continue
        progress = (r.get("forecast") or {}).get("regularSeasonProgress")
        if (
            family == FAMILY_PLAYOFF
            and isinstance(progress, Mapping)
            and progress.get("complete") is True
        ):
            ex["outcome_already_determined"] += 1
            continue
        key = (season, cutoff)
        prior = g["cand"].get(key)
        if prior is None:
            g["cand"][key] = (at, r)
        else:
            ex["superseded_same_cutoff"] += 1
            if at > prior[0]:
                g["cand"][key] = (at, r)

    rows: list[dict[str, Any]] = []
    for (lg, version), g in sorted(groups.items()):
        other = sum(x["forecasts"] for (l2, v2), x in groups.items() if l2 == lg and v2 != version)
        samples: list[Sample] = []
        sample_ex: Counter[str] = Counter()
        cutoffs: set[int] = set()
        for (season, cutoff), (_at, r) in sorted(g["cand"].items()):
            outcome = by_outcome[(lg, season)]
            odds = _odds_rows(r, family)
            base = _season_baseline(r, family, len(odds))
            if base is None:
                sample_ex["baseline_unavailable"] += 1
                continue
            cutoffs.add(cutoff)
            for row in odds:
                owner = row.get("ownerId")
                p = _num(row.get(_odds_field(family)))
                if owner is None:
                    sample_ex["row_without_owner"] += 1
                    continue
                if p is None or not 0.0 <= p <= 1.0:
                    sample_ex["invalid_probability"] += 1
                    continue
                owner = str(owner)
                if family == FAMILY_PLAYOFF:
                    y = 1.0 if owner in (outcome.playoff_owner_ids or frozenset()) else 0.0
                else:
                    y = 1.0 if owner == outcome.champion_owner_id else 0.0
                samples.append(Sample(f"{lg}|{season}|{owner}", season, p, base, y))
        ex = Counter(g["exclusions"])
        ex.update(sample_ex)
        ex["model_version_mixed"] = other
        result = evaluate_samples(samples, fam, rule)
        served = latest.get(lg, (None, None))[1] == version
        rows.append(
            {
                "family": family,
                "leagueKey": lg,
                "target": kind,
                "modelVersion": version,
                "isServedModel": served,
                "codeShas": sorted(g["codeShas"]),
                "scoringCard": {
                    "basis": "league_snapshot_sha256 (the league object, including scoring_settings)",
                    "ids": sorted(g["cards"]),
                },
                "cutoffBasis": "lastScoredWeek",
                "cutoffs": sorted(cutoffs),
                "forecastCount": g["forecasts"],
                "eligibleSamples": result["eligible"],
                "eligibleForecasts": len(g["cand"]),
                "exclusions": dict(sorted((k, v) for k, v in ex.items() if v)),
                **{k: v for k, v in result.items() if k != "eligible"},
                "clusterBy": fam_cluster(fam),
                "ruleBasis": True,
                "state": "scored" if samples else UNAVAILABLE,
                "reason": None if samples else _dominant(ex),
            }
        )
    return {
        "family": family,
        "state": "scored" if any(r["state"] == "scored" for r in rows) else UNAVAILABLE,
        "reason": None if any(r["state"] == "scored" for r in rows) else _dominant_rows(rows),
        "rows": rows,
    }


def fam_cluster(fam: FamilyRule) -> str:
    return "team_season" if fam.metric == "brier" else "league_week"


def _dominant(ex: Mapping[str, int]) -> str:
    items = [(v, k) for k, v in ex.items() if v and k != "model_version_mixed"]
    return max(items)[1] if items else "no_eligible_forecasts"


def _dominant_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    total: Counter[str] = Counter()
    for r in rows:
        total.update(
            {k: v for k, v in (r.get("exclusions") or {}).items() if k != "model_version_mixed"}
        )
    return _dominant(total)


# ── Game Day families ────────────────────────────────────────────────────────


def _gd_rows(
    result: gdc.ScorecardResult, target: str, family: str, rule: Rule, now: datetime
) -> dict[str, Any]:
    fam = rule.families[family]
    scored = [s for s in result.scored if s.target == target]
    weeks_info = (result.summary or {}).get("leagues") or {}
    excl_by_league: dict[str, Counter[str]] = {}
    gens_by_league: Counter[str] = Counter()
    for lg, block in weeks_info.items():
        c: Counter[str] = Counter()
        for w in block.get("weeks") or []:
            gens_by_league[lg] += int(w.get("uniqueGenerations") or 0)
            for k, v in (w.get("predictionExclusions") or {}).items():
                c[k] += int(v)
            for k, v in (w.get("predictionsMissingPerGenerationEvent") or {}).items():
                c[k] += int(v)
            if (w.get("outcome") or {}).get("state") == "unavailable":
                c["no_outcome_yet"] += 1
        excl_by_league[lg] = c
    if not weeks_info:
        return {
            "family": family,
            "state": UNAVAILABLE,
            "reason": "no_game_day_evidence",
            "rows": [],
        }
    latest: dict[str, tuple[datetime, str]] = {}
    for s in scored:
        if s.league_key not in latest or s.as_known_at > latest[s.league_key][0]:
            latest[s.league_key] = (s.as_known_at, s.model_version)
    keys = sorted({(s.league_key, s.model_version) for s in scored})
    rows: list[dict[str, Any]] = []
    for lg, version in keys:
        mine = [s for s in scored if s.league_key == lg and s.model_version == version]
        other = len({s.event for s in scored if s.league_key == lg and s.model_version != version})
        ex = Counter(excl_by_league.get(lg, {}))
        waited = [s for s in mine if now >= s.outcome_revision_at + rule.wait]
        ex["stat_correction_window_open"] += len(mine) - len(waited)
        ex["model_version_mixed"] = other
        states = sorted({s.state for s in waited} | {fam.state_basis or "pregame"})
        for state in states:
            basis = state == (fam.state_basis or "pregame")
            sel = [s for s in waited if s.state == state]
            samples = [
                Sample(
                    cluster="|".join(s.event.split("|")[:3]),
                    season=s.event.split("|")[1],
                    served=s.p,
                    base=0.5,
                    y=float(s.y),
                )
                for s in sel
            ]
            result_row = evaluate_samples(samples, fam, rule)
            rows.append(
                {
                    "family": family,
                    "leagueKey": lg,
                    "target": target,
                    "modelVersion": version,
                    "isServedModel": latest[lg][1] == version,
                    "codeShas": {
                        "state": UNAVAILABLE,
                        "reason": "generation_index_rows_record_no_code_sha",
                    },
                    "scoringCard": {
                        "state": UNAVAILABLE,
                        "reason": "generation_index_rows_do_not_record_the_scoring_card_hash",
                    },
                    "cutoffBasis": "game_state",
                    "cutoff": state,
                    "forecastCount": len(mine)
                    if basis
                    else len([s for s in mine if s.state == state]),
                    "generationRowsExamined": gens_by_league.get(lg, 0),
                    "eligibleSamples": result_row["eligible"],
                    "exclusions": dict(sorted((k, v) for k, v in ex.items() if v)),
                    **{k: v for k, v in result_row.items() if k != "eligible"},
                    "clusterBy": "league_week",
                    "ruleBasis": basis,
                    "state": "scored" if samples else UNAVAILABLE,
                    "reason": None if samples else "no_eligible_samples_for_state",
                }
            )
    if not rows:
        reason = (
            _dominant(sum(excl_by_league.values(), Counter()))
            if excl_by_league
            else "no_outcome_yet"
        )
        return {"family": family, "state": UNAVAILABLE, "reason": reason, "rows": []}
    return {"family": family, "state": "scored", "reason": None, "rows": rows}


# ── team weekly points ───────────────────────────────────────────────────────


def _week_actuals(
    ev: gdc.LeagueWeekEvidence, unique: Sequence[Mapping[str, Any]], outcome: gdc.WeekOutcomes
) -> dict[str, float]:
    gen = ev.latest_generation or {}
    resolved = gen.get("resolved") or {}
    raw: Mapping[str, Any] = {}
    if resolved.get("mode") == "final":
        raw = resolved.get("hostScores") or {}
    else:
        final = None
        for r in unique:
            if r.get("generationId") == outcome.revision_id:
                final = r
        raw = {
            str(rid): (side or {}).get("actualScore")
            for rid, side in ((final or {}).get("outcomes") or {}).items()
        }
    return {str(k): v for k, v in ((k, _num(x)) for k, x in raw.items()) if v is not None}


def points_family(
    evidence: Sequence[gdc.LeagueWeekEvidence],
    rule: Rule,
    now: datetime,
    kickoffs: Mapping[tuple[str, int, int], datetime] | None = None,
) -> dict[str, Any]:
    fam = rule.families[FAMILY_POINTS]
    if not evidence:
        return {
            "family": FAMILY_POINTS,
            "state": UNAVAILABLE,
            "reason": "no_game_day_evidence",
            "rows": [],
        }
    kickoffs = kickoffs or {}
    # (league, season) -> [(week, known_at, actuals)] for the trailing-mean baseline.
    weeks: dict[tuple[str, int], list[tuple[int, datetime, dict[str, float]]]] = {}
    prepared: list[
        tuple[gdc.LeagueWeekEvidence, list[Mapping[str, Any]], gdc.WeekOutcomes, dict[str, float]]
    ] = []
    group_ex: dict[tuple[str, str], Counter[str]] = {}
    group_n: Counter[tuple[str, str]] = Counter()
    for ev in sorted(evidence, key=lambda e: (str(e.league_key), int(e.season), int(e.week))):
        unique, _census = gdc.dedupe_index_rows(ev.index_rows)
        out = gdc.resolve_outcomes(ev, unique)
        if isinstance(out, str):
            continue
        actuals = _week_actuals(ev, unique, out)
        weeks.setdefault((str(ev.league_key), int(ev.season)), []).append(
            (int(ev.week), out.known_at, actuals)
        )
        prepared.append((ev, list(unique), out, actuals))
    served_latest: dict[str, tuple[datetime, str]] = {}
    samples_by: dict[tuple[str, str], list[Sample]] = {}
    for ev, unique, out, actuals in prepared:
        lg, season, week = str(ev.league_key), int(ev.season), int(ev.week)
        kickoff = kickoffs.get((lg, season, week))
        last: dict[tuple[str, str], tuple[datetime, Mapping[str, Any]]] = {}
        for row in unique:
            version = row.get("modelVersion")
            if row.get("mode") != "pregame":
                continue
            if not version:
                group_ex.setdefault((lg, "unrecorded"), Counter())["model_version_unrecorded"] += 1
                continue
            version = str(version)
            ex = group_ex.setdefault((lg, version), Counter())
            at = parse_instant(row.get("inputsFetchedAt"))
            if at is None:
                ex["unproven_instant"] += 1
                continue
            if at >= out.known_at:
                ex["at_or_after_outcome"] += 1
                continue
            if kickoff is not None and at >= kickoff:
                ex["forecast_after_kickoff"] += 1
                continue
            if lg not in served_latest or at > served_latest[lg][0]:
                served_latest[lg] = (at, version)
            for rid, side in (row.get("outcomes") or {}).items():
                key = (version, str(rid))
                if key not in last or (at, str(row.get("generationId"))) > (
                    last[key][0],
                    str(last[key][1].get("generationId")),
                ):
                    last[key] = (at, {**row, "_side": side, "_rid": str(rid)})
        for (version, rid), (at, row) in sorted(last.items()):
            ex = group_ex.setdefault((lg, version), Counter())
            group_n[(lg, version)] += 1
            mu = _num((row["_side"] or {}).get("expectedFinalBestBall"))
            y = actuals.get(rid)
            if mu is None:
                ex["expected_points_missing"] += 1
                continue
            if y is None:
                ex["no_outcome_yet"] += 1
                continue
            if now < out.revision_at + rule.wait:
                ex["stat_correction_window_open"] += 1
                continue
            prior = [
                a[rid]
                for w, known, a in weeks.get((lg, season), [])
                if w < week and known < at and rid in a
            ]
            if not prior:
                ex["baseline_unavailable"] += 1
                continue
            sd = _num((row["_side"] or {}).get("expectedFinalBestBallSd"))
            samples_by.setdefault((lg, version), []).append(
                Sample(f"{lg}|{season}|w{week}", str(season), mu, sum(prior) / len(prior), y, sd)
            )
    rows: list[dict[str, Any]] = []
    for (lg, version), ex in sorted(group_ex.items()):
        if version == "unrecorded":
            continue
        samples = samples_by.get((lg, version), [])
        other = sum(group_n[(l2, v2)] for (l2, v2) in group_n if l2 == lg and v2 != version)
        ex = Counter(ex)
        ex["model_version_mixed"] = other
        res = evaluate_samples(samples, fam, rule)
        rows.append(
            {
                "family": FAMILY_POINTS,
                "leagueKey": lg,
                "target": "expectedFinalBestBall",
                "modelVersion": version,
                "isServedModel": served_latest.get(lg, (None, None))[1] == version,
                "codeShas": {
                    "state": UNAVAILABLE,
                    "reason": "generation_index_rows_record_no_code_sha",
                },
                "scoringCard": {
                    "state": UNAVAILABLE,
                    "reason": "generation_index_rows_do_not_record_the_scoring_card_hash",
                },
                "cutoffBasis": "game_state",
                "cutoff": "pregame",
                "forecastCount": group_n[(lg, version)],
                "eligibleSamples": res["eligible"],
                "exclusions": dict(sorted((k, v) for k, v in ex.items() if v)),
                **{k: v for k, v in res.items() if k != "eligible"},
                "clusterBy": "league_week",
                "ruleBasis": True,
                "state": "scored" if samples else UNAVAILABLE,
                "reason": None if samples else _dominant(ex),
            }
        )
    if not rows:
        return {
            "family": FAMILY_POINTS,
            "state": UNAVAILABLE,
            "reason": "no_pregame_forecast_with_final_outcome",
            "rows": [],
        }
    ok = any(r["state"] == "scored" for r in rows)
    return {
        "family": FAMILY_POINTS,
        "state": "scored" if ok else UNAVAILABLE,
        "reason": None if ok else _dominant_rows(rows),
        "rows": rows,
    }


# ── trigger ──────────────────────────────────────────────────────────────────


def streak_key(row: Mapping[str, Any], rule: Rule) -> str:
    return "|".join(
        [
            str(row["leagueKey"]),
            str(row["family"]),
            str(row["target"]),
            str(row["modelVersion"]),
            rule.version,
        ]
    )


def apply_trigger(
    rows: Sequence[dict[str, Any]],
    rule: Rule,
    prior_streaks: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Advance the consecutive-evaluation streaks and return the fired review requests.

    Only the SERVED model, on the rule's basis rows, with a ``served_worse_than_baseline``
    verdict, advances a streak; a different eligible sample set is what makes an
    evaluation new, so re-running on identical data never advances it.  Any other
    state resets the streak to 0.  Returns ``(reviews, streaks)``; neither changes
    anything outside the scorecard.
    """
    prior_streaks = prior_streaks or {}
    streaks: dict[str, dict[str, Any]] = {}
    reviews: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("ruleBasis") or not row.get("isServedModel"):
            continue
        key = streak_key(row, rule)
        before = prior_streaks.get(key) or {}
        count = int(before.get("streak") or 0)
        digest = row.get("sampleDigest")
        if row.get("verdict") == VERDICT_WORSE:
            if digest != before.get("digest"):
                count += 1
        else:
            count = 0
        streaks[key] = {"streak": count, "digest": digest, "verdict": row.get("verdict")}
        row["streak"] = count
        row["streakRequired"] = rule.consecutive
        if count >= rule.consecutive:
            fam = rule.families[row["family"]]
            reviews.append(
                {
                    "ruleVersion": rule.version,
                    "leagueKey": row["leagueKey"],
                    "family": row["family"],
                    "target": row["target"],
                    "modelVersion": row["modelVersion"],
                    "metric": fam.metric,
                    "baseline": fam.baseline,
                    "margin": fam.margin,
                    "delta": row["delta"],
                    "deltaCi95": row.get("deltaCi95"),
                    "eligible": row["eligibleSamples"],
                    "streak": count,
                    "streakRequired": rule.consecutive,
                    "servedMetric": (row["served"] or {}).get(fam.metric),
                    "baselineMetric": (row["baseline"] or {}).get(fam.metric),
                    "category": review_category(row, rule),
                }
            )
    return reviews, streaks


def review_category(row: Mapping[str, Any], rule: Rule) -> str:
    return ":".join(
        [
            "forecast_degradation",
            str(row["leagueKey"]),
            str(row["family"]),
            str(row["target"]),
            str(row["modelVersion"]),
            rule.version,
        ]
    )


# ── top level ────────────────────────────────────────────────────────────────


def build_scorecard(
    *,
    rule: Rule,
    now: datetime,
    forecast_records: Sequence[Mapping[str, Any]],
    season_outcomes: Sequence[SeasonOutcome],
    game_day_evidence: Sequence[gdc.LeagueWeekEvidence],
    kickoffs: Mapping[tuple[str, int, int], datetime] | None = None,
    prior_streaks: Mapping[str, Mapping[str, Any]] | None = None,
    code_sha: str | None = None,
) -> dict[str, Any]:
    """The whole scorecard.  ``now`` is injected, so identical inputs give identical output."""
    families: dict[str, Any] = {}
    families[FAMILY_PLAYOFF] = season_family(
        FAMILY_PLAYOFF, forecast_records, season_outcomes, rule, now
    )
    families[FAMILY_TITLE] = season_family(
        FAMILY_TITLE, forecast_records, season_outcomes, rule, now
    )
    gd = gdc.evaluate(list(game_day_evidence))
    families[FAMILY_GD_WIN] = _gd_rows(gd, gdc.TARGET_WIN, FAMILY_GD_WIN, rule, now)
    families[FAMILY_GD_MEDIAN] = _gd_rows(gd, gdc.TARGET_MEDIAN, FAMILY_GD_MEDIAN, rule, now)
    families[FAMILY_POINTS] = points_family(game_day_evidence, rule, now, kickoffs)
    all_rows = [r for f in families.values() for r in f["rows"]]
    reviews, streaks = apply_trigger(all_rows, rule, prior_streaks)
    return {
        "schema": SCHEMA,
        "evaluatedAt": _iso(now),
        "ruleVersion": rule.version,
        "codeSha": code_sha,
        "effect": "evaluation only; changes no forecast, value, flag or served response",
        "statCorrectionWaitHours": rule.wait.total_seconds() / 3600.0,
        "families": families,
        "degradationReviews": reviews,
        "streaks": streaks,
    }


__all__ = [
    "FAMILIES",
    "Rule",
    "Sample",
    "SeasonOutcome",
    "apply_trigger",
    "binary_metrics",
    "build_scorecard",
    "evaluate_samples",
    "parse_rule",
    "points_metrics",
    "review_category",
    "season_outcome_from_json",
]
