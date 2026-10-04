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
    assert idp["offensePlayerRowsMovedIfPromoted"] == 0
    assert "pickRowsMovedIfPromoted" in idp
    for rep in idp["families"].values():
        assert rep["signedRelBiasMedian"] is not None
        assert rep["bridgeRowsSignalsLacks"] >= 0
    watch = mod.watch_list(shipped, promoted)
    assert any(w["why"].endswith("_elite") for w in watch)
    trades = mod.trade_check(box, shipped, promoted)
    assert trades == {"available": False, "reason": "ledger_not_built_on_this_host"}


def test_offense_build_without_signals_is_the_champion(box):
    mod = _load_script()
    champion, shipped, _promoted, _ = mod.build_three(box)
    assert champion["privateSourceAvailability"]["signalsSf"]["votes"] is False
    assert shipped["privateSourceAvailability"]["signalsSf"]["votes"] is True


def test_what_leaves_the_box_is_aggregates_only(box, capsys, monkeypatch):
    """The repository is public: the workflow log and artifact must carry no
    player name, Signals per-player number or private board value.  The full
    report stays 0600 in the private store."""
    import os

    mod = _load_script()
    monkeypatch.setattr(mod, "check_timer", lambda app_dir: {"timer": "stub"})
    monkeypatch.setattr(
        mod,
        "check_session",
        lambda: {"state": "connected", "capturedAt": "2026-10-04T00:00:00Z"},
    )
    monkeypatch.setattr(sys, "argv", ["verify", "--app-dir", str(box)])
    assert mod.main() == 0
    text = capsys.readouterr().out
    public = json.loads(text)

    _c, shipped, _p, _ = mod.build_three(box)
    names = [r["displayName"] for r in shipped["playersArray"] if r.get("displayName")]
    for name in names:
        assert f'"{name}"' not in text, name
    for key in (
        "familyRank",
        "wouldContribute",
        "valueContribution",
        "sourceShadowMeta",
        "watchList",
        "largestDisagreements",
        "capturedAt",
    ):
        assert f'"{key}"' not in text, key
    assert public["session"] == {"state": "connected"}
    assert public["watchList_outcomes"], "the gate outcomes are still reported"
    assert all("label" in w and "player" not in w for w in public["watchList_outcomes"])

    private = box / public["privateReport"]
    assert private.is_file()
    assert oct(os.stat(private).st_mode & 0o777) == "0o600"
    full = json.loads(private.read_text(encoding="utf-8"))
    assert full["watchList"] and "player" in full["watchList"][0]


def test_the_guard_refuses_a_name_or_a_forbidden_key():
    mod = _load_script()
    with pytest.raises(ValueError):
        mod.assert_public_safe({"a": ["Josh Allen"]}, ["Josh Allen"])
    with pytest.raises(ValueError):
        mod.assert_public_safe({"x": {"wouldContribute": 1}}, [])
    mod.assert_public_safe({"counts": {"DL": 3}}, ["Josh Allen"])
