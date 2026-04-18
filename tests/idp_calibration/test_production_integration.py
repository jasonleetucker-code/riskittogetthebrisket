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
    # QB untouched.
    assert rows[0]["rankDerivedValue"] == 9000
    # DL rank 1 and rank 2 both in bucket 1-6 => 0.5x multiplier. The
    # post-pass mutates rankDerivedValue so the global re-sort (in
    # build_api_data_contract) moves the row to a new merged rank.
    # Phase 5b then recomputes the value from the Hill curve on the
    # landed rank — snapshots are taken BEFORE the post-pass runs at
    # the build_api_data_contract level, not here. So the tests only
    # assert on the post-pass's multiplication output.
    dl_rows = [r for r in rows if r["position"] == "DL"]
    assert dl_rows[0]["rankDerivedValue"] == 2500  # 5000 * 0.5
    assert dl_rows[1]["rankDerivedValue"] == 1500  # 3000 * 0.5
    # LB scaled up
    lb = next(r for r in rows if r["position"] == "LB")
    assert lb["rankDerivedValue"] == 6000
    # DB scaled up
    db = next(r for r in rows if r["position"] == "DB")
    assert db["rankDerivedValue"] == 4000


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


def test_end_to_end_keeps_value_on_hill_curve_after_calibration(tmp_path, monkeypatch):
    """Core invariant of the rank-shift calibration: after
    ``build_api_data_contract`` runs, every ranked row's
    ``rankDerivedValue`` equals ``rank_to_value(canonicalConsensusRank)``
    — i.e. the value is always on the Hill curve at the player's final
    rank. No orphan multiplied numbers, always on the 1-9999 scale.
    """
    from src.api.data_contract import build_api_data_contract
    from src.canonical.player_valuation import rank_to_value

    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "version": 1,
        "active_mode": "blended",
        # Meaningful IDP calibration — DL 1-6 scaled up, DL 7-12 down.
        # Drives real rank reshuffles so we exercise the re-sort path.
        "multipliers": {
            "final": {
                "DL": {"1-6": 1.5, "7-12": 0.5},
            },
        },
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()

    # Minimal payload with a mix of positions so re-sort is exercised.
    players = {}
    for i in range(1, 8):
        players[f"Zzz DL {i:02d}"] = {
            "_composite": 8000 - i * 500,
            "_rawComposite": 8000 - i * 500,
            "_finalAdjusted": 8000 - i * 500,
            "_sites": 1,
            "position": "DL",
            "team": "TST",
            "_canonicalSiteValues": {"idpTradeCalc": 8000 - i * 500},
        }
    for i in range(1, 8):
        players[f"Zzz WR {i:02d}"] = {
            "_composite": 9000 - i * 400,
            "_rawComposite": 9000 - i * 400,
            "_finalAdjusted": 9000 - i * 400,
            "_sites": 1,
            "position": "WR",
            "team": "TST",
            "_canonicalSiteValues": {"ktc": 9000 - i * 400},
        }
    payload = {
        "players": players,
        "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktc": 9999, "idpTradeCalc": 9999},
        "sleeper": {"positions": {n: v["position"] for n, v in players.items()}},
    }
    contract = build_api_data_contract(payload)
    ranked = [r for r in contract["playersArray"] if r.get("canonicalConsensusRank")]
    # Invariant: every row's rankDerivedValue is exactly rank_to_value
    # of its final canonicalConsensusRank. Calibration moves rows
    # AROUND the board, but their landed value is always on the curve.
    for row in ranked:
        expected = int(rank_to_value(int(row["canonicalConsensusRank"])))
        assert row["rankDerivedValue"] == expected, (
            f"{row.get('canonicalName')!r} at rank "
            f"{row['canonicalConsensusRank']} has value "
            f"{row['rankDerivedValue']} but Hill curve says {expected}"
        )
    # And: snapshots exist on every ranked row so the /rankings toggle
    # has both a pre-calibration rank AND value to swap to.
    for row in ranked:
        assert "canonicalConsensusRankUncalibrated" in row
        assert "rankDerivedValueUncalibrated" in row


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
    # Post-pass only multiplies rankDerivedValue to drive the global
    # re-sort in build_api_data_contract; Phase 5b snaps the final
    # value back onto the Hill curve. These assertions pin the
    # intermediate multiplication step.
    # QB rank 1 is in 1-6 -> 1.10x; QB rank 2 is also in 1-6 -> 1.10x
    assert rows[0]["rankDerivedValue"] == 9900  # 9000 * 1.10
    assert rows[1]["rankDerivedValue"] == 9350  # 8500 * 1.10
    # WR -> 0.95x, TE -> 1.20x
    assert rows[2]["rankDerivedValue"] == 6650  # 7000 * 0.95
    assert rows[3]["rankDerivedValue"] == 7200  # 6000 * 1.20
    # IDP row untouched
    assert rows[4]["rankDerivedValue"] == 4000


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


def test_live_pipeline_rank_shift_keeps_value_on_hill_curve_offense(tmp_path, monkeypatch):
    """Offense calibration is applied as a rank SHIFT: the multiplier
    nudges rankDerivedValue pre-re-sort so the row lands at a new
    merged rank, then Phase 5b snaps the value back onto the Hill
    curve at the landed rank. The final value is always coherent with
    the rank on the 1-9999 scale — no orphan multiplied numbers.
    """
    from src.api.data_contract import build_api_data_contract
    from src.canonical.player_valuation import rank_to_value

    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "version": 1,
        "active_mode": "blended",
        "multipliers": {},
        "offense_multipliers": {
            "final": {
                "QB": {"1-6": 1.0, "7-12": 0.5},
            },
        },
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()

    # 7 QBs — QB7 falls in 7-12 and gets 0.5x, which drops him down the
    # merged board. His landed rank's Hill-curve value is what he ends
    # up with.
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
    ranked = [r for r in contract["playersArray"] if r.get("canonicalConsensusRank")]
    # Every ranked row's rankDerivedValue == rank_to_value(rank).
    for row in ranked:
        expected = int(rank_to_value(int(row["canonicalConsensusRank"])))
        assert row["rankDerivedValue"] == expected
    # QB7 carries the offense calibration stamp from the post-pass.
    qb7 = next(
        r for r in ranked
        if r.get("canonicalName") == "Zzz QB 07"
    )
    assert qb7.get("offenseCalibrationMultiplier") == 0.5
    # QB7's uncalibrated snapshot lets the toggle reconstruct the
    # pre-calibration view instantly.
    assert qb7.get("canonicalConsensusRankUncalibrated") is not None
    assert qb7.get("rankDerivedValueUncalibrated") is not None
