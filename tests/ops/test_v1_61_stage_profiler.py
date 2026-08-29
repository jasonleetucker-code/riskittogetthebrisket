from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "profile_sharp_roster_percentage.py"
_SPEC = importlib.util.spec_from_file_location("profile_sharp_roster_percentage", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


class _Owner:
    def work(self, value: int) -> int:
        return value + 1

    def fail(self) -> None:
        raise RuntimeError("boom")


def test_stage_recorder_preserves_return_value_and_restores_owner() -> None:
    owner = _Owner()
    original = owner.work.__func__
    recorder = _MOD.StageRecorder()

    recorder.wrap(owner, "work", "work")
    assert owner.work(4) == 5
    report = recorder.report()["work"]
    assert report["calls"] == 1
    assert report["totalMs"] >= 0
    assert report["maxMs"] >= 0

    recorder.restore()
    assert owner.work.__func__ is original
    assert owner.work(9) == 10


def test_stage_recorder_records_failure_without_swallowing_it() -> None:
    owner = _Owner()
    recorder = _MOD.StageRecorder()
    recorder.wrap(owner, "fail", "fail")

    try:
        owner.fail()
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:  # pragma: no cover - load-bearing negative assertion
        raise AssertionError("wrapped exception was swallowed")

    assert recorder.report()["fail"]["calls"] == 1
    recorder.restore()


def test_load_contract_accepts_direct_and_nested_payloads(tmp_path: Path) -> None:
    direct = tmp_path / "direct.json"
    direct.write_text('{"playersArray": [{"playerId": "1"}]}', encoding="utf-8")
    assert _MOD._load_contract(direct)["playersArray"][0]["playerId"] == "1"

    nested = tmp_path / "nested.json"
    nested.write_text(
        '{"contract": {"playersArray": [{"playerId": "2"}]}}',
        encoding="utf-8",
    )
    assert _MOD._load_contract(nested)["playersArray"][0]["playerId"] == "2"


def test_load_contract_refuses_missing_players_array(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"status": "ok"}', encoding="utf-8")

    try:
        _MOD._load_contract(path)
    except ValueError as exc:
        assert "no playersArray" in str(exc)
    else:  # pragma: no cover - load-bearing negative assertion
        raise AssertionError("invalid contract was accepted")
