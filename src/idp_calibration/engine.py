"""Top-level orchestrator for the IDP calibration lab.

``run_analysis`` takes two Sleeper league IDs plus optional advanced
settings and returns a fully populated run artifact dict that matches
the schema documented in ``docs/idp_calibration_lab.md``. The
artifact is self-contained — no shared mutable state — so the
storage layer can persist it as JSON and the frontend can render it
directly.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .anchors import DEFAULT_ANCHOR_RANKS, anchors_to_dict, build_all_anchors
from .buckets import DEFAULT_BUCKETS, BucketResult, bucketize, buckets_to_dict
from .lineup import LineupDemand, parse_lineup
from .replacement import ReplacementSettings, compute_replacement_levels, replacement_to_dict
from .scoring import LeagueScoring, parse_scoring
from .season_chain import DEFAULT_SEASONS, LeagueChain, resolve_seasons
from .stats_adapter import (
    AdapterUnavailable,
    HistoricalStatsAdapter,
    PlayerSeason,
    get_stats_adapter,
)
from .translation import (
    DEFAULT_BLEND,
    DEFAULT_YEAR_WEIGHTS,
    build_multi_year_multipliers,
    multipliers_to_dict,
    normalise_year_weights,
)
from .vor import (
    ScoredPlayer,
    VorRow,
    build_universe,
    compute_vor,
    score_universe,
    trim_to_top_n_per_position,
    vor_rows_to_dict,
)

POSITIONS: tuple[str, ...] = ("DL", "LB", "DB")


def _safe_int(value: Any, default: int) -> int:
    """Coerce ``value`` to int; return ``default`` on any parse error.

    Keeps malformed client payloads (e.g. ``"min_games": "abc"``) from
    bubbling a ``ValueError`` out of :meth:`AnalysisSettings.from_payload`
    as a 500 response. Callers should combine this with a value-level
    clamp where a negative or zero fallback is not safe.
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _safe_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class AnalysisSettings:
    seasons: list[int] = field(default_factory=lambda: list(DEFAULT_SEASONS))
    replacement: ReplacementSettings = field(default_factory=ReplacementSettings)
    bucket_edges: list[list[int]] = field(
        default_factory=lambda: [list(edge) for edge in DEFAULT_BUCKETS]
    )
    min_bucket_size: int = 3
    blend: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BLEND))
    year_weights: dict[int, float] = field(
        default_factory=lambda: dict(DEFAULT_YEAR_WEIGHTS)
    )
    anchor_ranks: list[int] = field(default_factory=lambda: list(DEFAULT_ANCHOR_RANKS))
    anchor_floor: float = 0.05
    min_games: int = 0
    top_n: int | None = None

    @staticmethod
    def from_payload(payload: dict[str, Any] | None) -> "AnalysisSettings":
        payload = payload or {}
        seasons_raw = payload.get("seasons") or DEFAULT_SEASONS
        try:
            seasons = [int(s) for s in seasons_raw]
        except (TypeError, ValueError):
            seasons = list(DEFAULT_SEASONS)
        replacement_raw = payload.get("replacement") or {}
        manual_raw = (replacement_raw or {}).get("manual") or {}
        manual_safe: dict[str, int] = {}
        if isinstance(manual_raw, dict):
            for k, v in manual_raw.items():
                parsed = _safe_int(v, 0)
                if parsed > 0:
                    manual_safe[str(k)] = parsed
        replacement = ReplacementSettings(
            mode=str(replacement_raw.get("mode") or "starter_plus_buffer"),
            buffer_pct=_safe_float(replacement_raw.get("buffer_pct"), 0.15),
            manual=manual_safe,
        )
        bucket_edges_raw = payload.get("bucket_edges") or [list(e) for e in DEFAULT_BUCKETS]
        bucket_edges: list[list[int]] = []
        for edge in bucket_edges_raw:
            try:
                lo, hi = int(edge[0]), int(edge[1])
                if lo <= hi:
                    bucket_edges.append([lo, hi])
            except (TypeError, ValueError, IndexError):
                continue
        if not bucket_edges:
            bucket_edges = [list(e) for e in DEFAULT_BUCKETS]
        blend_raw = payload.get("blend") or DEFAULT_BLEND
        blend = {
            "intrinsic": max(0.0, min(1.0, _safe_float(blend_raw.get("intrinsic"), 0.75))),
            "market": 0.0,
        }
        blend["market"] = round(1.0 - blend["intrinsic"], 6)
        year_weights_raw = payload.get("year_weights") or DEFAULT_YEAR_WEIGHTS
        year_weights: dict[int, float] = {}
        for k, v in year_weights_raw.items():
            try:
                year_weights[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
        if not year_weights:
            year_weights = dict(DEFAULT_YEAR_WEIGHTS)
        anchors = payload.get("anchor_ranks") or DEFAULT_ANCHOR_RANKS
        try:
            anchor_ranks = sorted({int(a) for a in anchors})
        except (TypeError, ValueError):
            anchor_ranks = list(DEFAULT_ANCHOR_RANKS)
        min_games = max(0, _safe_int(payload.get("min_games"), 0))
        top_n_raw = _safe_int(payload.get("top_n"), 0)
        top_n = top_n_raw if top_n_raw > 0 else None
        anchor_floor = max(0.0, min(1.0, _safe_float(payload.get("anchor_floor"), 0.05)))
        min_bucket_size = max(1, _safe_int(payload.get("min_bucket_size"), 3))
        return AnalysisSettings(
            seasons=seasons,
            replacement=replacement,
            bucket_edges=bucket_edges,
            min_bucket_size=min_bucket_size,
            blend=blend,
            year_weights=year_weights,
            anchor_ranks=anchor_ranks,
            anchor_floor=anchor_floor,
            min_games=min_games,
            top_n=top_n,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seasons": list(self.seasons),
            "replacement": {
                "mode": self.replacement.mode,
                "buffer_pct": self.replacement.buffer_pct,
                "manual": dict(self.replacement.manual),
            },
            "bucket_edges": [list(e) for e in self.bucket_edges],
            "min_bucket_size": self.min_bucket_size,
            "blend": dict(self.blend),
            "year_weights": {str(k): v for k, v in self.year_weights.items()},
            "anchor_ranks": list(self.anchor_ranks),
            "anchor_floor": self.anchor_floor,
            "min_games": self.min_games,
            "top_n": self.top_n,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_run_id(test_id: str, my_id: str, seasons: list[int]) -> str:
    basis = f"{test_id}|{my_id}|{','.join(str(s) for s in seasons)}|{_utc_now_iso()}"
    short = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:6]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{short}"


def _build_universe_for_season(
    season: int,
    *,
    adapter: HistoricalStatsAdapter | None = None,
    settings: AnalysisSettings,
) -> tuple[list[PlayerSeason], list[str], str]:
    """Return (universe, warnings, adapter_name) for a single season."""
    warnings: list[str] = []
    adapter_name = "none"
    if adapter is None:
        adapter, attempts = get_stats_adapter(season)
        adapter_name = adapter.name
        if adapter_name == "manual_fallback":
            warnings.append(
                f"{season}: stats unavailable via any adapter. Attempts: "
                + "; ".join(attempts)
            )
    else:
        adapter_name = adapter.name
    try:
        raw = adapter.fetch(season)
    except AdapterUnavailable as exc:
        warnings.append(f"{season}: {exc}")
        raw = []
    universe = build_universe(raw, min_games=settings.min_games)
    return universe, warnings, adapter_name


def run_analysis(
    test_league_id: str,
    my_league_id: str,
    settings: AnalysisSettings | None = None,
    *,
    stats_adapter_factory=None,
) -> dict[str, Any]:
    """Execute the full calibration analysis and return a run artifact.

    ``stats_adapter_factory`` is an optional ``(season) -> adapter`` hook
    used by tests to inject deterministic stats without hitting the
    network. When omitted, :func:`get_stats_adapter` picks the best
    adapter per season.
    """
    settings = settings or AnalysisSettings()
    settings_dict = settings.to_dict()
    warnings: list[str] = []

    test_chain = resolve_seasons(test_league_id, seasons=settings.seasons)
    my_chain = resolve_seasons(my_league_id, seasons=settings.seasons)
    warnings.extend(test_chain.warnings)
    warnings.extend(my_chain.warnings)

    per_season_payload: dict[int, dict[str, Any]] = {}
    per_season_per_position_buckets: dict[str, dict[int, list[BucketResult]]] = {
        pos: {} for pos in POSITIONS
    }
    resolved_seasons: list[int] = []

    for season in sorted({int(s) for s in settings.seasons}):
        test_res = test_chain.seasons.get(season)
        my_res = my_chain.seasons.get(season)
        if not (test_res and test_res.resolved and my_res and my_res.resolved):
            per_season_payload[season] = {
                "season": season,
                "resolved": False,
                "reason": (
                    (test_res.reason if test_res else "")
                    + " | "
                    + (my_res.reason if my_res else "")
                ).strip(" |"),
            }
            continue

        test_scoring = parse_scoring(test_res.league)
        my_scoring = parse_scoring(my_res.league)
        test_lineup = parse_lineup(test_res.league)
        my_lineup = parse_lineup(my_res.league)

        adapter = stats_adapter_factory(season) if stats_adapter_factory else None
        universe, stats_warnings, adapter_name = _build_universe_for_season(
            season, adapter=adapter, settings=settings
        )
        warnings.extend(stats_warnings)

        if not universe:
            per_season_payload[season] = {
                "season": season,
                "resolved": False,
                "reason": f"No usable stats for {season} (adapter={adapter_name}).",
                "adapter": adapter_name,
            }
            continue

        scored = score_universe(universe, test_scoring.idp_weights, my_scoring.idp_weights)
        if settings.top_n:
            scored = trim_to_top_n_per_position(scored, settings.top_n)
        repl_test_levels = compute_replacement_levels(
            ({"position": p.position, "points": p.points_test} for p in scored),
            test_lineup,
            settings.replacement,
        )
        repl_mine_levels = compute_replacement_levels(
            ({"position": p.position, "points": p.points_mine} for p in scored),
            my_lineup,
            settings.replacement,
        )
        replacement_test = {
            pos: lv.replacement_points for pos, lv in repl_test_levels.items()
        }
        replacement_mine = {
            pos: lv.replacement_points for pos, lv in repl_mine_levels.items()
        }
        vor_rows = compute_vor(scored, replacement_test, replacement_mine)

        position_buckets: dict[str, list[BucketResult]] = {}
        for pos in POSITIONS:
            buckets = bucketize(
                vor_rows,
                pos,
                buckets=[tuple(edge) for edge in settings.bucket_edges],
                min_bucket_size=settings.min_bucket_size,
            )
            position_buckets[pos] = buckets
            per_season_per_position_buckets[pos][season] = buckets

        per_season_payload[season] = {
            "season": season,
            "resolved": True,
            "adapter": adapter_name,
            "universe_size": len(universe),
            "test_scoring": test_scoring.summary(),
            "my_scoring": my_scoring.summary(),
            "test_lineup": test_lineup.to_dict(),
            "my_lineup": my_lineup.to_dict(),
            "replacement_test": replacement_to_dict(repl_test_levels),
            "replacement_mine": replacement_to_dict(repl_mine_levels),
            "buckets": {pos: buckets_to_dict(b) for pos, b in position_buckets.items()},
            "sample_vor_rows": vor_rows_to_dict(vor_rows)[:120],
        }
        resolved_seasons.append(season)

    normalised_weights = normalise_year_weights(
        settings.year_weights, seasons=resolved_seasons
    )
    multipliers = build_multi_year_multipliers(
        per_season_per_position_buckets,
        year_weights=normalised_weights,
        blend=settings.blend,
    )
    anchors = build_all_anchors(
        multipliers,
        anchor_ranks=settings.anchor_ranks,
        floor=settings.anchor_floor,
    )

    recommendation = _build_recommendation(multipliers, warnings)

    run_id = _make_run_id(test_league_id, my_league_id, settings.seasons)

    artifact: dict[str, Any] = {
        "run_id": run_id,
        "generated_at": _utc_now_iso(),
        "schema_version": 1,
        "inputs": {
            "test_league_id": str(test_league_id or ""),
            "my_league_id": str(my_league_id or ""),
        },
        "settings": settings_dict,
        "normalised_year_weights": {str(k): v for k, v in normalised_weights.items()},
        "resolved_seasons": resolved_seasons,
        "chains": {
            "test": test_chain.to_dict(),
            "mine": my_chain.to_dict(),
        },
        "per_season": {str(k): v for k, v in per_season_payload.items()},
        "multipliers": multipliers_to_dict(multipliers),
        "anchors": anchors_to_dict(anchors),
        "recommendation": recommendation,
        "warnings": warnings,
    }
    return artifact


def _build_recommendation(
    multipliers: dict[str, Any], warnings: list[str]
) -> dict[str, Any]:
    """Produce a plain-language summary block for the UI."""
    lines: list[str] = []
    notes: list[str] = []
    per_position: dict[str, dict[str, Any]] = {}
    for pos, pm in multipliers.items():
        if not pm.buckets:
            notes.append(f"No multiplier data available for {pos}.")
            continue
        # Compare the mid-tier (3rd bucket if available, otherwise last)
        idx = min(2, len(pm.buckets) - 1)
        mid = pm.buckets[idx]
        direction = "neutral"
        if mid.intrinsic > mid.market * 1.03:
            direction = "undervalued-by-market"
            lines.append(
                f"{pos}: my-league intrinsic value exceeds test-league market "
                f"at bucket {mid.label} by {((mid.intrinsic / max(mid.market, 1e-6)) - 1) * 100:.1f}%."
            )
        elif mid.market > mid.intrinsic * 1.03:
            direction = "overvalued-by-market"
            lines.append(
                f"{pos}: test-league market values bucket {mid.label} "
                f"{((mid.market / max(mid.intrinsic, 1e-6)) - 1) * 100:.1f}% higher than my-league intrinsic."
            )
        else:
            lines.append(f"{pos}: intrinsic and market align within 3% at {mid.label}.")
        per_position[pos] = {
            "direction": direction,
            "mid_bucket": mid.label,
            "intrinsic": mid.intrinsic,
            "market": mid.market,
            "final": mid.final,
        }
    if warnings:
        notes.append(f"{len(warnings)} warning(s) during analysis — review before promoting.")
    return {
        "summary_lines": lines,
        "notes": notes,
        "per_position": per_position,
        "recommended_mode": "blended",
    }
