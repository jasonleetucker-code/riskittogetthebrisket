"""Point-in-time evidence: nothing after T is visible at T; truth never leaks into pre-lock views."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.dfs import pit

LOCK = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))


def _snapshot(sid="snap_1", starts=(LOCK, LOCK + timedelta(hours=3))):
    athletes = [
        {
            "player_id": f"p{i}",
            "game": "AA@BB" if i % 2 else "CC@DD",
            "start_time_utc": None if s is None else s.isoformat(),
            "projection": 10.0 + i,
        }
        for i, s in enumerate(starts)
    ]
    return {
        "id": sid,
        "ruleset": "draftkings.nfl.classic@2026.1",
        "contentHash": "h" * 64,
        "createdAt": (LOCK - timedelta(days=1)).isoformat(),
        "body": {"athletes": athletes},
    }


def _obs(pid, value, at, source="srcA", kind="ownership"):
    return {
        "playerId": pid,
        "kind": kind,
        "source": source,
        "observedAt": at.isoformat(),
        "value": value,
    }


def test_lock_is_the_earliest_start_and_unknown_when_any_start_is_unknown():
    assert pit.index_slate("o", _snapshot())["lockAt"] == pit._utc(LOCK)
    assert pit.index_slate("o", _snapshot("snap_2", (LOCK, None)))["lockAt"] is None


def test_as_of_sees_only_what_was_published_and_held_by_then():
    pit.index_slate("o", _snapshot())
    t1, t2 = LOCK - timedelta(hours=5), LOCK - timedelta(hours=1)
    pit.record("o", "snap_1", [_obs("p0", 20.0, t1)], recorded_at=t1.isoformat())
    pit.record("o", "snap_1", [_obs("p0", 31.0, t2)], recorded_at=t2.isoformat())
    # Published early but only RECORDED after t2: not held at t2.
    late = LOCK - timedelta(minutes=30)
    pit.record("o", "snap_1", [_obs("p1", 9.0, t1, source="srcB")], recorded_at=late.isoformat())
    early_view = pit.as_of("o", "snap_1", t1 + timedelta(minutes=1))
    assert early_view["players"]["p0"]["ownership"]["srcA"]["value"] == 20.0
    view = pit.as_of("o", "snap_1", t2)
    assert view["players"]["p0"]["ownership"]["srcA"]["value"] == 31.0
    assert "p1" not in view["players"]
    assert "p1" in pit.as_of("o", "snap_1", late)["players"]
    assert early_view["digest"] != view["digest"]


def test_pre_lock_views_refuse_after_lock_and_unknown_lock():
    pit.index_slate("o", _snapshot())
    with pytest.raises(pit.PitError) as e:
        pit.as_of("o", "snap_1", LOCK + timedelta(seconds=1))
    assert e.value.code == "AFTER_LOCK"
    pit.index_slate("o", _snapshot("snap_2", (LOCK, None)))
    with pytest.raises(pit.PitError) as e:
        pit.as_of("o", "snap_2", LOCK - timedelta(hours=1))
    assert e.value.code == "LOCK_UNKNOWN"
    # An explicitly post-lock (review) view is allowed, and says so.
    assert pit.as_of("o", "snap_1", LOCK + timedelta(hours=9), pre_lock=False)["preLock"] is False


def test_ingest_is_append_only_and_idempotent():
    pit.index_slate("o", _snapshot())
    t = LOCK - timedelta(hours=2)
    first = pit.record("o", "snap_1", [_obs("p0", 20.0, t)], recorded_at=t.isoformat())
    again = pit.record("o", "snap_1", [_obs("p0", 20.0, t)], recorded_at=t.isoformat())
    assert (first["added"], again["added"], again["duplicates"]) == (1, 0, 1)
    with pytest.raises(pit.PitError) as e:
        pit.record(
            "o", "snap_1", [_obs("p0", 1.0, t)], recorded_at=(t - timedelta(minutes=1)).isoformat()
        )
    assert e.value.code == "RECORDED_BEFORE_OBSERVED"
    with pytest.raises(pit.PitError):
        pit.record("o", "snap_1", [{**_obs("p0", 1.0, t), "observedAt": "2026-10-04T12:00:00"}])


def test_views_are_owner_scoped():
    pit.index_slate("o", _snapshot())
    with pytest.raises(pit.PitError) as e:
        pit.as_of("someone_else", "snap_1", LOCK - timedelta(hours=1))
    assert e.value.code == "SLATE_NOT_INDEXED"


def test_capture_snapshot_records_imports_at_import_time():
    snap = _snapshot()
    snap["body"]["athletes"][0]["ownership"] = 25.0
    out = pit.capture_snapshot("o", snap)
    assert out["observations"]["added"] == 3  # 2 projections + 1 ownership
    view = pit.as_of("o", "snap_1", LOCK - timedelta(hours=1))
    assert view["players"]["p0"]["ownership"]["owner_import"]["value"] == 25.0
    # Nothing is visible before the import happened.
    assert pit.as_of("o", "snap_1", LOCK - timedelta(days=2))["players"] == {}


CRIT = {"minSamples": 20, "metric": "mae", "lowerIsBetter": True, "mustBeatBaselineBy": 0.5}


def test_models_are_versioned_and_promotion_needs_uncontaminated_predefined_evidence():
    m = pit.register_model("ownership.test", "1.0.0", "ownership", {"k": 1}, CRIT)
    assert m["role"] == "challenger"
    with pytest.raises(pit.PitError) as e:
        pit.register_model("ownership.test", "1.0.0", "ownership", {"k": 2}, CRIT)
    assert e.value.code == "VERSION_REUSED"
    after = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    good = {"windowStart": after, "n": 25, "challenger": {"mae": 3.0}, "baseline": {"mae": 4.0}}
    for bad, code in (
        ({**good, "windowStart": "2020-01-01T00:00:00+00:00"}, "EVALUATION_CONTAMINATED"),
        ({**good, "n": 5}, "INSUFFICIENT_EVIDENCE"),
        ({**good, "challenger": {"mae": 3.8}}, "DID_NOT_BEAT_BASELINE"),
    ):
        with pytest.raises(pit.PitError) as e:
            pit.promote("ownership.test", "1.0.0", bad)
        assert e.value.code == code
    assert pit.promote("ownership.test", "1.0.0", good)["role"] == "champion"
    pit.register_model("ownership.test", "1.1.0", "ownership", {"k": 3}, CRIT)
    pit.promote(
        "ownership.test",
        "1.1.0",
        good | {"windowStart": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()},
    )
    assert pit.model_role("ownership.test", "1.0.0")["role"] == "retired"
    back = pit.rollback("ownership.test", "1.0.0", "regressed live")
    assert (
        back["role"] == "champion"
        and pit.model_role("ownership.test", "1.1.0")["role"] == "retired"
    )


def test_decisions_are_frozen_with_honest_timing():
    pit.index_slate("o", _snapshot())  # lock tomorrow-ish in 2026 → decisions made now are pre-lock
    view = pit.as_of("o", "snap_1", LOCK - timedelta(hours=1))
    d = pit.freeze_decision(
        "o",
        "snap_1",
        as_of_view=view,
        contest_ref="c1:1",
        models=[{"modelId": "m", "version": "1"}],
        objective={"kind": "projection_baseline"},
        constraints={},
        selected=[{"lineup": ["p0"]}],
        rejected=[],
    )
    assert d["timing"] == "pre_lock" and d["inputsDigest"] == view["digest"]
    assert pit.get_decision("o", d["decisionId"])["selected"] == [{"lineup": ["p0"]}]
    assert pit.get_decision("other", d["decisionId"]) is None
    pit.index_slate("o", _snapshot("snap_past", (datetime(2020, 1, 1, tzinfo=timezone.utc),)))
    past = pit.freeze_decision(
        "o",
        "snap_past",
        as_of_view={"asOf": "x", "digest": "y"},
        contest_ref=None,
        models=[],
        objective={},
        constraints={},
        selected=[],
        rejected=[],
    )
    assert past["timing"] == "post_lock"  # can never count as forward evidence


def test_evaluations_keep_their_sample_size_and_scope():
    pit.record_evaluation(
        "o", "ownership", "srcA", {"sport": "nfl"}, 12, {"mae": 3.1}, {"result": "r1"}
    )
    ev = pit.list_evaluations("o", "ownership")
    assert ev[0]["n"] == 12 and ev[0]["scope"] == {"sport": "nfl"}
