"""``append_ledger.append_records``: the batch form keeps ``append_record``'s
append-only / idempotent semantics (it is now the single implementation)."""

from __future__ import annotations

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
