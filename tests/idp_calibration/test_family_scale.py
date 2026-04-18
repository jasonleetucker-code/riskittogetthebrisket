"""Cross-family IDP scaling layer.

Pins the math (``translation.compute_family_scale`` and
``translation.combine_family_scales``), the engine orchestration
(offense universe flows through + per-season scale lands in the
artifact), and the production read path (family_scale is applied
multiplicatively on top of the per-bucket multiplier).
"""
from __future__ import annotations

import math

from src.idp_calibration import engine, production, promotion, season_chain, storage
from src.idp_calibration.stats_adapter import HistoricalStatsAdapter, PlayerSeason
from src.idp_calibration.translation import (
    DEFAULT_BLEND,
    FamilyScale,
    combine_family_scales,
    compute_family_scale,
)


class TestComputeFamilyScale:
    def test_neutral_when_my_ratio_equals_test_ratio(self):
        scale = compute_family_scale(
            idp_vor_my=[100.0, 50.0, 20.0],
            idp_vor_test=[100.0, 50.0, 20.0],
            offense_vor_my=[400.0, 200.0],
            offense_vor_test=[400.0, 200.0],
        )
        assert abs(scale.intrinsic - 1.0) < 1e-9
        assert abs(scale.market - 1.0) < 1e-9
        assert abs(scale.final - 1.0) < 1e-9

    def test_my_league_values_idp_more_produces_scale_above_one(self):
        # My league: IDP produces 200 VOR, offense 400. Ratio = 0.50.
        # Test league: IDP produces 100 VOR, offense 400. Ratio = 0.25.
        # Intrinsic = 0.50 / 0.25 = 2.0 — IDP is twice as valuable in my
        # league relative to offense.
        scale = compute_family_scale(
            idp_vor_my=[200.0],
            idp_vor_test=[100.0],
            offense_vor_my=[400.0],
            offense_vor_test=[400.0],
        )
        assert abs(scale.intrinsic - 2.0) < 1e-9

    def test_sub_replacement_vor_is_ignored_in_sums(self):
        # Negative VOR contributions must not distort the "class value
        # bank" — we only sum above-replacement VOR.
        scale = compute_family_scale(
            idp_vor_my=[100.0, -50.0, -80.0],
            idp_vor_test=[100.0, -50.0, -80.0],
            offense_vor_my=[400.0, -100.0],
            offense_vor_test=[400.0, -100.0],
        )
        # Identical bank on both sides → scale = 1.0.
        assert abs(scale.intrinsic - 1.0) < 1e-9

    def test_scale_is_clamped_to_guard_rails(self):
        # Astronomical IDP-to-offense ratio (e.g. broken offense
        # scoring in one league) must not propagate as a 100x lift.
        scale = compute_family_scale(
            idp_vor_my=[1000.0],
            idp_vor_test=[1.0],
            offense_vor_my=[1.0],
            offense_vor_test=[1000.0],
            scale_max=4.0,
        )
        assert scale.intrinsic == 4.0

    def test_zero_offense_returns_neutral(self):
        # Guard against divide-by-zero when a side's offense universe
        # has no above-replacement VOR (e.g. empty universe).
        scale = compute_family_scale(
            idp_vor_my=[100.0],
            idp_vor_test=[100.0],
            offense_vor_my=[0.0, -10.0],   # no positive VOR
            offense_vor_test=[400.0],
        )
        assert scale.intrinsic == 1.0

    def test_blend_applies_to_final_channel(self):
        # With 75% intrinsic / 25% market, final should be the convex
        # combination of the two. Intrinsic computed as 2.0 above.
        scale = compute_family_scale(
            idp_vor_my=[200.0],
            idp_vor_test=[100.0],
            offense_vor_my=[400.0],
            offense_vor_test=[400.0],
            blend={"intrinsic": 0.75, "market": 0.25},
        )
        assert abs(scale.final - (0.75 * 2.0 + 0.25 * 1.0)) < 1e-9


