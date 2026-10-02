"""The raw archive is append-only, idempotent, revision-preserving and atomic."""

from __future__ import annotations

import sqlite3

import pytest

from src.trade import market_trade_archive as A

FAM = "synthetic_feed"


@pytest.fixture
def db(tmp_path):
    A._reset_setup_cache_for_tests()
    yield tmp_path / "mt" / "archive.sqlite"
    A._reset_setup_cache_for_tests()


def _fetch(fid: str, at: str = "2026-10-01T00:00:00+00:00") -> A.FetchRecord:
    return A.FetchRecord(fetch_id=fid, source_family=FAM, fetched_at=at, outcome="archived")


def _obs(native: str, payload: dict) -> A.RawObservation:
    return A.RawObservation(source_native_id=native, payload=payload, observed_date="2026-10-01")


def test_identical_reobservation_is_stored_once_and_counted_as_known(db):
    first = A.record_fetch(_fetch("f1"), [_obs("1", {"a": 1}), _obs("2", {"b": 2})], path=db)
    assert (first.new_count, first.known_count) == (2, 0)
    assert first.turnover_suspected is None  # first fetch: not determinable
    again = A.record_fetch(
        _fetch("f2", "2026-10-01T01:00:00+00:00"), [_obs("1", {"a": 1})], path=db
    )
    assert (again.new_count, again.known_count, again.revised_count) == (0, 1, 0)
    assert again.turnover_suspected is False
    assert len(A.read_observations(FAM, path=db)) == 2


def test_key_order_never_manufactures_a_revision(db):
    A.record_fetch(_fetch("f1"), [_obs("1", {"a": 1, "b": 2})], path=db)
    res = A.record_fetch(
        _fetch("f2", "2026-10-01T01:00:00+00:00"), [_obs("1", {"b": 2, "a": 1})], path=db
    )
    assert res.known_count == 1 and res.revised_count == 0


def test_a_changed_payload_is_a_kept_revision_not_an_overwrite(db):
    A.record_fetch(_fetch("f1"), [_obs("1", {"v": 1})], path=db)
    res = A.record_fetch(_fetch("f2", "2026-10-01T01:00:00+00:00"), [_obs("1", {"v": 2})], path=db)
    assert res.revised_count == 1
    rows = A.read_observations(FAM, path=db)
    assert [r["payload"]["v"] for r in rows] == [1, 2]
    assert [r["revision"] for r in rows] == [1, 2]
    assert all(r["revisionCount"] == 2 for r in rows)


def test_full_window_turnover_is_flagged(db):
    A.record_fetch(_fetch("f1"), [_obs("1", {"v": 1})], path=db)
    res = A.record_fetch(_fetch("f2", "2026-10-01T05:00:00+00:00"), [_obs("9", {"v": 9})], path=db)
    assert res.turnover_suspected is True


@pytest.mark.parametrize(
    "verb", ["UPDATE raw_observations SET payload_json = '{}'", "DELETE FROM raw_observations"]
)
def test_append_only_is_structural(db, verb):
    A.record_fetch(_fetch("f1"), [_obs("1", {"v": 1})], path=db)
    conn = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(verb)
    finally:
        conn.close()


def test_fetch_log_and_identity_snapshots_are_append_only_too(db):
    A.record_fetch(_fetch("f1"), [_obs("1", {"v": 1})], identity_entries=[{"playerID": 1}], path=db)
    conn = sqlite3.connect(db)
    try:
        for sql in ("DELETE FROM fetches", "UPDATE identity_snapshots SET entry_count = 0"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                conn.execute(sql)
    finally:
        conn.close()


def test_a_failed_fetch_leaves_the_archive_exactly_as_it_was(db, monkeypatch):
    A.record_fetch(_fetch("f1"), [_obs("1", {"v": 1})], path=db)

    class Boom(A.RawObservation):
        @property
        def source_native_id(self):  # type: ignore[override]
            raise RuntimeError("crash mid-fetch")

    good = _obs("2", {"v": 2})
    bad = object.__new__(Boom)
    with pytest.raises(RuntimeError):
        A.record_fetch(_fetch("f2", "2026-10-01T01:00:00+00:00"), [good, bad], path=db)
    natives = {r["sourceNativeId"] for r in A.read_observations(FAM, path=db)}
    assert natives == {"1"}, "a crash after observation 2 must not leave it half-committed"
    assert [f["fetch_id"] for f in A.read_fetches(FAM, path=db)] == ["f1"]


def test_readers_never_create_an_archive(tmp_path):
    missing = tmp_path / "nope" / "archive.sqlite"
    assert A.read_observations(FAM, path=missing) == []
    assert A.coverage(FAM, path=missing)["archiveExists"] is False
    assert not missing.exists()


def test_identity_snapshot_is_content_addressed(db):
    entries = [{"playerID": 2, "playerName": "B"}, {"playerID": 1, "playerName": "A"}]
    r1 = A.record_fetch(_fetch("f1"), [], identity_entries=entries, path=db)
    r2 = A.record_fetch(
        _fetch("f2", "2026-10-01T01:00:00+00:00"),
        [],
        identity_entries=list(reversed(entries)),
        path=db,
    )
    assert r1.identity_sha256 == r2.identity_sha256
    assert A.read_identity_snapshot(r1.identity_sha256, path=db) is not None
