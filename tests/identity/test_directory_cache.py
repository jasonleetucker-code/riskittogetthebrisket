"""The process-wide Sleeper directory index cache (request-path use)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from src.identity import directory_cache
from src.trade.screenshot_import.service import default_identity_context

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "identity_directory_subset.json"


@pytest.fixture(autouse=True)
def _reset():
    directory_cache.reset_for_tests()
    yield
    directory_cache.reset_for_tests()


@pytest.fixture()
def dump(tmp_path: Path) -> Path:
    path = tmp_path / "nfl_players.json"
    players = json.loads(FIXTURE.read_text(encoding="utf-8"))["players"]
    path.write_text(json.dumps(players), encoding="utf-8")
    return path


def test_missing_file_is_none_not_an_error(tmp_path: Path):
    assert directory_cache.get_default_sleeper_index(tmp_path / "absent.json") is None
    assert directory_cache.build_count() == 0


def test_unreadable_or_empty_file_is_none(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert directory_cache.get_default_sleeper_index(bad) is None
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert directory_cache.get_default_sleeper_index(empty) is None


def test_index_is_built_once_and_reused(dump: Path):
    first = directory_cache.get_default_sleeper_index(dump)
    second = directory_cache.get_default_sleeper_index(dump)
    assert first is not None and first is second
    assert directory_cache.build_count() == 1
    assert "4046" in first.by_sleeper_id  # Patrick Mahomes


def test_a_changed_file_is_reindexed(dump: Path):
    first = directory_cache.get_default_sleeper_index(dump)
    players = json.loads(dump.read_text(encoding="utf-8"))
    players["999999"] = {"full_name": "Zed Newguy", "position": "WR", "team": "NYJ", "active": True}
    dump.write_text(json.dumps(players), encoding="utf-8")
    st = dump.stat()
    os.utime(dump, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    second = directory_cache.get_default_sleeper_index(dump)
    assert second is not first
    assert "999999" in second.by_sleeper_id
    assert directory_cache.build_count() == 2


def test_concurrent_first_callers_build_once(dump: Path):
    results = []

    def worker():
        results.append(directory_cache.get_default_sleeper_index(dump))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({id(r) for r in results}) == 1
    assert directory_cache.build_count() == 1


def test_screenshot_identity_context_uses_the_cache(dump: Path, monkeypatch):
    monkeypatch.setattr(directory_cache, "default_directory_path", lambda: dump)
    a = default_identity_context()
    b = default_identity_context()
    assert a.index is not None and a.index is b.index
    assert directory_cache.build_count() == 1


def test_screenshot_identity_without_a_directory_is_explicitly_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(directory_cache, "default_directory_path", lambda: tmp_path / "x.json")
    assert default_identity_context().index is None
