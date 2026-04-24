"""Tests for ESPN depth chart + usage cross-check gate."""
from __future__ import annotations

import io
import json

import pytest

from src.api import feature_flags
from src.nfl_data import depth_charts as dc


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _sample_depth_payload():
    return {
        "team": {"abbreviation": "BUF"},
        "athletes": [
            {
                "position": {"abbreviation": "QB"},
                "items": [
                    {"athlete": {"id": "3918298", "displayName": "Josh Allen"}},
                    {"athlete": {"id": "5555", "displayName": "Mitch Trubisky"}},
                ],
            },
            {
                "position": {"abbreviation": "RB"},
                "items": [
                    {"athlete": {"id": "4017", "displayName": "James Cook"}},
                    {"athlete": {"id": "7777", "displayName": "Ty Johnson"}},
                    {"athlete": {"id": "9999", "displayName": "Backup"}},
                ],
            },
        ],
    }


def test_flag_off_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_DEPTH_CHART_VALIDATION", "0")
    feature_flags.reload()
    def opener(req, timeout=None):
        return io.BytesIO(b"{}")
    out = dc.fetch_team_depth_chart("2", _url_opener=opener, cache_dir=tmp_path)
    assert out == []


def test_parse_depth_payload_shapes(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_DEPTH_CHART_VALIDATION", "1")
    feature_flags.reload()
    def opener(req, timeout=None):
        return io.BytesIO(json.dumps(_sample_depth_payload()).encode("utf-8"))
    out = dc.fetch_team_depth_chart("2", _url_opener=opener, cache_dir=tmp_path)
    # 2 QBs + 3 RBs = 5 entries
    assert len(out) == 5
    qb1 = [e for e in out if e.position == "QB" and e.slot == 1][0]
    assert qb1.full_name == "Josh Allen"
    assert qb1.team_abbrev == "BUF"


def test_detect_slot_changes_promotion():
    prior = [
        dc.DepthChartEntry("BUF", "RB", 1, "A", "Starter A"),
        dc.DepthChartEntry("BUF", "RB", 2, "B", "Backup B"),
    ]
    current = [
        dc.DepthChartEntry("BUF", "RB", 1, "B", "Backup B"),
        dc.DepthChartEntry("BUF", "RB", 2, "A", "Starter A"),
    ]
    changes = dc.detect_slot_changes(prior, current)
    # Two entries changed: A demoted, B promoted.
    by_id = {c["espnAthleteId"]: c for c in changes}
    assert by_id["A"]["direction"] == "demoted"
    assert by_id["B"]["direction"] == "promoted"


def test_detect_slot_changes_debut():
    prior = []
    current = [dc.DepthChartEntry("BUF", "WR", 1, "N", "New")]
    changes = dc.detect_slot_changes(prior, current)
    assert changes[0]["direction"] == "debut"


def test_detect_slot_changes_no_change_emits_nothing():
    e = dc.DepthChartEntry("BUF", "QB", 1, "A", "A")
    changes = dc.detect_slot_changes([e], [e])
    assert changes == []


def test_usage_confirms_promotion_with_snap_delta():
    change = {"direction": "promoted", "espnAthleteId": "A", "fullName": "A"}
    # +8pp snap delta — confirms promotion.
    assert dc.usage_confirms_slot_change(change, 0.08) is True


def test_usage_rejects_promotion_with_snap_drop():
    """Direction mismatch — promoted player with declining snaps
    is not confirmed (could be a stat-sheet artifact)."""
    change = {"direction": "promoted"}
    assert dc.usage_confirms_slot_change(change, -0.08) is False


def test_usage_rejects_small_delta():
    """<5pp change is noise."""
    change = {"direction": "promoted"}
    assert dc.usage_confirms_slot_change(change, 0.02) is False


def test_usage_confirms_demotion_with_snap_drop():
    change = {"direction": "demoted"}
    assert dc.usage_confirms_slot_change(change, -0.10) is True


def test_debut_is_not_a_confirmed_signal():
    """A debut slot isn't a 'change' in the promoted/demoted sense —
    return False so we don't fire extra alerts on rookie debuts."""
    change = {"direction": "debut"}
    assert dc.usage_confirms_slot_change(change, 0.10) is False


def test_nfl_team_ids_covers_32_teams():
    assert len(dc.NFL_TEAM_IDS) == 32
