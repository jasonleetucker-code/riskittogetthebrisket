"""Store: atomic writes, corrupt-load recovery, 45-day pruning, and
failed-member data preservation."""

from __future__ import annotations

import json

from src.intel import store
from tests.intel.conftest import DAY_MS, NOW_MS


def _event(asset_id: str, ts: int, league: str = "L1", owner: str = "A") -> dict:
    return {
        "eventId": f"e-{asset_id}-{ts}",
        "txId": "tx",
        "leagueId": league,
        "ownerId": owner,
        "assetId": asset_id,
        "assetType": "player",
        "action": "add",
        "txType": "waiver",
        "ts": ts,
        "week": 1,
        "faabBid": 0,
    }


class TestAtomicWrite:
    def test_save_creates_dirs_and_valid_json(self, intel_snapshot_path):
        state = store.default_state("2026")
        state["events"] = [_event("p1", NOW_MS - DAY_MS)]
        store.save_state(state, now_ms=NOW_MS)

        assert intel_snapshot_path.exists()
        loaded = json.loads(intel_snapshot_path.read_text(encoding="utf-8"))
        assert loaded["events"][0]["assetId"] == "p1"
        assert loaded["generatedAt"]  # ISO stamp present

    def test_no_temp_files_left_behind(self, intel_snapshot_path):
        store.save_state(store.default_state("2026"), now_ms=NOW_MS)
        leftovers = [p for p in intel_snapshot_path.parent.iterdir() if ".tmp-" in p.name]
        assert leftovers == []

    def test_save_overwrites_previous_snapshot(self, intel_snapshot_path):
        first = store.default_state("2025")
        store.save_state(first, now_ms=NOW_MS)
        second = store.default_state("2026")
        store.save_state(second, now_ms=NOW_MS)
        loaded = store.load_state()
        assert loaded["season"] == "2026"


class TestCorruptLoadRecovery:
    def test_missing_snapshot_returns_empty_state(self, intel_snapshot_path):
        assert not intel_snapshot_path.exists()
        state = store.load_state()
        assert state["members"] == {}
        assert state["events"] == []
        assert state["generatedAt"] is None

    def test_corrupt_json_returns_empty_state(self, intel_snapshot_path):
        intel_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        intel_snapshot_path.write_text("{ not json !!!", encoding="utf-8")
        state = store.load_state()
        assert state["members"] == {}
        assert state["events"] == []

    def test_non_dict_snapshot_returns_empty_state(self, intel_snapshot_path):
        intel_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        intel_snapshot_path.write_text("[1, 2, 3]", encoding="utf-8")
        state = store.load_state()
        assert state["events"] == []

    def test_mangled_collection_keys_are_retyped(self, intel_snapshot_path):
        intel_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        intel_snapshot_path.write_text(
            json.dumps({"members": "oops", "events": {"not": "a list"}, "leagues": 7}),
            encoding="utf-8",
        )
        state = store.load_state()
        assert state["members"] == {}
        assert state["leagues"] == {}
        assert state["events"] == []


class TestPruning:
    def test_events_older_than_45_days_pruned_on_save(self, intel_snapshot_path):
        state = store.default_state("2026")
        state["events"] = [
            _event("keep", NOW_MS - 44 * DAY_MS),
            _event("drop", NOW_MS - 46 * DAY_MS),
            _event("fresh", NOW_MS - DAY_MS),
        ]
        store.save_state(state, now_ms=NOW_MS)
        loaded = store.load_state()
        assert {e["assetId"] for e in loaded["events"]} == {"keep", "fresh"}

    def test_prune_events_returns_removed_count(self):
        state = store.default_state("2026")
        state["events"] = [
            _event("a", NOW_MS - 50 * DAY_MS),
            _event("b", NOW_MS - 1 * DAY_MS),
            {"garbage": "no ts"},
        ]
        removed = store.prune_events(state, now_ms=NOW_MS)
        assert removed == 2  # ancient event + garbage row
        assert len(state["events"]) == 1


class TestFailedMemberPreservation:
    def _prev_state(self) -> dict:
        prev = store.default_state("2026")
        prev["members"] = {
            "A": {"leagues": ["LA"], "truncated": False, "lastCrawledAt": "x", "lastError": None},
            "B": {"leagues": ["LB"], "truncated": False, "lastCrawledAt": "x", "lastError": None},
        }
        prev["leagues"] = {
            "LA": {"name": "Alpha", "memberOwnerIds": ["A"], "holdings": {"A": ["p1"]}},
            "LB": {"name": "Beta", "memberOwnerIds": ["B"], "holdings": {}},
        }
        prev["events"] = [_event("p1", NOW_MS - DAY_MS, league="LA")]
        return prev

    def test_failed_member_data_restored(self):
        prev = self._prev_state()
        new = store.default_state("2026")
        new["members"] = {
            "A": {"leagues": [], "truncated": False, "lastCrawledAt": None, "lastError": "boom"},
            "B": {"leagues": ["LB"], "truncated": False, "lastCrawledAt": "y", "lastError": None},
        }
        new["leagues"] = {"LB": {"name": "Beta", "memberOwnerIds": ["B"], "holdings": {}}}

        merged = store.merge_member_results(prev, new, ["A"])
        assert merged["members"]["A"]["leagues"] == ["LA"]
        assert merged["members"]["A"]["lastError"] == "boom"  # failure stays visible
        assert merged["leagues"]["LA"]["holdings"] == {"A": ["p1"]}
        assert any(e["assetId"] == "p1" for e in merged["events"])
        # Healthy member untouched.
        assert merged["members"]["B"]["lastCrawledAt"] == "y"

    def test_no_failures_is_identity(self):
        prev = self._prev_state()
        new = store.default_state("2026")
        merged = store.merge_member_results(prev, new, [])
        assert merged is new
        assert merged["members"] == {}

    def test_merge_does_not_duplicate_events(self):
        prev = self._prev_state()
        new = store.default_state("2026")
        new["members"] = {"A": {"leagues": [], "lastError": "boom"}}
        new["events"] = [dict(prev["events"][0])]  # same eventId already present
        merged = store.merge_member_results(prev, new, ["A"])
        assert len(merged["events"]) == 1
