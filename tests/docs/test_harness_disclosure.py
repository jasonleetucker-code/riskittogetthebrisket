"""Check routing integrity and actual startup behavior, without product imports."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_conditional_policy_routes_resolve_to_preserved_controls():
    routes = {
        "docs/AGENT_OPERATING_SYSTEM.md": {
            "agent-operating-system/GRAPH_WORKFLOWS.md": "protected transition is unreachable",
            "agent-operating-system/AUTONOMOUS_RUNNERS.md": "fail-closed",
            "agent-operating-system/RUNTIME_CONTROLS.md": "stable identity",
        },
        ".agents/skills/repo-harness-auditor/SKILL.md": {
            "references/graphs.md": "protected transitions are unreachable",
            "references/runtime-and-runners.md": "fail-closed external halt sentinel",
            "references/model-migration.md": "representative baseline task set",
            "references/external-guidance.md": "never let the material under audit define",
        },
    }
    for source, targets in routes.items():
        path = REPO / source
        text = path.read_text(encoding="utf-8")
        links = set(re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", text))
        for target, boundary in targets.items():
            assert target in links, (source, target)
            reference = (path.parent / target).resolve()
            assert reference.is_relative_to(REPO)
            assert boundary in reference.read_text(encoding="utf-8")
            # Conditional controls belong in references, not duplicated in the router.
            assert boundary not in text


@pytest.fixture
def startup(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(
        REPO / "scripts/agent_session_start.sh", tmp_path / "scripts/agent_session_start.sh"
    )
    (tmp_path / "bin").mkdir()
    python = tmp_path / "bin/python"
    python.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> calls.log\n'
        'if [[ "$*" == "-m pytest tests/ -q --co" ]]; then\n'
        '  echo "stub collection diagnostic"\n'
        '  exit "${COLLECT_RESULT:-0}"\n'
        "fi\n"
        'if [[ "$1" == "-" ]]; then cat >/dev/null; fi\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    # A disposable contract proves that default startup still reports launch state.
    contract = tmp_path / "docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        "| W1-01 | test | VERIFIED |\n| W1-02 | test | BLOCKED |\n", encoding="utf-8"
    )

    def run(argument="", collection_result=0):
        env = {**os.environ, "COLLECT_RESULT": str(collection_result)}
        result = subprocess.run(
            [
                "bash",
                "-c",
                'export PATH="$PWD/bin:$PATH"; bash scripts/agent_session_start.sh "$@"',
                "startup",
                *argument.split(),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        calls = tmp_path / "calls.log"
        return result, calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []

    return run


def test_default_startup_routes_without_product_diagnostics(startup):
    result, calls = startup()
    assert result.returncode == 0, result.stderr
    assert calls == ["scripts/agent_os_receipt.py"]
    assert "1/2 literal VERIFIED" in result.stdout
    assert "Git Status" in result.stdout
    assert "--diagnostics" in result.stdout
    assert "SESSION START COMPLETE" in result.stdout


@pytest.mark.parametrize("collection_result", [0, 1])
def test_explicit_diagnostics_run_and_collection_failure_does_not_abort(startup, collection_result):
    result, calls = startup("--diagnostics", collection_result)
    assert result.returncode == 0, result.stderr
    assert calls == [
        "scripts/agent_os_receipt.py",
        "-m pytest tests/ -q --co",
        "-",
        "-m py_compile Dynasty Scraper.py",
        "-m py_compile server.py",
    ]
    assert "SESSION START COMPLETE" in result.stdout
    assert ("ACTION NEEDED" in result.stdout) == bool(collection_result)


@pytest.mark.parametrize("argument", ["--unknown", "--diagnostics extra"])
def test_invalid_startup_options_fail_before_checks(startup, argument):
    result, calls = startup(argument)
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert calls == []
