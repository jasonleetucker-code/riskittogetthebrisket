import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT_OS = REPO / "docs" / "AGENT_OPERATING_SYSTEM.md"
SCRIPT = REPO / "scripts" / "agent_os_receipt.py"


def test_agent_os_receipt_matches_git_blob_hash():
    expected = subprocess.run(
        ["git", "hash-object", "--no-filters", str(AGENT_OS)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    match = re.search(r"Agent OS loaded: ([0-9a-f]+)", result.stdout)
    assert match is not None
    assert match.group(1) == expected
    assert "first material checkpoint" in result.stdout


def test_session_start_hook_invokes_the_receipt_owner():
    hook = (REPO / ".claude" / "health-check.sh").read_text(encoding="utf-8")
    assert "python scripts/agent_os_receipt.py || true" in hook


def test_operating_system_requires_receipt_propagation():
    doc = AGENT_OS.read_text(encoding="utf-8")
    assert "Agent OS session receipt" in doc
    assert "Agent OS loaded: <git-blob-sha>" in doc
    assert "first meaningful progress checkpoint" in doc
    assert "PR description, final handoff" in doc
    assert "proves **which bytes the startup harness loaded**" in doc
