"""The on-box Signals verification script runs end to end on a synthetic box.

It is executed for real only on the production host (workflow
``signals-onbox-verification.yml``); this keeps it from rotting in between by
driving its builders and reports against the synthetic Signals fixture used by
``tests/api/test_signals_active_source.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "api"))

import test_signals_active_source as fixture  # noqa: E402


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "verify_signals_onbox", REPO / "scripts" / "verify_signals_onbox.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("box")
    fixture._write_store(root)
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "dynasty_data_2026-10-03.json").write_text(
        json.dumps(fixture._raw_payload()), encoding="utf-8"
    )
    return root


def test_builds_and_reports(box):
    mod = _load_script()
    champion, shipped, promoted, payload = mod.build_three(box)
    assert payload == "dynasty_data_2026-10-03.json"
    off = mod.offense_report(champion, shipped, mod.collector_state(box))
    assert off["availability"]["votes"] is True
    assert off["rowsVoted"] > 50
    assert off["fantasyCalcFamilyCap"]["maxCombinedPostCap"] <= 1.0 + 1e-9
    idp = mod.idp_report(shipped, promoted, mod._family_ladders())
    for fam, rep in idp["families"].items():
        assert rep["translated"] > 10, fam
        assert rep["extrapolated"] == 0
        assert rep["familyMismatches"] == 0
        assert rep["coordinatePools"] == ["shared_market"]
    assert idp["nonIdpRowsMovedIfPromoted"] == 0
    watch = mod.watch_list(shipped, promoted)
    assert any(w["why"].endswith("_elite") for w in watch)
    trades = mod.trade_check(box, shipped, promoted)
    assert trades == {"available": False, "reason": "ledger_not_built_on_this_host"}


def test_offense_build_without_signals_is_the_champion(box):
    mod = _load_script()
    champion, shipped, _promoted, _ = mod.build_three(box)
    assert champion["privateSourceAvailability"]["signalsSf"]["votes"] is False
    assert shipped["privateSourceAvailability"]["signalsSf"]["votes"] is True
