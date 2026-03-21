from __future__ import annotations

import bisect
import datetime as dt
import json
import os
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.utils import canonical_data_dir, normalize_player_name, repo_root

DEFAULT_CLAY_CONFIG: dict[str, Any] = {
    "enabled": True,
    # Required: each guide year must be explicitly configured in config/mike_clay_integration.json.
    "seasonWindowsByYear": {},
    "weights": {
        "offseason": 0.18,
        "week1": 0.06,
        "postWeek1Initial": 0.02,
    },
    "positionInfluence": {
        "QB": 0.76,
        "RB": 1.00,
        "WR": 0.96,
        "TE": 0.90,
        "DL": 0.98,
        "LB": 0.92,
        "DB": 0.88,
    },
    "positionDeltaCapPct": {
        "QB": 0.08,
        "RB": 0.12,
        "WR": 0.11,
        "TE": 0.10,
        "DL": 0.10,
        "LB": 0.09,
        "DB": 0.08,
    },
    "positionSignalBaseline": {
        "QB": 0.56,
        "RB": 0.54,
        "WR": 0.53,
        "TE": 0.52,
        "DL": 0.52,
        "LB": 0.52,
        "DB": 0.51,
    },
    "statusMultiplier": {
        "exact_match": 1.00,
        "deterministic_match": 0.97,
        "fuzzy_match_reviewed": 0.88,
    },
    "minSourceGate": 0.35,
    "sourceGateDivisor": 5.0,
    "minMatchConfidenceGate": 0.55,
    "maxMatchConfidenceGate": 1.00,
    "minEnabledMatchConfidence": 0.70,
    "minParseConfidence": 0.60,
}

VALID_MATCH_STATUSES = {"exact_match", "deterministic_match", "fuzzy_match_reviewed"}

_CLAY_DATASET_CACHE: dict[str, Any] = {
    "cacheKey": None,
    "dataset": None,
}


