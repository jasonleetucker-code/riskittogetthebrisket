"""Sparse-evidence shadow recorder: records both answers, writes nothing served.

``src/api/sparse_evidence_shadow.py``. The estimator stays OFF (G2c); this only
accumulates the evidence a re-preregistered candidate would need.
"""

from __future__ import annotations

import ast
import builtins
import copy
import inspect
import io
import json
import os
from pathlib import Path

import pytest

from src.api import feature_flags
from src.api import sparse_evidence as se
from src.api import sparse_evidence_shadow as shadow
from tests.archive_fixtures import newest_complete_raw_payload

#: Field names a served contract row carries.  A ledger line must never use
#: them, so it can never be read back as (or mistaken for) a served row.
SERVED_FIELDS = {
    "playersArray",
    "players",
    "rankDerivedValue",
    "canonicalConsensusRank",
    "_blendedValueUncapped",
    "sparseEvidence",
    "confidenceBucket",
    "singleSourceValuePenaltyApplied",
}


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    raw, _name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape")
    base = tmp_path_factory.mktemp("shadow")
    payload_path = base / "payload.json"
    payload_path.write_text(json.dumps(raw), encoding="utf-8")
    before = copy.deepcopy(raw)

    writes: list[str] = []
    real_open = builtins.open

    def tracking_open(file, mode="r", *a, **kw):
        if any(c in mode for c in "wax+"):
            writes.append(os.path.abspath(os.fspath(file)))
        return real_open(file, mode, *a, **kw)

    ledger_dir = base / "ledger"
    with pytest.MonkeyPatch.context() as m:
        # pathlib routes through io.open, everything else through builtins.open.
        m.setattr(builtins, "open", tracking_open)
        m.setattr(io, "open", tracking_open)
        result = shadow.record_board(
            raw, payload_path, base=ledger_dir, source="archive", payload_age_hours=1.25
        )
        again = shadow.record_board(raw, payload_path, base=ledger_dir, source="archive")
    return {
        "raw": raw,
        "before": before,
        "result": result,
        "again": again,
        "ledger": shadow.ledger_path(ledger_dir, result[0]["recordedAt"]),
        "index": shadow.index_path(ledger_dir),
        "ledger_dir": ledger_dir,
        "writes": writes,
    }


def test_records_both_answers_for_every_scoped_row(recorded):
    record, written = recorded["result"]
    assert written
    assert record["schema"] == shadow.SCHEMA
    assert record["identity"]["estimator"] == se.ESTIMATOR_VERSION
    assert record["identity"]["payloadSha256"] == record["board"]["payloadSha256"]
    assert record["pins"]["codeRevision"]
    assert record["counts"]["scoped"] == len(record["rows"]) > 0
    assert record["counts"].get("haircutRowsWithoutBlock", 0) == 0
    assert record["counts"].get("blockWithoutHaircut", 0) == 0
    for row in record["rows"]:
        assert row["evidenceState"] in se.IN_SCOPE_STATES
        assert row["incumbentValue"] is not None and row["challengerEstimate"] is not None
        low, high = row["challengerInterval"]
        assert low <= high == row["observedValue"]
        assert row["intervalLabel"] == "sensitivity_uncalibrated"
    assert sum(record["evidenceStates"].values()) == len(record["rows"])
    assert record["board"]["payloadAgeHours"] == 1.25
    assert record["board"]["staleBudgetHours"] == 6


