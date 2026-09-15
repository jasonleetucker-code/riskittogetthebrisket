"""Execute the safe branch with command sentinels; never access a remote host."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/diagnostics/c1a_closure_inventory.sh"


def run_inventory(scope="performance-safe", service="dynasty", failure=False):
    installed = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(installed) if installed.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash unavailable")
    prelude = r"""
APP_DIR="$PWD"
git() { [[ "$*" == *'rev-parse --verify HEAD' ]] || { echo FORBIDDEN_SECRET; return 91; }; printf '%040d\n' 1; }
systemctl() {
  [[ "$1" == show && "$3" == --property=* && "$4" == --value ]] || { echo FORBIDDEN_MUTATION; return 92; }
  [[ "${PROBE_FAILURE:-0}" == 0 ]] || return 1
  case "$3" in
    --property=LoadState) echo loaded ;;
    --property=ActiveState) echo inactive ;;
    --property=SubState) echo dead ;;
    --property=UnitFileState) echo static ;;
    --property=User|--property=Group) echo 'FORBIDDEN_SECRET=/key' ;;
    --property=MainPID) echo 0 ;;
    *) echo '123
FORBIDDEN_SECRET' ;;
  esac
}
journalctl() { echo FORBIDDEN_JOURNAL; return 93; }
sudo() { echo FORBIDDEN_SUDO; return 94; }
hostname() { echo FORBIDDEN_HOSTNAME; return 95; }
"""
    result = subprocess.run(
        [bash, "--noprofile", "--norc"],
        input=prelude + SCRIPT.read_text(encoding="utf-8"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        env={
            **os.environ,
            "INVENTORY_SCOPE": scope,
            "SERVICE_NAME": service,
            "PROBE_FAILURE": "1" if failure else "0",
        },
        timeout=30,
    )
    return result


def test_safe_scope_filters_arbitrary_unit_text_and_never_reaches_legacy():
    result = run_inventory()
    assert result.returncode == 0, result.stderr
    assert "FORBIDDEN" not in result.stdout + result.stderr
    assert "scope=performance-safe" in result.stdout
    assert "unit.dynasty.service.LoadState=loaded" in result.stdout
    assert "unit.dynasty.service.User=unavailable" in result.stdout
    assert "unit.dynasty.service.MemoryCurrent=unavailable" in result.stdout
    assert "unit.dynasty-source-producer.path.LoadState=loaded" in result.stdout
    assert "unit.nginx.service.LoadState=loaded" in result.stdout
    assert "snapshot_only" in result.stdout
    assert "[c1a-inventory]" not in result.stdout


@pytest.mark.parametrize("scope", ["restart", "performance-safe;echo SECRET", "unknown"])
def test_unknown_scope_refuses_before_any_inventory(scope):
    result = run_inventory(scope=scope)
    assert result.returncode == 1
    assert result.stdout == "inventory_error=invalid_scope\n"
    assert result.stderr == ""


@pytest.mark.parametrize("service", ["../other", "dynasty.service", "dynasty;restart", "bad\nname"])
def test_invalid_unit_prefix_refuses_without_echoing_input(service):
    result = run_inventory(service=service)
    assert result.returncode == 1
    assert result.stdout == "inventory_error=invalid_service\n"


def test_failed_probe_is_unknown_not_absent_or_denied():
    result = run_inventory(failure=True)
    assert result.returncode == 0
    assert "unit.dynasty.service.LoadState=probe_failed" in result.stdout
    assert "LoadState=not-found" not in result.stdout


def test_existing_workflow_default_and_concurrency_remain():
    workflow = (ROOT / ".github/workflows/c1a-closure-diagnostics.yml").read_text()
    assert "default: closure" in workflow
    assert "group: c1a-closure-diagnostics" in workflow
    assert "cancel-in-progress: false" in workflow
    assert 'INVENTORY_SCOPE=$(printf %q "$INVENTORY_SCOPE")' in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.index('case "${INVENTORY_SCOPE:-closure}"') < script.index('say "host=')
    assert "closure) ;;" in script
    # Existing closure output is still present behind the separate default branch.
    assert 'kv "remote origin"' in script
