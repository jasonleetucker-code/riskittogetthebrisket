from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bestball_marginal_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("bestball_marginal_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_report_measures_cost_including_candidates():
    mod = _load()
    report = mod.build_report(draws=30, max_players=4)
    assert report["beforeSideReuse"]["supportedOnThisTree"] is True
    assert report["beforeSideReuse"]["used"] is True
    t = report["totals"]
    assert t["playersSimulated"] == 4
    assert t["afterRuns"] == sum(r["afterRuns"] for r in report["players"])
    assert t["simulatedRostersIncludingBefore"] == t["afterRuns"] + 4
    for r in report["players"]:
        assert r["simulatedRosters"] == 1 + r["afterRuns"] >= 2
        assert r["elapsedS"] is not None and r["mcStandardError"] is not None


def test_report_without_reuse_resimulates_the_before_side():
    mod = _load()
    report = mod.build_report(draws=30, max_players=2, reuse=False)
    assert report["beforeSideReuse"]["used"] is False
    assert all(r["beforeSide"]["reused"] == 0 for r in report["players"])
    assert all(r["beforeSide"]["computed"] == r["afterRuns"] for r in report["players"])


def test_cli_exit_codes(capsys):
    mod = _load()
    assert mod.main(["--draws", "1"]) == 2
    assert mod.main(["--draws", "30", "--max-players", "1"]) == 0
    assert "not a probability" in capsys.readouterr().out
