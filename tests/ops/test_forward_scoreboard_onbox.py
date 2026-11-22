"""DYN10 V1b: the on-box forward scoreboard workflow and its public-safe summarizer."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "forward-scoreboard-onbox.yml"
MEASURED = REPO / "docs" / "measurements" / "forward-scoreboard-2026-11-22.json"

_spec = importlib.util.spec_from_file_location(
    "forward_scoreboard_summary", REPO / "scripts" / "forward_scoreboard_summary.py"
)
summ = importlib.util.module_from_spec(_spec)
sys.modules["forward_scoreboard_summary"] = summ
_spec.loader.exec_module(summ)


def _cell(**over):
    base = {
        "foldsAttempted": 4,
        "foldsUsable": 2,
        "meanSpearman": 0.05,
        "foldsPositive": 2,
        "meanPartialR": 0.02,
        "meanZeroGapShare": 0.01,
        "verdict": "underpowered: 2 usable fold(s).",
        "spearmanByFold": [{"origin": "2026-09-12", "n": 400, "rho": 0.04}],
        "momentumControl": {"originsMeasured": 2, "meanPartialRhoGivenMomentum": -0.04},
    }
    base.update(over)
    return base


def _payload(board):
    return {
        "schema": "forward-scoreboard/v1",
        "inputs": {"mode": "ledger", "ledger": "/home/dynasty/app/data/temporal_ledger.sqlite"},
        "horizons": {
            "30": {
                "horizonDays": 30,
                "foldsAttempted": 4,
                "folds": [{"origin": "2026-09-12", "marketUniverse": 9}],
                "board": board,
                "sources": {"ktc": {"provider": "keepTradeCut", "byGroup": {"ALL": _cell()}}},
            }
        },
    }


def test_real_scoreboard_whitelist_carries_unavailable_board():
    payload = json.loads(MEASURED.read_text(encoding="utf-8"))
    out = summ.whitelist_scoreboard(payload)
    h30 = out["horizons"]["30"]
    assert h30["board"]["status"] == "unavailable"  # carried through, not dropped
    assert h30["board"]["reason"]
    assert "byGroup" not in h30["board"]
    assert set(h30["sources"]) == set(payload["horizons"]["30"]["sources"])
    cell = h30["sources"]["ktc"]["byGroup"]["ALL"]
    assert cell["foldsUsable"] == 2 and cell["meanSpearman"] is not None
    assert cell["spearmanByFold"][0]["origin"] and cell["spearmanByFold"][0]["rho"] is not None
    assert cell["momentumControl"]["verdict"]
    assert h30["folds"][0]["persistence"]["ALL"]["spearmanLevel"] is not None
    assert out["caveats"] and out["inputs"]["mode"] == "archive"
    text = json.dumps(out)
    assert "exports/" not in text and ".zip" not in text and "archiveDir" not in text


def test_measured_board_is_summarized_by_group():
    board = {"status": "measured", "byGroup": {"ALL": _cell(), "QB": _cell()}}
    out = summ.whitelist_scoreboard(_payload(board))
    assert out["horizons"]["30"]["board"]["status"] == "measured"
    assert set(out["horizons"]["30"]["board"]["byGroup"]) == {"ALL", "QB"}


def test_whitelist_drops_planted_private_fields():
    payload = _payload({"status": "measured", "byGroup": {"ALL": _cell(playerName="Jane Doe")}})
    h = payload["horizons"]["30"]
    h["board"]["byGroup"]["ALL"]["spearmanByFold"][0].update(
        assetKey="player:4046", playerName="Jane Doe"
    )
    h["board"]["byGroup"]["12345678"] = _cell()
    h["board"]["byGroup"]["ALL"]["originsUnusable"] = [
        {"origin": "2026-07-14", "reason": "read /home/dynasty/app/data/x.sqlite failed"}
    ]
    h["sources"]["99887766"] = {"provider": "x", "byGroup": {"ALL": _cell()}}
    h["sources"]["ktc"]["topAssets"] = ["Jane Doe", "player:4046"]
    h["folds"][0]["worstAsset"] = "player:4046"
    payload["caveats"] = ["fine caveat", "see /home/dynasty/app/data/temporal_ledger.sqlite"]
    payload["leaked"] = {"owner": "someone"}
    out = summ.whitelist_scoreboard(payload)
    text = json.dumps(out)
    for needle in (
        "Jane Doe",
        "player:4046",
        "12345678",
        "99887766",
        "/home/",
        ".sqlite",
        "leaked",
    ):
        assert needle not in text, needle
    assert out["caveats"] == ["fine caveat"] and out["caveatsDropped"] == 1
    assert out["inputs"] == {"mode": "ledger", "ledgerCorrections": None}
    unusable = out["horizons"]["30"]["board"]["byGroup"]["ALL"]["originsUnusable"][0]
    assert unusable["reason"] is None


def test_whitelist_is_pure():
    payload = _payload({"status": "unavailable", "reason": "none"})
    before = copy.deepcopy(payload)
    summ.whitelist_scoreboard(payload)
    assert payload == before


def test_cli_exit_codes(tmp_path):
    cmd = [sys.executable, str(REPO / "scripts" / "forward_scoreboard_summary.py")]
    good = tmp_path / "ok.json"
    good.write_text(
        json.dumps(_payload({"status": "unavailable", "reason": "r"})), encoding="utf-8"
    )
    assert subprocess.run([*cmd, str(good)], capture_output=True).returncode == 0
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert subprocess.run([*cmd, str(bad)], capture_output=True).returncode == 2
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not json", encoding="utf-8")
    proc = subprocess.run([*cmd, str(garbage)], capture_output=True, text=True)
    assert proc.returncode == 3
    assert proc.stdout.strip() == "summary failed: JSONDecodeError"
    missing = subprocess.run([*cmd, str(tmp_path / "nope.json")], capture_output=True, text=True)
    assert missing.returncode == 3 and missing.stdout.strip() == "summary failed: FileNotFoundError"
    assert str(tmp_path) not in missing.stdout


def test_workflow_shape():
    text = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert list(wf[True]) == ["workflow_dispatch"]  # dispatch only, no schedule
    assert wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["group"] == "forward-scoreboard-onbox"
    assert wf["concurrency"]["group"] != "production-deploy"
    assert "--ledger" in text and "trap 'rm -rf \"$WORK\"' EXIT" in text
    assert "-lt $((SIZE * 3))" in text  # 3x headroom refusal
    assert "market_trades" not in text


def test_workflow_drops_remote_stderr():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/forward_scoreboard_summary.py" in text
    assert "--markdown 2>/dev/null" in text
    assert ">/dev/null 2>&1" in text  # the scoreboard run itself is silent
