"""Custom-alert rule validation, evaluation, and cooldown tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.news import custom_alerts as ca


def test_validate_value_crosses_rule():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Caleb Williams",
        "params": {"threshold": 7000, "direction": "above"},
    })
    assert rule["kind"] == "value_crosses"
    assert rule["displayName"] == "Caleb Williams"
    assert rule["params"] == {"threshold": 7000, "direction": "above"}
    assert rule["channels"] == ["email"]
    assert rule["id"].startswith("alert_")


def test_validate_rank_change_rule():
    rule = ca.validate_rule({
        "kind": "rank_change",
        "displayName": "Bo Nix",
        "params": {"minDelta": 10},
        "channels": ["email", "push"],
    })
    assert rule["params"] == {"minDelta": 10}
    assert set(rule["channels"]) == {"email", "push"}


@pytest.mark.parametrize(
    "payload,detail_part",
    [
        ({"kind": "bogus", "displayName": "X"}, "unknown rule kind"),
        ({"kind": "value_crosses"}, "displayName"),
        ({"kind": "value_crosses", "displayName": "X"}, "threshold"),
        (
            {"kind": "value_crosses", "displayName": "X",
             "params": {"threshold": 1, "direction": "sideways"}},
            "direction",
        ),
        ({"kind": "rank_change", "displayName": "X"}, "minDelta"),
        (
            {"kind": "rank_change", "displayName": "X",
             "params": {"minDelta": 10}, "channels": []},
            "channel",
        ),
    ],
)
def test_validate_rejects_bad_input(payload, detail_part):
    with pytest.raises(ValueError) as exc:
        ca.validate_rule(payload)
    assert detail_part.lower() in str(exc.value).lower()


def _fake_player(name="Test Player", *, value=6000, rank_change=0, rank=50):
    return {
        "displayName": name,
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
        "rankChange": rank_change,
    }


def test_value_crosses_above_fires_when_value_meets_threshold():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Caleb",
        "params": {"threshold": 5000, "direction": "above"},
    })
    hits = ca.evaluate_alerts([rule], [_fake_player("Caleb", value=6000)])
    assert len(hits) == 1
    assert hits[0].kind == "value_crosses"
    assert "↑" in hits[0].title


def test_value_crosses_above_silent_when_below_threshold():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Caleb",
        "params": {"threshold": 7000, "direction": "above"},
    })
    hits = ca.evaluate_alerts([rule], [_fake_player("Caleb", value=6000)])
    assert hits == []


def test_value_crosses_below_fires_when_value_drops_under_threshold():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Bo",
        "params": {"threshold": 4000, "direction": "below"},
    })
    hits = ca.evaluate_alerts([rule], [_fake_player("Bo", value=3500)])
    assert len(hits) == 1
    assert "↓" in hits[0].title


def test_rank_change_fires_when_delta_meets_threshold():
    rule = ca.validate_rule({
        "kind": "rank_change",
        "displayName": "Drake",
        "params": {"minDelta": 5},
    })
    hits = ca.evaluate_alerts([rule], [_fake_player("Drake", rank_change=-7)])
    assert len(hits) == 1
    assert hits[0].kind == "rank_change"


def test_rank_change_silent_when_movement_below_threshold():
    rule = ca.validate_rule({
        "kind": "rank_change",
        "displayName": "Drake",
        "params": {"minDelta": 10},
    })
    hits = ca.evaluate_alerts([rule], [_fake_player("Drake", rank_change=3)])
    assert hits == []


def test_cooldown_suppresses_recent_fire():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Caleb",
        "params": {"threshold": 5000, "direction": "above"},
    })
    # 1 hour ago → still in 24h cooldown.
    last_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )
    skey = f"{rule['id']}::caleb"
    state = {skey: {"lastFiredAt": last_iso}}
    hits = ca.evaluate_alerts(
        [rule], [_fake_player("Caleb", value=6000)], state=state,
    )
    assert hits == []


def test_cooldown_lifts_after_24h():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Caleb",
        "params": {"threshold": 5000, "direction": "above"},
    })
    # 25 hours ago → cooldown elapsed.
    last_iso = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )
    skey = f"{rule['id']}::caleb"
    state = {skey: {"lastFiredAt": last_iso}}
    hits = ca.evaluate_alerts(
        [rule], [_fake_player("Caleb", value=6000)], state=state,
    )
    assert len(hits) == 1


def test_mark_fired_records_timestamp_under_state_key():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Caleb",
        "params": {"threshold": 5000, "direction": "above"},
    })
    [hit] = ca.evaluate_alerts([rule], [_fake_player("Caleb", value=6000)])
    new_state = ca.mark_fired({}, hit)
    assert hit.state_key in new_state
    assert "lastFiredAt" in new_state[hit.state_key]


def test_prune_state_drops_only_matching_rule_id():
    other = "alert_keepme"
    rule_id = "alert_drop"
    state = {
        f"{rule_id}::caleb": {"lastFiredAt": "2026-01-01T00:00:00Z"},
        f"{other}::bo": {"lastFiredAt": "2026-01-02T00:00:00Z"},
    }
    pruned = ca.prune_state_for_removed_rule(state, rule_id)
    assert f"{other}::bo" in pruned
    assert f"{rule_id}::caleb" not in pruned


def test_unknown_player_does_not_fire():
    rule = ca.validate_rule({
        "kind": "value_crosses",
        "displayName": "Phantom",
        "params": {"threshold": 1, "direction": "above"},
    })
    hits = ca.evaluate_alerts([rule], [_fake_player("Caleb", value=9999)])
    assert hits == []
