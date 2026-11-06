"""``evaluate`` command end to end on synthetic inputs: receipt gate, finality, predictions
path, PROV from a real archive on disk, deterministic evidence file.  No network."""

from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from datetime import timedelta
from pathlib import Path

from src.ros import weekly_projection_archive as arch
from src.ros.idp_opportunity.prospective import fit_frozen
from tests.ros.idp_opportunity._fixtures import card, season
from tests.ros.idp_opportunity.test_prospective_eval import (
    FP_BLOB,
    FROZEN_BASE,
    KICK_AAA,
    RECEIPT,
    WEEK,
    _row,
)

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/idp_opportunity_prospective_evaluate.py"
SCRIPT_REL = "scripts/idp_opportunity_prospective.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_idp_prosp_e2e", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_refuses_weeks_outside_the_evaluation_window():
    mod = _load_script()
    assert mod.main(["evaluate", "--week", "8"]) == 2
    assert mod.main(["evaluate", "--week", "9", "--retrospective"]) == 2


def test_cmd_evaluate_end_to_end(tmp_path, monkeypatch):
    mod = _load_script()
    data = season(6)
    fp, diag = fit_frozen(data, card(), [2, 3, 4])
    out_dir = tmp_path / mod.OUT_DIR
    (out_dir / "freeze_receipts").mkdir(parents=True)
    frozen = {**FROZEN_BASE, "fit": diag, "params": fp.to_dict()}
    (tmp_path / mod.FROZEN).write_text(json.dumps(frozen), encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / SCRIPT_REL).write_text("# stub\n", encoding="utf-8")
    (tmp_path / "src/ros/idp_opportunity").mkdir(parents=True)
    for name in ("prospective.py", "model.py", "prospective_eval.py", "evaluate.py"):
        (tmp_path / "src/ros/idp_opportunity" / name).write_text("# stub\n", encoding="utf-8")
    receipt_rel = (mod.OUT_DIR / "freeze_receipts" / "week06.json").as_posix()
    (tmp_path / receipt_rel).write_text(json.dumps(RECEIPT), encoding="utf-8")
    blobs = {
        mod.FROZEN.as_posix(): FP_BLOB,
        "src/ros/idp_opportunity/prospective.py": "p" * 40,
        "src/ros/idp_opportunity/model.py": "m" * 40,
        SCRIPT_REL: "s" * 40,
        receipt_rel: "r" * 40,
    }
    added = {receipt_rel: (KICK_AAA - timedelta(days=2)).isoformat()}

    def fake_git(*a):
        if a[0] == "hash-object":
            return blobs.get(a[1], "e" * 40)
        if a[0] == "log":
            return added.get(a[-1], "")
        if a[0] == "ls-files":
            return a[-1]
        if a[0] == "status":
            return ""
        if a[0] == "cat-file":
            return None
        return None

    games_csv = tmp_path / "games.csv"
    games_csv.write_text(
        "season,game_type,week,home_team,away_team,gameday,gametime,result\n"
        "2026,REG,6,AAA,BBB,2026-11-04,20:15,3\n",
        encoding="utf-8",
    )
    league_json = tmp_path / "league.json"
    league_json.write_text(json.dumps({"status": "in_season"}), encoding="utf-8")

    def fake_download(url, cache, name, refresh=False):
        return (games_csv, "h1") if name == "games.csv" else (league_json, "h2")

    games = {"finalWeeks": [6], "firstKickoffUtc": {6: KICK_AAA}}
    archive = tmp_path / "archive"
    arch.record_capture(
        source_key="sleeperWeeklyProjections",
        season=2026,
        week=6,
        fetched_at=KICK_AAA - timedelta(days=1),
        rows=[_row("1", "AAA", "g", 5), _row("5", "BBB", "g", 6), _row("2", "AAA", "g", 3)],
        base_dir=archive,
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_git", fake_git)
    monkeypatch.setattr(mod, "_load", lambda args, w: (data, {"inputsHash": "x"}, games))
    monkeypatch.setattr(
        mod, "_card", lambda args, bt: (card(), {"fingerprint": "sf1:test", "source": "synthetic"})
    )
    monkeypatch.setattr(mod, "_backtest_helpers", lambda: None)
    monkeypatch.setattr(mod.S, "cached_download", fake_download)
    state = tmp_path / "state.json"
    args = Namespace(
        week=WEEK,
        cache_dir=str(tmp_path / "cache"),
        league_id="L",
        refresh=False,
        allow_deviation=False,
        retrospective=False,
        archive_root=str(archive),
        nfl_state_json=str(state),
        decision_inputs=None,
        scoring_card=None,
    )
    # the host still DISPLAYS week 6: scoring is done but lineups are not awarded -> refused
    state.write_text(json.dumps({"season": "2026", "display_week": 6}), encoding="utf-8")
    assert mod.cmd_evaluate(args) == 2
    assert not (out_dir / "evaluations").exists()
    # the host has moved on: final -> evaluated
    state.write_text(json.dumps({"season": "2026", "display_week": 7}), encoding="utf-8")
    assert mod.cmd_evaluate(args) == 0
    path = out_dir / "evaluations" / "week06.json"
    first = path.read_bytes()
    doc = json.loads(first)
    assert doc["label"] == "PROSPECTIVE"
    assert doc["predictionPath"] == "regenerated_from_frozen"
    assert doc["receipt"]["blob"] == "r" * 40
    assert doc["result"]["coverage"]["PROV"]["rows"] == 3
    assert doc["result"]["population"]["players"] == 9
    # deterministic: a re-run is byte-identical
    assert mod.cmd_evaluate(args) == 0
    assert path.read_bytes() == first
    # a receipt committed AFTER the first kickoff is refused, whatever else is true
    added[receipt_rel] = (KICK_AAA + timedelta(hours=1)).isoformat()
    path.unlink()
    assert mod.cmd_evaluate(args) == 2
    assert not path.exists()
    # the receipted script blob must equal the receipt's: a different blob is a deviation
    added[receipt_rel] = (KICK_AAA - timedelta(days=2)).isoformat()
    blobs[SCRIPT_REL] = "n" * 40
    assert mod.cmd_evaluate(args) == 2
    assert not path.exists()
    args.allow_deviation = True
    assert mod.cmd_evaluate(args) == 0
    assert json.loads(path.read_bytes())["label"].startswith("DEVIATION")


def test_receipted_script_is_untouched_by_the_evaluator():
    root = Path(__file__).resolve().parents[3]
    receipt = json.loads(
        (
            root
            / "docs/projections/evidence/idp_opportunity/prospective/freeze_receipts/week09.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["code"][SCRIPT_REL] == "beb7640f1a58e961f5a0949b007feb589a6df221"
