"""Read-only fixture tests for league scoring and roster fingerprint/drift."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "scripts" / "audit_league_settings.py"
spec = importlib.util.spec_from_file_location("audit_league_settings", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    snapshot = {
        "league_id": "1312006700437352448",
        "season": "2026",
        "settings": {
            "num_teams": 12, "best_ball": 1, "taxi_slots": 0, "leg": 7,
            "daily_waivers_last_ran": 20, "playoff_teams": 7,
        },
        "roster_positions": ["QB", "TE", "SUPER_FLEX", "DL", "BN", "BN"],
        "scoring_settings": {"bonus_rec_te": 0, "idp_qb_hit": 2.13, "pass_td": 6},
    }
    registry = {"leagues": [{
        "key": "dynasty_main", "sleeperLeagueId": snapshot["league_id"],
        "bestBall": True,
        "rosterSettings": {
            "teamCount": 12, "rosterSize": 6, "taxiSize": 0,
            "starters": {"QB": 1, "TE": 1, "SFLEX": 1, "DL": 1},
        },
    }]}
    return registry, snapshot


def test_matching_rules_and_starter_alias():
    reg, snap = fixture()
    report = mod.audit(reg, snap, snap["league_id"])
    assert report["status"] == "MATCH"
    assert report["sleeper_shape"]["starters"]["SUPER_FLEX"] == 1


def test_scoring_fingerprint_is_stable_across_key_order_and_progress():
    _reg, snap = fixture()
    old = mod.fingerprint(snap)
    changed = {
        **snap,
        "scoring_settings": dict(reversed(list(snap["scoring_settings"].items()))),
        "settings": {**snap["settings"], "leg": 8, "daily_waivers_last_ran": 21},
    }
    assert mod.fingerprint(changed) == old


def test_material_scoring_change_alters_fingerprint():
    _reg, snap = fixture()
    altered = {
        **snap,
        "scoring_settings": {**snap["scoring_settings"], "idp_qb_hit": 3},
    }
    assert mod.fingerprint(altered) != mod.fingerprint(snap)


def test_roster_drift_is_reported():
    reg, snap = fixture()
    reg["leagues"][0]["rosterSettings"]["starters"]["TE"] = 2
    out = mod.audit(reg, snap, snap["league_id"])
    assert out["status"] == "DRIFT"
    assert out["drift"][0]["setting"] == "starters"


def test_wrong_league_is_fail_closed():
    reg, snap = fixture()
    snap["league_id"] = "other"
    with pytest.raises(ValueError, match="does not match"):
        mod.audit(reg, snap, "1312006700437352448")


def test_missing_scoring_fails_not_zero_filled():
    reg, snap = fixture()
    del snap["scoring_settings"]
    with pytest.raises(ValueError, match="scoring_settings"):
        mod.audit(reg, snap, "1312006700437352448")
