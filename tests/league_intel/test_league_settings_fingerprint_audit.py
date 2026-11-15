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
            "num_teams": 12,
            "best_ball": 1,
            "taxi_slots": 0,
            "leg": 7,
            "daily_waivers_last_ran": 20,
            "playoff_teams": 7,
        },
        "roster_positions": ["QB", "TE", "SUPER_FLEX", "DL", "BN", "BN"],
        "scoring_settings": {"bonus_rec_te": 0, "idp_qb_hit": 2.13, "pass_td": 6},
    }
    registry = {
        "leagues": [
            {
                "key": "dynasty_main",
                "sleeperLeagueId": snapshot["league_id"],
                "bestBall": True,
                "rosterSettings": {
                    "teamCount": 12,
                    "rosterSize": 6,
                    "taxiSize": 0,
                    "starters": {"QB": 1, "TE": 1, "SFLEX": 1, "DL": 1},
                },
            }
        ]
    }
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


def test_archived_registry_and_snapshot_match_2026_07_26():
    """Historical parity proof only — NOT a check of current Sleeper settings."""
    root = Path(__file__).resolve().parents[2]
    registry = mod._read_json(root / "config/leagues/registry.json")
    snapshot = mod._read_json(root / "config/league_intel/sleeper_league_snapshot_2026-07-26.json")
    result = mod.audit(registry, snapshot, "1312006700437352448")
    assert result["status"] == "MATCH"
    assert result["scoring_keys"] == 141
    assert result["sleeper_shape"]["roster_size"] == 58
    assert sum(result["sleeper_shape"]["starters"].values()) == 21
    assert result["sleeper_shape"]["starters"]["TE"] == 2
    assert sum(result["sleeper_shape"]["starters"][key] for key in ("DL", "LB", "DB")) == 9
    assert snapshot["scoring_settings"]["bonus_rec_te"] == 0


# ── LI1842 checkbox 1: live October 2026 reconciliation ─────────────────────
#
# The tests below pin COMMITTED evidence (no network).  They prove the archived
# 2026-10-26 live fetch is internally consistent and that its drift against the
# 2026-07-26 snapshot is exactly what the audit document reports.  They do NOT
# prove Sleeper's CURRENT settings: only ``--live`` does that.

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "docs" / "audits" / "evidence"
MAIN_ID = "1312006700437352448"
NEW_ID = "1320092771247222784"
JULY_SNAPSHOT = ROOT / "config" / "league_intel" / "sleeper_league_snapshot_2026-07-26.json"
LANE_A_SCORING_FINGERPRINT = "sf1:9e51824690d091f9"  # IDP accuracy Lane A pin (PR #1931)
LANE_A_ROSTER_FINGERPRINT = "rf1:10f897578eea2fe4"

DRIFTED_KEYS = {
    "bonus_fd_qb": (0.67, 0.4),
    "bonus_rec_wr": (0.0, 0.02),
    "idp_blk_kick": (5.32, 5.3),
    "idp_def_td": (6.38, 6.36),
    "idp_ff": (4.25, 4.24),
    "idp_int": (5.32, 5.3),
    "idp_pass_def": (5.32, 5.3),
    "idp_qb_hit": (2.13, 2.12),
    "idp_safe": (5.32, 5.3),
    "idp_tkl_loss": (4.25, 4.24),
    "pass_cmp": (0.15, 0.37),
    "pass_inc": (-0.22, -0.67),
    "pass_yd": (0.03333333333333333, 0.04),
    "rec": (0.08, 0.1),
    "rec_0_4": (0.17, 0.25),
    "rec_10_19": (0.67, 0.75),
    "rec_20_29": (0.92, 1.0),
    "rec_30_39": (1.17, 1.25),
    "rec_40p": (1.92, 2.0),
    "rec_5_9": (0.42, 0.5),
    "rush_att": (0.08, 0.01),
}
ZERO_ADDED_KEYS = {
    "blk_kick_ret_yd",
    "bonus_rush_td_qb",
    "fgm_50_59",
    "idp_tkl",
    "pass_td_50p",
    "rec_td_50p",
    "rush_td_50p",
}


def _evidence(name: str) -> dict:
    return mod._read_json(EVIDENCE_DIR / name)


def test_scoring_card_diff_separates_changed_added_removed_and_zero_keys():
    out = mod.scoring_card_diff(
        {"rec": 1, "pass_td": 4, "gone": 2.0, "gone_zero": 0},
        {"rec": 1.0, "pass_td": 6, "new": 0.5, "new_zero": 0.0},
    )
    assert [row["key"] for row in out["changed"]] == ["pass_td"]
    assert {row["key"]: row["is_zero"] for row in out["added"]} == {
        "new": False,
        "new_zero": True,
    }
    assert {row["key"]: row["is_zero"] for row in out["removed"]} == {
        "gone": False,
        "gone_zero": True,
    }
    # 1 changed + 1 non-zero added + 1 non-zero removed; `1` vs `1.0` is not a change
    assert out["rate_changes"] == 3
    assert out["status"] == "SCORING_DRIFT"


def test_zero_only_additions_are_not_scoring_drift():
    out = mod.scoring_card_diff({"rec": 1.0}, {"rec": 1.0, "fgm_50_59": 0.0})
    assert out["rate_changes"] == 0
    assert out["status"] == "SCORING_MATCH"


def test_non_numeric_scoring_value_fails_closed_not_zero_filled():
    with pytest.raises((ValueError, TypeError)):
        mod.scoring_card_diff({"rec": 1.0}, {"rec": "lots"})
    with pytest.raises(ValueError):
        mod.scoring_card_diff(None, {"rec": 1.0})