class TestCombineFamilyScales:
    def test_weighted_mean_across_seasons(self):
        per_season = {
            2024: FamilyScale(intrinsic=1.2, market=1.0, final=1.15),
            2025: FamilyScale(intrinsic=1.4, market=1.0, final=1.30),
        }
        combined = combine_family_scales(per_season, {2024: 0.3, 2025: 0.7})
        # Weighted mean of intrinsic: 0.3 * 1.2 + 0.7 * 1.4 = 1.34
        assert abs(combined.intrinsic - 1.34) < 1e-9
        assert abs(combined.market - 1.0) < 1e-9

    def test_zero_weight_seasons_dropped(self):
        per_season = {
            2024: FamilyScale(intrinsic=5.0, market=1.0, final=3.0),
            2025: FamilyScale(intrinsic=1.2, market=1.0, final=1.1),
        }
        combined = combine_family_scales(per_season, {2024: 0.0, 2025: 1.0})
        assert abs(combined.intrinsic - 1.2) < 1e-9

    def test_empty_seasons_returns_neutral(self):
        combined = combine_family_scales({}, {})
        assert combined.intrinsic == 1.0
        assert combined.market == 1.0
        assert combined.final == 1.0


# ── Integration: end-to-end through the engine ──


class _MixedAdapter(HistoricalStatsAdapter):
    name = "mixed"

    def _fetch_impl(self, season):
        rows = []
        # 60 IDP players
        for i in range(60):
            pos = ("DL", "LB", "DB")[i % 3]
            rows.append(
                PlayerSeason(
                    player_id=f"idp_{i}",
                    name=f"IDP{i}",
                    position=pos,
                    games=16,
                    stats={
                        "idp_tkl_solo": 100 - i,
                        "idp_sack": max(0, 15 - i / 5),
                    },
                )
            )
        # 90 offense players (balanced across QB/RB/WR/TE)
        for i in range(90):
            pos = ("QB", "RB", "WR", "TE")[i % 4]
            rows.append(
                PlayerSeason(
                    player_id=f"off_{i}",
                    name=f"Off{i}",
                    position=pos,
                    games=16,
                    stats={
                        "pass_yd": max(0, 4500 - i * 30) if pos == "QB" else 0,
                        "pass_td": max(0, 35 - i / 2) if pos == "QB" else 0,
                        "rush_yd": max(0, 1400 - i * 10) if pos == "RB" else 0,
                        "rush_td": max(0, 14 - i / 4) if pos == "RB" else 0,
                        "rec": max(0, 100 - i) if pos in ("WR", "TE") else 0,
                        "rec_yd": max(0, 1400 - i * 10) if pos in ("WR", "TE") else 0,
                        "rec_td": max(0, 12 - i / 4) if pos in ("WR", "TE") else 0,
                    },
                )
            )
        return rows


def _chain_builder(
    *,
    idp_solo_my: float,
    idp_solo_test: float,
    mine_has_extra_flex: bool = True,
):
    """Return a chain fetcher that resolves just 2025."""

    def _builder(league_id, max_hops):
        is_mine = league_id == "MINE"
        positions = [
            "QB", "RB", "RB", "WR", "WR", "TE", "FLEX",
            "DL", "DL", "LB", "LB", "DB", "DB", "IDP_FLEX",
        ]
        if is_mine and mine_has_extra_flex:
            positions.append("IDP_FLEX")
        positions += ["BN"] * 6
        return [
            {
                "league_id": f"{league_id}_2025",
                "season": 2025,
                "previous_league_id": "",
                "scoring_settings": {
                    "idp_tkl_solo": idp_solo_my if is_mine else idp_solo_test,
                    "idp_sack": 4.0,
                    "pass_yd": 0.04,
                    "pass_td": 4.0,
                    "rush_yd": 0.1,
                    "rush_td": 6.0,
                    "rec": 1.0,
                    "rec_yd": 0.1,
                    "rec_td": 6.0,
                },
                "roster_positions": positions,
                "total_rosters": 12,
            }
        ]

    return _builder


def test_engine_emits_family_scale_in_artifact(monkeypatch):
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        _chain_builder(idp_solo_my=1.5, idp_solo_test=1.0),
    )
    settings = engine.AnalysisSettings(seasons=[2025])
    art = engine.run_analysis(
        "TEST", "MINE", settings, stats_adapter_factory=lambda s: _MixedAdapter()
    )
    assert "family_scale" in art
    fs = art["family_scale"]
    # My league has heavier IDP scoring (1.5× solo) + an extra IDP flex,
    # so intrinsic must come out > 1.0 (IDP is worth more per unit of
    # offense in my league vs test).
    assert fs["intrinsic"] > 1.0
    assert fs["final"] > 1.0
    # Each season also emits a family_scale in per_season.
    assert art["per_season"]["2025"]["family_scale"] is not None
    # And the recommendation block surfaces the family-scale line.
    assert any("IDP family scale" in line for line in art["recommendation"]["summary_lines"])


