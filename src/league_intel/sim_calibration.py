"""Points-model calibration for the best-ball simulation (LI-8).

The playoff sim needs, per player-week, a distribution of FANTASY POINTS.
What it has is ``rosValue`` — a 0-100 consensus composite with no units.
Bridging the two used to be two magic constants living in
``playoff_sim.py``::

    mean = rosValue / 2.7          # "produces a believable weekly mean"
    cv   = _PLAYER_CV_BY_POSITION  # "calibrated from public weekly-scoring
                                   #  datasets"

Neither was traceable to this league.  The divisor was tuned by eye, and
the CV table cited a dataset that is named nowhere in the repo and uses
generic PPR assumptions — in a superflex league that scores IDP on five
separate event keys and has *deleted* its TE premium (ADR-009), those
numbers describe a different game.

This module replaces both with a calibration derived from **real stat
lines scored under this league's own settings** via
``src.league_intel.scorer.score_stat_line`` — the same exact scorer that
reconciled 1,415/1,415 rostered player-weeks to within 0.011 (LI-2).

What it produces
────────────────
A versioned artifact at ``data/league_intel/sim_points_model.json``::

    {
      "schemaVersion": 1,
      "generatedAt": "...Z",
      "configVersion": 1,
      "season": "2025",
      "weeks": [1, 2, 3],
      "sampleSize": 1415,
      "scale": {"rosValuePerPoint": 2.71, "r2": 0.63, "n": 402},
      "byPosition": {"QB": {"cv": 0.31, "n": 48, "meanPoints": 18.9}, ...},
      "provenance": {...}
    }

Runtime NEVER fetches.  ``playoff_sim`` loads this artifact if present
and falls back to the legacy constants with an explicit
``pointsModelSource: "fallback-constants"`` stamp when it is absent, so
a sim run always declares which model produced it.

Why a build-time artifact and not a live call: Sleeper's stat endpoints
are the only source of real stat lines, the sim runs inside a request
path, and LI-1 established the dated-snapshot pattern for exactly this
(one polite fetch, diffed, written, never mutated in place).

Scope boundary
──────────────
This calibrates the rosValue→points SCALE and per-position VARIANCE.  It
does not project per-player stat lines — that is LI-6's job.  When LI-6
lands, ``PointsModel`` gains a stat-line path and the scale term becomes
a fallback for unprojected players.  The interface is shaped for that
now so the swap does not churn the sim.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.league_intel.scorer import score_stat_line

LOG = logging.getLogger("league_intel.sim_calibration")

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "league_intel"
MODEL_PATH = DATA_DIR / "sim_points_model.json"

SCHEMA_VERSION = 1

# Legacy constants, kept ONLY as the documented fallback so a missing
# artifact degrades to prior behavior instead of crashing.  Any sim run
# using these stamps ``pointsModelSource: "fallback-constants"``.
FALLBACK_ROS_VALUE_PER_POINT = 2.7
FALLBACK_CV_BY_POSITION: dict[str, float] = {
    "QB": 0.32,
    "RB": 0.55,
    "WR": 0.60,
    "TE": 0.65,
    "DL": 0.55,
    "DE": 0.55,
    "DT": 0.55,
    "EDGE": 0.55,
    "LB": 0.45,
    "DB": 0.50,
    "S": 0.50,
    "CB": 0.55,
}
FALLBACK_DEFAULT_CV = 0.55

# A position needs this many scored player-weeks before its measured CV
# is trusted; below it we keep the fallback and say so.
MIN_SAMPLES_PER_POSITION = 30

# CV is clamped to a physically sane band.  A measured CV outside this
# usually means the position's sample is contaminated (e.g. a handful of
# zero-snap weeks), not that the position is genuinely that volatile.
CV_CLAMP = (0.15, 1.20)


@dataclass(frozen=True)
class PositionCalibration:
    """Measured weekly-points behavior for one position."""

    position: str
    cv: float
    mean_points: float
    n: int
    measured: bool  # False ⇒ fallback CV (sample below the floor)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cv": round(self.cv, 4),
            "meanPoints": round(self.mean_points, 3),
            "n": self.n,
            "measured": self.measured,
        }


@dataclass
class PointsModel:
    """rosValue → weekly fantasy points, with per-position variance.

    ``draw`` is the sim's hot path: one Gaussian per player per week,
    truncated at zero (a fantasy week cannot score negative in
    aggregate for a starter-worthy player, and the optimizer would
    never start a negative anyway).
    """

    ros_value_per_point: float = FALLBACK_ROS_VALUE_PER_POINT
    cv_by_position: Mapping[str, float] = field(
        default_factory=lambda: dict(FALLBACK_CV_BY_POSITION)
    )
    default_cv: float = FALLBACK_DEFAULT_CV
    source: str = "fallback-constants"
    generated_at: str | None = None
    sample_size: int = 0

    def mean_points(self, ros_value: float) -> float:
        """Expected weekly points for a player at ``ros_value``."""
        if self.ros_value_per_point <= 0:
            return 0.0
        return max(0.0, float(ros_value) / self.ros_value_per_point)

    def cv_for(self, position: str) -> float:
        return self.cv_by_position.get((position or "").upper(), self.default_cv)

    def draw_from_mean(self, mean: float, position: str, rng: Any) -> float:
        """Sample one weekly point total from a mean ALREADY IN POINTS.

        The variance half of this model — the per-position CV measured
        under this league's own scoring — is independent of how the mean
        was obtained.  ``draw`` gets its mean by converting a ``rosValue``
        through the fitted scale; a caller holding a real point
        projection (Game Day, and eventually LI-6's stat-line path)
        supplies it directly and skips that conversion.

        This is the seam the module docstring already anticipated
        ("``PointsModel`` gains a stat-line path and the scale term
        becomes a fallback for unprojected players.  The interface is
        shaped for that now so the swap does not churn the sim").  It is
        deliberately the SAME variance model rather than a second one:
        two engines disagreeing about how volatile a QB week is would be
        exactly the duplicate-owner problem this repo keeps closing.
        """
        if mean <= 0.0:
            return 0.0
        sd = max(0.5, mean * self.cv_for(position))
        return max(0.0, rng.gauss(mean, sd))

    def draw(self, ros_value: float, position: str, rng: Any) -> float:
        """Sample one weekly point total.  Hot path — keep it cheap."""
        return self.draw_from_mean(self.mean_points(ros_value), position, rng)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rosValuePerPoint": self.ros_value_per_point,
            "defaultCv": self.default_cv,
            "source": self.source,
            "generatedAt": self.generated_at,
            "sampleSize": self.sample_size,
            "cvByPosition": dict(self.cv_by_position),
        }


DEFAULT_POINTS_MODEL = PointsModel()


def load_points_model(path: Path | None = None) -> PointsModel:
    """Load the calibrated model, or the documented fallback.

    Never raises: a missing, unreadable, or schema-mismatched artifact
    degrades to ``DEFAULT_POINTS_MODEL`` with the fallback source stamp,
    because a sim that refuses to run is worse than one that declares a
    weaker model.
    """
    target = path or MODEL_PATH
    try:
        if not target.exists():
            return PointsModel()
        blob = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("sim points model unreadable (%s): %s", target, exc)
        return PointsModel()

    if not isinstance(blob, dict) or blob.get("schemaVersion") != SCHEMA_VERSION:
        LOG.warning(
            "sim points model schema mismatch (want %s, got %r) — using fallback",
            SCHEMA_VERSION,
            (blob or {}).get("schemaVersion") if isinstance(blob, dict) else None,
        )
        return PointsModel()

    scale = blob.get("scale") or {}
    try:
        per_point = float(scale.get("rosValuePerPoint") or 0.0)
    except (TypeError, ValueError):
        per_point = 0.0
    if per_point <= 0:
        LOG.warning("sim points model has no usable scale — using fallback")
        return PointsModel()

    cvs: dict[str, float] = dict(FALLBACK_CV_BY_POSITION)
    for pos, entry in (blob.get("byPosition") or {}).items():
        if not isinstance(entry, dict):
            continue
        try:
            cv = float(entry.get("cv"))
        except (TypeError, ValueError):
            continue
        if cv > 0:
            cvs[str(pos).upper()] = cv

    return PointsModel(
        ros_value_per_point=per_point,
        cv_by_position=cvs,
        source="calibrated",
        generated_at=blob.get("generatedAt"),
        sample_size=int(blob.get("sampleSize") or 0),
    )


# ── Calibration (build-time) ───────────────────────────────────────


def _clamp_cv(cv: float) -> float:
    lo, hi = CV_CLAMP
    return max(lo, min(hi, cv))


def calibrate_positions(
    scored_weeks: Mapping[str, list[float]],
) -> dict[str, PositionCalibration]:
    """Per-position CV + mean from scored player-weeks.

    ``scored_weeks`` maps position → the list of that position's weekly
    point totals (already run through the exact scorer).  Positions
    below ``MIN_SAMPLES_PER_POSITION`` keep the fallback CV and are
    stamped ``measured=False`` so the artifact never implies more
    evidence than it has.
    """
    out: dict[str, PositionCalibration] = {}
    for pos, points in scored_weeks.items():
        key = str(pos).upper()
        vals = [float(v) for v in points if v is not None]
        n = len(vals)
        if n == 0:
            continue
        mean = statistics.fmean(vals)
        if n < MIN_SAMPLES_PER_POSITION or mean <= 0:
            out[key] = PositionCalibration(
                position=key,
                cv=FALLBACK_CV_BY_POSITION.get(key, FALLBACK_DEFAULT_CV),
                mean_points=mean,
                n=n,
                measured=False,
            )
            continue
        sd = statistics.pstdev(vals)
        out[key] = PositionCalibration(
            position=key,
            cv=_clamp_cv(sd / mean),
            mean_points=mean,
            n=n,
            measured=True,
        )
    return out


def calibrate_scale(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """Fit ``rosValue ≈ k × points`` over (ros_value, mean_points) pairs.

    Least-squares through the origin — the relationship must pass
    through (0, 0): a player with no ROS value projects no points, and
    an intercept would let a worthless player score.  ``k`` is the
    divisor the sim applies.

    Returns ``{rosValuePerPoint, r2, n}``.  ``r2`` is reported so a weak
    fit is visible in the artifact rather than silently trusted.
    """
    usable = [(rv, pts) for rv, pts in pairs if rv > 0 and pts > 0]
    n = len(usable)
    if n < 2:
        return {"rosValuePerPoint": FALLBACK_ROS_VALUE_PER_POINT, "r2": 0.0, "n": n}

    num = sum(rv * pts for rv, pts in usable)
    den = sum(pts * pts for _, pts in usable)
    if den <= 0:
        return {"rosValuePerPoint": FALLBACK_ROS_VALUE_PER_POINT, "r2": 0.0, "n": n}
    k = num / den

    mean_rv = statistics.fmean([rv for rv, _ in usable])
    ss_tot = sum((rv - mean_rv) ** 2 for rv, _ in usable)
    ss_res = sum((rv - k * pts) ** 2 for rv, pts in usable)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return {"rosValuePerPoint": round(k, 4), "r2": round(r2, 4), "n": n}


def build_calibration(
    *,
    stat_lines_by_week: Mapping[int, Mapping[str, Mapping[str, Any]]],
    positions: Mapping[str, str],
    ros_values: Mapping[str, float],
    config: Any,
    season: str,
) -> dict[str, Any]:
    """Score real stat lines and emit the calibration artifact.

    Args:
        stat_lines_by_week: ``{week: {player_id: stat_line}}`` as served
            by ``GET /v1/stats/nfl/regular/{season}/{week}``.
        positions: ``{player_id: position}``.
        ros_values: ``{player_id: rosValue}`` — only players present here
            contribute to the SCALE fit (the CV fit uses every scored
            week, since variance does not need a value anchor).
        config: LeagueIntelConfig or a scoring-settings mapping.
        season: the season the stat lines came from.

    Pure apart from the clock: callers supply the data, this scores it.
    """
    by_position: dict[str, list[float]] = {}
    per_player_points: dict[str, list[float]] = {}

    for week in sorted(stat_lines_by_week):
        for pid, line in (stat_lines_by_week[week] or {}).items():
            if not isinstance(line, Mapping):
                continue
            pos = str(positions.get(pid) or "").upper()
            if not pos:
                continue
            pts = score_stat_line(line, config).total_points
            by_position.setdefault(pos, []).append(pts)
            per_player_points.setdefault(pid, []).append(pts)

    per_position = calibrate_positions(by_position)

    # Scale: one (rosValue, meanPoints) pair per player with both.
    pairs: list[tuple[float, float]] = []
    for pid, pts_list in per_player_points.items():
        rv = ros_values.get(pid)
        if rv is None or not pts_list:
            continue
        try:
            rv_f = float(rv)
        except (TypeError, ValueError):
            continue
        if rv_f <= 0:
            continue
        pairs.append((rv_f, statistics.fmean(pts_list)))
    scale = calibrate_scale(pairs)

    total_samples = sum(len(v) for v in by_position.values())
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "configVersion": getattr(config, "config_version", None),
        "season": str(season),
        "weeks": sorted(stat_lines_by_week),
        "sampleSize": total_samples,
        "scale": scale,
        "byPosition": {k: v.to_dict() for k, v in sorted(per_position.items())},
        "provenance": {
            "scorer": "src.league_intel.scorer.score_stat_line",
            "statSource": f"GET /v1/stats/nfl/regular/{season}/{{week}}",
            "minSamplesPerPosition": MIN_SAMPLES_PER_POSITION,
            "cvClamp": list(CV_CLAMP),
            "note": (
                "Scale is a through-origin least-squares fit of rosValue on "
                "mean weekly points. Positions with measured=false kept the "
                "documented fallback CV because their sample was below the "
                "floor."
            ),
        },
    }


def write_calibration(payload: Mapping[str, Any], path: Path | None = None) -> Path:
    """Atomically write the artifact (temp file + replace)."""
    target = path or MODEL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{int(time.time() * 1000)}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    tmp.replace(target)
    return target


def fetch_stat_lines(
    season: str,
    weeks: list[int],
    *,
    fetcher: Callable[[str], Any],
    sleep_s: float = 1.0,
) -> dict[int, dict[str, Any]]:
    """Fetch weekly stat lines, one polite request per week.

    ``fetcher`` is injected so tests never touch the network and the
    rate-limit policy stays the caller's decision.  Weeks that fail are
    skipped with a warning rather than aborting the run — a calibration
    on three weeks is better than none.
    """
    out: dict[int, dict[str, Any]] = {}
    for i, week in enumerate(weeks):
        if i > 0 and sleep_s > 0:
            time.sleep(sleep_s)
        url = f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
        try:
            blob = fetcher(url)
        except Exception as exc:  # noqa: BLE001 — one bad week must not abort
            LOG.warning("stat-line fetch failed for %s wk%s: %s", season, week, exc)
            continue
        if isinstance(blob, Mapping):
            out[int(week)] = dict(blob)
    return out


__all__ = [
    "CV_CLAMP",
    "DEFAULT_POINTS_MODEL",
    "FALLBACK_CV_BY_POSITION",
    "FALLBACK_ROS_VALUE_PER_POINT",
    "MIN_SAMPLES_PER_POSITION",
    "MODEL_PATH",
    "PointsModel",
    "PositionCalibration",
    "SCHEMA_VERSION",
    "build_calibration",
    "calibrate_positions",
    "calibrate_scale",
    "fetch_stat_lines",
    "load_points_model",
    "write_calibration",
]