def test_report_carries_canonical_sf1_and_no_baseline_block_by_default():
    reg, snap = fixture()
    report = mod.audit(reg, snap, snap["league_id"])
    assert report["scoring_fingerprint_sf1"] == mod.canonical_scoring_fingerprint(
        snap["scoring_settings"]
    )
    assert str(report["scoring_fingerprint_sf1"]).startswith("sf1:")
    assert "scoring_baseline" not in report


def test_baseline_for_a_different_league_is_refused():
    reg, snap = fixture()
    other = {**snap, "league_id": "someone-else"}
    with pytest.raises(ValueError, match="Baseline league_id"):
        mod.audit(reg, snap, snap["league_id"], other)


def test_registry_match_says_nothing_about_scoring():
    """MATCH is roster shape only: the registry carries no scoring card."""
    reg, snap = fixture()
    drifted = {**snap, "scoring_settings": {**snap["scoring_settings"], "pass_td": 4}}
    report = mod.audit(reg, drifted, snap["league_id"], snap)
    assert report["status"] == "MATCH"
    assert report["scoring_baseline"]["status"] == "SCORING_DRIFT"


def test_committed_live_evidence_is_internally_consistent_and_matches_lane_a_pin():
    evidence = _evidence("league_rules_dynasty_main_2026-10-26.json")
    meta = evidence["evidence"]
    assert meta["fetchedAtUtc"] == "2026-10-26T08:25:58Z"
    assert meta["scoringFingerprint"] == LANE_A_SCORING_FINGERPRINT
    assert meta["rosterFormatFingerprint"] == LANE_A_ROSTER_FINGERPRINT
    # The stamp is a cache of the card: it must agree with the card it describes.
    assert (
        mod.canonical_scoring_fingerprint(evidence["scoring_settings"])
        == (meta["scoringFingerprint"])
    )
    assert len(evidence["scoring_settings"]) == 148
    # transient progress keys are not evidence
    assert not set(mod.NON_RULE_SETTINGS) & set(evidence["settings"])


def test_live_dynasty_main_registry_roster_shape_matches_2026_10_26():
    registry = mod._read_json(mod.DEFAULT_REGISTRY)
    report = mod.audit(registry, _evidence("league_rules_dynasty_main_2026-10-26.json"), MAIN_ID)
    assert report["status"] == "MATCH", report["drift"]
    assert report["sleeper_shape"]["roster_size"] == 58
    assert report["sleeper_shape"]["teams"] == 12
    assert report["sleeper_shape"]["best_ball"] is True
    assert report["sleeper_shape"]["starters"]["TE"] == 2
    assert report["rules_fingerprint"] == (
        "aeed26b858b779ff0daa5371ca4817995176419ec4c23826827de2b77cc2d138"
    )


def test_live_card_drifted_from_2026_07_26_snapshot_on_exactly_the_reported_keys():
    snapshot = mod._read_json(JULY_SNAPSHOT)
    registry = mod._read_json(mod.DEFAULT_REGISTRY)
    report = mod.audit(
        registry,
        _evidence("league_rules_dynasty_main_2026-10-26.json"),
        MAIN_ID,
        snapshot,
    )
    base = report["scoring_baseline"]
    assert base["status"] == "SCORING_DRIFT"
    assert base["baseline_sf1"] == "sf1:b7ad1575925091f6"
    assert base["observed_sf1"] == LANE_A_SCORING_FINGERPRINT
    assert base["baseline_keys"] == 141 and base["observed_keys"] == 148
    assert {row["key"]: (row["baseline"], row["observed"]) for row in base["changed"]} == (
        DRIFTED_KEYS
    )
    assert {row["key"] for row in base["added"]} == ZERO_ADDED_KEYS
    assert all(row["is_zero"] for row in base["added"])
    assert base["removed"] == []
    assert base["rate_changes"] == 21
    # tight end: still no scoring premium on the live card
    live = _evidence("league_rules_dynasty_main_2026-10-26.json")["scoring_settings"]
    assert live["bonus_rec_te"] == 0
    assert live["bonus_fd_te"] == live["bonus_fd_wr"] == live["bonus_fd_rb"] == 1.0


def test_dynasty_new_card_is_unchanged_since_its_2026_08_25_snapshot():
    snapshot = mod._read_json(
        ROOT / "config" / "league_intel" / "dynasty_new" / "sleeper_league_snapshot_2026-08-25.json"
    )
    registry = mod._read_json(mod.DEFAULT_REGISTRY)
    report = mod.audit(
        registry, _evidence("league_rules_dynasty_new_2026-10-26.json"), NEW_ID, snapshot
    )
    assert report["scoring_baseline"]["status"] == "SCORING_MATCH"
    assert report["scoring_fingerprint_sf1"] == "sf1:82a5f8ef2bfdb098"
    # and the two leagues' factual scoring identities really differ, whatever
    # their shared scoringProfile LABEL says (W18-F001)
    assert report["scoring_fingerprint_sf1"] != LANE_A_SCORING_FINGERPRINT


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LI1842-DRIFT-02: config/leagues/registry.json dynasty_new.rosterSettings.rosterSize "
        "is 27 but the live roster_positions has 24 slots (BN 17 -> 14 since the 2026-08-25 "
        "snapshot).  Remove this marker when the registry is reconciled (owner decision: "
        "whether rosterSize is len(roster_positions) or includes taxi/reserve)."
    ),
)
def test_dynasty_new_registry_roster_size_matches_live():
    registry = mod._read_json(mod.DEFAULT_REGISTRY)
    report = mod.audit(registry, _evidence("league_rules_dynasty_new_2026-10-26.json"), NEW_ID)
    assert report["status"] == "MATCH", report["drift"]
