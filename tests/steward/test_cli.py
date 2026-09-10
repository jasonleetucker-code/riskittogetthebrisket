import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.steward.__main__ import main
from src.steward.store import StewardStore
from src.steward.sync import generated_conflicts

ROOT = Path(__file__).resolve().parents[2]


def test_brief_save_compiles_retrievable_knowledge_and_retains_partial(tmp_path, capsys):
    path = tmp_path / "state.db"
    state = StewardStore(path)
    state.write(
        "campaign", {"objective": "bounded harness work", "partial": ["P9"]}, expected_revision=0
    )
    state.close()
    args = ["--repo", str(ROOT), "--state", str(path), "brief", "--save"]
    assert main(args) == 0
    assert "UNKNOWN" in capsys.readouterr().out
    assert main(args) == 0
    capsys.readouterr()
    state = StewardStore(path)
    records = state.retrieve("campaign")["records"]
    assert len(records) == 1
    assert records[0]["summary"]["objective"] == "bounded harness work"
    assert records[0]["summary"]["partial"] == ["P9"]
    raw = state.raw_evidence(records[0]["evidence_ids"][0])
    assert raw["content"]["report"]["head"]
    assert raw["content"]["github"] is None
    assert state.read("campaign")[1]["partial"] == ["P9"]
    state.close()


def test_launch_checkpoint_cannot_skip_literal_rows(tmp_path):
    path = tmp_path / "state.db"
    update = tmp_path / "update.json"
    update.write_text(json.dumps({"task_states": {"P0": {"state": "SUPERSEDED"}}}))
    with pytest.raises(ValueError, match="literal launch"):
        main(
            [
                "--repo",
                str(ROOT),
                "--state",
                str(path),
                "checkpoint",
                str(update),
                "--expected-revision",
                "0",
            ]
        )


def test_generated_data_conflict_detected_in_real_git_history(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Steward test")
    (tmp_path / "data").mkdir()
    artifact = tmp_path / "data" / "generated.json"
    artifact.write_text('{"value": 1}\n')
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    git("switch", "-c", "candidate")
    artifact.write_text('{"value": 2}\n')
    git("commit", "-am", "candidate")
    candidate = git("rev-parse", "HEAD")
    git("switch", "main")
    artifact.write_text('{"value": 3}\n')
    git("commit", "-am", "new source")
    assert generated_conflicts(tmp_path, base, candidate, "main") == ["data/generated.json"]


def test_cli_new_process_reports_actual_head(tmp_path):
    output = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "src.steward",
            "--repo",
            str(ROOT),
            "--state",
            str(tmp_path / "state.db"),
            "brief",
            "--json",
        ],
        text=True,
        encoding="utf-8",
    )
    result = json.loads(output)
    assert len(result["head"]) == 40
    assert result["remote_observed_at"] is None
    assert result["manifest_rows"] == 163
    assert all(route["status"] == "BLOCKED" for route in result["routing"])


def test_integration_refuses_dirty_or_unobserved_remote(monkeypatch, capsys):
    import src.steward.__main__ as cli

    observation = {
        "head": "a" * 40,
        "origin_main": "b" * 40,
        "previous_main": "b" * 40,
        "changed_paths": [],
        "commits": [],
        "dirty": True,
    }
    monkeypatch.setattr(cli, "observe", lambda *args: observation)
    monkeypatch.setattr(cli, "generated_conflicts", lambda *args: [])
    monkeypatch.setattr(cli, "github_snapshot", lambda: {"head": "b" * 40})
    args = ["check-integration", "--base", "b" * 40, "--surfaces", "src/steward"]
    assert cli.main(args + ["--github"]) == 2
    observation["dirty"] = False
    assert cli.main(args) == 2
    assert cli.main(args + ["--github"]) == 0
    capsys.readouterr()


def test_open_pr_inventory_is_paginated(monkeypatch):
    import src.steward.__main__ as cli

    commands = []

    def output(command, **kwargs):
        commands.append(command)
        endpoint = command[2]
        if endpoint.endswith("commits/main"):
            return '{"sha": "observed"}'
        if "state=open" in endpoint:
            return '[[], [{"number": 1}]]'
        return "[]"

    monkeypatch.setattr(cli.subprocess, "check_output", output)
    result = cli.github_snapshot()
    assert result["pulls"] == [{"number": 1}]
    assert any("pulls?state=open" in command[2] and "--paginate" in command for command in commands)
