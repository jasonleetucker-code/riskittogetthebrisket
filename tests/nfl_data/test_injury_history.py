"""As-known injury history (Adaptive Learning G4): append-only, deduplicated,
point-in-time, fail-closed on an unproven fetch.  ``src/nfl_data/injury_history.py``."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from src.nfl_data import cache as nfl_cache
from src.nfl_data import injury_history as ih
from src.nfl_data.injury_feed import CACHE_KEY
from src.utils import append_ledger as al

T0 = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc).timestamp()


def _entry(eid: str, name: str, status: str, **extra) -> dict:
    base = {
        "espnAthleteId": eid,
        "fullName": name,
        "position": "WR",
        "teamAbbrev": "BUF",
        "status": status,
        "bodyPart": "",
        "description": "",
        "dateReported": "",
        "returning": "",
    }
    base.update(extra)
    return base


DIRECTORY = {
    "100": {"full_name": "Alpha Player", "position": "WR", "team": "BUF", "espn_id": "9001"},
    "200": {"full_name": "Beta Player", "position": "RB", "team": "SF", "espn_id": "9002"},
    # Two Sleeper players claiming one ESPN id: must never be resolved.
    "300": {"full_name": "Gamma One", "position": "TE", "team": "KC", "espn_id": "9003"},
    "301": {"full_name": "Gamma Two", "position": "TE", "team": "KC", "espn_id": "9003"},
}


def _records(base):
    return list(al.iter_all_records(base))


def _capture(base, entries, fetched_at, directory=DIRECTORY):
    return ih.capture(
        entries,
        fetched_at=fetched_at,
        base=base,
        directory=directory,
        directory_provenance={"path": "fixture"},
        recorded_at=datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat(),
    )


def test_snapshot_keeps_status_fields_identity_and_nulls(tmp_path):
    entries = [
        _entry("9001", "Alpha Player", "QUESTIONABLE", bodyPart="Knee", dateReported="2026-10-02"),
        _entry("9002", "Beta Player", "OUT"),
        _entry("9003", "Gamma", "IR"),
        _entry("7777", "Unknown Guy", "DOUBTFUL"),
    ]
    out = _capture(tmp_path, entries, T0)
    assert out == {"written": True, "kind": "snapshot", "key": out["key"]}
    [rec] = _records(tmp_path)
    assert rec["provider"] == "espn"
    assert rec["fetchedAt"] == datetime.fromtimestamp(T0, tz=timezone.utc).isoformat()
    # The endpoint has no as-of stamp: None WITH a reason, never the fetch time.
    assert rec["providerAsOf"] is None
    assert rec["nullReasons"]["providerAsOf"] == ih.PROVIDER_AS_OF_NULL_REASON
    by_id = {e["espnAthleteId"]: e for e in rec["entries"]}
    alpha = by_id["9001"]
    assert alpha["status"] == "QUESTIONABLE" and alpha["bodyPart"] == "Knee"
    # Missing fields stay null -- never "" and never coerced.
    assert alpha["description"] is None and alpha["returning"] is None
    assert by_id["9002"]["dateReported"] is None
    assert alpha["identity"] == {
        "status": "resolved",
        "sleeperId": "100",
        "method": "espn_id",
        "policy": alpha["identity"]["policy"],
    }
    assert by_id["9003"]["identity"]["status"] == "unresolved"
    assert by_id["9003"]["identity"]["reason"] == "espn_id_shared_by_multiple_sleeper_players"
    assert by_id["7777"]["identity"] == {
        "status": "unresolved",
        "sleeperId": None,
        "reason": "espn_id_not_in_sleeper_directory",
    }
    assert rec["unresolvedCount"] == 2


def test_unknown_espn_id_is_never_resolved_by_name(tmp_path):
    # Same NAME as a directory player, different (unknown) ESPN id.
    _capture(tmp_path, [_entry("5555", "Alpha Player", "OUT")], T0)
    [rec] = _records(tmp_path)
    assert rec["entries"][0]["identity"]["sleeperId"] is None


def test_no_directory_keeps_everyone_unresolved(tmp_path):
    ih.capture(
        [_entry("9001", "Alpha Player", "OUT")],
        fetched_at=T0,
        base=tmp_path,
        directory=None,
        directory_provenance={"path": None, "nullReason": "no_readable_sleeper_directory"},
    )
    [rec] = _records(tmp_path)
    assert rec["entries"][0]["identity"]["reason"] == "no_sleeper_directory"
    assert rec["identityDirectory"]["nullReason"] == "no_readable_sleeper_directory"


def test_identical_refetch_is_a_reobservation_not_a_copy(tmp_path):
    entries = [_entry("9001", "Alpha Player", "OUT")]
    first = _capture(tmp_path, entries, T0)
    second = _capture(tmp_path, entries, T0 + 4 * 3600)
    assert second["kind"] == "reobserved"
    recs = _records(tmp_path)
    assert [r["kind"] for r in recs] == ["snapshot", "reobserved"]
    assert recs[1]["snapshotKey"] == first["key"]
    assert "entries" not in recs[1]
    assert recs[1]["contentSha256"] == recs[0]["contentSha256"]


def test_same_fetch_twice_writes_nothing(tmp_path):
    entries = [_entry("9001", "Alpha Player", "OUT")]
    _capture(tmp_path, entries, T0)
    again = _capture(tmp_path, entries, T0)  # cache hit: same fetched_at
    assert again["written"] is False
    assert len(_records(tmp_path)) == 1


def test_existing_lines_are_never_rewritten(tmp_path):
    _capture(tmp_path, [_entry("9001", "Alpha Player", "OUT")], T0)
    files = al.ledger_files(tmp_path)
    before = files[0].read_bytes()
    _capture(tmp_path, [_entry("9001", "Alpha Player", "IR")], T0 + 3600)
    _capture(tmp_path, [_entry("9001", "Alpha Player", "IR")], T0 + 7200)
    assert files[0].read_bytes().startswith(before)


def test_a_to_b_to_a_records_the_third_state(tmp_path):
    a = [_entry("9001", "Alpha Player", "QUESTIONABLE")]
    b = [_entry("9001", "Alpha Player", "OUT")]
    _capture(tmp_path, a, T0)
    _capture(tmp_path, b, T0 + 3600)
    third = _capture(tmp_path, a, T0 + 7200)
    assert third["kind"] == "snapshot"
    assert [r["kind"] for r in _records(tmp_path)] == ["snapshot", "snapshot", "snapshot"]


def test_directory_change_alone_does_not_make_a_new_snapshot(tmp_path):
    entries = [_entry("9001", "Alpha Player", "OUT")]
    _capture(tmp_path, entries, T0, directory={})
    second = _capture(tmp_path, entries, T0 + 3600)
    assert second["kind"] == "reobserved"


def test_as_known_at_never_selects_a_future_row(tmp_path):
    _capture(tmp_path, [_entry("9001", "Alpha Player", "QUESTIONABLE")], T0)
    _capture(tmp_path, [_entry("9001", "Alpha Player", "QUESTIONABLE")], T0 + 3600)
    _capture(tmp_path, [_entry("9001", "Alpha Player", "OUT")], T0 + 7200)

    def at(offset):
        return datetime.fromtimestamp(T0 + offset, tz=timezone.utc)

    before = ih.as_known_at(at(-1), base=tmp_path)
    assert before == {"state": "unavailable", "reason": "no_capture_at_or_before"}

    mid = ih.as_known_at(at(5400), base=tmp_path)
    assert mid["state"] == "known"
    assert mid["snapshot"]["entries"][0]["status"] == "QUESTIONABLE"
    # The re-observation proves the state was still current at T0+1h.
    assert mid["lastObservedAt"] == at(3600).isoformat()
    assert mid["observedAgeSeconds"] == 1800

    exact = ih.as_known_at(at(7200).isoformat(), base=tmp_path)
    assert exact["snapshot"]["entries"][0]["status"] == "OUT"


def test_as_known_at_unparseable_input(tmp_path):
    assert ih.as_known_at("not a time", base=tmp_path)["state"] == "unavailable"


def test_store_dir_honours_override(tmp_path, monkeypatch):
    monkeypatch.setenv(ih.ENV_DIR, str(tmp_path / "x"))
    assert ih.store_dir() == tmp_path / "x"
    monkeypatch.delenv(ih.ENV_DIR)
    assert ih.store_dir() == ih.DEFAULT_DIR
    assert ih.DEFAULT_DIR.as_posix().endswith("data/nfl_data/injury_history")


def test_load_directory_provenance(tmp_path):
    missing = tmp_path / "missing.json"
    good = tmp_path / "players.json"
    good.write_text(json.dumps(DIRECTORY), encoding="utf-8")
    directory, prov = ih.load_directory((missing, good))
    assert directory == DIRECTORY and prov["playerCount"] == 4
    none, prov2 = ih.load_directory((missing,))
    assert none is None and prov2["nullReason"] == "no_readable_sleeper_directory"


def test_capture_safely_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    assert ih.capture_safely([_entry("1", "x", "OUT")], fetched_at=T0, base=blocker / "sub") is None


# ── the fetch proof ─────────────────────────────────────────────────


@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    return d


def test_proof_accepts_a_fresh_matching_entry(cache_dir):
    entries = [_entry("9001", "Alpha Player", "OUT")]
    nfl_cache.put(CACHE_KEY, entries, cache_dir=cache_dir)
    started = time.time()
    fetched_at, reason = ih.proven_fetch_time(
        entries, started_at=started, ttl_seconds=1800, cache_dir=cache_dir
    )
    assert reason is None and abs(fetched_at - started) < 60


def test_proof_rejects_no_entry(cache_dir):
    assert ih.proven_fetch_time(
        [], started_at=time.time(), ttl_seconds=1800, cache_dir=cache_dir
    ) == (
        None,
        "no_cache_entry",
    )


def test_proof_rejects_a_failed_fetch_returning_empty(cache_dir):
    # The cache holds the last good report; the fetch failed and returned [].
    nfl_cache.put(CACHE_KEY, [_entry("9001", "Alpha Player", "OUT")], cache_dir=cache_dir)
    fetched_at, reason = ih.proven_fetch_time(
        [], started_at=time.time(), ttl_seconds=1800, cache_dir=cache_dir
    )
    assert fetched_at is None and reason == "returned_entries_differ_from_cache_entry"


def test_proof_rejects_an_entry_past_its_ttl(cache_dir):
    nfl_cache.put(CACHE_KEY, [], cache_dir=cache_dir)
    fetched_at, reason = ih.proven_fetch_time(
        [], started_at=time.time() + 3600, ttl_seconds=1800, cache_dir=cache_dir
    )
    assert fetched_at is None and reason == "cache_entry_older_than_ttl"
