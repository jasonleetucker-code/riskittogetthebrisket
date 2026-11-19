"""The one CI apt installer repairs a runner with no Ubuntu archive and never skips (STAB-10).

Evidence the repair answers: Deploy run 44368941410, hard-gate shard 2 (image
ubuntu-26.04 20261103.629) -- ``apt-get update`` fetched only
packages.microsoft.com, so ``tesseract-ocr`` had no install candidate on all
four in-job attempts, while seven sibling shards on the same image passed.

``scripts/ci/install_apt_packages.sh`` runs here for real, against fake
``sudo`` / ``apt-get`` / ``apt-cache`` / ``dpkg`` on PATH that model a healthy
runner, the broken one, a flaky network, a restore that does not help and a
genuinely unknown package.  The workflow tests pin that every tesseract
install goes through the script and that no inline copy survives.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "install_apt_packages.sh"
WORKFLOWS = ROOT / ".github" / "workflows"
RESTORED = "ci-restored-ubuntu-archive.sources"

_FAKES = {
    "sudo": 'exec "$@"\n',
    "dpkg": "echo amd64\n",
    # update: honours a scripted number of transient failures; an index whose
    # Release says o=Ubuntu exists only on a healthy runner, or once the restored
    # sources file is present (unless the restored archive is unreachable).
    "apt-get": r"""
echo "apt-get $*" >> "$STATE/calls"
for a in "$@"; do case "$a" in update|install) verb="$a"; break;; esac; done
if [[ "$verb" == update ]]; then
  left=$(cat "$STATE/update_failures_left" 2>/dev/null || echo 0)
  if (( left > 0 )); then echo $((left - 1)) > "$STATE/update_failures_left"; exit 100; fi
  if [[ -e "$STATE/healthy" ]] || { [[ -e "$APT_ETC_DIR/sources.list.d/ci-restored-ubuntu-archive.sources" ]] && [[ ! -e "$STATE/restore_useless" ]]; }; then
    touch "$STATE/ubuntu_index"
  fi
  exit 0
fi
if [[ "$verb" == install ]]; then
  [[ -e "$STATE/ubuntu_index" ]] || { echo "E: Unable to locate package" >&2; exit 100; }
  for a in "$@"; do
    if grep -qx -- "$a" "$STATE/unknown" 2>/dev/null; then echo "E: Unable to locate package $a" >&2; exit 100; fi
  done
  touch "$STATE/installed"; exit 0
fi
exit 0
""",
    "apt-cache": r"""
