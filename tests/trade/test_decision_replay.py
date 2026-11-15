"""TC-C historical replay (asset-only) through ``src/history`` as-of reads."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.history import store
from src.trade import decision_replay as dr


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "ledger.sqlite"
    store._reset_setup_cache_for_tests()

    def write(key, day, value, at):
        res = store.write_observations(
            [
                {
                    "asset_key": key,
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": day,
                    "observed_at": at,
                    "value": value,
                    "origin": "test",
                }
            ],
            path=path,
        )
        assert res["written"] == 1, res

    write("player:1", "2026-08-01", 6000, "2026-08-01T12:00:00+00:00")
    write("player:2", "2026-08-01", 5000, "2026-08-01T12:00:00+00:00")
    # A LATER observation that must never be read for an earlier replay.
    write("player:2", "2026-09-01", 9000, "2026-09-01T12:00:00+00:00")
    return path


AT = datetime(2026, 8, 15, tzinfo=timezone.utc)


def test_replay_uses_values_known_at_the_time_and_the_live_decision_path(ledger):
    out = dr.replay_asset_only(
        [{"name": "B", "assetKey": "player:2"}],
        [{"name": "A", "assetKey": "player:1"}],
        AT,
        ledger_path=ledger,
    )
    # 6,000 in for 5,000 out (the September 9,000 is in the future of AT).
    assert out["decision"]["headline"] == "YES"
    assert out["decision"]["components"]["objectiveValue"]["vaAdjustedGap"] == 1000
    assert {a["fidelity"] for a in out["assets"]} == {"nearest-prior"}
    assert out["mode"] == "asset_only" and out["executes"] is False
    assert out["teamContextReplay"]["state"] == "deferred"
    assert out["decision"]["receipt"]["strategy"]["source"] == "asset_only"


def test_a_later_date_reads_the_later_value(ledger):
    later = datetime(2026, 9, 2, tzinfo=timezone.utc)
    out = dr.replay_asset_only(
        [{"name": "B", "assetKey": "player:2"}],
        [{"name": "A", "assetKey": "player:1"}],
        later,
        ledger_path=ledger,
    )
    assert out["decision"]["headline"] == "NO"


def test_missing_history_is_not_enough_evidence_never_zero(ledger):
    before_floor = datetime(2026, 7, 1, tzinfo=timezone.utc)
    out = dr.replay_asset_only(
        [{"name": "B", "assetKey": "player:2"}],
        [{"name": "A", "assetKey": "player:1"}],
        before_floor,
        ledger_path=ledger,
    )
    assert out["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert {a["missingReason"] for a in out["assets"]} == {"before_history_boundary"}
    unknown = dr.replay_asset_only(
        [{"name": "B", "assetKey": "player:2"}],
        [{"name": "Ghost", "assetKey": "player:999"}],
        AT,
        ledger_path=ledger,
    )
    assert unknown["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert "unpriced_assets" in {g["code"] for g in unknown["decision"]["missingEvidence"]}
