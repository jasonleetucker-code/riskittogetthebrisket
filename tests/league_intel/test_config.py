"""LI-1 — canonical league config: loading, validation, refresh/drift."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_intel import config as li_config
from src.league_intel.config import (
    CONFIG_VERSION,
    LeagueConfigError,
    build_config_from_snapshot,
    diff_league_config,
    find_latest_snapshot,
    load_canonical_config,
    refresh_snapshot,
)

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "config" / "league_intel"


# ── Loading the real committed snapshot ───────────────────────────────


class TestLoadCanonicalConfig:
    def test_loads_latest_snapshot(self):
        cfg = load_canonical_config()
        assert cfg.config_version == CONFIG_VERSION == 1
        assert cfg.sleeper_league_id == "1312006700437352448"
        assert cfg.season == "2026"
        assert cfg.sourced_at >= "2026-07-26"

    def test_scoring_settings_full_141_keys(self):
        cfg = load_canonical_config()
        assert len(cfg.scoring_settings) == 141
        assert all(isinstance(v, float) for v in cfg.scoring_settings.values())
        # Audit-pinned spot rates (SETTINGS_AUDIT.md)
        assert cfg.scoring_settings["pass_int"] == -4.0
        assert cfg.scoring_settings["pass_int_td"] == -2.0
        assert cfg.scoring_settings["rec"] == 0.08
        assert cfg.scoring_settings["fgm"] == 0.0
        assert cfg.scoring_settings["fgm_yds"] == 0.07
        assert cfg.scoring_settings["idp_tkl_solo"] == 1.33

    def test_roster_slot_structure_21_starters(self):
        cfg = load_canonical_config()
        assert len(cfg.starter_slots) == 21
        assert dict(cfg.starter_counts) == {
            "QB": 1,
            "RB": 2,
            "WR": 3,
            "TE": 2,
            "FLEX": 2,
            "SUPER_FLEX": 1,
            "K": 1,
            "DL": 3,
            "LB": 3,
            "DB": 3,
        }
        assert cfg.bench_slots == 37
        assert cfg.roster_size == 58

    def test_league_shape_settings(self):
        cfg = load_canonical_config()
        assert cfg.team_count == 12
        assert cfg.best_ball is True
        assert cfg.playoff_teams == 7
        assert cfg.playoff_week_start == 15
        assert cfg.taxi_slots == 0
        assert cfg.reserve_slots == 0
        assert cfg.draft_rounds == 6
        assert cfg.waiver_budget == 100

    def test_to_dict_round_trip_fields(self):
        d = load_canonical_config().to_dict()
        assert d["configVersion"] == 1
        assert d["rosterSize"] == 58
        assert d["starterCounts"]["TE"] == 2
        assert len(d["scoringSettings"]) == 141


# ── Validation failures ───────────────────────────────────────────────


def _minimal_snapshot() -> dict:
    raw = json.loads(find_latest_snapshot().read_text())
    return raw


class TestValidation:
    def test_missing_league_id_rejected(self):
        raw = _minimal_snapshot()
        raw["league_id"] = ""
        with pytest.raises(LeagueConfigError, match="league_id"):
            build_config_from_snapshot(raw, snapshot_path=Path("x.json"))

    def test_missing_scoring_rejected(self):
        raw = _minimal_snapshot()
        raw["scoring_settings"] = {}
        with pytest.raises(LeagueConfigError, match="scoring_settings"):
            build_config_from_snapshot(raw, snapshot_path=Path("x.json"))

    def test_truncated_scoring_rejected(self):
        raw = _minimal_snapshot()
        raw["scoring_settings"] = {"pass_yd": 0.04}
        with pytest.raises(LeagueConfigError, match="required keys"):
            build_config_from_snapshot(raw, snapshot_path=Path("x.json"))

    def test_non_numeric_rate_rejected(self):
        raw = _minimal_snapshot()
        raw["scoring_settings"]["pass_yd"] = "lots"
        with pytest.raises(LeagueConfigError, match="non-numeric"):
            build_config_from_snapshot(raw, snapshot_path=Path("x.json"))

    def test_missing_roster_positions_rejected(self):
        raw = _minimal_snapshot()
        raw["roster_positions"] = []
        with pytest.raises(LeagueConfigError, match="roster_positions"):
            build_config_from_snapshot(raw, snapshot_path=Path("x.json"))

    def test_bench_only_roster_rejected(self):
        raw = _minimal_snapshot()
        raw["roster_positions"] = ["BN", "BN"]
        with pytest.raises(LeagueConfigError, match="starter"):
            build_config_from_snapshot(raw, snapshot_path=Path("x.json"))

    def test_roster_count_mismatch_rejected(self):
        raw = _minimal_snapshot()
        raw["total_rosters"] = 10  # settings.num_teams stays 12
        with pytest.raises(LeagueConfigError, match="total_rosters"):
            build_config_from_snapshot(raw, snapshot_path=Path("x.json"))

    def test_empty_dir_raises(self, tmp_path):
        with pytest.raises(LeagueConfigError, match="no league snapshot"):
            find_latest_snapshot(tmp_path)


# ── Refresh + drift ───────────────────────────────────────────────────


def _seed_dir(tmp_path: Path) -> Path:
    stored = _minimal_snapshot()
    (tmp_path / "sleeper_league_snapshot_2026-07-01.json").write_text(json.dumps(stored))
    return tmp_path


class TestRefreshSnapshot:
    def test_no_drift_no_write(self, tmp_path):
        d = _seed_dir(tmp_path)
        live = _minimal_snapshot()
        live["last_message_id"] = "999999"  # chatter must not read as drift
        live["settings"] = dict(live["settings"], leg=9, last_scored_leg=8)
        drift = refresh_snapshot(snapshot_dir=d, fetcher=lambda url: live)
        assert drift.has_drift is False
        assert drift.new_snapshot is None
        assert len(list(d.glob("*.json"))) == 1  # nothing written

    def test_scoring_drift_reported_and_new_snapshot_written(self, tmp_path):
        d = _seed_dir(tmp_path)
        live = _minimal_snapshot()
        live["scoring_settings"] = dict(live["scoring_settings"], rec=0.5)
        drift = refresh_snapshot(snapshot_dir=d, fetcher=lambda url: live)
        assert drift.has_drift is True
        assert drift.scoring_changed == {"rec": (0.08, 0.5)}
        assert drift.new_snapshot is not None and drift.new_snapshot.exists()
        # Old snapshot untouched (report, not mutation)
        old = json.loads((d / "sleeper_league_snapshot_2026-07-01.json").read_text())
        assert old["scoring_settings"]["rec"] == 0.08
        # New snapshot becomes the one load_canonical_config picks up
        assert find_latest_snapshot(d) == drift.new_snapshot
        assert load_canonical_config(d).scoring_settings["rec"] == 0.5

    def test_roster_drift_flagged(self, tmp_path):
        d = _seed_dir(tmp_path)
        live = _minimal_snapshot()
        live["roster_positions"] = [p for p in live["roster_positions"] if p != "K"]
        live["settings"] = dict(live["settings"])
        drift = refresh_snapshot(snapshot_dir=d, fetcher=lambda url: live, write=False)
        assert drift.roster_positions_changed is True
        assert drift.new_snapshot is None
        assert len(list(d.glob("*.json"))) == 1  # write=False honored

    def test_malformed_live_payload_rejected_not_persisted(self, tmp_path):
        d = _seed_dir(tmp_path)
        with pytest.raises(LeagueConfigError):
            refresh_snapshot(snapshot_dir=d, fetcher=lambda url: {"nope": True})
        assert len(list(d.glob("*.json"))) == 1

    def test_diff_pure_function(self):
        stored = _minimal_snapshot()
        live = json.loads(json.dumps(stored))
        live["settings"]["playoff_teams"] = 6
        drift = diff_league_config(stored, live, stored_path=Path("s.json"))
        assert drift.settings_changed == {"playoff_teams": (7, 6)}
        assert drift.scoring_changed == {}
        assert drift.to_dict()["hasDrift"] is True

    def test_default_snapshot_dir_is_repo_config(self):
        assert li_config.SNAPSHOT_DIR == SNAPSHOT_DIR
