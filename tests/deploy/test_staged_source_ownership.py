"""Execute the real deploy probe loop without any systemd or deployment action."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_legacy_deploy_probes_owned_timers_but_skips_cutover_workers(tmp_path):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash is unavailable; no shell was installed for this test")
    source = (REPO / "deploy/deploy.sh").read_text(encoding="utf-8")
    begin = source.index('  for timer_template in "${APP_DIR}"/deploy/systemd/*.timer.template; do')
    end = source.index("  shopt -u nullglob", begin)
    loop = source[begin:end]
    templates = tmp_path / "deploy/systemd"
    templates.mkdir(parents=True)
    for stem in ("source-producer", "league-serving", "bdvm-refresh", "future-owned"):
        (templates / f"dynasty-{stem}.timer.template").touch()
    script = (
        'APP_DIR="$PWD"\nSERVICE_NAME=example\nSYSTEMCTL_BIN=systemctl\n'
        'missing_timers=""\ntimer_templates_found=""\nshopt -s nullglob\n'
        'sudo() { printf "PROBE %s\\n" "$*" >> probes.log; return 1; }\n'
        + loop
        + 'printf "MISSING%s\\n" "$missing_timers"\n'
    )
    result = subprocess.run(
        [bash, "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr
    probes = (tmp_path / "probes.log").read_text(encoding="utf-8")
    assert "source-producer" not in result.stdout
    assert "league-serving" not in result.stdout
    assert "source-producer" not in probes
    assert "league-serving" not in probes
    assert "PROBE -n systemctl cat example-bdvm-refresh.timer" in probes
    assert "PROBE -n systemctl cat example-future-owned.timer" in probes
    assert "MISSING example-bdvm-refresh.timer example-future-owned.timer" in result.stdout
