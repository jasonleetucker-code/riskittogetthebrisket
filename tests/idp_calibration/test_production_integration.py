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


def test_offense_multipliers_scale_only_offense(tmp_path, monkeypatch):
    """Promoted offense calibration multiplies QB/RB/WR/TE rows by the
    per-bucket factor and leaves IDP rows untouched."""
    from src.api.data_contract import _apply_offense_calibration_post_pass

    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "version": 1,
        "active_mode": "blended",
        "multipliers": {},
        "offense_multipliers": {
            "final": {
                "QB": {"1-6": 1.10, "7-12": 1.05},
                "WR": {"1-6": 0.95},
                "TE": {"1-6": 1.20},
            },
        },
        "anchors": {},
        "offense_anchors": {},
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()

    rows = [
        {"position": "QB", "rankDerivedValue": 9000},
        {"position": "QB", "rankDerivedValue": 8500},
        {"position": "WR", "rankDerivedValue": 7000},
        {"position": "TE", "rankDerivedValue": 6000},
        {"position": "DL", "rankDerivedValue": 4000},
    ]
    _apply_offense_calibration_post_pass(rows, {})
    # QB rank 1 is in 1-6 -> 1.10x; QB rank 2 is also in 1-6 -> 1.10x
    assert rows[0]["rankDerivedValue"] == 9900  # 9000 * 1.10
    assert rows[1]["rankDerivedValue"] == 9350  # 8500 * 1.10
    # WR -> 0.95x, TE -> 1.20x
    assert rows[2]["rankDerivedValue"] == 6650  # 7000 * 0.95
    assert rows[3]["rankDerivedValue"] == 7200  # 6000 * 1.20
    # IDP row untouched
    assert rows[4]["rankDerivedValue"] == 4000
    assert "rankDerivedValueUncalibrated" not in rows[4]
    # Snapshots on offense rows
    assert rows[0]["rankDerivedValueUncalibrated"] == 9000
    assert rows[2]["rankDerivedValueUncalibrated"] == 7000
    assert rows[3]["rankDerivedValueUncalibrated"] == 6000


def test_offense_post_pass_noop_when_block_absent(tmp_path, monkeypatch):
    """Pre-offense-calibration promoted configs (no offense_multipliers
    block at all) must be a strict no-op — backward compat with runs
    promoted before this feature shipped."""
    from src.api.data_contract import _apply_offense_calibration_post_pass

    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "active_mode": "blended",
        "multipliers": {"final": {"DL": {"1-6": 0.5}}},
        # no offense_multipliers key at all
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()
    rows = [{"position": "QB", "rankDerivedValue": 9000}]
    _apply_offense_calibration_post_pass(rows, {})
    assert rows[0]["rankDerivedValue"] == 9000
    assert "rankDerivedValueUncalibrated" not in rows[0]


def test_live_pipeline_does_not_apply_offense_calibration(tmp_path, monkeypatch):
    """Even with a fully-populated offense_multipliers block in the
    promoted config, the live pipeline must leave offense values
    untouched. Offense trade value is anchored to market-derived
    rankings; VOR-based bucket multipliers would override a well-
    calibrated market with a thin season-points-only signal. The lab
    still surfaces the offense analysis for reference but the post-
    pass call site is intentionally disabled.
    """
    from src.api.data_contract import build_api_data_contract

    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "version": 1,
        "active_mode": "blended",
        "multipliers": {},  # no IDP multipliers either — isolate offense
        "offense_multipliers": {
            "QB": {
                "position": "QB",
                "buckets": [
                    {"label": "1-6", "final": 1.0, "count": 6},
                    {"label": "7-12", "final": 0.50, "count": 6},
                ],
            },
        },
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()

    # Build a minimal valid-shape payload with 7 QBs so QB7 would be
    # in the 7-12 bucket and get 0.50x *if* the post-pass ran.
    players = {}
    for i in range(1, 8):
        name = f"Zzz QB {i:02d}"
        players[name] = {
            "_composite": 10000 - i * 500,
            "_rawComposite": 10000 - i * 500,
            "_finalAdjusted": 10000 - i * 500,
            "_sites": 1,
            "position": "QB",
            "team": "TST",
            "_canonicalSiteValues": {"ktc": 10000 - i * 500},
        }
    payload = {
        "players": players,
        "sites": [{"key": "ktc"}],
        "maxValues": {"ktc": 9999},
        "sleeper": {"positions": {name: "QB" for name in players}},
    }
    contract = build_api_data_contract(payload)
    rows = sorted(
        [r for r in contract["playersArray"] if r.get("position") == "QB"],
        key=lambda r: -int(r.get("rankDerivedValue") or 0),
    )
    # QB7 should still be at its original rankDerivedValue range — not
    # halved by the offense post-pass. We assert that no offense row
    # has an ``offenseCalibrationMultiplier`` stamp (which the post-
    # pass would set on rows it touched).
    for row in rows:
        assert "offenseCalibrationMultiplier" not in row, (
            f"Offense calibration was applied to {row.get('canonicalName')!r} — "
            "the post-pass call should be disabled."
        )