def test_engine_neutral_when_leagues_are_identical(monkeypatch):
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        _chain_builder(idp_solo_my=1.0, idp_solo_test=1.0, mine_has_extra_flex=False),
    )
    settings = engine.AnalysisSettings(seasons=[2025])
    art = engine.run_analysis(
        "TEST", "MINE", settings, stats_adapter_factory=lambda s: _MixedAdapter()
    )
    fs = art["family_scale"]
    # Identical leagues produce neutral scale. Allow a tiny numerical
    # wobble but it should be well under 1%.
    assert abs(fs["intrinsic"] - 1.0) < 0.01
    assert abs(fs["final"] - 1.0) < 0.01


# ── Production read path: family_scale is applied multiplicatively ──


def _write_config(path, *, family_scale_final, dl_bucket_final):
    """Helper: write a minimal promoted config with a family scale and
    one DL bucket so we can verify the multiplicative combination."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "active_mode": "blended",
                "family_scale": {
                    "intrinsic": family_scale_final,
                    "market": 1.0,
                    "final": family_scale_final,
                },
                "multipliers": {
                    "DL": {
                        "position": "DL",
                        "buckets": [
                            {
                                "label": "1-6",
                                "intrinsic": dl_bucket_final,
                                "market": dl_bucket_final,
                                "final": dl_bucket_final,
                                "count": 10,
                            },
                        ],
                    },
                },
                "anchors": {},
            }
        )
    )


def test_production_combines_family_scale_with_bucket(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    _write_config(cfg_path, family_scale_final=1.3, dl_bucket_final=0.5)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()
    # Expected: 1.3 (family) × 0.5 (bucket) = 0.65.
    assert abs(production.get_idp_bucket_multiplier("DL", 1) - 0.65) < 1e-9


def test_production_family_scale_missing_is_identity(tmp_path, monkeypatch):
    # Pre-Family-Scale promoted configs must keep working. Absent
    # family_scale block → family lift = 1.0 (identity).
    import json

    cfg_path = tmp_path / "config" / "idp_calibration.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "active_mode": "blended",
                "multipliers": {
                    "DL": {
                        "position": "DL",
                        "buckets": [
                            {
                                "label": "1-6",
                                "intrinsic": 0.5,
                                "market": 0.5,
                                "final": 0.5,
                                "count": 10,
                            },
                        ],
                    },
                },
                "anchors": {},
            }
        )
    )
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()
    assert abs(production.get_idp_bucket_multiplier("DL", 1) - 0.5) < 1e-9


def test_production_family_scale_insane_value_clamped(tmp_path, monkeypatch):
    # Defend against a hand-edited config with a nonsense value.
    # compute_family_scale bounds outputs at [0.25, 4.0]; production
    # re-clamps at read time so even an operator-edited config with
    # a bogus value can't corrupt the board.
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    _write_config(cfg_path, family_scale_final=100.0, dl_bucket_final=0.5)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()
    # 100 clamped to 4.0, then × 0.5 = 2.0.
    assert abs(production.get_idp_bucket_multiplier("DL", 1) - 2.0) < 1e-9


def test_promotion_persists_family_scale(tmp_path, monkeypatch):
    """End-to-end: run_analysis → storage.save_run → promotion.promote_run
    → production config contains the family_scale block."""
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        _chain_builder(idp_solo_my=1.5, idp_solo_test=1.0),
    )
    settings = engine.AnalysisSettings(seasons=[2025])
    art = engine.run_analysis(
        "TEST", "MINE", settings, stats_adapter_factory=lambda s: _MixedAdapter()
    )
    storage.save_run(art, base=tmp_path)
    result = promotion.promote_run(
        art["run_id"], active_mode="blended", base=tmp_path
    )
    assert result["ok"] is True
    cfg_path = promotion.production_config_path(tmp_path)
    import json

    promoted = json.loads(cfg_path.read_text())
    assert "family_scale" in promoted
    assert promoted["family_scale"]["intrinsic"] > 1.0
    assert promoted["family_scale"]["final"] > 1.0
