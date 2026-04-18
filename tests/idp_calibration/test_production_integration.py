"""Verify the promoted config flows into the live valuation pipeline.

Tests the integration point in ``src/api/data_contract.py``:
``_apply_idp_calibration_post_pass`` is called after Phase 4 and
multiplies ``rankDerivedValue`` for IDP rows only.
"""
from __future__ import annotations

from src.api.data_contract import _apply_idp_calibration_post_pass
from src.idp_calibration import production
from src.idp_calibration.promotion import production_config_path
from src.utils.config_loader import save_json


def _rows():
    return [
        {"position": "QB", "rankDerivedValue": 9000},
        {"position": "DL", "rankDerivedValue": 5000},
        {"position": "DL", "rankDerivedValue": 3000},
        {"position": "LB", "rankDerivedValue": 4000},
        {"position": "DB", "rankDerivedValue": 2000},
    ]


def test_no_config_is_strict_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "production_config_path", lambda base=None: tmp_path / "config/idp_calibration.json")
    monkeypatch.setattr(
        "src.api.data_contract._idp_production.production_config_path",
        lambda base=None: tmp_path / "config/idp_calibration.json",
        raising=False,
    )
    production.reset_cache()
    rows = _rows()
    before = [r["rankDerivedValue"] for r in rows]
    _apply_idp_calibration_post_pass(rows, {})
    after = [r["rankDerivedValue"] for r in rows]
    assert before == after


def test_promoted_multipliers_scale_only_idp(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "version": 1,
        "active_mode": "blended",
        "multipliers": {
            "final": {
                "DL": {"1-6": 0.5, "7-12": 0.5, "13-24": 0.5},
                "LB": {"1-6": 1.5},
                "DB": {"1-6": 2.0},
            }
        },
        "anchors": {},
    }
    save_json(cfg_path, config)
    # Point the production loader at our temp config.
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()

    rows = _rows()
    _apply_idp_calibration_post_pass(rows, {})
    # QB untouched (no snapshot either — offense rows are never touched)
    assert rows[0]["rankDerivedValue"] == 9000
    assert "rankDerivedValueUncalibrated" not in rows[0]
    # DL rank 1 and rank 2 both in bucket 1-6 => 0.5x
    dl_rows = [r for r in rows if r["position"] == "DL"]
    assert dl_rows[0]["rankDerivedValue"] == 2500  # 5000 * 0.5
    assert dl_rows[1]["rankDerivedValue"] == 1500  # 3000 * 0.5
    # Pre-calibration snapshots preserved so the frontend toggle can
    # swap the display instantly without refetching.
    assert dl_rows[0]["rankDerivedValueUncalibrated"] == 5000
    assert dl_rows[1]["rankDerivedValueUncalibrated"] == 3000
    # LB scaled up
    lb = next(r for r in rows if r["position"] == "LB")
    assert lb["rankDerivedValue"] == 6000
    assert lb["rankDerivedValueUncalibrated"] == 4000
    # DB scaled up
    db = next(r for r in rows if r["position"] == "DB")
    assert db["rankDerivedValue"] == 4000
    assert db["rankDerivedValueUncalibrated"] == 2000


def test_empty_bucket_config_is_identity_not_anchor_floor(tmp_path, monkeypatch):
    """A promoted config with no real bucket data must be a no-op, NOT a
    ~95% value cut via the anchor floor."""
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    # Count = 0 on every bucket; anchors look convincing but are all 0.05.
    config = {
        "active_mode": "blended",
        "multipliers": {
            "DL": {"position": "DL", "buckets": [
                {"label": "1-6", "intrinsic": 0.05, "market": 0.05, "final": 0.05, "count": 0},
            ]},
        },
        "anchors": {
            "final": {
                "DL": [{"rank": 1, "value": 0.05}, {"rank": 100, "value": 0.05}],
            },
        },
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()
    # Must return identity, not 0.05.
    assert production.get_idp_bucket_multiplier("DL", 1) == 1.0
    assert production.get_idp_bucket_multiplier("DL", 50) == 1.0


def test_position_alias_collapses_to_canonical(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "active_mode": "blended",
        "multipliers": {"final": {"DL": {"1-6": 0.5}}},
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()
    rows = [{"position": "EDGE", "rankDerivedValue": 4000}]
    _apply_idp_calibration_post_pass(rows, {})
    assert rows[0]["rankDerivedValue"] == 2000  # EDGE -> DL -> 0.5x
    assert rows[0]["rankDerivedValueUncalibrated"] == 4000


def test_snapshot_populated_even_when_multiplier_is_identity(tmp_path, monkeypatch):
    """IDP rows that happen to land in a 1.0 bucket still get a
    pre-calibration snapshot so the frontend toggle works uniformly
    across every IDP row regardless of bucket position."""
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "active_mode": "blended",
        "multipliers": {"final": {"DL": {"1-6": 1.0}}},
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()
    rows = [{"position": "DL", "rankDerivedValue": 4000}]
    _apply_idp_calibration_post_pass(rows, {})
    assert rows[0]["rankDerivedValue"] == 4000
    assert rows[0]["rankDerivedValueUncalibrated"] == 4000