def test_re_recording_the_same_board_is_a_no_op(recorded):
    _record, written = recorded["again"]
    assert written is False
    lines = recorded["ledger"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_the_recorder_never_writes_a_served_field(recorded):
    # 1. Its only file writes are the monthly ledger and its key index.
    ledger = os.path.abspath(recorded["ledger"])
    index = os.path.abspath(recorded["index"])
    assert recorded["writes"] and set(recorded["writes"]) == {ledger, index}
    # 2. The input payload is not mutated.
    assert recorded["raw"] == recorded["before"]
    # 3. The flag is back at its served default: nothing later builds C.
    assert feature_flags.is_enabled("sparse_evidence_estimator") is False
    # 4. A ledger line uses none of a served row's field names.
    line = json.loads(recorded["ledger"].read_text(encoding="utf-8").splitlines()[0])
    assert not (_keys(line["rows"]) | set(line)) & SERVED_FIELDS


def test_the_module_has_no_write_path_but_the_ledger_append():
    """Structural: the only file-writing call -- in this module and in the shared
    append-only owner it delegates to -- is in ``append_record``."""
    from src.utils import append_ledger  # noqa: PLC0415

    writers = {"write_text", "write_bytes", "replace", "rename", "unlink", "dump"}
    for module in (shadow, append_ledger):
        tree = ast.parse(inspect.getsource(module))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in writers:
                        raise AssertionError(f"{fn.name} calls {node.func.attr}")
                    if node.func.attr == "open" and fn.name != "append_record":
                        mode = node.args[0] if node.args else None
                        assert isinstance(mode, ast.Constant) and mode.value in ("r", "rb"), fn.name
    source = inspect.getsource(shadow)
    assert "latest_contract_data" not in source
    assert "set_enabled" not in source and "_DEFAULTS" not in source


def _rec(key, month="2026-10"):
    return {"key": key, "recordedAt": f"{month}-01T08:05:00+00:00"}


def test_a_torn_final_line_is_repaired_without_rewriting(tmp_path):
    path = shadow.ledger_path(tmp_path, "2026-10")
    path.write_text('{"key": "a"}\n{"key": "b", "tor', encoding="utf-8")
    assert shadow.append_record(tmp_path, _rec("c"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"key": "a"}' and lines[1] == '{"key": "b", "tor'
    assert [r["key"] for r in shadow.iter_records(path)] == ["a", "c"]
    assert not shadow.append_record(tmp_path, _rec("a"))


def test_records_rotate_monthly_and_nothing_is_lost(tmp_path):
    # A pre-rotation single-file ledger stays readable and its keys still count.
    (tmp_path / shadow.LEGACY_LEDGER_NAME).write_text('{"key": "old"}\n', encoding="utf-8")
    assert not shadow.append_record(tmp_path, _rec("old", "2026-11"))
    assert shadow.append_record(tmp_path, _rec("sep", "2026-09"))
    assert shadow.append_record(tmp_path, _rec("oct1", "2026-10"))
    assert shadow.append_record(tmp_path, _rec("oct2", "2026-10"))
    assert [p.name for p in shadow.ledger_files(tmp_path)] == [
        "ledger.jsonl",
        "ledger-2026-09.jsonl",
        "ledger-2026-10.jsonl",
    ]
    assert [r["key"] for r in shadow.iter_all_records(tmp_path)] == ["old", "sep", "oct1", "oct2"]
    keys = shadow.index_path(tmp_path).read_text(encoding="utf-8").split()
    assert sorted(keys) == ["oct1", "oct2", "old", "sep"]


def test_idempotency_reads_the_index_not_the_ledger(tmp_path, monkeypatch):
    assert shadow.append_record(tmp_path, _rec("a"))
    assert shadow.append_record(tmp_path, _rec("b"))

    def _no_full_scan(*_a, **_k):
        raise AssertionError("re-parsed the whole ledger")

    from src.utils import append_ledger  # noqa: PLC0415

    # The scan, if any, happens inside the shared owner shadow delegates to.
    monkeypatch.setattr(append_ledger, "iter_records", _no_full_scan)
    monkeypatch.setattr(shadow, "iter_records", _no_full_scan)
    assert not shadow.append_record(tmp_path, _rec("a"))
    assert shadow.append_record(tmp_path, _rec("c"))


def test_a_missing_index_is_rebuilt_from_the_files(tmp_path):
    for k in ("a", "b"):
        assert shadow.append_record(tmp_path, _rec(k))
    shadow.index_path(tmp_path).unlink()
    assert not shadow.append_record(tmp_path, _rec("a"))
    assert shadow.append_record(tmp_path, _rec("c"))
    keys = sorted(shadow.index_path(tmp_path).read_text(encoding="utf-8").split())
    assert keys == ["a", "b", "c"]


def test_a_crash_between_ledger_and_index_does_not_duplicate(tmp_path):
    assert shadow.append_record(tmp_path, _rec("a"))
    # The ledger line landed; the process died before the index append.
    with shadow.ledger_path(tmp_path, "2026-10").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_rec("b")) + "\n")
    assert not shadow.append_record(tmp_path, _rec("b"))
    assert [r["key"] for r in shadow.iter_all_records(tmp_path)] == ["a", "b"]


def _payload(root, rel, stamp):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"scrapeTimestamp": stamp} if stamp else {"date": "2026-10-01"}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_freshest_payload_wins_by_its_own_scrape_time(tmp_path):
    from datetime import datetime, timezone  # noqa: PLC0415

    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    _payload(tmp_path, "exports/latest/dynasty_data_2026-10-01.json", "2026-09-29T12:00:00Z")
    fresh = _payload(tmp_path, "data/dynasty_data_2026-10-01.json", "2026-10-01T10:00:00Z")
    path, raw, age = shadow.newest_live_payload(tmp_path, now=now)
    assert path == fresh and raw["scrapeTimestamp"].startswith("2026-10-01")
    assert age == pytest.approx(2.0)


