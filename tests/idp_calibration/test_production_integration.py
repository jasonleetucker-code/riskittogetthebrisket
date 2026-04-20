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


def test_end_to_end_values_are_monotonic_with_ranks_after_calibration(tmp_path, monkeypatch):
    """With calibration active, ``rankDerivedValue`` is the weighted
    Hill-curve blend from per-source ranks times the calibration
    multiplier. It is NOT re-snapped to ``rank_to_value(int rank)`` —
    that was the old Phase 5b behaviour, which threw away the
    fractional-rank nuance (Josh Allen at source ranks [1,1,1,2,1]
    gets a blended ~9976, not the integer-rank Hill(1)=9999).

    What we lock in instead:
      * ranks are a strict sort of ranked values (monotonic)
      * each ranked row carries pre-calibration rank + value
        snapshots so the /rankings toggle can swap coherently
      * values past the offense top-tier bear the signature of
        calibration (at least one IDP row has a non-unit multiplier
        stamp when meaningful buckets are promoted)
    """
    from src.api.data_contract import build_api_data_contract

    cfg_path = tmp_path / "config" / "idp_calibration.json"
    config = {
        "version": 1,
        "active_mode": "blended",
        "multipliers": {
            "final": {
                "DL": {"1-6": 1.5, "7-12": 0.5},
            },
        },
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()

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
    ranked = sorted(
        [r for r in contract["playersArray"] if r.get("canonicalConsensusRank")],
        key=lambda r: int(r["canonicalConsensusRank"]),
    )
    # Invariant 1: values decrease (or tie) as rank increases.
    for a, b in zip(ranked, ranked[1:]):
        assert int(a["rankDerivedValue"]) >= int(b["rankDerivedValue"]), (
            f"Value inversion: rank {a['canonicalConsensusRank']} "
            f"({a['rankDerivedValue']}) < rank {b['canonicalConsensusRank']} "
            f"({b['rankDerivedValue']})"
        )
    # Invariant 2: every ranked row carries the pre-calibration
    # snapshot so the /rankings toggle can reconstruct the
    # uncalibrated board coherently.
    for row in ranked:
        assert "canonicalConsensusRankUncalibrated" in row
        assert "rankDerivedValueUncalibrated" in row
    # Invariant 3: at least one DL row carries the calibration stamp
    # — otherwise the test isn't actually exercising the multiplier
    # path.
    stamped = [r for r in ranked if r.get("idpCalibrationMultiplier")]
    assert stamped, "No row was stamped with idpCalibrationMultiplier"


def test_idp_lookup_interpolates_anchor_curve_no_cliffs(tmp_path, monkeypatch):
    """Consecutive ranks must never produce a cliff greater than the
    neighbouring anchor-to-anchor slope. Pinning this guards against
    someone accidentally re-introducing step-function bucket lookup
    in production.py — the old behaviour produced 48-90% cliffs at
    bucket boundaries (e.g. LB6 ≠ LB7 by 0.67).
    """
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    # Realistic-shape config with bucket-derived multipliers AND an
    # anchor curve between them. Live runs always include both.
    config = {
        "version": 1,
        "active_mode": "blended",
        "multipliers": {
            "LB": {
                "position": "LB",
                "buckets": [
                    {"label": "1-6",   "final": 1.00, "count": 6},
                    {"label": "7-12",  "final": 0.67, "count": 6},
                    {"label": "13-24", "final": 0.40, "count": 12},
                    {"label": "25-36", "final": 0.07, "count": 12},
                    {"label": "37-60", "final": 0.05, "count": 24},
                ],
            },
        },
        "anchors": {
            "final": {
                "LB": [
                    {"rank": 1, "value": 1.00},
                    {"rank": 3, "value": 1.00},
                    {"rank": 6, "value": 1.00},
                    {"rank": 12, "value": 0.67},
                    {"rank": 24, "value": 0.40},
                    {"rank": 36, "value": 0.07},
                    {"rank": 48, "value": 0.05},
                    {"rank": 72, "value": 0.05},
                    {"rank": 100, "value": 0.05},
                ],
            },
        },
    }
    save_json(cfg_path, config)
    monkeypatch.setattr(production, "production_config_path", lambda base=None: cfg_path)
    production.reset_cache()

    # Sample every rank from 1..48 and verify no adjacent cliff > 8%.
    # 8% is a generous ceiling — piecewise-linear interpolation
    # between anchor points should hold each step to the local anchor
    # slope, which is at most a few percent per rank on this curve.
    prev = production.get_idp_bucket_multiplier("LB", 1)
    max_adjacent_drop = 0.0
    for r in range(2, 49):
        curr = production.get_idp_bucket_multiplier("LB", r)
        drop = prev - curr
        if drop > max_adjacent_drop:
            max_adjacent_drop = drop
        prev = curr
    assert max_adjacent_drop < 0.08, (
        f"Adjacent-rank cliff of {max_adjacent_drop:.3f} exceeds smoothness "
        "budget — production.py probably regressed to step-function bucket lookup."
    )
    # Spot-check interpolation: rank 9 sits halfway between anchor 6
    # (value 1.00) and anchor 12 (value 0.67), so interpolated value
    # should be ~0.835 (halfway).
    mid = production.get_idp_bucket_multiplier("LB", 9)
    assert 0.82 < mid < 0.85, f"rank 9 interpolation off — got {mid}"


def test_live_pipeline_does_not_apply_offense_calibration(tmp_path, monkeypatch):
    """Offense calibration is deliberately NOT applied to live values
    even when a promoted config has offense_multipliers populated. The
    lab still computes the analysis, but offense trade value should
    stay anchored to the market-derived rankings — VOR bucket
    multipliers produce artefacts (QB cliffs, Mahomes-at-half-of-QB1)
    that don't survive user review. Re-promoting offense from the lab
    is a no-op on the live board.
    """
    from src.api.data_contract import build_api_data_contract

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
    qbs = [r for r in contract["playersArray"] if r.get("position") == "QB"]
    for row in qbs:
        assert "offenseCalibrationMultiplier" not in row, (
            f"Offense calibration was applied to {row.get('canonicalName')!r} — "
            "post-pass should be disabled."
        )
