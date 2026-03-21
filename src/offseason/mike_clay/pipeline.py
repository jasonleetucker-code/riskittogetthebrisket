from __future__ import annotations

import csv
import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.utils import canonical_data_dir, repo_root, save_json

from .constants import (
    IMPORT_PIPELINE_VERSION,
    LOW_CONFIDENCE_THRESHOLD,
    MATCH_STATUS_VALUES,
    READINESS_MIN_MATCH_RATE,
    READINESS_MIN_PARSE_SUCCESS_RATE,
)
from .matcher import (
    PlayerMatcher,
    duplicate_canonical_name_report,
    load_canonical_players,
    load_manual_match_overrides,
    manual_override_for_row,
    normalize_position_code,
    normalize_team_code,
)
from .parser import MikeClayParseBundle, parse_mike_clay_pdf


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _timestamp_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write("")
        return
    keys: list[str] = []
    key_set: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in key_set:
                key_set.add(key)
                keys.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _starter_lookup_index(starter_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from src.utils import normalize_player_name

    out: dict[str, dict[str, Any]] = {}
    for row in starter_rows:
        name = normalize_player_name(row.get("player_name_source"))
        if not name:
            continue
        team = normalize_team_code(row.get("team_canonical") or row.get("team_source"))
        pos = normalize_position_code(row.get("position_source"))
        slot = str(row.get("slot") or "").strip()
        key = f"{name}|{team}|{pos}"
        if key not in out:
            out[key] = {
                "starter_projected": True,
                "starter_slot": slot,
                "starter_team_canonical": team,
                "starter_position_canonical": pos,
            }
        for fallback_key in (
            f"{name}|{team}|",
            f"{name}||{pos}",
            f"{name}||",
        ):
            out.setdefault(
                fallback_key,
                {
                    "starter_projected": True,
                    "starter_slot": slot,
                    "starter_team_canonical": team,
                    "starter_position_canonical": pos,
                },
            )
    return out


def _build_team_context(bundle: MikeClayParseBundle) -> dict[str, dict[str, Any]]:
    team_context: dict[str, dict[str, Any]] = {}

    def _ensure_team(team: str) -> dict[str, Any]:
        key = normalize_team_code(team)
        team_context.setdefault(key, {"canonical_team_id": key})
        return team_context[key]

    for row in bundle.team_rows:
        team = _ensure_team(str(row.get("team_canonical") or row.get("team_name_source") or ""))
        team.update(
            {
                "projected_wins": row.get("projected_wins"),
                "projected_losses": row.get("projected_losses"),
                "projected_points_for": row.get("projected_points_for"),
                "projected_points_against": row.get("projected_points_against"),
                "projected_point_diff": row.get("projected_point_diff"),
                "favored_games": row.get("favored_games"),
                "schedule_rank_from_standings": row.get("schedule_rank_from_standings"),
                "team_name_source": row.get("team_name_source"),
            }
        )

    for row in bundle.sos_rows:
        team = _ensure_team(str(row.get("team_canonical") or row.get("team_name_source") or ""))
        team.update(
            {
                "strength_of_schedule_rank": row.get("strength_of_schedule_rank"),
                "schedule_tokens": row.get("schedule_tokens"),
            }
        )

    for row in bundle.unit_grade_rows:
        team = _ensure_team(str(row.get("team_canonical") or row.get("team_name_source") or ""))
        team.update(
            {
                "qb_grade": row.get("qb_grade"),
                "rb_grade": row.get("rb_grade"),
                "wr_grade": row.get("wr_grade"),
                "te_grade": row.get("te_grade"),
                "ol_grade": row.get("ol_grade"),
                "di_grade": row.get("di_grade"),
                "ed_grade": row.get("ed_grade"),
                "lb_grade": row.get("lb_grade"),
                "cb_grade": row.get("cb_grade"),
                "s_grade": row.get("s_grade"),
                "offense_grade": row.get("offense_grade"),
                "offense_rank": row.get("offense_rank"),
                "defense_grade": row.get("defense_grade"),
                "defense_rank": row.get("defense_rank"),
                "total_grade": row.get("total_grade"),
                "total_rank": row.get("total_rank"),
            }
        )

    category_order: dict[str, int] = defaultdict(int)
    for row in bundle.unit_rank_rows:
        category = str(row.get("unit_category") or "").strip().lower()
        if not category:
            continue
        category_order[category] += 1
        team = _ensure_team(str(row.get("team_canonical") or row.get("team_name_source") or ""))
        team[f"{category}_unit_rank"] = category_order[category]
        team[f"{category}_unit_grade"] = row.get("unit_grade")

    for row in bundle.coaching_rows:
        team = _ensure_team(str(row.get("team_canonical") or row.get("team_source") or ""))
        team["head_coach"] = row.get("head_coach")

    return team_context


def _team_grade_for_position(team_context_row: dict[str, Any], position_canonical: str) -> float | None:
    if not team_context_row:
        return None
    position_key = {
        "QB": "qb_grade",
        "RB": "rb_grade",
        "WR": "wr_grade",
        "TE": "te_grade",
        "DL": "di_grade",
        "LB": "lb_grade",
        "DB": "cb_grade",
    }.get(position_canonical, "")
    if not position_key:
        return None
    value = team_context_row.get(position_key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_counts(normalized_players: list[dict[str, Any]]) -> dict[str, Any]:
    by_position = Counter()
    by_team = Counter()
    by_status = Counter()
    for row in normalized_players:
        by_position[str(row.get("position_canonical") or "UNKNOWN")] += 1
        by_team[str(row.get("team_canonical") or "UNKNOWN")] += 1
        by_status[str(row.get("match_status") or "unknown")] += 1
    return {
        "by_position": dict(sorted(by_position.items())),
        "by_team": dict(sorted(by_team.items())),
        "by_status": dict(sorted(by_status.items())),
    }


_IMPACT_TIER_RANK = {"high": 3, "medium": 2, "low": 1}
_UNRESOLVED_HIGH_RISK_METHODS = {"normalized_name_ambiguous", "alias_norm_ambiguous", "fuzzy_ratio_tie"}
_REVIEW_REASON_LABELS = {
    "manual_override": "Resolved using explicit manual override.",
    "exact_name_casefold": "Exact canonical name match.",
    "normalized_name_unique": "Deterministic normalized-name match.",
    "alias_norm_unique": "Deterministic alias/normalized-name match.",
    "fuzzy_ratio_high": "High-threshold fuzzy match (manually reviewed).",
    "fuzzy_ratio_tie": "Multiple near-equal fuzzy candidates; unsafe to auto-resolve.",
    "fuzzy_below_threshold": "Closest fuzzy candidate did not meet trust threshold.",
    "no_fuzzy_candidates": "No canonical candidate found in current universe.",
    "normalized_name_ambiguous": "Multiple normalized-name candidates; unsafe to auto-resolve.",
    "alias_norm_ambiguous": "Multiple alias candidates; unsafe to auto-resolve.",
    "empty_name": "Source row missing player name.",
    "empty_normalized_name": "Source name could not be normalized.",
    "empty_search_pool": "No canonical search pool for this position.",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if out != out:  # NaN guard
            return default
        return out
    except (TypeError, ValueError):
        return default


def _impact_tier(row: dict[str, Any]) -> str:
    position = str(row.get("position_canonical") or "").upper()
    points = _safe_float(row.get("projected_points"))
    starter = bool(row.get("starter_projected"))

    if position in {"QB", "RB", "WR", "TE"}:
        if points >= 90.0 or (starter and points >= 70.0):
            return "high"
        if points >= 35.0:
            return "medium"
        return "low"

    if points >= 120.0:
        return "high"
    if points >= 70.0:
        return "medium"
    return "low"


def _impact_score(row: dict[str, Any]) -> float:
    points = _safe_float(row.get("projected_points"))
    starter_bonus = 18.0 if bool(row.get("starter_projected")) else 0.0
    position_bonus = {
        "QB": 35.0,
        "RB": 30.0,
        "WR": 28.0,
        "TE": 24.0,
        "DL": 18.0,
        "LB": 20.0,
        "DB": 16.0,
    }.get(str(row.get("position_canonical") or "").upper(), 10.0)
    rank = _safe_float(row.get("positional_rank"))
    rank_penalty = min(max(rank, 0.0), 300.0) / 15.0
    return round(points + starter_bonus + position_bonus - rank_penalty, 4)


def _review_reason(row: dict[str, Any]) -> str:
    method = str(row.get("match_method") or "").strip()
    if method in _REVIEW_REASON_LABELS:
        return _REVIEW_REASON_LABELS[method]
    if method:
        return f"Match method: {method}"
    return "No match reason provided."


def _recommended_action(row: dict[str, Any]) -> str:
    status = str(row.get("match_status") or "")
    method = str(row.get("match_method") or "")
    tier = str(row.get("impact_tier") or "low")

    if method == "manual_override" and status in {"exact_match", "deterministic_match", "fuzzy_match_reviewed"}:
        return "safely_resolved_this_pass"
    if status in {"ambiguous_duplicate"}:
        return "leave_unresolved_high_risk"
    if status == "unresolved":
        if method in _UNRESOLVED_HIGH_RISK_METHODS:
            return "leave_unresolved_high_risk"
        if tier in {"high", "medium"}:
            return "needs_canonical_input_or_manual_review"
        return "leave_unresolved_low_impact"
    if status == "fuzzy_match_reviewed":
        return "needs_manual_confirmation"
    return "matched"


def _enrich_identity_review_row(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    tier = _impact_tier(row)
    score = _impact_score(row)
    enriched["impact_tier"] = tier
    enriched["impact_score"] = score
    enriched["review_reason"] = _review_reason(row)
    enriched["recommended_action"] = _recommended_action(enriched)
    return enriched


def _sort_identity_review_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = [_enrich_identity_review_row(r) for r in rows]
    return sorted(
        enriched,
        key=lambda r: (
            _IMPACT_TIER_RANK.get(str(r.get("impact_tier") or "low"), 0),
            float(r.get("impact_score") or 0.0),
            float(_safe_float(r.get("projected_points"))),
            1 if bool(r.get("starter_projected")) else 0,
            str(r.get("player_name_source") or ""),
        ),
        reverse=True,
    )


def _identity_hardening_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    safely_resolved = [r for r in rows if str(r.get("recommended_action")) == "safely_resolved_this_pass"]
    unresolved = [r for r in rows if str(r.get("match_status") or "") == "unresolved"]
    likely_resolvable = [
        r for r in unresolved if str(r.get("recommended_action") or "") == "needs_canonical_input_or_manual_review"
    ]
    unresolved_high_risk = [r for r in unresolved if str(r.get("recommended_action") or "") == "leave_unresolved_high_risk"]
    unresolved_low_impact = [r for r in unresolved if str(r.get("recommended_action") or "") == "leave_unresolved_low_impact"]
    fuzzy_needs_confirmation = [r for r in rows if str(r.get("recommended_action") or "") == "needs_manual_confirmation"]

    return {
        "counts": {
            "safely_resolved_this_pass": len(safely_resolved),
            "still_unresolved_likely_resolvable_with_more_canonical_inputs": len(likely_resolvable),
            "intentionally_left_unresolved_high_risk": len(unresolved_high_risk),
            "intentionally_left_unresolved_low_impact": len(unresolved_low_impact),
            "fuzzy_matches_needing_manual_confirmation": len(fuzzy_needs_confirmation),
        },
        "safely_resolved_this_pass": safely_resolved,
        "still_unresolved_likely_resolvable_with_more_canonical_inputs": likely_resolvable,
        "intentionally_left_unresolved_high_risk": unresolved_high_risk,
        "intentionally_left_unresolved_low_impact": unresolved_low_impact,
        "fuzzy_matches_needing_manual_confirmation": fuzzy_needs_confirmation,
    }


def _conflicting_positions(normalized_players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in normalized_players:
        canonical_id = str(row.get("canonical_player_id") or "")
        if not canonical_id:
            continue
        grouped[canonical_id].add(str(row.get("position_canonical") or ""))
    out: list[dict[str, Any]] = []
    for canonical_id, positions in grouped.items():
        positions_clean = sorted(p for p in positions if p)
        if len(positions_clean) <= 1:
            continue
        out.append(
            {
                "canonical_player_id": canonical_id,
                "positions": positions_clean,
            }
        )
    out.sort(key=lambda x: x["canonical_player_id"])
    return out


def _conflicting_source_identities(normalized_players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in normalized_players:
        canonical_id = str(row.get("canonical_player_id") or "")
        if not canonical_id:
            continue
        grouped[canonical_id].add(str(row.get("player_name_source") or "").strip())
    out: list[dict[str, Any]] = []
    for canonical_id, names in grouped.items():
        unique_names = sorted(n for n in names if n)
        if len(unique_names) <= 1:
            continue
        out.append(
            {
                "canonical_player_id": canonical_id,
                "source_names": unique_names,
            }
        )
    out.sort(key=lambda x: x["canonical_player_id"])
    return out


def _duplicate_source_rows(normalized_players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_players:
        key = "|".join(
            [
                str(row.get("player_name_source") or "").strip().lower(),
                str(row.get("team_canonical") or "").strip().upper(),
                str(row.get("position_canonical") or "").strip().upper(),
            ]
        )
        grouped[key].append(row)
    out: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        if len(rows) <= 1:
            continue
        out.append(
            {
                "source_identity_key": key,
                "row_count": len(rows),
                "rows": rows[:5],
            }
        )
    out.sort(key=lambda x: x["source_identity_key"])
    return out


def _duplicate_canonical_matches(normalized_players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_players:
        canonical_id = str(row.get("canonical_player_id") or "").strip()
        if not canonical_id:
            continue
        grouped[canonical_id].append(row)
    out: list[dict[str, Any]] = []
    for canonical_id, rows in grouped.items():
        if len(rows) <= 1:
            continue
        out.append(
            {
                "canonical_player_id": canonical_id,
                "row_count": len(rows),
                "source_rows": [
                    {
                        "player_name_source": r.get("player_name_source"),
                        "team_canonical": r.get("team_canonical"),
                        "position_canonical": r.get("position_canonical"),
                        "positional_rank": r.get("positional_rank"),
                    }
                    for r in rows[:10]
                ],
            }
        )
    out.sort(key=lambda x: (-x["row_count"], x["canonical_player_id"]))
    return out


def _qa_ready_reasons(
    *,
    parse_success_rate: float,
    match_rate: float,
    normalized_players: list[dict[str, Any]],
    team_rows: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ready = True
    if parse_success_rate < READINESS_MIN_PARSE_SUCCESS_RATE:
        ready = False
        reasons.append(
            f"parse_success_rate_below_threshold ({parse_success_rate:.3f} < {READINESS_MIN_PARSE_SUCCESS_RATE:.3f})"
        )
    if match_rate < READINESS_MIN_MATCH_RATE:
        ready = False
        reasons.append(f"match_rate_below_threshold ({match_rate:.3f} < {READINESS_MIN_MATCH_RATE:.3f})")
    if len(normalized_players) < 200:
        ready = False
        reasons.append("too_few_player_rows_parsed")
    if len(team_rows) < 30:
        ready = False
        reasons.append("too_few_team_rows_parsed")
    if not reasons:
        reasons.append("all_readiness_thresholds_met")
    return ready, reasons


def run_mike_clay_import(
    pdf_path: str | Path,
    *,
    data_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    guide_year_hint: int | None = None,
    manual_match_overrides_path: str | Path | None = None,
    dynasty_data_path: str | Path | None = None,
    write_csv: bool = True,
) -> dict[str, Any]:
    run_started_at = _utc_now_iso()
    pdf = Path(pdf_path).resolve()
    if not pdf.exists():
        raise FileNotFoundError(f"Mike Clay PDF not found: {pdf}")

    root = repo_root()
    resolved_data_dir = Path(data_dir).resolve() if data_dir else canonical_data_dir(root)
    imports_root = Path(output_dir).resolve() if output_dir else (resolved_data_dir / "imports" / "mike_clay")

    log_steps: list[dict[str, Any]] = []
    step_started = _utc_now_iso()
    bundle = parse_mike_clay_pdf(pdf, guide_year_hint=guide_year_hint)
    log_steps.append(
        {
            "step": "parse_pdf",
            "started_at": step_started,
            "finished_at": _utc_now_iso(),
            "positional_rows": len(bundle.positional_rows),
            "warnings": len(bundle.warnings),
        }
    )

    step_started = _utc_now_iso()
    canonical_players, canonical_meta = load_canonical_players(
        resolved_data_dir,
        dynasty_data_path=Path(dynasty_data_path).resolve() if dynasty_data_path else None,
    )
    matcher = PlayerMatcher(canonical_players)
    duplicate_canonical_name_rows = duplicate_canonical_name_report(canonical_players)
    log_steps.append(
        {
            "step": "load_canonical_universe",
            "started_at": step_started,
            "finished_at": _utc_now_iso(),
            "canonical_player_count": len(canonical_players),
            "canonical_duplicates": len(duplicate_canonical_name_rows),
            "source_path": canonical_meta.get("sourcePath"),
        }
    )

    step_started = _utc_now_iso()
    manual_override_path = (
        Path(manual_match_overrides_path).resolve()
        if manual_match_overrides_path
        else (resolved_data_dir / "imports" / "mike_clay" / "manual_match_overrides.csv")
    )
    manual_overrides = load_manual_match_overrides(manual_override_path)
    team_context = _build_team_context(bundle)
    starter_index = _starter_lookup_index(bundle.starter_rows)

    import_timestamp = _utc_now_iso()
    normalized_players: list[dict[str, Any]] = []
    for idx, row in enumerate(bundle.positional_rows, start=1):
        team_source = str(row.get("team_source") or "")
        team_canonical = normalize_team_code(team_source)
        position_source = str(row.get("position_source") or "")
        position_canonical = normalize_position_code(position_source)
        override_row = manual_override_for_row(
            manual_overrides,
            player_name_source=str(row.get("player_name_source") or ""),
            team_source=team_source,
            position_source=position_source,
        )
        match = matcher.match(
            player_name_source=str(row.get("player_name_source") or ""),
            team_canonical=team_canonical,
            position_canonical=position_canonical,
            manual_override=override_row,
        )

        from src.utils import normalize_player_name

        name_norm = normalize_player_name(row.get("player_name_source"))
        starter_data = None
        for fallback_key in (
            f"{name_norm}|{team_canonical}|{position_canonical}",
            f"{name_norm}|{team_canonical}|",
            f"{name_norm}||{position_canonical}",
            f"{name_norm}||",
        ):
            starter_data = starter_index.get(fallback_key)
            if starter_data:
                break

        ctx = team_context.get(team_canonical, {})
        team_position_grade = _team_grade_for_position(ctx, position_canonical)
        normalized_players.append(
            {
                "row_id": idx,
                "canonical_player_id": match.canonical_player_id,
                "player_name_source": row.get("player_name_source"),
                "player_name_canonical": match.player_name_canonical,
                "team_source": team_source,
                "team_canonical": team_canonical,
                "position_source": position_source,
                "position_canonical": position_canonical,
                "positional_rank": row.get("positional_rank"),
                "projected_games": row.get("projected_games"),
                "projected_points": row.get("projected_points"),
                "passing_attempts": row.get("passing_attempts"),
                "passing_completions": row.get("passing_completions"),
                "passing_yards": row.get("passing_yards"),
                "passing_tds": row.get("passing_tds"),
                "interceptions": row.get("interceptions"),
                "sacks_taken": row.get("sacks_taken"),
                "rushing_attempts": row.get("rushing_attempts"),
                "rushing_yards": row.get("rushing_yards"),
                "rushing_tds": row.get("rushing_tds"),
                "targets": row.get("targets"),
                "receptions": row.get("receptions"),
                "receiving_yards": row.get("receiving_yards"),
                "receiving_tds": row.get("receiving_tds"),
                "carry_share_pct": row.get("carry_share_pct"),
                "target_share_pct": row.get("target_share_pct"),
                "idp_snaps": row.get("idp_snaps"),
                "idp_total_tackles": row.get("idp_total_tackles"),
                "idp_solo_tackles": row.get("idp_solo_tackles"),
                "idp_assist_tackles": row.get("idp_assist_tackles"),
                "idp_tfl": row.get("idp_tfl"),
                "idp_sacks": row.get("idp_sacks"),
                "idp_interceptions": row.get("idp_interceptions"),
                "idp_forced_fumbles": row.get("idp_forced_fumbles"),
                "starter_projected": bool(starter_data.get("starter_projected")) if starter_data else False,
                "starter_slot": starter_data.get("starter_slot") if starter_data else None,
                "team_projected_wins": ctx.get("projected_wins"),
                "team_projected_losses": ctx.get("projected_losses"),
                "team_projected_points_for": ctx.get("projected_points_for"),
                "team_projected_points_against": ctx.get("projected_points_against"),
                "team_strength_of_schedule_rank": ctx.get("strength_of_schedule_rank"),
                "team_offense_grade": ctx.get("offense_grade"),
                "team_defense_grade": ctx.get("defense_grade"),
                "team_total_grade": ctx.get("total_grade"),
                "team_offense_rank": ctx.get("offense_rank"),
                "team_defense_rank": ctx.get("defense_rank"),
                "team_total_rank": ctx.get("total_rank"),
                "team_head_coach": ctx.get("head_coach"),
                "team_position_grade": team_position_grade,
                "match_status": match.match_status,
                "match_confidence": match.match_confidence,
                "match_method": match.match_method,
                "match_candidates": match.candidate_names,
                "parse_confidence": row.get("parse_confidence"),
                "guide_year": bundle.guide_year,
                "guide_version": bundle.guide_updated_date,
                "source_file": bundle.source_file,
                "parser_version": bundle.parser_version,
                "import_timestamp": import_timestamp,
            }
        )
    log_steps.append(
        {
            "step": "normalize_and_match",
            "started_at": step_started,
            "finished_at": _utc_now_iso(),
            "normalized_players": len(normalized_players),
            "manual_override_count": len(manual_overrides),
        }
    )

    normalized_teams: list[dict[str, Any]] = []
    for team_code, row in sorted(team_context.items()):
        normalized_teams.append(
            {
                "canonical_team_id": team_code,
                "team_name_source": row.get("team_name_source"),
                "projected_wins": row.get("projected_wins"),
                "projected_losses": row.get("projected_losses"),
                "projected_points_for": row.get("projected_points_for"),
                "projected_points_against": row.get("projected_points_against"),
                "projected_point_diff": row.get("projected_point_diff"),
                "favored_games": row.get("favored_games"),
                "strength_of_schedule_rank": row.get("strength_of_schedule_rank"),
                "schedule_rank_from_standings": row.get("schedule_rank_from_standings"),
                "offense_grade": row.get("offense_grade"),
                "offense_rank": row.get("offense_rank"),
                "defense_grade": row.get("defense_grade"),
                "defense_rank": row.get("defense_rank"),
                "total_grade": row.get("total_grade"),
                "total_rank": row.get("total_rank"),
                "qb_grade": row.get("qb_grade"),
                "rb_grade": row.get("rb_grade"),
                "wr_grade": row.get("wr_grade"),
                "te_grade": row.get("te_grade"),
                "ol_grade": row.get("ol_grade"),
                "di_grade": row.get("di_grade"),
                "ed_grade": row.get("ed_grade"),
                "lb_grade": row.get("lb_grade"),
                "cb_grade": row.get("cb_grade"),
                "s_grade": row.get("s_grade"),
                "head_coach": row.get("head_coach"),
                "qb_unit_rank": row.get("qb_unit_rank"),
                "rb_unit_rank": row.get("rb_unit_rank"),
                "wr_unit_rank": row.get("wr_unit_rank"),
                "te_unit_rank": row.get("te_unit_rank"),
                "ol_unit_rank": row.get("ol_unit_rank"),
                "di_unit_rank": row.get("di_unit_rank"),
                "ed_unit_rank": row.get("ed_unit_rank"),
                "lb_unit_rank": row.get("lb_unit_rank"),
                "cb_unit_rank": row.get("cb_unit_rank"),
                "s_unit_rank": row.get("s_unit_rank"),
                "guide_year": bundle.guide_year,
                "guide_version": bundle.guide_updated_date,
                "source_file": bundle.source_file,
                "parser_version": bundle.parser_version,
                "import_timestamp": import_timestamp,
            }
        )

    unmatched_players = _sort_identity_review_rows([row for row in normalized_players if row.get("match_status") == "unresolved"])
    ambiguous_players = _sort_identity_review_rows(
        [row for row in normalized_players if row.get("match_status") == "ambiguous_duplicate"]
    )
    low_confidence_players = _sort_identity_review_rows(
        [
            row
            for row in normalized_players
            if float(row.get("match_confidence") or 0.0) < LOW_CONFIDENCE_THRESHOLD
        ]
    )
    conflicting_positions = _conflicting_positions(normalized_players)
    conflicting_source_identities = _conflicting_source_identities(normalized_players)
    duplicate_source_rows = _duplicate_source_rows(normalized_players)
    duplicate_canonical_matches = _duplicate_canonical_matches(normalized_players)
    counts = _build_counts(normalized_players)
    invalid_status_rows = [
        row
        for row in normalized_players
        if str(row.get("match_status") or "") not in MATCH_STATUS_VALUES
    ]

    parse_fail_count = len([w for w in bundle.warnings if str(w.get("type", "")).endswith("_parse_fail")])
    parse_success_rate = len(normalized_players) / max(1, len(normalized_players) + parse_fail_count)
    matched_count = len(normalized_players) - len(unmatched_players) - len(ambiguous_players)
    match_rate = matched_count / max(1, len(normalized_players))
    ready_for_formula_integration, readiness_reasons = _qa_ready_reasons(
        parse_success_rate=parse_success_rate,
        match_rate=match_rate,
        normalized_players=normalized_players,
        team_rows=normalized_teams,
    )

    guide_year_folder = str(bundle.guide_year or guide_year_hint or "unknown")
    run_id = f"mike_clay_{guide_year_folder}_{_timestamp_run_id()}"
    run_dir = imports_root / guide_year_folder / run_id
    raw_dir = run_dir / "raw"
    normalized_dir = run_dir / "normalized"
    reports_dir = run_dir / "reports"
    logs_dir = run_dir / "logs"
    review_dir = run_dir / "review"
    for directory in (raw_dir, normalized_dir, reports_dir, logs_dir, review_dir):
        directory.mkdir(parents=True, exist_ok=True)

    metadata = {
        "run_id": run_id,
        "status": "success",
        "source_file": str(pdf.name),
        "source_path": str(pdf),
        "guide_year": bundle.guide_year,
        "guide_version": bundle.guide_updated_date,
        "import_timestamp": import_timestamp,
        "parser_version": bundle.parser_version,
        "pipeline_version": IMPORT_PIPELINE_VERSION,
        "canonical_universe_source": canonical_meta.get("sourcePath"),
        "manual_override_path": str(manual_override_path) if manual_override_path.exists() else "",
        "ready_for_formula_integration": ready_for_formula_integration,
        "readiness_reasons": readiness_reasons,
    }
    identity_hardening_summary: dict[str, Any] = {"counts": {}}

    import_summary = {
        **metadata,
        "counts": {
            "positional_rows_parsed": len(bundle.positional_rows),
            "normalized_players": len(normalized_players),
            "normalized_teams": len(normalized_teams),
            "warnings": len(bundle.warnings),
            "parse_fail_count": parse_fail_count,
            "matched_count": matched_count,
            "unmatched_count": len(unmatched_players),
            "ambiguous_count": len(ambiguous_players),
            "low_confidence_count": len(low_confidence_players),
            "conflicting_positions_count": len(conflicting_positions),
            "conflicting_source_identities_count": len(conflicting_source_identities),
            "duplicate_source_row_count": len(duplicate_source_rows),
            "duplicate_canonical_matches_count": len(duplicate_canonical_matches),
            "canonical_duplicate_name_count": len(duplicate_canonical_name_rows),
            "invalid_match_status_count": len(invalid_status_rows),
        },
        "rates": {
            "parse_success_rate": round(parse_success_rate, 4),
            "match_rate": round(match_rate, 4),
        },
        "status_counts": counts.get("by_status", {}),
        "position_counts": counts.get("by_position", {}),
        "team_counts": counts.get("by_team", {}),
        "identity_hardening": identity_hardening_summary.get("counts", {}),
    }

    parse_anomaly_rows: list[dict[str, Any]] = []
    for warning in bundle.warnings:
        parse_anomaly_rows.append(
            {
                "type": warning.get("type"),
                "page": warning.get("page"),
                "section": warning.get("section"),
                "line": warning.get("line"),
                "segment": warning.get("segment"),
            }
        )

    review_candidate_rows: list[dict[str, Any]] = []
    for row in normalized_players:
        status = str(row.get("match_status") or "")
        method = str(row.get("match_method") or "")
        if status in {"unresolved", "ambiguous_duplicate", "fuzzy_match_reviewed"} or method == "manual_override":
            review_candidate_rows.append(row)

    manual_review_rows = _sort_identity_review_rows(review_candidate_rows)
    manual_review_rows = [
        {
            "player_name_source": row.get("player_name_source"),
            "team_source": row.get("team_source"),
            "team_canonical": row.get("team_canonical"),
            "position_source": row.get("position_source"),
            "position_canonical": row.get("position_canonical"),
            "canonical_player_id": row.get("canonical_player_id") or "",
            "player_name_canonical": row.get("player_name_canonical") or "",
            "projected_points": row.get("projected_points"),
            "starter_projected": row.get("starter_projected"),
            "match_status": row.get("match_status"),
            "match_confidence": row.get("match_confidence"),
            "match_method": row.get("match_method"),
            "impact_tier": row.get("impact_tier"),
            "impact_score": row.get("impact_score"),
            "review_reason": row.get("review_reason"),
            "recommended_action": row.get("recommended_action"),
            "notes": "",
        }
        for row in manual_review_rows
    ]
    identity_hardening_summary = _identity_hardening_summary(manual_review_rows)
    import_summary["identity_hardening"] = identity_hardening_summary.get("counts", {})

    save_json(run_dir / "import_metadata.json", metadata)
    save_json(raw_dir / "pages.json", bundle.pages)
    save_json(raw_dir / "positional_rows.json", bundle.positional_rows)
    save_json(raw_dir / "team_rows.json", bundle.team_rows)
    save_json(raw_dir / "sos_rows.json", bundle.sos_rows)
    save_json(raw_dir / "unit_grade_rows.json", bundle.unit_grade_rows)
    save_json(raw_dir / "unit_rank_rows.json", bundle.unit_rank_rows)
    save_json(raw_dir / "coaching_rows.json", bundle.coaching_rows)
    save_json(raw_dir / "starter_rows.json", bundle.starter_rows)

    save_json(normalized_dir / "mike_clay_players_normalized.json", normalized_players)
    save_json(normalized_dir / "mike_clay_teams_normalized.json", normalized_teams)

    save_json(reports_dir / "unmatched_players.json", unmatched_players)
    save_json(reports_dir / "ambiguous_players.json", ambiguous_players)
    save_json(reports_dir / "low_confidence_matches.json", low_confidence_players)
    save_json(reports_dir / "duplicate_name_report.json", duplicate_canonical_name_rows)
    save_json(reports_dir / "duplicate_source_rows.json", duplicate_source_rows)
    save_json(reports_dir / "duplicate_canonical_matches.json", duplicate_canonical_matches)
    save_json(reports_dir / "conflicting_positions.json", conflicting_positions)
    save_json(reports_dir / "conflicting_source_identities.json", conflicting_source_identities)
    save_json(reports_dir / "parse_anomaly_report.json", parse_anomaly_rows)
    save_json(reports_dir / "counts_by_position_team_status.json", counts)
    save_json(reports_dir / "identity_resolution_hardening_summary.json", identity_hardening_summary)
    save_json(reports_dir / "import_summary.json", import_summary)

    if write_csv:
        _write_rows_csv(raw_dir / "positional_rows.csv", bundle.positional_rows)
        _write_rows_csv(raw_dir / "team_rows.csv", bundle.team_rows)
        _write_rows_csv(raw_dir / "sos_rows.csv", bundle.sos_rows)
        _write_rows_csv(raw_dir / "unit_grade_rows.csv", bundle.unit_grade_rows)
        _write_rows_csv(raw_dir / "unit_rank_rows.csv", bundle.unit_rank_rows)
        _write_rows_csv(raw_dir / "coaching_rows.csv", bundle.coaching_rows)
        _write_rows_csv(raw_dir / "starter_rows.csv", bundle.starter_rows)
        _write_rows_csv(normalized_dir / "mike_clay_players_normalized.csv", normalized_players)
        _write_rows_csv(normalized_dir / "mike_clay_teams_normalized.csv", normalized_teams)
        _write_rows_csv(reports_dir / "unmatched_players.csv", unmatched_players)
        _write_rows_csv(reports_dir / "ambiguous_players.csv", ambiguous_players)
        _write_rows_csv(reports_dir / "low_confidence_matches.csv", low_confidence_players)
        _write_rows_csv(
            reports_dir / "identity_resolution_hardening_safely_resolved.csv",
            list(identity_hardening_summary.get("safely_resolved_this_pass") or []),
        )
        _write_rows_csv(
            reports_dir / "identity_resolution_hardening_still_unresolved_likely_resolvable.csv",
            list(identity_hardening_summary.get("still_unresolved_likely_resolvable_with_more_canonical_inputs") or []),
        )
        _write_rows_csv(
            reports_dir / "identity_resolution_hardening_intentionally_left_high_risk.csv",
            list(identity_hardening_summary.get("intentionally_left_unresolved_high_risk") or []),
        )
        _write_rows_csv(reports_dir / "parse_anomaly_report.csv", parse_anomaly_rows)
        _write_rows_csv(review_dir / "manual_match_review.csv", manual_review_rows)

    import_log = {
        "run_started_at": run_started_at,
        "run_finished_at": _utc_now_iso(),
        "steps": log_steps,
        "run_id": run_id,
        "status": "success",
    }
    save_json(logs_dir / "import_log.json", import_log)

    latest_payload = {
        **import_summary,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "normalized_players_path": str(normalized_dir / "mike_clay_players_normalized.json"),
        "normalized_teams_path": str(normalized_dir / "mike_clay_teams_normalized.json"),
        "unmatched_report_path": str(reports_dir / "unmatched_players.json"),
        "parse_anomaly_report_path": str(reports_dir / "parse_anomaly_report.json"),
    }
    save_json(imports_root / "mike_clay_import_latest.json", latest_payload)
    save_json(resolved_data_dir / "validation" / "mike_clay_import_status_latest.json", latest_payload)

    return latest_payload
