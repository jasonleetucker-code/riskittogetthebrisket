from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "profile_sharp_roster_percentage.py"
_SPEC = importlib.util.spec_from_file_location("profile_sharp_roster_percentage_default", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def _ok_payload() -> dict:
    return {
        "status": "ok",
        "totalQualifyingPlayers": 0,
        "players": [],
        "sample": {"eligibleRosters": 0},
        "exclusions": {"storedRosters": 0},
        "lastUpdated": None,
    }


def test_main_omits_contract_without_reading_latest_export(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        _MOD,
        "_parse_args",
        lambda: argparse.Namespace(contract=None, ledger_path=None, timeout_seconds=5),
    )
    monkeypatch.setattr(
        _MOD,
        "_latest_contract_path",
        lambda: (_ for _ in ()).throw(AssertionError("latest export must not be consulted")),
    )
    monkeypatch.setattr(_MOD, "_install_stage_wrappers", lambda recorder: None)

    def fake_build_board(*, contract=None, ledger_path=None):
        seen["contract"] = contract
        seen["ledger_path"] = ledger_path
        return _ok_payload()

    monkeypatch.setattr(_MOD.roster_percentage, "build_board", fake_build_board)

    assert _MOD.main() == 0
    assert seen == {"contract": None, "ledger_path": None}
    output = capsys.readouterr().out
    assert '"contractPath": null' in output
    assert '"contractPlayers": 0' in output


def test_main_loads_only_an_explicit_contract(monkeypatch, tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        '{"playersArray": [{"playerId": "42"}]}',
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        _MOD,
        "_parse_args",
        lambda: argparse.Namespace(contract=contract_path, ledger_path=None, timeout_seconds=5),
    )
    monkeypatch.setattr(_MOD, "_install_stage_wrappers", lambda recorder: None)

    def fake_build_board(*, contract=None, ledger_path=None):
        seen["contract"] = contract
        return _ok_payload()

    monkeypatch.setattr(_MOD.roster_percentage, "build_board", fake_build_board)

    assert _MOD.main() == 0
    assert isinstance(seen["contract"], dict)
    assert seen["contract"]["playersArray"][0]["playerId"] == "42"
