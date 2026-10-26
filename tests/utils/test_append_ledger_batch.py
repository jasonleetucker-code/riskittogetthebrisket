"""``append_ledger.append_records``: the batch form keeps ``append_record``'s
append-only / idempotent semantics (it is now the single implementation)."""

from __future__ import annotations

import json

import pytest

from src.utils import append_ledger as al


def _rec(key, month="2026-10"):
    return {"key": key, "recordedAt": f"{month}-04T00:00:00+00:00", "v": key}


def test_batch_writes_each_new_key_once_and_reports_the_count(tmp_path):
    assert al.append_records(tmp_path, [_rec("a"), _rec("b"), _rec("a")]) == 2
    assert al.append_records(tmp_path, [_rec("b"), _rec("c")]) == 1
    assert [r["key"] for r in al.iter_all_records(tmp_path)] == ["a", "b", "c"]
    assert al.recorded_keys(tmp_path) == {"a", "b", "c"}


def test_batch_routes_by_month_and_keeps_order(tmp_path):
    al.append_records(tmp_path, [_rec("x", "2026-09"), _rec("y", "2026-10"), _rec("z", "2026-09")])
    files = [p.name for p in al.ledger_files(tmp_path)]
    assert files == ["ledger-2026-09.jsonl", "ledger-2026-10.jsonl"]
    assert [r["key"] for r in al.iter_records(tmp_path / "ledger-2026-09.jsonl")] == ["x", "z"]


def test_batch_never_rewrites_and_survives_a_torn_tail(tmp_path):
    al.append_records(tmp_path, [_rec("a")])
    path = al.ledger_files(tmp_path)[0]
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"key":"torn"')  # crash mid-append
    before = path.read_bytes()
    al.append_records(tmp_path, [_rec("b")])
    assert path.read_bytes().startswith(before)
    assert [r["key"] for r in al.iter_records(path)] == ["a", "b"]


def test_missing_index_is_reseeded_not_forgotten(tmp_path):
    al.append_records(tmp_path, [_rec("a"), _rec("b")])
    al.index_path(tmp_path).unlink()
    assert al.append_records(tmp_path, [_rec("a"), _rec("c")]) == 1
    assert al.recorded_keys(tmp_path) == {"a", "b", "c"}


def test_single_record_api_is_unchanged(tmp_path):
    assert al.append_record(tmp_path, _rec("a")) is True
    assert al.append_record(tmp_path, _rec("a")) is False


def test_empty_batch_writes_nothing(tmp_path):
    assert al.append_records(tmp_path, []) == 0
    assert not al.index_path(tmp_path).exists()


# ── crash between a batch's data append and its index append (G4 review) ──


def _simulate_crash_after_data(tmp_path, records):
    """Lines durable in the ledger, keys never reached the index."""
    path = al.ledger_path(tmp_path, records[0]["recordedAt"])
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")


def test_a_crashed_batch_is_recovered_in_full_not_just_its_last_line(tmp_path):
    al.append_records(tmp_path, [_rec("a")])
    _simulate_crash_after_data(tmp_path, [_rec("b"), _rec("c"), _rec("d")])
    assert al.recorded_keys(tmp_path) == {"a", "b", "c", "d"}
    # The next refresh re-offers the same batch plus one new record.
    assert al.append_records(tmp_path, [_rec("b"), _rec("c"), _rec("d"), _rec("e")]) == 1
    keys = [r["key"] for r in al.iter_all_records(tmp_path)]
    assert keys == ["a", "b", "c", "d", "e"]
    # The recovered keys are now IN the index, so later writes cannot strand them.
    index = set(al.index_path(tmp_path).read_text(encoding="utf-8").split())
    assert index == {"a", "b", "c", "d", "e"}
    al.append_records(tmp_path, [_rec("f")])
    assert al.append_records(tmp_path, [_rec("b"), _rec("c")]) == 0
    assert len(list(al.iter_all_records(tmp_path))) == 6


def test_crash_injected_inside_append_records(tmp_path, monkeypatch):
    al.append_records(tmp_path, [_rec("a")])
    real = al._append_index

    def crash(*_a, **_k):
        raise OSError("power loss between data fsync and index append")

    monkeypatch.setattr(al, "_append_index", crash)
    with pytest.raises(OSError):
        al.append_records(tmp_path, [_rec("b"), _rec("c"), _rec("d")])
    monkeypatch.setattr(al, "_append_index", real)
    assert al.append_records(tmp_path, [_rec("b"), _rec("c"), _rec("d")]) == 0
    assert [r["key"] for r in al.iter_all_records(tmp_path)] == ["a", "b", "c", "d"]


def test_crashed_batch_spanning_two_month_files_is_recovered(tmp_path):
    al.append_records(tmp_path, [_rec("a", "2026-09"), _rec("b", "2026-10")])
    _simulate_crash_after_data(tmp_path, [_rec("x", "2026-09")])
    _simulate_crash_after_data(tmp_path, [_rec("y", "2026-10")])
    assert al.append_records(tmp_path, [_rec("x", "2026-09"), _rec("y", "2026-10")]) == 0
    assert len(list(al.iter_all_records(tmp_path))) == 4


def test_recovery_skips_a_torn_tail_line(tmp_path):
    al.append_records(tmp_path, [_rec("a")])
    _simulate_crash_after_data(tmp_path, [_rec("b")])
    path = al.ledger_files(tmp_path)[-1]
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"key":"tor')
    assert al.recorded_keys(tmp_path) == {"a", "b"}
    assert al.append_records(tmp_path, [_rec("b"), _rec("c")]) == 1
    assert [r["key"] for r in al.iter_all_records(tmp_path)] == ["a", "b", "c"]