def test_a_payload_without_a_scrape_time_has_unknown_age(tmp_path):
    _payload(tmp_path, "exports/latest/dynasty_data_x.json", None)
    _path, _raw, age = shadow.newest_live_payload(tmp_path)
    assert age is None


@pytest.mark.parametrize("age", [6.5, None])
def test_cli_refuses_a_stale_or_ageless_board(tmp_path, monkeypatch, age):
    import scripts.sparse_evidence_shadow as cli  # noqa: PLC0415

    payload = _payload(tmp_path, "p/dynasty_data.json", "2026-01-01T00:00:00Z")

    def _boom(*_a, **_k):
        raise AssertionError("a stale board was built")

    monkeypatch.setattr(
        shadow, "newest_live_payload", lambda _root, **_k: (payload, {}, age, b"{}")
    )
    monkeypatch.setattr(shadow, "record_board", _boom)
    ledger_dir = tmp_path / "ledger"
    assert cli.main(["record", "--dir", str(ledger_dir)]) == 3
    assert not ledger_dir.exists()


def test_cli_allow_stale_records_and_passes_the_age(tmp_path, monkeypatch):
    import scripts.sparse_evidence_shadow as cli  # noqa: PLC0415

    payload = _payload(tmp_path, "p/dynasty_data.json", "2026-01-01T00:00:00Z")
    seen = {}

    def _fake(raw, path, *, base, source, payload_age_hours, payload_bytes=None):
        seen["age"] = payload_age_hours
        return {"counts": {}, "evidenceStates": {}, "board": {"payloadAgeHours": 9.0}}, True

    monkeypatch.setattr(
        shadow, "newest_live_payload", lambda _root, **_k: (payload, {}, 9.0, b"{}")
    )
    monkeypatch.setattr(shadow, "record_board", _fake)
    assert cli.main(["record", "--dir", str(tmp_path / "l"), "--allow-stale"]) == 0
    assert seen["age"] == 9.0


def test_shadow_rows_flag_a_scope_disagreement():
    inc = {"playersArray": [{"displayName": "X", "position": "WR", "rankDerivedValue": 300,
                             "singleSourceValuePenaltyApplied": True}]}  # fmt: skip
    ch = {"playersArray": [{"displayName": "X", "position": "WR", "rankDerivedValue": 1000}]}
    rows, counts = shadow.shadow_rows(inc, ch)
    assert rows == [] and counts == {"haircutRowsWithoutBlock": 1}


def test_cli_without_a_payload_is_a_soft_failure(tmp_path, monkeypatch):
    import scripts.sparse_evidence_shadow as cli  # noqa: PLC0415

    monkeypatch.setattr(shadow, "newest_live_payload", lambda _root, **_k: None)
    assert cli.main(["record", "--dir", str(tmp_path)]) == 1
    assert not any(Path(tmp_path).iterdir())


def test_a_torn_index_line_never_swallows_the_next_key(tmp_path):
    """A crash mid-append to ledger.keys leaves a partial line; the next key must
    land on its own line so it is recognised (no duplicate on a re-record)."""
    rec_a = {"key": "board-a", "recordedAt": "2026-10-01T08:05:00+00:00"}
    rec_b = {"key": "board-b", "recordedAt": "2026-10-01T20:05:00+00:00"}
    assert shadow.append_record(tmp_path, rec_a)
    index = shadow.index_path(tmp_path)
    with index.open("a", encoding="utf-8") as fh:
        fh.write("board-tor")  # torn: no trailing newline
    assert shadow.append_record(tmp_path, rec_b)
    assert "board-b" in shadow.recorded_keys(tmp_path)
    assert not shadow.append_record(tmp_path, rec_b)
