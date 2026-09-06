import importlib.util
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT_OS = REPO / "docs" / "AGENT_OPERATING_SYSTEM.md"
SCRIPT = REPO / "scripts" / "agent_os_receipt.py"
RECEIPT = REPO / ".claude" / "session-receipts" / "latest.env"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _parse_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _load_receipt_module():
    spec = importlib.util.spec_from_file_location("agent_os_receipt", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_os_receipt_matches_loaded_bytes_head_and_repo_state():
    expected_loaded = _git("hash-object", "--no-filters", str(AGENT_OS))
    expected_head_blob = _git("rev-parse", "HEAD:docs/AGENT_OPERATING_SYSTEM.md")
    expected_repo_head = _git("rev-parse", "HEAD")

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    assert re.search(r"^AGENT OS LOAD RECEIPT: ", result.stdout, re.MULTILINE)
    assert f"loaded={expected_loaded}" in result.stdout
    assert f"head_blob={expected_head_blob}" in result.stdout
    assert f"repo_head={expected_repo_head}" in result.stdout

    values = _parse_env(RECEIPT)
    assert values["AGENT_OS_PATH"] == "docs/AGENT_OPERATING_SYSTEM.md"
    assert values["AGENT_OS_LOADED_BLOB_SHA"] == expected_loaded
    assert values["AGENT_OS_HEAD_BLOB_SHA"] == expected_head_blob
    assert values["REPO_HEAD_SHA"] == expected_repo_head
    assert values["AGENT_OS_DIRTY"] == (
        "false" if expected_loaded == expected_head_blob else "true"
    )
    assert datetime.fromisoformat(values["LOADED_AT_UTC"].replace("Z", "+00:00"))
    assert not list(RECEIPT.parent.glob(".latest.*.tmp"))


def test_receipt_path_is_local_and_gitignored():
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(RECEIPT.relative_to(REPO))],
        cwd=REPO,
        check=False,
    )
    assert ignored.returncode == 0


def test_receipt_degrades_unprovable_state_to_unknown(monkeypatch, tmp_path):
    module = _load_receipt_module()
    monkeypatch.setattr(module, "AGENT_OS", tmp_path / "missing-agent-os.md")
    monkeypatch.setattr(module, "_git_text", lambda *args, **kwargs: module.UNKNOWN)

    values = module.build_receipt()

    assert values["AGENT_OS_LOADED_BLOB_SHA"] == "UNKNOWN"
    assert values["AGENT_OS_HEAD_BLOB_SHA"] == "UNKNOWN"
    assert values["REPO_HEAD_SHA"] == "UNKNOWN"
    assert values["AGENT_OS_DIRTY"] == "UNKNOWN"


def test_session_start_hook_invokes_the_receipt_owner():
    hook = (REPO / ".claude" / "health-check.sh").read_text(encoding="utf-8")
    assert "python scripts/agent_os_receipt.py || true" in hook


def test_claude_md_has_real_agent_os_import_on_own_line():
    claude_lines = (REPO / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert "@docs/AGENT_OPERATING_SYSTEM.md" in claude_lines


def test_operating_system_requires_receipt_propagation():
    doc = AGENT_OS.read_text(encoding="utf-8")
    assert "Agent OS session receipt" in doc
    assert "AGENT OS LOAD RECEIPT:" in doc
    assert ".claude/session-receipts/latest.env" in doc
    assert "Agent-OS-Receipt: <AGENT_OS_LOADED_BLOB_SHA>" in doc
    assert "new material work-claim status text" in doc
    assert "does **not** prove cognitive comprehension" in doc