def _safe_num(value: Any) -> float | None:
    try:
        n = float(value)
    except Exception:
        return None
    if n != n:  # NaN guard
        return None
    if n in (float("inf"), float("-inf")):
        return None
    return n


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _parse_date(raw: Any) -> dt.date | None:
    txt = str(raw or "").strip()
    if not txt:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _config_path(root: Path) -> Path:
    env_path = os.getenv("MIKE_CLAY_INTEGRATION_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    return (root / "config" / "mike_clay_integration.json").resolve()


def _default_latest_import_path(data_dir: Path) -> Path:
    return (data_dir / "imports" / "mike_clay" / "mike_clay_import_latest.json").resolve()


def _resolve_latest_import_path(data_dir: Path) -> Path:
    env_path = os.getenv("MIKE_CLAY_IMPORT_LATEST_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _default_latest_import_path(data_dir)


def _resolve_season_window(
    *,
    cfg: dict[str, Any],
    guide_year: int | None,
    now_utc: dt.datetime,
) -> dict[str, Any]:
    effective_year = int(guide_year or now_utc.year)
    season_windows = cfg.get("seasonWindowsByYear")
    if not isinstance(season_windows, dict):
        season_windows = {}

    year_key = str(effective_year)
    raw_window = season_windows.get(year_key)
    if raw_window is None:
        raw_window = season_windows.get(effective_year)  # tolerate non-string keys

    errors: list[str] = []
    configured = isinstance(raw_window, dict)
    window_obj = raw_window if isinstance(raw_window, dict) else {}
    offseason_start = _parse_date(window_obj.get("offseasonStartDate"))
    week1_start = _parse_date(window_obj.get("week1StartDate"))
    week1_end = _parse_date(window_obj.get("week1EndDate"))

    if not configured:
        errors.append(f"missing seasonWindowsByYear[{year_key}]")
    if offseason_start is None:
        errors.append("offseasonStartDate must be YYYY-MM-DD")
    if week1_start is None:
        errors.append("week1StartDate must be YYYY-MM-DD")
    if week1_end is None:
        errors.append("week1EndDate must be YYYY-MM-DD")
    if offseason_start and week1_start and offseason_start >= week1_start:
        errors.append("offseasonStartDate must be before week1StartDate")
    if week1_start and week1_end and week1_end < week1_start:
        errors.append("week1EndDate must be on/after week1StartDate")

    return {
        "year": effective_year,
        "configured": configured,
        "valid": len(errors) == 0,
        "errors": errors,
        "offseasonStartDate": str(offseason_start) if offseason_start else "",
        "week1StartDate": str(week1_start) if week1_start else "",
        "week1EndDate": str(week1_end) if week1_end else "",
        "offseasonStart": offseason_start,
        "week1Start": week1_start,
        "week1End": week1_end,
    }


def _resolve_phase_and_weight(*, cfg: dict[str, Any], guide_year: int | None, now_utc: dt.datetime) -> tuple[str, float, dict[str, Any]]:
    override_phase = str(os.getenv("MIKE_CLAY_FORCE_PHASE", "")).strip().lower()
    override_weight_raw = os.getenv("MIKE_CLAY_FORCE_WEIGHT", "").strip()

    window = _resolve_season_window(cfg=cfg, guide_year=guide_year, now_utc=now_utc)
    effective_year = int(window.get("year") or now_utc.year)
    weights = cfg.get("weights", {})
    offseason_weight = float(_safe_num(weights.get("offseason")) or 0.0)
    week1_weight = float(_safe_num(weights.get("week1")) or 0.0)
    post_initial = float(_safe_num(weights.get("postWeek1Initial")) or 0.0)

    offseason_start = window.get("offseasonStart")
    week1_start = window.get("week1Start")
    week1_end = window.get("week1End")

    cutover_window: dict[str, Any] = {
        "policy": "explicit_yearly_window",
        "source": "config.seasonWindowsByYear",
        "guideYear": effective_year,
        "configured": bool(window.get("configured")),
        "valid": bool(window.get("valid")),
        "errors": list(window.get("errors") or []),
        "offseasonStartDate": str(window.get("offseasonStartDate") or ""),
        "week1StartDate": str(window.get("week1StartDate") or ""),
        "week1EndDate": str(window.get("week1EndDate") or ""),
        "activeWindowStartDate": str(window.get("offseasonStartDate") or ""),
        "activeWindowEndDateExclusive": str(window.get("week1StartDate") or ""),
    }

    now_date = now_utc.date()

    if override_phase:
        forced_phase = override_phase
        if override_weight_raw:
            forced_weight = float(_safe_num(override_weight_raw) or 0.0)
        elif forced_phase == "offseason":
            forced_weight = offseason_weight
        elif forced_phase == "week1":
            forced_weight = week1_weight
        elif forced_phase in {"post_week1_decay", "postweek1", "post-week1"}:
            forced_weight = post_initial
        else:
            forced_weight = 0.0
        cutover_window["overrideApplied"] = True
        return (forced_phase, max(0.0, forced_weight), cutover_window)

    if not bool(window.get("valid")) or not offseason_start or not week1_start or not week1_end:
        return ("season_window_invalid", 0.0, cutover_window)

    if now_date < offseason_start:
        phase = "pre_offseason"
        weight = 0.0
    elif now_date < week1_start:
        phase = "offseason"
        weight = offseason_weight
    elif now_date <= week1_end:
        phase = "week1_inactive"
        weight = 0.0
    else:
        phase = "in_season_inactive"
        weight = 0.0

    if override_weight_raw:
        weight = float(_safe_num(override_weight_raw) or 0.0)

    return (phase, max(0.0, weight), cutover_window)


def _cache_key(latest_path: Path, normalized_path: Path) -> str:
    latest_mtime = latest_path.stat().st_mtime if latest_path.exists() else 0
    norm_mtime = normalized_path.stat().st_mtime if normalized_path.exists() else 0
    return f"{latest_path}::{latest_mtime}::{normalized_path}::{norm_mtime}"


def _row_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    status = str(row.get("match_status") or "")
    status_rank = {"exact_match": 3.0, "deterministic_match": 2.0, "fuzzy_match_reviewed": 1.0}.get(status, 0.0)
    match_conf = float(_safe_num(row.get("match_confidence")) or 0.0)
    starter = 1.0 if row.get("starter_projected") else 0.0
    projected_points = float(_safe_num(row.get("projected_points")) or 0.0)
    return (status_rank, match_conf, starter, projected_points)


def _build_metric_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[float]]:
    index: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        pos = str(row.get("position_canonical") or "").upper()
        if not pos:
            continue
        metrics = {
            "projected_points": _safe_num(row.get("projected_points")),
            "projected_games": _safe_num(row.get("projected_games")),
            "passing_attempts": _safe_num(row.get("passing_attempts")),
            "rushing_attempts": _safe_num(row.get("rushing_attempts")),
            "targets": _safe_num(row.get("targets")),
            "passing_tds": _safe_num(row.get("passing_tds")),
            "rushing_tds": _safe_num(row.get("rushing_tds")),
            "receiving_tds": _safe_num(row.get("receiving_tds")),
            "idp_snaps": _safe_num(row.get("idp_snaps")),
            "idp_total_tackles": _safe_num(row.get("idp_total_tackles")),
            "idp_sacks": _safe_num(row.get("idp_sacks")),
            "idp_interceptions": _safe_num(row.get("idp_interceptions")),
            "idp_forced_fumbles": _safe_num(row.get("idp_forced_fumbles")),
            "idp_tfl": _safe_num(row.get("idp_tfl")),
        }
        for metric_key, value in metrics.items():
            if value is None:
                continue
            index[(pos, metric_key)].append(float(value))
    for key in list(index.keys()):
        index[key].sort()
    return dict(index)


def _build_dataset(latest_payload: dict[str, Any]) -> dict[str, Any]:
    normalized_path_raw = str(latest_payload.get("normalized_players_path") or "").strip()
    normalized_path = Path(normalized_path_raw).resolve() if normalized_path_raw else Path("")
    rows_payload = _load_json(normalized_path, default=[])
    rows = [r for r in rows_payload if isinstance(r, dict)]

    eligible_rows = [
        r
        for r in rows
        if str(r.get("match_status") or "") in VALID_MATCH_STATUSES
        and float(_safe_num(r.get("match_confidence")) or 0.0) >= 0.70
        and float(_safe_num(r.get("parse_confidence")) or 0.0) >= 0.60
    ]

    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        canonical_id = str(row.get("canonical_player_id") or "").strip()
        if canonical_id:
            by_id[canonical_id].append(row)
        for name_key in (row.get("player_name_canonical"), row.get("player_name_source")):
            norm = normalize_player_name(str(name_key or ""))
            if norm:
                by_name[norm].append(row)

    for mapping in (by_id, by_name):
        for key, candidate_rows in mapping.items():
            candidate_rows.sort(key=_row_sort_key, reverse=True)

    metric_index = _build_metric_index(eligible_rows)
    return {
        "latestPayload": latest_payload,
        "normalizedPath": str(normalized_path) if normalized_path else "",
        "rows": rows,
        "eligibleRows": eligible_rows,
        "byCanonicalId": dict(by_id),
        "byName": dict(by_name),
        "metricIndex": metric_index,
    }


def _load_dataset_cached(latest_path: Path) -> dict[str, Any]:
    latest_payload = _load_json(latest_path, default={})
    if not isinstance(latest_payload, dict):
        return {"status": "missing"}
    normalized_path_raw = str(latest_payload.get("normalized_players_path") or "").strip()
    if not normalized_path_raw:
        return {"status": "missing"}
    normalized_path = Path(normalized_path_raw).resolve()
    if not normalized_path.exists():
        return {"status": "missing"}

    key = _cache_key(latest_path, normalized_path)
    if _CLAY_DATASET_CACHE.get("cacheKey") == key and isinstance(_CLAY_DATASET_CACHE.get("dataset"), dict):
        return _CLAY_DATASET_CACHE["dataset"]

    dataset = _build_dataset(latest_payload)
    dataset["status"] = "ok"
    dataset["cacheKey"] = key
    _CLAY_DATASET_CACHE["cacheKey"] = key
    _CLAY_DATASET_CACHE["dataset"] = dataset
    return dataset


def _percentile(metric_index: dict[tuple[str, str], list[float]], pos: str, metric: str, value: float | None) -> float:
    if value is None:
        return 0.5
    values = metric_index.get((pos, metric))
    if not values:
        return 0.5
    rank = bisect.bisect_right(values, float(value))
    return _clamp(rank / max(1, len(values)), 0.0, 1.0)


def _resolve_clay_row(
    dataset: dict[str, Any],
    *,
    canonical_name: str,
    player_id: str,
    position: str,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    if player_id:
        canonical_id = f"sleeper:{player_id}"
        candidates.extend(dataset.get("byCanonicalId", {}).get(canonical_id, []))
    if not candidates:
        norm_name = normalize_player_name(canonical_name)
        if norm_name:
            candidates.extend(dataset.get("byName", {}).get(norm_name, []))
    if not candidates:
        return None

    pos_upper = str(position or "").upper()
    if pos_upper:
        pos_filtered = [r for r in candidates if str(r.get("position_canonical") or "").upper() == pos_upper]
        if pos_filtered:
            candidates = pos_filtered

    candidates = sorted(candidates, key=_row_sort_key, reverse=True)
    return candidates[0] if candidates else None


def _team_environment_score(row: dict[str, Any], pos: str) -> float:
    wins = _safe_num(row.get("team_projected_wins"))
    wins_score = _clamp((float(wins) - 3.0) / 10.0, 0.0, 1.0) if wins is not None else 0.5

    if pos in {"QB", "RB", "WR", "TE"}:
        grade = _safe_num(row.get("team_position_grade"))
        if grade is None:
            grade = _safe_num(row.get("team_offense_grade"))
        rank = _safe_num(row.get("team_offense_rank"))
    else:
        grade = _safe_num(row.get("team_position_grade"))
        if grade is None:
            grade = _safe_num(row.get("team_defense_grade"))
        rank = _safe_num(row.get("team_defense_rank"))

    grade_score = _clamp((float(grade) - 2.0) / 8.0, 0.0, 1.0) if grade is not None else 0.5
    rank_score = _clamp((33.0 - float(rank)) / 32.0, 0.0, 1.0) if rank is not None else 0.5
    return _clamp((0.45 * wins_score) + (0.35 * grade_score) + (0.20 * rank_score), 0.0, 1.0)


def _schedule_score(row: dict[str, Any]) -> float:
    schedule_rank = _safe_num(row.get("team_strength_of_schedule_rank"))
    if schedule_rank is None:
        return 0.5
    return _clamp((33.0 - float(schedule_rank)) / 32.0, 0.0, 1.0)


def _role_certainty_score(row: dict[str, Any]) -> float:
    starter = bool(row.get("starter_projected"))
    starter_base = 1.0 if starter else 0.78
    match_conf = _clamp(float(_safe_num(row.get("match_confidence")) or 0.70), 0.50, 1.00)
    status = str(row.get("match_status") or "")
    status_boost = {"exact_match": 1.00, "deterministic_match": 0.97, "fuzzy_match_reviewed": 0.88}.get(status, 0.70)
    return _clamp(starter_base * match_conf * status_boost, 0.0, 1.0)


def _durability_score(row: dict[str, Any], metric_index: dict[tuple[str, str], list[float]], pos: str) -> float:
    games = _safe_num(row.get("projected_games"))
    if games is not None:
        return _clamp((float(games) - 8.0) / 9.0, 0.0, 1.0)
    if pos in {"DL", "LB", "DB"}:
        snaps = _safe_num(row.get("idp_snaps"))
        if snaps is not None:
            return _percentile(metric_index, pos, "idp_snaps", snaps)
    return 0.72


def _offense_signals(row: dict[str, Any], metric_index: dict[tuple[str, str], list[float]], pos: str) -> dict[str, float]:
    projected_points = _safe_num(row.get("projected_points"))
    production = _percentile(metric_index, pos, "projected_points", projected_points)

    pass_att = _safe_num(row.get("passing_attempts")) or 0.0
    rush_att = _safe_num(row.get("rushing_attempts")) or 0.0
    targets = _safe_num(row.get("targets")) or 0.0
    if pos == "QB":
        opportunity_val = pass_att + (0.70 * rush_att)
    elif pos == "RB":
        opportunity_val = rush_att + (0.80 * targets)
    else:
        opportunity_val = targets + (0.35 * rush_att)

    td_val = (
        (_safe_num(row.get("passing_tds")) or 0.0)
        + (_safe_num(row.get("rushing_tds")) or 0.0)
        + (_safe_num(row.get("receiving_tds")) or 0.0)
    )
    opportunity = _percentile(metric_index, pos, "targets", opportunity_val)
    touchdowns = _percentile(metric_index, pos, "receiving_tds", td_val)
    durability = _durability_score(row, metric_index, pos)
    team_env = _team_environment_score(row, pos)
    schedule = _schedule_score(row)
    role_certainty = _role_certainty_score(row)
    starter_conf = 1.0 if row.get("starter_projected") else 0.0

    overall = (
        (0.34 * production)
        + (0.18 * opportunity)
        + (0.14 * durability)
        + (0.12 * touchdowns)
        + (0.10 * team_env)
        + (0.06 * schedule)
        + (0.06 * role_certainty)
    )
    return {
        "projectedProductionScore": round(production, 6),
        "workloadOpportunityScore": round(opportunity, 6),
        "durabilityGamesScore": round(durability, 6),
        "touchdownExpectationScore": round(touchdowns, 6),
        "teamEnvironmentScore": round(team_env, 6),
        "scheduleScore": round(schedule, 6),
        "roleCertaintyScore": round(role_certainty, 6),
        "starterConfidenceScore": round(starter_conf, 6),
        "idpProductionScore": 0.0,
        "idpOpportunityScore": 0.0,
        "overallSignal": round(_clamp(overall, 0.0, 1.0), 6),
    }


def _idp_signals(row: dict[str, Any], metric_index: dict[tuple[str, str], list[float]], pos: str) -> dict[str, float]:
    projected_points = _safe_num(row.get("projected_points"))
    points_score = _percentile(metric_index, pos, "projected_points", projected_points)
    tackles_score = _percentile(metric_index, pos, "idp_total_tackles", _safe_num(row.get("idp_total_tackles")))
    splash_raw = (
        (2.0 * (_safe_num(row.get("idp_sacks")) or 0.0))
        + (3.0 * (_safe_num(row.get("idp_interceptions")) or 0.0))
        + (2.0 * (_safe_num(row.get("idp_forced_fumbles")) or 0.0))
        + (0.30 * (_safe_num(row.get("idp_tfl")) or 0.0))
    )
    splash_score = _percentile(metric_index, pos, "idp_sacks", splash_raw)
    snaps_score = _percentile(metric_index, pos, "idp_snaps", _safe_num(row.get("idp_snaps")))
    durability = _durability_score(row, metric_index, pos)
    team_env = _team_environment_score(row, pos)
    schedule = _schedule_score(row)
    role_certainty = _role_certainty_score(row)
    starter_conf = 1.0 if row.get("starter_projected") else 0.0

    idp_production = _clamp((0.52 * points_score) + (0.28 * tackles_score) + (0.20 * splash_score), 0.0, 1.0)
    idp_opportunity = _clamp((0.62 * snaps_score) + (0.38 * tackles_score), 0.0, 1.0)
    overall = (
        (0.36 * idp_production)
        + (0.26 * idp_opportunity)
        + (0.16 * durability)
        + (0.10 * team_env)
        + (0.06 * schedule)
        + (0.06 * role_certainty)
    )
    return {
        "projectedProductionScore": round(points_score, 6),
        "workloadOpportunityScore": round(idp_opportunity, 6),
        "durabilityGamesScore": round(durability, 6),
        "touchdownExpectationScore": 0.0,
        "teamEnvironmentScore": round(team_env, 6),
        "scheduleScore": round(schedule, 6),
        "roleCertaintyScore": round(role_certainty, 6),
        "starterConfidenceScore": round(starter_conf, 6),
        "idpProductionScore": round(idp_production, 6),
        "idpOpportunityScore": round(idp_opportunity, 6),
        "overallSignal": round(_clamp(overall, 0.0, 1.0), 6),
    }


def _resolve_signals(row: dict[str, Any], metric_index: dict[tuple[str, str], list[float]], pos: str) -> dict[str, float]:
    if pos in {"DL", "LB", "DB"}:
        return _idp_signals(row, metric_index, pos)
    return _offense_signals(row, metric_index, pos)


def get_mike_clay_runtime_context(*, now_utc: dt.datetime | None = None) -> dict[str, Any]:
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    root = repo_root()
    data_dir = canonical_data_dir(root)

    cfg_path = _config_path(root)
    cfg_file = _load_json(cfg_path, default={})
    cfg = _deep_merge(DEFAULT_CLAY_CONFIG, cfg_file if isinstance(cfg_file, dict) else {})
    cfg["enabled"] = _env_bool("MIKE_CLAY_ENABLED", bool(cfg.get("enabled", True)))

    latest_path = _resolve_latest_import_path(data_dir)
    dataset = _load_dataset_cached(latest_path) if cfg.get("enabled") else {"status": "disabled"}
    latest_payload = dataset.get("latestPayload") if isinstance(dataset, dict) else {}
    if not isinstance(latest_payload, dict):
        latest_payload = {}
    counts = latest_payload.get("counts") if isinstance(latest_payload.get("counts"), dict) else {}
    guide_year = int(_safe_num(latest_payload.get("guide_year")) or 0) or None
    phase, phase_weight, cutover_window = _resolve_phase_and_weight(cfg=cfg, guide_year=guide_year, now_utc=now)

    has_dataset = isinstance(dataset, dict) and dataset.get("status") == "ok"
    ready_flag = bool(latest_payload.get("ready_for_formula_integration")) if isinstance(latest_payload, dict) else False
    import_data_ready = bool(has_dataset and ready_flag)
    enabled = bool(cfg.get("enabled"))
    cutover_valid = bool((cutover_window or {}).get("valid"))
    seasonal_gating_active = bool(cutover_valid and phase == "offseason" and phase_weight > 0.0)
    active = bool(enabled and import_data_ready and seasonal_gating_active)

    if not enabled:
        seasonal_reason = "disabled"
    elif not has_dataset:
        seasonal_reason = "dataset_missing"
    elif not ready_flag:
        seasonal_reason = "import_not_ready"
    elif not cutover_valid:
        seasonal_reason = "season_window_invalid"
    elif phase != "offseason":
        seasonal_reason = f"outside_active_window:{phase}"
    elif phase_weight <= 0.0:
        seasonal_reason = "offseason_weight_zero"
    else:
        seasonal_reason = "active"

    return {
        "config": cfg,
        "configPath": str(cfg_path),
        "latestImportPath": str(latest_path),
        "datasetLoaded": bool(has_dataset),
        "datasetStatus": str(dataset.get("status") or "missing") if isinstance(dataset, dict) else "missing",
        "dataset": dataset if has_dataset else None,
        "enabled": enabled,
        "active": active,
        "seasonPhase": phase,
        "phaseWeight": round(float(phase_weight), 6),
        "seasonalGatingActive": seasonal_gating_active,
        "seasonalGatingConfigured": cutover_valid,
        "seasonalGatingReason": seasonal_reason,
        "seasonalGatingErrors": list((cutover_window or {}).get("errors") or []),
        "cutoverWindow": cutover_window,
        "importDataReady": import_data_ready,
        "guideYear": latest_payload.get("guide_year"),
        "guideVersion": latest_payload.get("guide_version"),
        "importTimestamp": latest_payload.get("import_timestamp"),
        "runId": latest_payload.get("run_id"),
        "unresolvedCount": int((counts or {}).get("unmatched_count") or 0),
        "ambiguousCount": int((counts or {}).get("ambiguous_count") or 0),
        "lowConfidenceCount": int((counts or {}).get("low_confidence_count") or 0),
        "matchRate": float(_safe_num((latest_payload.get("rates") or {}).get("match_rate")) or 0.0),
        "readyForFormulaIntegration": ready_flag,
        "status": str(latest_payload.get("status") or ("ready" if has_dataset else "missing")),
        "readinessReasons": list(latest_payload.get("readiness_reasons") or []),
        "lastValidationRun": now.isoformat(),
    }


def apply_mike_clay_overlay(
    *,
    runtime: dict[str, Any] | None,
    canonical_name: str,
    player_id: str | None,
    pos: str,
    base_value: int,
    source_count: int,
) -> tuple[int, dict[str, Any]]:
    base = int(max(1, base_value))
    default_layer = {
        "active": bool(runtime.get("active")) if isinstance(runtime, dict) else False,
        "seasonPhase": str(runtime.get("seasonPhase") or "unknown") if isinstance(runtime, dict) else "unknown",
        "weightUsed": float(runtime.get("phaseWeight") or 0.0) if isinstance(runtime, dict) else 0.0,
        "guideYear": runtime.get("guideYear") if isinstance(runtime, dict) else None,
        "guideVersion": runtime.get("guideVersion") if isinstance(runtime, dict) else None,
        "importTimestamp": runtime.get("importTimestamp") if isinstance(runtime, dict) else None,
        "baseValue": base,
        "value": base,
        "deltaFromBase": 0,
        "deltaPctFromBase": 0.0,
        "source": "offseason_clay_inactive",
        "applied": False,
        "excludedReason": "inactive",
        "signals": {},
        "supportTier": "none",
    }
    if not isinstance(runtime, dict) or not runtime.get("active"):
        return base, default_layer
    if pos not in {"QB", "RB", "WR", "TE", "DL", "LB", "DB"}:
        layer = deepcopy(default_layer)
        layer["source"] = "offseason_clay_non_player_asset"
        layer["excludedReason"] = "unsupported_position"
        return base, layer

    dataset = runtime.get("dataset") or {}
    if not isinstance(dataset, dict):
        layer = deepcopy(default_layer)
        layer["source"] = "offseason_clay_dataset_missing"
        layer["excludedReason"] = "dataset_missing"
        return base, layer

    row = _resolve_clay_row(
        dataset,
        canonical_name=canonical_name,
        player_id=str(player_id or "").strip(),
        position=pos,
    )
    if not row:
        layer = deepcopy(default_layer)
        layer["source"] = "offseason_clay_no_match"
        layer["excludedReason"] = "no_canonical_match"
        return base, layer

    cfg = runtime.get("config") or DEFAULT_CLAY_CONFIG
    status = str(row.get("match_status") or "")
    match_conf = float(_safe_num(row.get("match_confidence")) or 0.0)
    parse_conf = float(_safe_num(row.get("parse_confidence")) or 0.0)
    if status not in VALID_MATCH_STATUSES:
        layer = deepcopy(default_layer)
        layer["source"] = "offseason_clay_excluded_status"
        layer["excludedReason"] = "status_not_supported"
        layer["matchStatus"] = status
        return base, layer
    if match_conf < float(_safe_num(cfg.get("minEnabledMatchConfidence")) or 0.70):
        layer = deepcopy(default_layer)
        layer["source"] = "offseason_clay_low_match_confidence"
        layer["excludedReason"] = "low_match_confidence"
        layer["matchStatus"] = status
        layer["matchConfidence"] = match_conf
        return base, layer
    if parse_conf < float(_safe_num(cfg.get("minParseConfidence")) or 0.60):
        layer = deepcopy(default_layer)
        layer["source"] = "offseason_clay_low_parse_confidence"
        layer["excludedReason"] = "low_parse_confidence"
        layer["parseConfidence"] = parse_conf
        return base, layer

    metric_index = dataset.get("metricIndex") or {}
    signals = _resolve_signals(row, metric_index, pos)

    pos_influence = float(_safe_num((cfg.get("positionInfluence") or {}).get(pos)) or 0.9)
    baseline = float(_safe_num((cfg.get("positionSignalBaseline") or {}).get(pos)) or 0.52)
    phase_weight = float(_safe_num(runtime.get("phaseWeight")) or 0.0)
    status_mult = float(_safe_num((cfg.get("statusMultiplier") or {}).get(status)) or 0.85)
    min_conf_gate = float(_safe_num(cfg.get("minMatchConfidenceGate")) or 0.55)
    max_conf_gate = float(_safe_num(cfg.get("maxMatchConfidenceGate")) or 1.00)
    confidence_gate = _clamp(match_conf, min_conf_gate, max_conf_gate)
    source_gate_divisor = float(_safe_num(cfg.get("sourceGateDivisor")) or 5.0)
    min_source_gate = float(_safe_num(cfg.get("minSourceGate")) or 0.35)
    source_gate = _clamp(float(source_count) / max(1.0, source_gate_divisor), min_source_gate, 1.0)
    durability_score = float(signals.get("durabilityGamesScore") or 0.5)
    role_score = float(signals.get("roleCertaintyScore") or 0.5)
    durability_gate = _clamp(0.55 + (0.45 * durability_score), 0.45, 1.0)
    role_gate = _clamp(0.65 + (0.35 * role_score), 0.55, 1.0)

    centered_signal = float(signals.get("overallSignal") or 0.5) - baseline
    raw_delta_pct = centered_signal * 0.30 * pos_influence

    projected_games = _safe_num(row.get("projected_games"))
    low_games_penalty = 0.0
    if projected_games is not None and projected_games < 12.0:
        low_games_penalty = min(0.12, (12.0 - float(projected_games)) * 0.018)

    weighted_delta_pct = (
        raw_delta_pct
        * phase_weight
        * status_mult
        * confidence_gate
        * source_gate
        * durability_gate
        * role_gate
    )
    if low_games_penalty > 0:
        if weighted_delta_pct > 0:
            weighted_delta_pct *= max(0.0, 1.0 - (1.4 * low_games_penalty))
        weighted_delta_pct -= (0.20 * phase_weight * low_games_penalty)

    if not bool(row.get("starter_projected")) and weighted_delta_pct > 0:
        weighted_delta_pct *= 0.85

    cap_pct = float(_safe_num((cfg.get("positionDeltaCapPct") or {}).get(pos)) or 0.10)
    weighted_delta_pct = _clamp(weighted_delta_pct, -cap_pct, cap_pct)

    adjusted_value = int(round(base * (1.0 + weighted_delta_pct)))
    adjusted_value = int(_clamp(adjusted_value, 1, 9999))
    delta_value = int(adjusted_value - base)
    support_tier = (
        "strong"
        if float(signals.get("overallSignal") or 0.0) >= 0.70
        else "weak"
        if float(signals.get("overallSignal") or 0.0) <= 0.40
        else "moderate"
    )
    layer = {
        "active": True,
        "seasonPhase": str(runtime.get("seasonPhase") or ""),
        "weightUsed": round(phase_weight, 6),
        "guideYear": runtime.get("guideYear"),
        "guideVersion": runtime.get("guideVersion"),
        "importTimestamp": runtime.get("importTimestamp"),
        "baseValue": base,
        "value": adjusted_value,
        "deltaFromBase": delta_value,
        "deltaPctFromBase": round(delta_value / max(1, base), 6),
        "source": "offseason_clay_overlay_applied" if delta_value != 0 else "offseason_clay_overlay_neutral",
        "applied": bool(delta_value != 0),
        "excludedReason": "",
        "signals": signals,
        "supportTier": support_tier,
        "matchStatus": status,
        "matchConfidence": round(match_conf, 6),
        "parseConfidence": round(parse_conf, 6),
        "starterProjected": bool(row.get("starter_projected")),
        "starterSlot": row.get("starter_slot"),
        "projectedGames": projected_games,
        "guardrails": {
            "centeredSignal": round(centered_signal, 6),
            "rawDeltaPct": round(raw_delta_pct, 6),
            "weightedDeltaPct": round(weighted_delta_pct, 6),
            "capPct": round(cap_pct, 6),
            "statusMultiplier": round(status_mult, 6),
            "confidenceGate": round(confidence_gate, 6),
            "sourceGate": round(source_gate, 6),
            "durabilityGate": round(durability_gate, 6),
            "roleGate": round(role_gate, 6),
            "lowGamesPenalty": round(low_games_penalty, 6),
            "positionInfluence": round(pos_influence, 6),
            "positionBaseline": round(baseline, 6),
        },
    }
    return adjusted_value, layer
