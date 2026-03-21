from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable


DEFAULT_REQUIRED_SOURCES = [
    "ktc",
    "fantasyCalc",
    "draftSharks",
    "dynastyNerds",
    "idpTradeCalc",
    "dlfSf",
    "dlfIdp",
    "dlfRsf",
    "dlfRidp",
]

DEFAULT_CRITICAL_SOURCES = [
    "dynastyNerds",
    "idpTradeCalc",
]

DEFAULT_SOURCE_MIN_PLAYER_COUNT = {
    "ktc": 300,
    "fantasycalc": 250,
    "draftsharks": 250,
    "yahoo": 250,
    "dynastynerds": 200,
    "idptradecalc": 400,
    "dlfsf": 150,
    "dlfidp": 100,
    "dlfrsf": 40,
    "dlfridp": 20,
}

DEFAULT_MIN_TOP_VALUE_BY_POSITION = {
    "QB": 6000,
    "RB": 4500,
    "WR": 4500,
    "TE": 4000,
    "DL": 3000,
    "LB": 3000,
    "DB": 2200,
}

DEFAULT_MAX_COVERAGE_COLLAPSE_RATIO = 0.45
DEFAULT_MIN_COVERAGE_COLLAPSE_DROP = 20
DEFAULT_DISAGREEMENT_MIN_SOURCES = 3
DEFAULT_MAX_DISAGREEMENT_REL_SPREAD = 1.5
DEFAULT_MIN_DISAGREEMENT_ABS_DELTA = 1800
DEFAULT_MAX_OVERNIGHT_SWING_PCT = 0.35
DEFAULT_MIN_OVERNIGHT_SWING_ABS_DELTA = 900
DEFAULT_POLICY_DISAGREEMENT_DEGRADE_PLAYER_COUNT = 35
DEFAULT_POLICY_DISAGREEMENT_BLOCK_PLAYER_COUNT = 90
DEFAULT_POLICY_DISAGREEMENT_DEGRADE_SOURCE_SPIKE_COUNT = 20
DEFAULT_POLICY_DISAGREEMENT_BLOCK_CRITICAL_SOURCE_SPIKE_COUNT = 55
DEFAULT_POLICY_OVERNIGHT_SWING_DEGRADE_COUNT = 3
DEFAULT_POLICY_OVERNIGHT_SWING_BLOCK_COUNT = 8
DEFAULT_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_DROP_PCT = 75.0
DEFAULT_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_RATIO = 0.30


RegressionRunner = Callable[[Path, "PromotionGateConfig"], dict[str, Any]]


@dataclass(frozen=True)
class PromotionGateConfig:
    required_sources: list[str]
    critical_sources: list[str]
    source_min_player_count: dict[str, int]
    max_payload_age_hours: float
    max_source_age_hours: float
    min_player_count: int
    min_active_sources: int
    min_canonical_site_map_coverage: float
    max_unmatched_rate: float
    max_duplicate_canonical_matches: int
    max_conflicting_positions: int
    max_conflicting_source_identities: int
    required_positions: list[str]
    min_top_value_by_position: dict[str, int]
    max_coverage_collapse_ratio: float
    min_coverage_collapse_drop: int
    disagreement_min_sources: int
    max_disagreement_rel_spread: float
    min_disagreement_abs_delta: int
    max_overnight_swing_pct: float
    min_overnight_swing_abs_delta: int
    policy_disagreement_degrade_player_count: int
    policy_disagreement_block_player_count: int
    policy_disagreement_degrade_source_spike_count: int
    policy_disagreement_block_critical_source_spike_count: int
    policy_overnight_swing_degrade_count: int
    policy_overnight_swing_block_count: int
    policy_critical_coverage_collapse_block_drop_pct: float
    policy_critical_coverage_collapse_block_ratio: float
    policy_waivers: list[dict[str, Any]]
    run_regression_tests: bool
    regression_command: str
    regression_timeout_sec: int


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _split_csv(raw: str | None, default_values: list[str]) -> list[str]:
    if not raw or str(raw).strip() == "":
        return [str(v).strip() for v in default_values if str(v).strip()]
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw).split(","):
        item = part.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _normalize_source_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return "".join(ch for ch in text if ch.isalnum())


def _parse_source_min_counts(raw: str | None) -> dict[str, int]:
    out = dict(DEFAULT_SOURCE_MIN_PLAYER_COUNT)
    if not raw or str(raw).strip() == "":
        return out
    try:
        parsed = json.loads(raw)
    except Exception:
        return out
    if not isinstance(parsed, dict):
        return out
    for key, val in parsed.items():
        try:
            source_key = _normalize_source_key(key)
            if not source_key:
                continue
            out[source_key] = int(val)
        except Exception:
            continue
    return out


def _parse_top_value_thresholds(raw: str | None) -> dict[str, int]:
    out = dict(DEFAULT_MIN_TOP_VALUE_BY_POSITION)
    if not raw or str(raw).strip() == "":
        return out
    try:
        parsed = json.loads(raw)
    except Exception:
        return out
    if not isinstance(parsed, dict):
        return out
    for key, val in parsed.items():
        pos = str(key).strip().upper()
        if not pos:
            continue
        try:
            out[pos] = int(val)
        except Exception:
            continue
    return out


def _parse_policy_waivers(raw: str | None) -> list[dict[str, Any]]:
    if not raw or str(raw).strip() == "":
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("ruleId") or item.get("rule") or "").strip().lower()
        if not rule_id:
            continue
        scope = str(item.get("scope") or "global").strip().lower() or "global"
        out.append(
            {
                "ruleId": rule_id,
                "scope": scope,
                "reason": str(item.get("reason") or "").strip(),
                "ticket": str(item.get("ticket") or "").strip(),
                "expiresAt": str(item.get("expiresAt") or item.get("expires_at") or "").strip(),
            }
        )
    return out


