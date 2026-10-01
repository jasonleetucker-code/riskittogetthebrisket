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
        result = shadow.record_board(raw, payload_path, base=ledger_dir, source="archive")
        again = shadow.record_board(raw, payload_path, base=ledger_dir, source="archive")
    return {
        "raw": raw,
        "before": before,
        "result": result,
        "again": again,
        "ledger": shadow.ledger_path(ledger_dir),
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


def test_re_recording_the_same_board_is_a_no_op(recorded):
    _record, written = recorded["again"]
    assert written is False
    lines = recorded["ledger"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_the_recorder_never_writes_a_served_field(recorded):
    # 1. Its only file writes are the ledger itself.
    ledger = os.path.abspath(recorded["ledger"])
    assert recorded["writes"] and set(recorded["writes"]) == {ledger}
    # 2. The input payload is not mutated.
    assert recorded["raw"] == recorded["before"]
    # 3. The flag is back at its served default: nothing later builds C.
    assert feature_flags.is_enabled("sparse_evidence_estimator") is False
    # 4. A ledger line uses none of a served row's field names.
    line = json.loads(recorded["ledger"].read_text(encoding="utf-8").splitlines()[0])
    assert not (_keys(line["rows"]) | set(line)) & SERVED_FIELDS


def test_the_module_has_no_write_path_but_the_ledger_append():
    """Structural: the only file-writing call in the module is in ``append_record``."""
    tree = ast.parse(inspect.getsource(shadow))
    writers = {"write_text", "write_bytes", "replace", "rename", "unlink", "dump"}
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


def test_a_torn_final_line_is_repaired_without_rewriting(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"key": "a"}\n{"key": "b", "tor', encoding="utf-8")
    assert shadow.append_record(path, {"key": "c"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"key": "a"}' and lines[1] == '{"key": "b", "tor'
    assert [r["key"] for r in shadow.iter_records(path)] == ["a", "c"]
    assert not shadow.append_record(path, {"key": "a"})


def test_shadow_rows_flag_a_scope_disagreement():
    inc = {"playersArray": [{"displayName": "X", "position": "WR", "rankDerivedValue": 300,
                             "singleSourceValuePenaltyApplied": True}]}  # fmt: skip
    ch = {"playersArray": [{"displayName": "X", "position": "WR", "rankDerivedValue": 1000}]}
    rows, counts = shadow.shadow_rows(inc, ch)
    assert rows == [] and counts == {"haircutRowsWithoutBlock": 1}


def test_cli_without_a_payload_is_a_soft_failure(tmp_path, monkeypatch):
    import scripts.sparse_evidence_shadow as cli  # noqa: PLC0415

    monkeypatch.setattr(shadow, "newest_live_payload", lambda _root: None)
    assert cli.main(["record", "--dir", str(tmp_path)]) == 1
    assert not any(Path(tmp_path).iterdir())