[[ "$1" == policy ]] || exit 0
shift
if (( $# == 0 )); then
  echo "Package files:"
  echo " 500 https://packages.microsoft.com/ubuntu/26.04/prod resolute/main amd64 Packages"
  echo "     release o=microsoft-ubuntu-resolute-prod resolute,a=resolute"
  if [[ -e "$STATE/ubuntu_index" ]]; then
    echo " 500 http://archive.ubuntu.com/ubuntu resolute/universe amd64 Packages"
    echo "     release v=26.04,o=Ubuntu,a=resolute,n=resolute,l=Ubuntu,c=universe,b=amd64"
  fi
  exit 0
fi
for pkg in "$@"; do
  if [[ -e "$STATE/ubuntu_index" ]] && ! grep -qx -- "$pkg" "$STATE/unknown" 2>/dev/null; then
    printf '%s:\n  Installed: (none)\n  Candidate: 5.5.0-1\n' "$pkg"
  fi
done
""",
}


@pytest.fixture
def runner(tmp_path):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to run the installer")
    bin_dir, state, apt_dir = tmp_path / "bin", tmp_path / "state", tmp_path / "etc_apt"
    for d in (bin_dir, state, apt_dir / "sources.list.d"):
        d.mkdir(parents=True)
    for name, body in _FAKES.items():
        fake = bin_dir / name
        fake.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        fake.chmod(0o755)
    os_release = tmp_path / "os-release"
    os_release.write_text(
        'ID=ubuntu\nVERSION_ID="26.04"\nVERSION_CODENAME=resolute\n', encoding="utf-8"
    )
    keyring = tmp_path / "ubuntu-archive-keyring.gpg"
    keyring.write_bytes(b"key")

    def run(*packages: str):
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "STATE": str(state),
            "APT_ETC_DIR": str(apt_dir),
            "OS_RELEASE_FILE": str(os_release),
            "UBUNTU_KEYRING": str(keyring),
            "APT_RETRY_SLEEP_UNIT": "0",
        }
        return subprocess.run(
            [bash, str(SCRIPT), *packages], env=env, capture_output=True, text=True, timeout=60
        )

    def calls() -> list[str]:
        path = state / "calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    return {
        "run": run,
        "calls": calls,
        "state": state,
        "restored": apt_dir / "sources.list.d" / RESTORED,
        "os_release": os_release,
    }


def _verbs(calls: list[str]) -> list[str]:
    return [next(w for w in c.split() if w in ("update", "install")) for c in calls]


def test_healthy_runner_installs_once_and_is_never_modified(runner):
    (runner["state"] / "healthy").touch()
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _verbs(runner["calls"]()) == ["update", "install"]
    assert not runner["restored"].exists()
    assert "::warning" not in result.stdout


def test_runner_with_no_ubuntu_archive_is_repaired_for_its_own_codename(runner):
    # The 44368941410 shard-2 runner: update succeeds, Microsoft only.
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning title=Runner apt sources repaired::" in result.stdout
    assert (runner["state"] / "installed").exists()
    assert _verbs(runner["calls"]()) == ["update", "update", "install"]
    sources = runner["restored"].read_text(encoding="utf-8")
    blocks = [b for b in sources.strip().split("\n\n")]
    assert len(blocks) == 2
    assert "URIs: http://archive.ubuntu.com/ubuntu" in blocks[0]
    assert "Suites: resolute resolute-updates resolute-backports" in blocks[0]
    assert "URIs: http://security.ubuntu.com/ubuntu" in blocks[1]
    assert "Suites: resolute-security" in blocks[1]
    for block in blocks:
        assert "Types: deb" in block
        assert "Components: main universe" in block
        assert re.search(r"^Signed-By: \S+ubuntu-archive-keyring\.gpg$", block, re.M)


def test_transient_update_failures_keep_the_bounded_retry(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "update_failures_left").write_text("2", encoding="utf-8")
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("::warning::apt attempt") == 2
    assert not runner["restored"].exists()


def test_a_restore_that_does_not_help_fails_loudly_and_says_re_run(runner):
    (runner["state"] / "restore_useless").touch()
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 1
    assert "::error title=Runner apt sources broken::" in result.stdout
    assert "restoring the standard Ubuntu archive did not make" in result.stdout
    assert "re-run the job" in result.stdout
    assert "Nothing was skipped" in result.stdout
    # One restore, then the bounded attempts: never an unbounded loop.
    assert result.stdout.count("Runner apt sources repaired") == 1
    assert _verbs(runner["calls"]()).count("update") == 5
    assert "install" not in _verbs(runner["calls"]())


def test_unknown_package_on_a_healthy_runner_is_not_blamed_on_the_runner(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "unknown").write_text("no-such-package\n", encoding="utf-8")
    result = runner["run"]("tesseract-ocr", "no-such-package")
    assert result.returncode == 1
    assert "Runner apt sources broken" not in result.stdout
    assert not runner["restored"].exists()
    assert (
        "::error::apt install of tesseract-ocr no-such-package failed after 4 attempts "
        "(no install candidate for: no-such-package)."
    ) in result.stdout


def test_a_runner_that_cannot_name_its_codename_is_not_guessed(runner):
    runner["os_release"].write_text("ID=debian\n", encoding="utf-8")
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 1
    assert "Cannot restore Ubuntu sources" in result.stdout
    assert "::error title=Runner apt sources broken::" in result.stdout
    assert not runner["restored"].exists()


def test_no_packages_is_a_usage_error(runner):
    result = runner["run"]()
    assert result.returncode == 2
    assert "usage" in result.stderr


# ── workflow wiring ──────────────────────────────────────────────────

INSTALL_STEP = "Install tesseract-ocr (screenshot import OCR tests)"
CALLERS = {
    ("pr-validation.yml", "backend"): "bash scripts/ci/install_apt_packages.sh tesseract-ocr",
    ("release-candidate.yml", "hard-gate"): "bash scripts/ci/install_apt_packages.sh tesseract-ocr",
    ("deploy.yml", "hard-gate"): 'bash "${INSTALLER}" tesseract-ocr',
}


@pytest.mark.parametrize(("workflow", "job"), sorted(CALLERS))
def test_every_tesseract_install_goes_through_the_shared_installer(workflow, job):
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    step = next(s for s in doc["jobs"][job]["steps"] if s.get("name") == INSTALL_STEP)
    run = step["run"]
    assert CALLERS[(workflow, job)] in run
    assert "apt-get" not in run, "the inline apt copy must not come back"
    assert "continue-on-error" not in step, "the install is a gate input; it must never be skipped"


def test_deploy_hard_gate_reads_the_installer_from_the_workflow_commit():
    # The hard gate checks out the TARGET tree; a rollback target can predate
    # the script, so the installer must come from the workflow commit.
    doc = yaml.safe_load((WORKFLOWS / "deploy.yml").read_text(encoding="utf-8"))
    job = doc["jobs"]["hard-gate"]
    checkout = next(s for s in job["steps"] if s.get("name") == "Checkout")
    assert checkout["with"]["fetch-depth"] == 0
    step = next(s for s in job["steps"] if s.get("name") == INSTALL_STEP)
    assert 'git show "${GITHUB_SHA}:scripts/ci/install_apt_packages.sh"' in step["run"]


def test_no_workflow_inlines_a_tesseract_apt_install():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "apt-get" in line and "install" in line and "tesseract" in line:
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []
