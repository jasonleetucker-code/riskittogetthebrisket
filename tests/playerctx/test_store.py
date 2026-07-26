"""Snapshot store: atomic write semantics + defensive load."""

from __future__ import annotations

import json

import pytest

from src.playerctx import store


def _players() -> dict:
    return {
        "00-0033280": {
            "gsisId": "00-0033280",
            "sleeperId": "4034",
            "name": "Christian McCaffrey",
            "team": "SF",
            "position": "RB",
        }
    }


class TestWriteSnapshot:
    def test_roundtrip_and_shape(self, tmp_path):
        target = tmp_path / "snapshot.json"
        written = store.write_snapshot(
            _players(), counts={"players": 1}, sources={"contracts": {"url": "u"}}, path=target
        )
        assert written == target
        payload = store.load_snapshot(target)
        assert payload is not None
        assert payload["schemaVersion"] == store.SCHEMA_VERSION
        assert payload["generatedAt"]  # ISO stamp present
        assert payload["counts"] == {"players": 1}
        assert payload["sleeperIndex"] == {"4034": "00-0033280"}
        assert payload["players"]["00-0033280"]["name"] == "Christian McCaffrey"

    def test_compact_encoding(self, tmp_path):
        target = tmp_path / "snapshot.json"
        store.write_snapshot(_players(), path=target)
        raw = target.read_text(encoding="utf-8")
        assert ": " not in raw and ", " not in raw  # separators=(",", ":")

    def test_failed_write_leaves_no_tmp_and_keeps_last_good(self, tmp_path):
        target = tmp_path / "snapshot.json"
        store.write_snapshot(_players(), path=target)
        before = target.read_text(encoding="utf-8")
        with pytest.raises(TypeError):
            # object() is not JSON-serializable → dump raises mid-write
            store.write_snapshot({"bad": {"sleeperId": object()}}, path=target)
        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.glob("*.tmp-*")) == []


class TestLoadSnapshot:
    def test_missing_returns_none(self, tmp_path):
        assert store.load_snapshot(tmp_path / "nope.json") is None

    def test_corrupt_returns_none(self, tmp_path):
        p = tmp_path / "snapshot.json"
        p.write_text("{not json", encoding="utf-8")
        assert store.load_snapshot(p) is None

    def test_wrong_shape_returns_none(self, tmp_path):
        p = tmp_path / "snapshot.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert store.load_snapshot(p) is None
        p.write_text(json.dumps({"players": "not-a-dict"}), encoding="utf-8")
        assert store.load_snapshot(p) is None