def load_promotion_gate_config() -> PromotionGateConfig:
    required_sources = _split_csv(
        os.getenv("PROMOTION_REQUIRED_SOURCES"),
        DEFAULT_REQUIRED_SOURCES,
    )
    critical_sources = _split_csv(
        os.getenv("PROMOTION_CRITICAL_SOURCES"),
        DEFAULT_CRITICAL_SOURCES,
    )
    required_positions = _split_csv(
        os.getenv("PROMOTION_REQUIRED_POSITIONS"),
        ["QB", "RB", "WR", "TE", "DL", "LB", "DB"],
    )
    # Preserve virtualenv interpreter path exactly as invoked; resolving symlinks
    # can escape the venv and break dependency visibility on runtime hosts.
    python_executable = str(sys.executable or "python")
    default_regression_command = (
        f"\"{python_executable}\" -m unittest "
        "tests.api.test_identity_resolution "
        "tests.api.test_league_route_resilience "
        "tests.api.test_value_pipeline_golden "
        "tests.api.test_promotion_gate -v"
    )

    return PromotionGateConfig(
        required_sources=required_sources,
        critical_sources=critical_sources,
        source_min_player_count=_parse_source_min_counts(os.getenv("PROMOTION_SOURCE_MIN_COUNTS_JSON")),
        max_payload_age_hours=_env_float("PROMOTION_MAX_PAYLOAD_AGE_HOURS", 12.0),
        max_source_age_hours=_env_float("PROMOTION_MAX_SOURCE_AGE_HOURS", 18.0),
        min_player_count=_env_int("PROMOTION_MIN_PLAYER_COUNT", 900),
        min_active_sources=_env_int("PROMOTION_MIN_ACTIVE_SOURCES", 8),
        min_canonical_site_map_coverage=_env_float("PROMOTION_MIN_CANONICAL_SITE_MAP_COVERAGE", 0.85),
        max_unmatched_rate=_env_float("PROMOTION_MAX_UNMATCHED_RATE", 0.03),
        max_duplicate_canonical_matches=_env_int("PROMOTION_MAX_DUPLICATE_CANONICAL_MATCHES", 10),
        max_conflicting_positions=_env_int("PROMOTION_MAX_CONFLICTING_POSITIONS", 3),
        max_conflicting_source_identities=_env_int("PROMOTION_MAX_CONFLICTING_SOURCE_IDENTITIES", 400),
        required_positions=required_positions,
        min_top_value_by_position=_parse_top_value_thresholds(os.getenv("PROMOTION_MIN_TOP_VALUE_BY_POSITION_JSON")),
        max_coverage_collapse_ratio=_env_float(
            "PROMOTION_MAX_COVERAGE_COLLAPSE_RATIO",
            DEFAULT_MAX_COVERAGE_COLLAPSE_RATIO,
        ),
        min_coverage_collapse_drop=_env_int(
            "PROMOTION_MIN_COVERAGE_COLLAPSE_DROP",
            DEFAULT_MIN_COVERAGE_COLLAPSE_DROP,
        ),
        disagreement_min_sources=_env_int(
            "PROMOTION_DISAGREEMENT_MIN_SOURCES",
            DEFAULT_DISAGREEMENT_MIN_SOURCES,
        ),
        max_disagreement_rel_spread=_env_float(
            "PROMOTION_MAX_DISAGREEMENT_REL_SPREAD",
            DEFAULT_MAX_DISAGREEMENT_REL_SPREAD,
        ),
        min_disagreement_abs_delta=_env_int(
            "PROMOTION_MIN_DISAGREEMENT_ABS_DELTA",
            DEFAULT_MIN_DISAGREEMENT_ABS_DELTA,
        ),
        max_overnight_swing_pct=_env_float(
            "PROMOTION_MAX_OVERNIGHT_SWING_PCT",
            DEFAULT_MAX_OVERNIGHT_SWING_PCT,
        ),
        min_overnight_swing_abs_delta=_env_int(
            "PROMOTION_MIN_OVERNIGHT_SWING_ABS_DELTA",
            DEFAULT_MIN_OVERNIGHT_SWING_ABS_DELTA,
        ),
        policy_disagreement_degrade_player_count=_env_int(
            "PROMOTION_POLICY_DISAGREEMENT_DEGRADE_PLAYER_COUNT",
            DEFAULT_POLICY_DISAGREEMENT_DEGRADE_PLAYER_COUNT,
        ),
        policy_disagreement_block_player_count=_env_int(
            "PROMOTION_POLICY_DISAGREEMENT_BLOCK_PLAYER_COUNT",
            DEFAULT_POLICY_DISAGREEMENT_BLOCK_PLAYER_COUNT,
        ),
        policy_disagreement_degrade_source_spike_count=_env_int(
            "PROMOTION_POLICY_DISAGREEMENT_DEGRADE_SOURCE_SPIKE_COUNT",
            DEFAULT_POLICY_DISAGREEMENT_DEGRADE_SOURCE_SPIKE_COUNT,
        ),
        policy_disagreement_block_critical_source_spike_count=_env_int(
            "PROMOTION_POLICY_DISAGREEMENT_BLOCK_CRITICAL_SOURCE_SPIKE_COUNT",
            DEFAULT_POLICY_DISAGREEMENT_BLOCK_CRITICAL_SOURCE_SPIKE_COUNT,
        ),
        policy_overnight_swing_degrade_count=_env_int(
            "PROMOTION_POLICY_OVERNIGHT_SWING_DEGRADE_COUNT",
            DEFAULT_POLICY_OVERNIGHT_SWING_DEGRADE_COUNT,
        ),
        policy_overnight_swing_block_count=_env_int(
            "PROMOTION_POLICY_OVERNIGHT_SWING_BLOCK_COUNT",
            DEFAULT_POLICY_OVERNIGHT_SWING_BLOCK_COUNT,
        ),
        policy_critical_coverage_collapse_block_drop_pct=_env_float(
            "PROMOTION_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_DROP_PCT",
            DEFAULT_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_DROP_PCT,
        ),
        policy_critical_coverage_collapse_block_ratio=_env_float(
            "PROMOTION_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_RATIO",
            DEFAULT_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_RATIO,
        ),
        policy_waivers=_parse_policy_waivers(os.getenv("PROMOTION_POLICY_WAIVERS_JSON")),
        run_regression_tests=_env_bool("PROMOTION_RUN_REGRESSION_TESTS", True),
        regression_command=str(
            os.getenv(
                "PROMOTION_REGRESSION_COMMAND",
                default_regression_command,
            )
        ).strip(),
        regression_timeout_sec=_env_int("PROMOTION_REGRESSION_TIMEOUT_SEC", 420),
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_since(ts: datetime | None, now: datetime) -> float | None:
    if ts is None:
        return None
    delta = now - ts.astimezone(timezone.utc)
    return max(0.0, delta.total_seconds() / 3600.0)


def _site_counts(payload: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    rows = payload.get("sites")
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _normalize_source_key(row.get("key"))
        if not key:
            continue
        try:
            out[key] = int(row.get("playerCount") or 0)
        except Exception:
            out[key] = 0
    return out


def _source_runtime_summary(payload: dict[str, Any]) -> dict[str, Any]:
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    summary = settings.get("sourceRunSummary")
    return summary if isinstance(summary, dict) else {}


def _source_runtime_rows(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = summary.get("sources")
    if not isinstance(rows, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in rows.items():
        if not isinstance(value, dict):
            continue
        src = _normalize_source_key(key)
        if not src:
            continue
        out[src] = value
    return out


def _identity_totals(payload: dict[str, Any]) -> dict[str, Any]:
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    identity = settings.get("identityResolutionDiagnostics")
    if not isinstance(identity, dict):
        return {}
    totals = identity.get("totals")
    return totals if isinstance(totals, dict) else {}


def _to_positive_float(value: Any) -> float | None:
    try:
        n = float(value)
    except Exception:
        return None
    if n <= 0:
        return None
    return n


_POSITION_FAMILY = {
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "CB": "DB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
    "SAF": "DB",
    "ILB": "LB",
    "MLB": "LB",
    "OLB": "LB",
}


def _normalize_position(value: Any) -> str:
    pos = str(value or "").strip().upper()
    if not pos:
        return ""
    return _POSITION_FAMILY.get(pos, pos)


def _row_full_value(row: dict[str, Any]) -> int:
    bundle = row.get("valueBundle") if isinstance(row.get("valueBundle"), dict) else {}
    raw = bundle.get("fullValue") if isinstance(bundle, dict) else None
    if raw is None:
        raw = row.get("fullValue")
    try:
        return int(raw)
    except Exception:
        return 0


def _is_intentional_quarantine_row(row: dict[str, Any], bundle: dict[str, Any]) -> bool:
    guardrails = bundle.get("guardrails") if isinstance(bundle.get("guardrails"), dict) else {}
    final_status = str(guardrails.get("finalAuthorityStatus") or "").strip().lower()
    return bool(
        bool(guardrails.get("quarantined"))
        or bool(row.get("quarantinedFromFinalAuthority"))
        or final_status == "quarantined"
    )


def _site_presence_counts(
    rows: list[dict[str, Any]],
    *,
    required_positions: list[str],
    known_sources: set[str] | None = None,
) -> dict[str, Any]:
    req_positions = [str(p).strip().upper() for p in required_positions if str(p).strip()]
    req_set = set(req_positions)
    offense_positions = {"QB", "RB", "WR", "TE"} & req_set
    idp_positions = {"DL", "LB", "DB"} & req_set

    population_by_position: dict[str, int] = {p: 0 for p in req_positions}
    by_source: dict[str, dict[str, Any]] = {}

    def _ensure_source(source_key: str) -> dict[str, Any]:
        source = _normalize_source_key(source_key)
        row = by_source.get(source)
        if isinstance(row, dict):
            return row
        row = {
            "source": source,
            "totalCoverageRows": 0,
            "offenseCoverageRows": 0,
            "idpCoverageRows": 0,
            "pickCoverageRows": 0,
            "otherCoverageRows": 0,
            "byPosition": {p: 0 for p in req_positions},
            "ratioByPosition": {p: 0.0 for p in req_positions},
        }
        by_source[source] = row
        return row

    if isinstance(known_sources, set):
        for src in known_sources:
            if str(src).strip():
                _ensure_source(src)

    for row in rows:
        if not isinstance(row, dict):
            continue
        pos = _normalize_position(row.get("position"))
        if pos in req_set:
            population_by_position[pos] = int(population_by_position.get(pos, 0) or 0) + 1

        canonical = row.get("canonicalSiteValues")
        if not isinstance(canonical, dict):
            continue
        seen_sources: set[str] = set()
        for site_key, site_val in canonical.items():
            site_num = _to_positive_float(site_val)
            if site_num is None:
                continue
            source = _normalize_source_key(site_key)
            if not source or source in seen_sources:
                continue
            seen_sources.add(source)
            source_row = _ensure_source(source)
            source_row["totalCoverageRows"] = int(source_row.get("totalCoverageRows", 0) or 0) + 1
            if pos in req_set:
                source_row["byPosition"][pos] = int(source_row["byPosition"].get(pos, 0) or 0) + 1
                if pos in offense_positions:
                    source_row["offenseCoverageRows"] = int(source_row.get("offenseCoverageRows", 0) or 0) + 1
                elif pos in idp_positions:
                    source_row["idpCoverageRows"] = int(source_row.get("idpCoverageRows", 0) or 0) + 1
            elif pos == "PICK":
                source_row["pickCoverageRows"] = int(source_row.get("pickCoverageRows", 0) or 0) + 1
            else:
                source_row["otherCoverageRows"] = int(source_row.get("otherCoverageRows", 0) or 0) + 1

    for source_row in by_source.values():
        ratios: dict[str, float] = {}
        by_position = source_row.get("byPosition") if isinstance(source_row.get("byPosition"), dict) else {}
        for pos in req_positions:
            denom = int(population_by_position.get(pos, 0) or 0)
            numer = int(by_position.get(pos, 0) or 0)
            ratios[pos] = round(float(numer) / float(denom), 4) if denom > 0 else 0.0
        source_row["ratioByPosition"] = ratios

    return {
        "populationByPosition": population_by_position,
        "sources": dict(sorted(by_source.items(), key=lambda kv: kv[0])),
    }


def _detect_coverage_collapses(
    *,
    current_coverage: dict[str, Any],
    baseline_coverage: dict[str, Any] | None,
    required_positions: list[str],
    max_ratio: float,
    min_drop: int,
) -> list[dict[str, Any]]:
    if not isinstance(baseline_coverage, dict):
        return []
    current_sources = (
        current_coverage.get("sources")
        if isinstance(current_coverage.get("sources"), dict)
        else {}
    )
    baseline_sources = (
        baseline_coverage.get("sources")
        if isinstance(baseline_coverage.get("sources"), dict)
        else {}
    )
    if not baseline_sources:
        return []

    req_positions = [str(p).strip().upper() for p in required_positions if str(p).strip()]
    issues: list[dict[str, Any]] = []
    collapse_ratio = max(0.0, float(max_ratio))
    collapse_drop = max(1, int(min_drop))

    for source, base_row in baseline_sources.items():
        if not isinstance(base_row, dict):
            continue
        current_row = (
            current_sources.get(source)
            if isinstance(current_sources.get(source), dict)
            else {}
        )
        base_by_pos = base_row.get("byPosition") if isinstance(base_row.get("byPosition"), dict) else {}
        cur_by_pos = current_row.get("byPosition") if isinstance(current_row.get("byPosition"), dict) else {}
        for pos in req_positions:
            baseline_count = int(base_by_pos.get(pos, 0) or 0)
            current_count = int(cur_by_pos.get(pos, 0) or 0)
            if baseline_count <= 0:
                continue
            drop = max(0, baseline_count - current_count)
            ratio = (float(current_count) / float(baseline_count)) if baseline_count > 0 else 1.0
            if drop < collapse_drop:
                continue
            if ratio > collapse_ratio:
                continue
            issues.append(
                {
                    "source": str(source),
                    "position": str(pos),
                    "baselineCount": baseline_count,
                    "currentCount": current_count,
                    "dropCount": drop,
                    "dropPct": round((float(drop) / float(baseline_count)) * 100.0, 2),
                    "currentToBaselineRatio": round(ratio, 4),
                    "maxAllowedRatio": round(collapse_ratio, 4),
                    "minDropCount": collapse_drop,
                }
            )
    return sorted(
        issues,
        key=lambda row: (
            -float(row.get("dropPct", 0.0) or 0.0),
            -int(row.get("dropCount", 0) or 0),
            str(row.get("source") or ""),
            str(row.get("position") or ""),
        ),
    )


def _player_disagreement_metrics(
    rows: list[dict[str, Any]],
    *,
    min_sources: int,
    max_rel_spread: float,
    min_abs_delta: int,
) -> dict[str, Any]:
    min_required_sources = max(2, int(min_sources))
    rel_spread_threshold = max(0.0, float(max_rel_spread))
    abs_delta_threshold = max(1, int(min_abs_delta))

    per_player: list[dict[str, Any]] = []
    extremes: list[dict[str, Any]] = []
    source_extreme_participation: dict[str, int] = {}
    calc_rows: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        canonical = row.get("canonicalSiteValues")
        if not isinstance(canonical, dict):
            continue

        source_values: dict[str, float] = {}
        for source_key, source_value in canonical.items():
            site_num = _to_positive_float(source_value)
            if site_num is None:
                continue
            source = _normalize_source_key(source_key)
            if not source:
                continue
            source_values[source] = float(site_num)

        if len(source_values) < 2:
            continue

        sorted_vals = sorted(source_values.values())
        min_val = float(sorted_vals[0])
        max_val = float(sorted_vals[-1])
        val_count = len(sorted_vals)
        mid = val_count // 2
        if val_count % 2:
            median_val = float(sorted_vals[mid])
        else:
            median_val = float((sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0)
        abs_delta = float(max_val - min_val)
        rel_spread = float(abs_delta / median_val) if median_val > 0 else None
        spread_ratio = float(max_val / min_val) if min_val > 0 else None

        metric_row = {
            "name": str(row.get("canonicalName") or ""),
            "position": _normalize_position(row.get("position")),
            "sourceCount": val_count,
            "minValue": int(round(min_val)),
            "maxValue": int(round(max_val)),
            "medianValue": int(round(median_val)),
            "maxAbsDelta": int(round(abs_delta)),
            "relativeSpread": round(rel_spread, 4) if rel_spread is not None else None,
            "relativeSpreadPct": round((rel_spread or 0.0) * 100.0, 2) if rel_spread is not None else None,
            "spreadRatio": round(spread_ratio, 4) if spread_ratio is not None else None,
        }
        per_player.append(metric_row)
        calc_rows.append(
            {
                "metric": metric_row,
                "sourceValuesFloat": source_values,
                "minValueFloat": min_val,
                "maxValueFloat": max_val,
                "sourceCount": val_count,
                "relativeSpread": rel_spread,
                "absDelta": abs_delta,
            }
        )

    rel_spread_population = [
        float(row.get("relativeSpread"))
        for row in calc_rows
        if int(row.get("sourceCount") or 0) >= min_required_sources
        and isinstance(row.get("relativeSpread"), (int, float))
    ]
    dynamic_rel_threshold = rel_spread_threshold
    if rel_spread_population:
        rel_sorted = sorted(rel_spread_population)
        mid = len(rel_sorted) // 2
        if len(rel_sorted) % 2:
            rel_median = float(rel_sorted[mid])
        else:
            rel_median = float((rel_sorted[mid - 1] + rel_sorted[mid]) / 2.0)
        abs_devs = sorted(abs(v - rel_median) for v in rel_sorted)
        if abs_devs:
            mid_dev = len(abs_devs) // 2
            if len(abs_devs) % 2:
                mad = float(abs_devs[mid_dev])
            else:
                mad = float((abs_devs[mid_dev - 1] + abs_devs[mid_dev]) / 2.0)
            robust_sigma = float(mad * 1.4826)
            dynamic_rel_threshold = max(rel_spread_threshold, rel_median + (3.0 * robust_sigma))

    for row in calc_rows:
        rel_spread = row.get("relativeSpread")
        abs_delta = float(row.get("absDelta") or 0.0)
        source_count = int(row.get("sourceCount") or 0)
        if not isinstance(rel_spread, (int, float)):
            continue
        if source_count < min_required_sources:
            continue
        if float(rel_spread) < float(dynamic_rel_threshold):
            continue
        if abs_delta < float(abs_delta_threshold):
            continue

        metric_row = row.get("metric") if isinstance(row.get("metric"), dict) else {}
        source_values = (
            row.get("sourceValuesFloat")
            if isinstance(row.get("sourceValuesFloat"), dict)
            else {}
        )
        max_val = float(row.get("maxValueFloat") or 0.0)
        min_val = float(row.get("minValueFloat") or 0.0)
        max_sources = sorted([k for k, v in source_values.items() if abs(float(v) - max_val) < 1e-9])
        min_sources_list = sorted([k for k, v in source_values.items() if abs(float(v) - min_val) < 1e-9])
        for source in set(max_sources + min_sources_list):
            source_extreme_participation[source] = int(source_extreme_participation.get(source, 0) or 0) + 1
        extremes.append(
            {
                **metric_row,
                "maxSources": max_sources,
                "minSources": min_sources_list,
                "sourceValues": {
                    k: int(round(float(v)))
                    for k, v in sorted(source_values.items(), key=lambda kv: kv[0])
                },
            }
        )

    per_player.sort(
        key=lambda row: (
            -(float(row.get("relativeSpread", 0.0) or 0.0)),
            -(int(row.get("maxAbsDelta", 0) or 0)),
            str(row.get("name") or ""),
        )
    )
    extremes.sort(
        key=lambda row: (
            -(float(row.get("relativeSpread", 0.0) or 0.0)),
            -(int(row.get("maxAbsDelta", 0) or 0)),
            str(row.get("name") or ""),
        )
    )

    return {
        "evaluatedPlayerCount": len(per_player),
        "minSourceCountThreshold": min_required_sources,
        "configuredMaxRelativeSpreadThreshold": round(rel_spread_threshold, 4),
        "effectiveMaxRelativeSpreadThreshold": round(dynamic_rel_threshold, 4),
        "minAbsoluteDeltaThreshold": abs_delta_threshold,
        "players": per_player,
        "extremePlayers": extremes,
        "sourceExtremeParticipation": dict(
            sorted(source_extreme_participation.items(), key=lambda kv: (-int(kv[1]), kv[0]))
        ),
    }


def _overnight_swing_flags(
    current_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    *,
    max_pct: float,
    min_abs_delta: int,
) -> list[dict[str, Any]]:
    pct_threshold = max(0.0, float(max_pct))
    abs_threshold = max(1, int(min_abs_delta))
    baseline_by_name: dict[str, dict[str, Any]] = {}
    for row in baseline_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("canonicalName") or "").strip()
        if not name:
            continue
        baseline_by_name[name] = row

    flags: list[dict[str, Any]] = []
    for row in current_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("canonicalName") or "").strip()
        if not name:
            continue
        prev_row = baseline_by_name.get(name)
        if not isinstance(prev_row, dict):
            continue

        current_full = _row_full_value(row)
        baseline_full = _row_full_value(prev_row)
        if current_full <= 0 or baseline_full <= 0:
            continue

        delta = int(current_full - baseline_full)
        abs_delta = abs(delta)
        pct_move = float(abs_delta) / float(max(1, baseline_full))
        if abs_delta < abs_threshold or pct_move < pct_threshold:
            continue
        flags.append(
            {
                "name": name,
                "position": _normalize_position(row.get("position")),
                "baselineFullValue": baseline_full,
                "currentFullValue": current_full,
                "delta": delta,
                "absDelta": abs_delta,
                "pctMove": round(pct_move, 4),
                "pctMoveDisplay": round(pct_move * 100.0, 2),
            }
        )

    return sorted(
        flags,
        key=lambda row: (
            -(float(row.get("pctMove", 0.0) or 0.0)),
            -(int(row.get("absDelta", 0) or 0)),
            str(row.get("name") or ""),
        ),
    )


def _recommend_source_handling(
    *,
    source_freshness_rows: list[dict[str, Any]],
    required_missing: list[str],
    required_below_min: list[dict[str, Any]],
    coverage_collapses: list[dict[str, Any]],
    disagreement_participation: dict[str, int],
    critical_sources: set[str],
) -> list[dict[str, Any]]:
    below_min_sources = {
        _normalize_source_key(row.get("source"))
        for row in required_below_min
        if isinstance(row, dict) and _normalize_source_key(row.get("source"))
    }
    missing_sources = {_normalize_source_key(v) for v in required_missing if _normalize_source_key(v)}

    collapse_by_source: dict[str, list[dict[str, Any]]] = {}
    for issue in coverage_collapses:
        if not isinstance(issue, dict):
            continue
        source = _normalize_source_key(issue.get("source"))
        if not source:
            continue
        collapse_by_source.setdefault(source, []).append(issue)

    recommendations: list[dict[str, Any]] = []
    for row in source_freshness_rows:
        if not isinstance(row, dict):
            continue
        source = _normalize_source_key(row.get("source"))
        if not source:
            continue
        status = str(row.get("status") or "").strip().lower()
        reasons: list[str] = []
        action = "keep"
        multiplier = 1.0

        if source in missing_sources or status in {"missing", "failed", "timed_out"}:
            action = "skip"
            multiplier = 0.0
            reasons.append("source_missing_or_unavailable")
        elif status in {"stale", "missing_timestamp"}:
            action = "downweight"
            multiplier = min(multiplier, 0.5)
            reasons.append("source_stale")
        elif status == "partial":
            action = "downweight"
            multiplier = min(multiplier, 0.7)
            reasons.append("source_partial")

        if source in below_min_sources:
            if action == "keep":
                action = "downweight"
                multiplier = min(multiplier, 0.65)
            reasons.append("below_min_required_count")

        collapse_rows = collapse_by_source.get(source, [])
        if collapse_rows:
            max_drop_pct = max(float(i.get("dropPct", 0.0) or 0.0) for i in collapse_rows)
            if action != "skip":
                if len(collapse_rows) >= 2 or max_drop_pct >= 80.0:
                    action = "downweight"
                    multiplier = min(multiplier, 0.35)
                else:
                    action = "downweight"
                    multiplier = min(multiplier, 0.6)
            reasons.append("position_coverage_collapse")

        disagreement_hits = int(disagreement_participation.get(source, 0) or 0)
        if disagreement_hits >= 10 and action == "keep":
            action = "downweight"
            multiplier = min(multiplier, 0.8)
            reasons.append("extreme_disagreement_participation")

        if source in critical_sources and action == "downweight" and status in {"stale", "partial"}:
            multiplier = min(multiplier, 0.5)

        recommendations.append(
            {
                "source": source,
                "critical": source in critical_sources,
                "status": status,
                "recommendedAction": action,
                "weightMultiplier": round(multiplier, 2),
                "reasons": sorted(set(reasons)),
                "signals": {
                    "belowMinCount": source in below_min_sources,
                    "missing": source in missing_sources,
                    "coverageCollapseCount": len(collapse_rows),
                    "disagreementSpikeCount": disagreement_hits,
                },
            }
        )

    recommendations.sort(key=lambda row: (str(row.get("source") or "")))
    return recommendations


def _issue_scope(*, source: str | None = None, position: str | None = None) -> str:
    src = _normalize_source_key(source) if source else ""
    pos = _normalize_position(position) if position else ""
    if src and pos:
        return f"source:{src}|position:{pos}"
    if src:
        return f"source:{src}"
    return "global"


def _build_policy_issue(
    *,
    rule_id: str,
    severity: str,
    action: str,
    message: str,
    source: str | None = None,
    position: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue = {
        "ruleId": str(rule_id).strip().lower(),
        "severity": str(severity).strip().lower(),
        "action": str(action).strip().lower(),
        "scope": _issue_scope(source=source, position=position),
        "source": (_normalize_source_key(source) if source else None),
        "position": (_normalize_position(position) if position else None),
        "message": str(message).strip(),
        "details": details if isinstance(details, dict) else {},
    }
    return issue


def _dedupe_policy_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        key = (
            str(issue.get("ruleId") or "").strip().lower(),
            str(issue.get("severity") or "").strip().lower(),
            str(issue.get("scope") or "").strip().lower(),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _apply_policy_waivers(
    *,
    hard_fail_issues: list[dict[str, Any]],
    configured_waivers: list[dict[str, Any]],
    now_utc: datetime,
) -> dict[str, Any]:
    parsed_waivers: list[dict[str, Any]] = []
    invalid_waivers: list[dict[str, Any]] = []

    for waiver in configured_waivers:
        if not isinstance(waiver, dict):
            continue
        rule_id = str(waiver.get("ruleId") or "").strip().lower()
        scope = str(waiver.get("scope") or "global").strip().lower() or "global"
        if not rule_id:
            invalid_waivers.append(
                {
                    "waiver": waiver,
                    "reason": "missing_rule_id",
                }
            )
            continue
        expires_at_raw = str(waiver.get("expiresAt") or "").strip()
        expires_at = _parse_iso(expires_at_raw) if expires_at_raw else None
        if expires_at_raw and expires_at is None:
            invalid_waivers.append(
                {
                    "waiver": waiver,
                    "reason": "invalid_expires_at",
                }
            )
            continue
        if expires_at and now_utc > expires_at.astimezone(timezone.utc):
            invalid_waivers.append(
                {
                    "waiver": waiver,
                    "reason": "expired",
                }
            )
            continue
        parsed_waivers.append(
            {
                **waiver,
                "ruleId": rule_id,
                "scope": scope,
                "expiresAt": expires_at.isoformat() if expires_at else None,
            }
        )

    remaining_hard_fail: list[dict[str, Any]] = []
    waived_hard_fail: list[dict[str, Any]] = []
    applied_waivers: list[dict[str, Any]] = []
    consumed_waiver_indices: set[int] = set()
    for issue in hard_fail_issues:
        if not isinstance(issue, dict):
            continue
        rule_id = str(issue.get("ruleId") or "").strip().lower()
        scope = str(issue.get("scope") or "global").strip().lower() or "global"
        matched_idx = None
        matched_waiver = None
        for idx, waiver in enumerate(parsed_waivers):
            if str(waiver.get("ruleId") or "").strip().lower() != rule_id:
                continue
            waiver_scope = str(waiver.get("scope") or "global").strip().lower() or "global"
            if waiver_scope in {"*", "global"} or waiver_scope == scope:
                matched_idx = idx
                matched_waiver = waiver
                break

        if matched_waiver is None:
            remaining_hard_fail.append(issue)
            continue

        consumed_waiver_indices.add(int(matched_idx))
        waived_issue = {
            **issue,
            "waived": True,
            "waiver": {
                "ruleId": matched_waiver.get("ruleId"),
                "scope": matched_waiver.get("scope"),
                "reason": matched_waiver.get("reason"),
                "ticket": matched_waiver.get("ticket"),
                "expiresAt": matched_waiver.get("expiresAt"),
            },
        }
        waived_hard_fail.append(waived_issue)
        applied_waivers.append(
            {
                "ruleId": matched_waiver.get("ruleId"),
                "scope": matched_waiver.get("scope"),
                "issueScope": scope,
                "reason": matched_waiver.get("reason"),
                "ticket": matched_waiver.get("ticket"),
                "expiresAt": matched_waiver.get("expiresAt"),
            }
        )

    unmatched_waivers = [
        waiver
        for idx, waiver in enumerate(parsed_waivers)
        if idx not in consumed_waiver_indices
    ]

    return {
        "remainingHardFailIssues": remaining_hard_fail,
        "waivedHardFailIssues": waived_hard_fail,
        "appliedWaivers": applied_waivers,
        "configuredWaivers": parsed_waivers,
        "invalidWaivers": invalid_waivers,
        "unmatchedWaivers": unmatched_waivers,
    }


def _evaluate_trust_policy(
    *,
    source_freshness_rows: list[dict[str, Any]],
    required_source_set: set[str],
    critical_source_set: set[str],
    required_missing: list[str],
    required_below_min: list[dict[str, Any]],
    coverage_collapses: list[dict[str, Any]],
    disagreement: dict[str, Any],
    overnight_swings: list[dict[str, Any]],
    cfg: PromotionGateConfig,
    now_utc: datetime,
) -> dict[str, Any]:
    hard_fail_issues: list[dict[str, Any]] = []
    degrade_issues: list[dict[str, Any]] = []
    warn_only_issues: list[dict[str, Any]] = []

    freshness_by_source: dict[str, dict[str, Any]] = {}
    for row in source_freshness_rows:
        if not isinstance(row, dict):
            continue
        source = _normalize_source_key(row.get("source"))
        if not source:
            continue
        freshness_by_source[source] = row

    for source in sorted({*required_source_set, *set(freshness_by_source.keys())}):
        row = freshness_by_source.get(source) if isinstance(freshness_by_source.get(source), dict) else {}
        status = str((row or {}).get("status") or "").strip().lower()
        is_required = source in required_source_set
        is_critical = source in critical_source_set
        is_missing = source in {_normalize_source_key(s) for s in required_missing}
        if is_critical and status in {"missing", "failed", "timed_out"}:
            hard_fail_issues.append(
                _build_policy_issue(
                    rule_id="critical_source_unavailable",
                    severity="hard_fail",
                    action="block",
                    source=source,
                    message=f"Critical source '{source}' is unavailable ({status or 'missing'}).",
                    details={"status": status or "missing"},
                )
            )
        elif is_critical and status in {"stale", "missing_timestamp"}:
            hard_fail_issues.append(
                _build_policy_issue(
                    rule_id="critical_source_stale",
                    severity="hard_fail",
                    action="block",
                    source=source,
                    message=f"Critical source '{source}' is stale or missing freshness timestamps.",
                    details={"status": status or "stale"},
                )
            )
        elif is_critical and status == "partial":
            hard_fail_issues.append(
                _build_policy_issue(
                    rule_id="critical_source_partial_mapping",
                    severity="hard_fail",
                    action="block",
                    source=source,
                    message=f"Critical source '{source}' is in partial state.",
                    details={"status": status},
                )
            )
        elif is_required and (is_missing or status in {"missing", "failed", "timed_out"}):
            hard_fail_issues.append(
                _build_policy_issue(
                    rule_id="required_source_unavailable",
                    severity="hard_fail",
                    action="block",
                    source=source,
                    message=f"Required source '{source}' is unavailable ({status or 'missing'}).",
                    details={"status": status or "missing"},
                )
            )
        elif is_required and status in {"stale", "missing_timestamp", "partial", "running"}:
            degrade_issues.append(
                _build_policy_issue(
                    rule_id="required_source_degraded",
                    severity="degrade",
                    action="downweight",
                    source=source,
                    message=f"Required source '{source}' is degraded ({status}).",
                    details={"status": status},
                )
            )
        elif status in {"stale", "missing_timestamp", "partial", "running"}:
            warn_only_issues.append(
                _build_policy_issue(
                    rule_id="optional_source_degraded",
                    severity="warn",
                    action="warn",
                    source=source,
                    message=f"Optional source '{source}' is degraded ({status}).",
                    details={"status": status},
                )
            )

    for row in required_below_min:
        if not isinstance(row, dict):
            continue
        source = _normalize_source_key(row.get("source"))
        if not source:
            continue
        count = int(row.get("count") or 0)
        min_count = int(row.get("minCount") or 0)
        hard_fail_issues.append(
            _build_policy_issue(
                rule_id=(
                    "critical_source_below_min_count"
                    if source in critical_source_set
                    else "required_source_below_min_count"
                ),
                severity="hard_fail",
                action="block",
                source=source,
                message=f"Required source '{source}' is below minimum count ({count} < {min_count}).",
                details={"count": count, "minCount": min_count},
            )
        )

    for issue in coverage_collapses:
        if not isinstance(issue, dict):
            continue
        source = _normalize_source_key(issue.get("source"))
        if not source:
            continue
        position = _normalize_position(issue.get("position"))
        drop_pct = float(issue.get("dropPct") or 0.0)
        ratio = float(issue.get("currentToBaselineRatio") or 1.0)
        is_critical = source in critical_source_set
        is_required = source in required_source_set
        details = {
            "dropPct": round(drop_pct, 2),
            "currentToBaselineRatio": round(ratio, 4),
            "baselineCount": int(issue.get("baselineCount") or 0),
            "currentCount": int(issue.get("currentCount") or 0),
        }
        if is_critical and (
            drop_pct >= float(cfg.policy_critical_coverage_collapse_block_drop_pct)
            or ratio <= float(cfg.policy_critical_coverage_collapse_block_ratio)
        ):
            hard_fail_issues.append(
                _build_policy_issue(
                    rule_id="critical_source_coverage_collapse",
                    severity="hard_fail",
                    action="block",
                    source=source,
                    position=position,
                    message=(
                        f"Critical source '{source}' collapsed coverage for {position} "
                        f"(drop={drop_pct:.2f}%, ratio={ratio:.4f})."
                    ),
                    details=details,
                )
            )
        elif is_required:
            degrade_issues.append(
                _build_policy_issue(
                    rule_id="required_source_coverage_collapse",
                    severity="degrade",
                    action="downweight",
                    source=source,
                    position=position,
                    message=(
                        f"Required source '{source}' coverage dropped for {position} "
                        f"(drop={drop_pct:.2f}%, ratio={ratio:.4f})."
                    ),
                    details=details,
                )
            )
        else:
            warn_only_issues.append(
                _build_policy_issue(
                    rule_id="optional_source_coverage_collapse",
                    severity="warn",
                    action="warn",
                    source=source,
                    position=position,
                    message=(
                        f"Optional source '{source}' coverage dropped for {position} "
                        f"(drop={drop_pct:.2f}%, ratio={ratio:.4f})."
                    ),
                    details=details,
                )
            )

    extreme_players = disagreement.get("extremePlayers") if isinstance(disagreement, dict) else []
    extreme_players = extreme_players if isinstance(extreme_players, list) else []
    source_participation = disagreement.get("sourceExtremeParticipation") if isinstance(disagreement, dict) else {}
    source_participation = source_participation if isinstance(source_participation, dict) else {}
    extreme_count = len(extreme_players)
    highest_source_spike = max((int(v) for v in source_participation.values()), default=0)
    highest_critical_source_spike = max(
        (
            int(source_participation.get(src) or 0)
            for src in critical_source_set
            if _normalize_source_key(src)
        ),
        default=0,
    )
    top_sources = sorted(
        (
            {
                "source": _normalize_source_key(source),
                "spikeCount": int(count or 0),
                "critical": _normalize_source_key(source) in critical_source_set,
            }
            for source, count in source_participation.items()
            if _normalize_source_key(source)
        ),
        key=lambda row: (-int(row.get("spikeCount") or 0), str(row.get("source") or "")),
    )[:10]
    disagreement_details = {
        "extremePlayerCount": extreme_count,
        "highestSourceSpikeCount": highest_source_spike,
        "highestCriticalSourceSpikeCount": highest_critical_source_spike,
        "topSourceSpikes": top_sources,
    }
    if (
        extreme_count >= int(cfg.policy_disagreement_block_player_count)
        or highest_critical_source_spike >= int(cfg.policy_disagreement_block_critical_source_spike_count)
    ):
        hard_fail_issues.append(
            _build_policy_issue(
                rule_id="severe_disagreement_spike",
                severity="hard_fail",
                action="block",
                message=(
                    "Extreme cross-source disagreement exceeded blocking policy thresholds."
                ),
                details=disagreement_details,
            )
        )
    elif (
        extreme_count >= int(cfg.policy_disagreement_degrade_player_count)
        or highest_source_spike >= int(cfg.policy_disagreement_degrade_source_spike_count)
    ):
        degrade_issues.append(
            _build_policy_issue(
                rule_id="elevated_disagreement_spike",
                severity="degrade",
                action="downweight",
                message="Cross-source disagreement exceeded degrade thresholds.",
                details=disagreement_details,
            )
        )
    elif extreme_count > 0:
        warn_only_issues.append(
            _build_policy_issue(
                rule_id="disagreement_spike_observed",
                severity="warn",
                action="warn",
                message="Cross-source disagreement spikes were observed.",
                details=disagreement_details,
            )
        )

    swing_count = len(overnight_swings)
    swing_details = {
        "flaggedSwingCount": swing_count,
        "sample": overnight_swings[:20],
    }
    if swing_count >= int(cfg.policy_overnight_swing_block_count):
        hard_fail_issues.append(
            _build_policy_issue(
                rule_id="overnight_swing_anomaly",
                severity="hard_fail",
                action="block",
                message="Overnight swing anomalies exceeded blocking threshold.",
                details=swing_details,
            )
        )
    elif swing_count >= int(cfg.policy_overnight_swing_degrade_count):
        degrade_issues.append(
            _build_policy_issue(
                rule_id="overnight_swing_anomaly",
                severity="degrade",
                action="downweight",
                message="Overnight swing anomalies exceeded degrade threshold.",
                details=swing_details,
            )
        )
    elif swing_count > 0:
        warn_only_issues.append(
            _build_policy_issue(
                rule_id="overnight_swing_anomaly",
                severity="warn",
                action="warn",
                message="Overnight swing anomalies were observed.",
                details=swing_details,
            )
        )

    hard_fail_issues = _dedupe_policy_issues(hard_fail_issues)
    degrade_issues = _dedupe_policy_issues(degrade_issues)
    warn_only_issues = _dedupe_policy_issues(warn_only_issues)

    waiver_result = _apply_policy_waivers(
        hard_fail_issues=hard_fail_issues,
        configured_waivers=cfg.policy_waivers,
        now_utc=now_utc,
    )
    remaining_hard_fail = waiver_result.get("remainingHardFailIssues") or []
    waived_hard_fail = waiver_result.get("waivedHardFailIssues") or []

    if remaining_hard_fail:
        publish_decision = "block"
    elif degrade_issues:
        publish_decision = "allow_with_degrade"
    elif warn_only_issues:
        publish_decision = "allow_with_warning"
    else:
        publish_decision = "allow"

    return {
        "ok": publish_decision != "block",
        "publishDecision": publish_decision,
        "hardFailIssues": remaining_hard_fail,
        "waivedHardFailIssues": waived_hard_fail,
        "degradeIssues": degrade_issues,
        "warnOnlyIssues": warn_only_issues,
        "counts": {
            "hardFail": len(remaining_hard_fail),
            "hardFailWaived": len(waived_hard_fail),
            "degrade": len(degrade_issues),
            "warn": len(warn_only_issues),
        },
        "waivers": {
            "configured": waiver_result.get("configuredWaivers") or [],
            "applied": waiver_result.get("appliedWaivers") or [],
            "invalid": waiver_result.get("invalidWaivers") or [],
            "unmatched": waiver_result.get("unmatchedWaivers") or [],
        },
        "requiredWaiversToUnblock": [
            {
                "ruleId": str(issue.get("ruleId") or ""),
                "scope": str(issue.get("scope") or "global"),
            }
            for issue in remaining_hard_fail
        ],
    }


def _run_regression_subprocess(repo_root: Path, cfg: PromotionGateConfig) -> dict[str, Any]:
    if not cfg.regression_command:
        return {
            "ok": False,
            "status": "invalid_config",
            "command": "",
            "durationSec": 0.0,
            "returnCode": None,
            "stdoutTail": "",
            "stderrTail": "PROMOTION_REGRESSION_COMMAND is empty",
        }

    env = dict(os.environ)
    env.setdefault("DYNASTY_SCRAPER_SKIP_BOOTSTRAP", "true")
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath.strip():
        env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(repo_root)

    started = time.time()
    try:
        proc = subprocess.run(
            cfg.regression_command,
            cwd=str(repo_root),
            shell=True,
            text=True,
            capture_output=True,
            timeout=max(30, int(cfg.regression_timeout_sec)),
            env=env,
        )
        elapsed = round(time.time() - started, 2)
        stdout_tail = "\n".join((proc.stdout or "").splitlines()[-40:])
        stderr_tail = "\n".join((proc.stderr or "").splitlines()[-40:])
        return {
            "ok": proc.returncode == 0,
            "status": "passed" if proc.returncode == 0 else "failed",
            "command": cfg.regression_command,
            "durationSec": elapsed,
            "returnCode": int(proc.returncode),
            "stdoutTail": stdout_tail,
            "stderrTail": stderr_tail,
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = round(time.time() - started, 2)
        stdout_tail = "\n".join((exc.stdout or "").splitlines()[-40:]) if exc.stdout else ""
        stderr_tail = "\n".join((exc.stderr or "").splitlines()[-40:]) if exc.stderr else ""
        return {
            "ok": False,
            "status": "timeout",
            "command": cfg.regression_command,
            "durationSec": elapsed,
            "returnCode": None,
            "stdoutTail": stdout_tail,
            "stderrTail": stderr_tail,
        }


def evaluate_promotion_candidate(
    *,
    raw_payload: dict[str, Any],
    contract_payload: dict[str, Any],
    contract_report: dict[str, Any],
    repo_root: Path,
    trigger: str,
    source_meta: dict[str, Any] | None = None,
    baseline_raw_payload: dict[str, Any] | None = None,
    baseline_contract_payload: dict[str, Any] | None = None,
    config: PromotionGateConfig | None = None,
    now: datetime | None = None,
    regression_runner: RegressionRunner | None = None,
) -> dict[str, Any]:
    cfg = config or load_promotion_gate_config()
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_meta = source_meta if isinstance(source_meta, dict) else {}

    errors: list[str] = []
    warnings: list[str] = []
    gates: dict[str, dict[str, Any]] = {}

    site_counts = _site_counts(raw_payload)
    summary = _source_runtime_summary(raw_payload)
    summary_rows = _source_runtime_rows(summary)
    rows = contract_payload.get("playersArray")
    rows = rows if isinstance(rows, list) else []
    baseline_rows = []
    if isinstance(baseline_contract_payload, dict):
        maybe_rows = baseline_contract_payload.get("playersArray")
        if isinstance(maybe_rows, list):
            baseline_rows = maybe_rows

    required_source_set = {_normalize_source_key(s) for s in cfg.required_sources if _normalize_source_key(s)}
    critical_source_set = {_normalize_source_key(s) for s in cfg.critical_sources if _normalize_source_key(s)}
    timed_out_sources = {
        _normalize_source_key(v)
        for v in (summary.get("timedOutSources") or [])
        if _normalize_source_key(v)
    }
    failed_sources = {
        _normalize_source_key(v)
        for v in (summary.get("failedSources") or [])
        if _normalize_source_key(v)
    }

    required_missing: list[str] = []
    required_below_min: list[dict[str, Any]] = []
    critical_issues: list[str] = []

    for source in cfg.required_sources:
        key = _normalize_source_key(source)
        if not key:
            continue
        count = int(site_counts.get(key, 0))
        min_count = int(cfg.source_min_player_count.get(key, 1))
        if count <= 0:
            required_missing.append(key)
            if key in critical_source_set:
                critical_issues.append(f"{key}:missing")
            continue
        if count < min_count:
            required_below_min.append(
                {
                    "source": key,
                    "count": count,
                    "minCount": min_count,
                }
            )
            if key in critical_source_set:
                critical_issues.append(f"{key}:below_min_count")

    required_gate_ok = not required_missing and not required_below_min
    gates["requiredSourcePresence"] = {
        "ok": required_gate_ok,
        "requiredSources": sorted(required_source_set),
        "criticalSources": sorted(critical_source_set),
        "missingSources": sorted(required_missing),
        "belowMinCountSources": sorted(required_below_min, key=lambda x: str(x.get("source"))),
        "sourceCounts": site_counts,
    }
    if not required_gate_ok:
        errors.append("required_source_presence_failed")

    payload_ts = _parse_iso(raw_payload.get("scrapeTimestamp"))
    if payload_ts is None:
        payload_ts = _parse_iso(summary.get("finishedAt"))
    payload_age_h = _hours_since(payload_ts, now_utc)
    freshness_issues: list[dict[str, Any]] = []
    source_freshness_all: list[dict[str, Any]] = []

    settings = raw_payload.get("settings") if isinstance(raw_payload.get("settings"), dict) else {}
    dlf_import = settings.get("dlfImport") if isinstance(settings.get("dlfImport"), dict) else {}
    dlf_source_map = {
        "dlfsf": "dlfsf",
        "dlfidp": "dlfidp",
        "dlfrsf": "dlfrsf",
        "dlfridp": "dlfridp",
    }
    stale_csv_sources: set[str] = set()
    for raw_key, meta in dlf_import.items():
        if not isinstance(meta, dict) or not bool(meta.get("stale")):
            continue
        raw_norm = _normalize_source_key(raw_key)
        mapped = dlf_source_map.get(raw_norm, raw_norm)
        if mapped:
            stale_csv_sources.add(mapped)

    if payload_age_h is None:
        freshness_issues.append(
            {
                "scope": "payload",
                "reason": "missing_scrape_timestamp",
            }
        )
    elif payload_age_h > float(cfg.max_payload_age_hours):
        freshness_issues.append(
            {
                "scope": "payload",
                "reason": "payload_too_old",
                "ageHours": round(payload_age_h, 3),
                "maxAgeHours": float(cfg.max_payload_age_hours),
            }
        )

    source_catalog = set(site_counts.keys()) | required_source_set | critical_source_set
    for source in sorted(source_catalog):
        key = _normalize_source_key(source)
        if not key:
            continue
        row = summary_rows.get(key) if isinstance(summary_rows.get(key), dict) else {}
        enabled = bool(row.get("enabled", True)) if row else True
        runtime_state = str(row.get("state") or "").strip().lower() if row else ""
        count = int(site_counts.get(key, 0) or 0)
        row_finished = _parse_iso((row or {}).get("finishedAt"))
        row_started = _parse_iso((row or {}).get("startedAt"))
        src_ts = row_finished or row_started or payload_ts
        age_h = _hours_since(src_ts, now_utc)
        status = "fresh"
        if not enabled:
            status = "disabled"
        elif key in failed_sources or runtime_state == "failed":
            status = "failed"
        elif key in timed_out_sources or runtime_state == "timeout":
            status = "timed_out"
        elif key in stale_csv_sources:
            status = "stale"
        elif count <= 0:
            status = "missing"
        elif age_h is None:
            status = "missing_timestamp"
        elif age_h > float(cfg.max_source_age_hours):
            status = "stale"
        elif runtime_state == "partial":
            status = "partial"
        elif runtime_state == "running":
            status = "running"
        source_freshness_all.append(
            {
                "source": key,
                "required": key in required_source_set,
                "critical": key in critical_source_set,
                "enabled": enabled,
                "siteCount": count,
                "runtimeState": runtime_state or None,
                "ageHours": (round(age_h, 3) if age_h is not None else None),
                "status": status,
                "finishedAt": (row_finished.isoformat() if row_finished else None),
                "startedAt": (row_started.isoformat() if row_started else None),
                "staleCsv": key in stale_csv_sources,
            }
        )
        if key in critical_source_set and status in {"failed", "timed_out", "missing", "missing_timestamp", "stale"}:
            freshness_issues.append(
                {
                    "scope": "source",
                    "source": key,
                    "reason": status,
                    "ageHours": (round(age_h, 3) if age_h is not None else None),
                }
            )

    freshness_ok = not freshness_issues
    critical_freshness = [row for row in source_freshness_all if bool(row.get("critical"))]
    gates["sourceFreshness"] = {
        "ok": freshness_ok,
        "payloadAgeHours": (round(payload_age_h, 3) if payload_age_h is not None else None),
        "maxPayloadAgeHours": float(cfg.max_payload_age_hours),
        "maxSourceAgeHours": float(cfg.max_source_age_hours),
        "allSourceFreshness": source_freshness_all,
        "criticalSourceFreshness": critical_freshness,
        "staleSources": sorted(
            [
                str(row.get("source") or "")
                for row in source_freshness_all
                if str(row.get("status") or "") in {"stale", "missing_timestamp"}
            ]
        ),
        "missingSources": sorted(
            [
                str(row.get("source") or "")
                for row in source_freshness_all
                if str(row.get("status") or "") in {"missing", "failed", "timed_out"}
            ]
        ),
        "issues": freshness_issues,
    }
    if not freshness_ok:
        errors.append("source_freshness_failed")

    coverage = {}
    if isinstance(contract_payload.get("valueAuthority"), dict):
        coverage_raw = contract_payload["valueAuthority"].get("coverage")
        if isinstance(coverage_raw, dict):
            coverage = coverage_raw

    player_count = int(contract_payload.get("playerCount") or 0)
    if player_count <= 0:
        rows = contract_payload.get("playersArray")
        if isinstance(rows, list):
            player_count = len(rows)
    active_sources = sum(1 for count in site_counts.values() if int(count) > 0)
    canonical_site_map_present = int(coverage.get("canonicalSiteMapPresent") or 0)
    canonical_ratio = (
        float(canonical_site_map_present) / float(player_count)
        if player_count > 0
        else 0.0
    )

    coverage_issues: list[dict[str, Any]] = []
    if player_count < int(cfg.min_player_count):
        coverage_issues.append(
            {
                "metric": "playerCount",
                "actual": player_count,
                "min": int(cfg.min_player_count),
            }
        )
    if active_sources < int(cfg.min_active_sources):
        coverage_issues.append(
            {
                "metric": "activeSources",
                "actual": active_sources,
                "min": int(cfg.min_active_sources),
            }
        )
    if canonical_ratio < float(cfg.min_canonical_site_map_coverage):
        coverage_issues.append(
            {
                "metric": "canonicalSiteMapCoverage",
                "actual": round(canonical_ratio, 4),
                "min": float(cfg.min_canonical_site_map_coverage),
            }
        )

    gates["coverageThresholds"] = {
        "ok": not coverage_issues,
        "playerCount": player_count,
        "minPlayerCount": int(cfg.min_player_count),
        "activeSourceCount": active_sources,
        "minActiveSourceCount": int(cfg.min_active_sources),
        "canonicalSiteMapCoverage": round(canonical_ratio, 4),
        "minCanonicalSiteMapCoverage": float(cfg.min_canonical_site_map_coverage),
        "issues": coverage_issues,
    }
    if coverage_issues:
        errors.append("coverage_thresholds_failed")

    merge_totals = _identity_totals(raw_payload)
    source_rows = int(merge_totals.get("sourceRows") or 0)
    unmatched_rows = int(merge_totals.get("unmatchedRows") or 0)
    duplicate_matches = int(merge_totals.get("duplicateCanonicalMatches") or 0)
    conflicting_positions = int(merge_totals.get("conflictingPositions") or 0)
    conflicting_source_identities = int(merge_totals.get("conflictingSourceIdentities") or 0)
    unmatched_rate = (float(unmatched_rows) / float(source_rows)) if source_rows > 0 else 1.0

    merge_issues: list[dict[str, Any]] = []
    if not merge_totals:
        merge_issues.append({"metric": "identityResolutionDiagnostics", "reason": "missing"})
    else:
        if unmatched_rate > float(cfg.max_unmatched_rate):
            merge_issues.append(
                {
                    "metric": "unmatchedRate",
                    "actual": round(unmatched_rate, 6),
                    "max": float(cfg.max_unmatched_rate),
                }
            )
        if duplicate_matches > int(cfg.max_duplicate_canonical_matches):
            merge_issues.append(
                {
                    "metric": "duplicateCanonicalMatches",
                    "actual": duplicate_matches,
                    "max": int(cfg.max_duplicate_canonical_matches),
                }
            )
        if conflicting_positions > int(cfg.max_conflicting_positions):
            merge_issues.append(
                {
                    "metric": "conflictingPositions",
                    "actual": conflicting_positions,
                    "max": int(cfg.max_conflicting_positions),
                }
            )
        if conflicting_source_identities > int(cfg.max_conflicting_source_identities):
            merge_issues.append(
                {
                    "metric": "conflictingSourceIdentities",
                    "actual": conflicting_source_identities,
                    "max": int(cfg.max_conflicting_source_identities),
                }
            )

    gates["mergeIntegrity"] = {
        "ok": not merge_issues,
        "sourceRows": source_rows,
        "unmatchedRows": unmatched_rows,
        "unmatchedRate": round(unmatched_rate, 6),
        "maxUnmatchedRate": float(cfg.max_unmatched_rate),
        "duplicateCanonicalMatches": duplicate_matches,
        "maxDuplicateCanonicalMatches": int(cfg.max_duplicate_canonical_matches),
        "conflictingPositions": conflicting_positions,
        "maxConflictingPositions": int(cfg.max_conflicting_positions),
        "conflictingSourceIdentities": conflicting_source_identities,
        "maxConflictingSourceIdentities": int(cfg.max_conflicting_source_identities),
        "issues": merge_issues,
    }
    if merge_issues:
        errors.append("merge_integrity_failed")

    regression_gate: dict[str, Any]
    if cfg.run_regression_tests:
        runner = regression_runner or _run_regression_subprocess
        regression = runner(repo_root, cfg)
        regression_gate = {
            "ok": bool(regression.get("ok")),
            **regression,
        }
    else:
        regression_gate = {
            "ok": True,
            "status": "skipped_by_config",
            "command": cfg.regression_command,
            "durationSec": 0.0,
            "returnCode": None,
            "stdoutTail": "",
            "stderrTail": "",
        }
        warnings.append("regression_tests_skipped_by_config")
    gates["regressionTests"] = regression_gate
    if not regression_gate.get("ok"):
        errors.append("regression_tests_failed")

    invalid_value_rows = 0
    intentional_quarantine_rows = 0
    intentional_quarantine_missing_full_value_rows = 0
    pos_counts: dict[str, int] = {}
    pos_max: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pos = str(row.get("position") or "").strip().upper()
        bundle = row.get("valueBundle") if isinstance(row.get("valueBundle"), dict) else {}
        full_value = bundle.get("fullValue")
        intentional_quarantine = _is_intentional_quarantine_row(row, bundle)
        if intentional_quarantine:
            intentional_quarantine_rows += 1

        values = [
            bundle.get("rawValue"),
            bundle.get("scoringAdjustedValue"),
            bundle.get("scarcityAdjustedValue"),
            bundle.get("bestBallAdjustedValue"),
        ]
        if full_value is None:
            if intentional_quarantine:
                intentional_quarantine_missing_full_value_rows += 1
            else:
                values.append(full_value)
        else:
            values.append(full_value)
        parsed_ok = True
        parsed_vals: list[int] = []
        for value in values:
            try:
                n = int(value)
            except Exception:
                parsed_ok = False
                break
            if n < 1 or n > 9999:
                parsed_ok = False
                break
            parsed_vals.append(n)
        if not parsed_ok:
            invalid_value_rows += 1

        if pos:
            pos_counts[pos] = pos_counts.get(pos, 0) + 1
            if parsed_vals:
                top_candidate = parsed_vals[-1]
                if intentional_quarantine and full_value is None and len(parsed_vals) >= 4:
                    # Intentionally quarantined rows have no final fullValue by design;
                    # use best-ball adjusted value for positional ceiling sanity.
                    top_candidate = parsed_vals[3]
                pos_max[pos] = max(pos_max.get(pos, 0), top_candidate)

    formula_issues: list[dict[str, Any]] = []
    if invalid_value_rows > 0:
        formula_issues.append(
            {
                "metric": "invalidValueRows",
                "actual": invalid_value_rows,
                "max": 0,
            }
        )

    for pos in cfg.required_positions:
        pos_key = str(pos).strip().upper()
        count = int(pos_counts.get(pos_key, 0))
        if count <= 0:
            formula_issues.append(
                {
                    "metric": "positionMissing",
                    "position": pos_key,
                    "actual": count,
                    "min": 1,
                }
            )
            continue
        top_value = int(pos_max.get(pos_key, 0))
        min_top = int(cfg.min_top_value_by_position.get(pos_key, 1))
        if top_value < min_top:
            formula_issues.append(
                {
                    "metric": "positionTopValueTooLow",
                    "position": pos_key,
                    "actual": top_value,
                    "min": min_top,
                }
            )

    gates["formulaSanity"] = {
        "ok": not formula_issues,
        "invalidValueRows": invalid_value_rows,
        "intentionalQuarantineRows": intentional_quarantine_rows,
        "intentionalQuarantineMissingFullValueRows": intentional_quarantine_missing_full_value_rows,
        "requiredPositions": [str(p).upper() for p in cfg.required_positions],
        "positionCounts": pos_counts,
        "positionTopValues": pos_max,
        "positionTopValueMinimums": {
            str(k).upper(): int(v) for k, v in cfg.min_top_value_by_position.items()
        },
        "issues": formula_issues,
    }
    if formula_issues:
        errors.append("formula_sanity_failed")

    contract_ok = bool(contract_report.get("ok"))
    gates["contractValidation"] = {
        "ok": contract_ok,
        "status": contract_report.get("status"),
        "errorCount": int(contract_report.get("errorCount") or 0),
        "warningCount": int(contract_report.get("warningCount") or 0),
        "errorsSample": list((contract_report.get("errors") or [])[:20]),
        "warningsSample": list((contract_report.get("warnings") or [])[:20]),
    }
    if not contract_ok:
        errors.append("contract_validation_failed")

    known_sources = set(site_counts.keys()) | set(summary_rows.keys()) | required_source_set | critical_source_set
    current_coverage = _site_presence_counts(
        rows,
        required_positions=cfg.required_positions,
        known_sources=known_sources,
    )
    baseline_coverage = None
    if baseline_rows:
        baseline_coverage = _site_presence_counts(
            baseline_rows,
            required_positions=cfg.required_positions,
            known_sources=known_sources,
        )
    coverage_collapses = _detect_coverage_collapses(
        current_coverage=current_coverage,
        baseline_coverage=baseline_coverage,
        required_positions=cfg.required_positions,
        max_ratio=float(cfg.max_coverage_collapse_ratio),
        min_drop=int(cfg.min_coverage_collapse_drop),
    )

    disagreement = _player_disagreement_metrics(
        rows,
        min_sources=int(cfg.disagreement_min_sources),
        max_rel_spread=float(cfg.max_disagreement_rel_spread),
        min_abs_delta=int(cfg.min_disagreement_abs_delta),
    )
    overnight_swings = _overnight_swing_flags(
        rows,
        baseline_rows,
        max_pct=float(cfg.max_overnight_swing_pct),
        min_abs_delta=int(cfg.min_overnight_swing_abs_delta),
    ) if baseline_rows else []

    source_freshness_rows = gates["sourceFreshness"].get("allSourceFreshness")
    source_freshness_rows = source_freshness_rows if isinstance(source_freshness_rows, list) else []
    missing_sources = sorted({
        _normalize_source_key(src)
        for src in (
            list(required_missing)
            + [
                row.get("source")
                for row in source_freshness_rows
                if str(row.get("status") or "") in {"missing", "failed", "timed_out"}
            ]
        )
        if _normalize_source_key(src)
    })
    stale_sources = sorted(
        {
            _normalize_source_key(row.get("source"))
            for row in source_freshness_rows
            if str(row.get("status") or "") in {"stale", "missing_timestamp"}
            and _normalize_source_key(row.get("source"))
        }
    )
    auto_handling = _recommend_source_handling(
        source_freshness_rows=source_freshness_rows,
        required_missing=required_missing,
        required_below_min=required_below_min,
        coverage_collapses=coverage_collapses,
        disagreement_participation=(
            disagreement.get("sourceExtremeParticipation")
            if isinstance(disagreement.get("sourceExtremeParticipation"), dict)
            else {}
        ),
        critical_sources=critical_source_set,
    )

    trust_policy = _evaluate_trust_policy(
        source_freshness_rows=source_freshness_rows,
        required_source_set=required_source_set,
        critical_source_set=critical_source_set,
        required_missing=required_missing,
        required_below_min=required_below_min,
        coverage_collapses=coverage_collapses,
        disagreement=disagreement,
        overnight_swings=overnight_swings,
        cfg=cfg,
        now_utc=now_utc,
    )
    gates["trustPolicy"] = {
        "ok": bool(trust_policy.get("ok")),
        "publishDecision": trust_policy.get("publishDecision"),
        "counts": trust_policy.get("counts"),
        "hardFailIssues": list((trust_policy.get("hardFailIssues") or [])[:80]),
        "waivedHardFailIssues": list((trust_policy.get("waivedHardFailIssues") or [])[:80]),
        "degradeIssues": list((trust_policy.get("degradeIssues") or [])[:120]),
        "warnOnlyIssues": list((trust_policy.get("warnOnlyIssues") or [])[:120]),
        "waivers": trust_policy.get("waivers"),
        "requiredWaiversToUnblock": list((trust_policy.get("requiredWaiversToUnblock") or [])[:80]),
    }
    if not bool(trust_policy.get("ok")):
        errors.append("trust_policy_failed")
    if int((trust_policy.get("counts") or {}).get("degrade", 0) or 0) > 0:
        warnings.append("trust_policy_degrade")
    if int((trust_policy.get("counts") or {}).get("warn", 0) or 0) > 0:
        warnings.append("trust_policy_warn")

    critical_missing = [src for src in missing_sources if src in critical_source_set]
    critical_stale = [src for src in stale_sources if src in critical_source_set]
    critical_collapses = [
        issue
        for issue in coverage_collapses
        if _normalize_source_key(issue.get("source")) in critical_source_set
    ]
    operator_status = "ok"
    if str(trust_policy.get("publishDecision") or "") == "block":
        operator_status = "critical"
    elif str(trust_policy.get("publishDecision") or "").startswith("allow_with_"):
        operator_status = "warning"
    elif critical_missing or critical_stale or critical_collapses:
        operator_status = "critical"
    elif missing_sources or stale_sources or coverage_collapses or disagreement.get("extremePlayers") or overnight_swings:
        operator_status = "warning"
    if operator_status != "ok":
        warnings.append("operator_observability_flags")

    baseline_source_meta = (
        baseline_raw_payload.get("scrapeTimestamp")
        if isinstance(baseline_raw_payload, dict)
        else None
    )
    operator_report = {
        "status": operator_status,
        "summary": {
            "trackedSources": len(source_freshness_rows),
            "freshSourceCount": sum(
                1 for row in source_freshness_rows if str(row.get("status") or "") == "fresh"
            ),
            "missingSourceCount": len(missing_sources),
            "staleSourceCount": len(stale_sources),
            "coverageCollapseCount": len(coverage_collapses),
            "extremeDisagreementCount": len(disagreement.get("extremePlayers") or []),
            "overnightSwingCount": len(overnight_swings),
            "policyHardFailCount": int((trust_policy.get("counts") or {}).get("hardFail", 0) or 0),
            "policyHardFailWaivedCount": int((trust_policy.get("counts") or {}).get("hardFailWaived", 0) or 0),
            "policyDegradeCount": int((trust_policy.get("counts") or {}).get("degrade", 0) or 0),
            "policyWarnCount": int((trust_policy.get("counts") or {}).get("warn", 0) or 0),
        },
        "flags": {
            "missingSources": missing_sources,
            "staleSources": stale_sources,
            "coverageCollapseByPosition": coverage_collapses[:80],
            "extremeDisagreementSpikes": list(disagreement.get("extremePlayers") or [])[:80],
            "unexpectedOvernightSwings": overnight_swings[:80],
        },
        "autoHandlingRecommendations": auto_handling,
        "policy": {
            "publishDecision": trust_policy.get("publishDecision"),
            "hardFailIssues": list((trust_policy.get("hardFailIssues") or [])[:80]),
            "waivedHardFailIssues": list((trust_policy.get("waivedHardFailIssues") or [])[:80]),
            "degradeIssues": list((trust_policy.get("degradeIssues") or [])[:120]),
            "warnOnlyIssues": list((trust_policy.get("warnOnlyIssues") or [])[:120]),
            "waivers": trust_policy.get("waivers"),
            "requiredWaiversToUnblock": list((trust_policy.get("requiredWaiversToUnblock") or [])[:80]),
        },
    }

    observability = {
        "thresholds": {
            "maxCoverageCollapseRatio": float(cfg.max_coverage_collapse_ratio),
            "minCoverageCollapseDrop": int(cfg.min_coverage_collapse_drop),
            "disagreementMinSources": int(cfg.disagreement_min_sources),
            "maxDisagreementRelativeSpread": float(cfg.max_disagreement_rel_spread),
            "minDisagreementAbsoluteDelta": int(cfg.min_disagreement_abs_delta),
            "maxOvernightSwingPct": float(cfg.max_overnight_swing_pct),
            "minOvernightSwingAbsoluteDelta": int(cfg.min_overnight_swing_abs_delta),
        },
        "baseline": {
            "present": bool(baseline_rows),
            "scrapeTimestamp": baseline_source_meta,
            "playerCount": len(baseline_rows),
        },
        "sourceFreshness": {
            "payloadAgeHours": gates["sourceFreshness"].get("payloadAgeHours"),
            "maxPayloadAgeHours": gates["sourceFreshness"].get("maxPayloadAgeHours"),
            "maxSourceAgeHours": gates["sourceFreshness"].get("maxSourceAgeHours"),
            "sources": source_freshness_rows,
        },
        "sourceCoverageByPosition": {
            "current": current_coverage,
            "baseline": baseline_coverage,
            "collapseFlags": coverage_collapses,
        },
        "playerDisagreement": disagreement,
        "overnightSwings": {
            "flags": overnight_swings,
        },
        "flags": operator_report["flags"],
        "autoHandlingRecommendations": auto_handling,
        "operatorReport": operator_report,
        "policy": operator_report.get("policy"),
    }

    overall_ok = all(bool(g.get("ok")) for g in gates.values())
    if critical_issues:
        errors.append("critical_sources_failed")
        overall_ok = False

    if summary.get("partialRun"):
        warnings.append("source_run_partial")

    status = "pass" if overall_ok else "fail"
    report = {
        "generatedAt": _utc_now_iso(),
        "status": status,
        "trigger": str(trigger or ""),
        "sourceMeta": source_meta,
        "summary": {
            "gateCount": len(gates),
            "passedGates": sum(1 for g in gates.values() if g.get("ok")),
            "failedGates": sum(1 for g in gates.values() if not g.get("ok")),
            "errors": sorted(set(errors)),
            "warnings": sorted(set(warnings)),
            "criticalIssues": sorted(set(critical_issues)),
        },
        "metrics": {
            "playerCount": player_count,
            "activeSourceCount": active_sources,
            "requiredSourceCount": len(cfg.required_sources),
            "criticalSourceCount": len(cfg.critical_sources),
        },
        "gates": gates,
        "observability": observability,
        "operatorReport": operator_report,
        "policy": operator_report.get("policy"),
    }
    return report
