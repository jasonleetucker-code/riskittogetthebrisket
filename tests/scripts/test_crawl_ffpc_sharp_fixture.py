"""Offline end-to-end demonstration of the public FFPC adapter CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def test_fixture_dry_run_never_needs_network_or_database():
    proc = subprocess.run(
        [
            sys.executable,
            str(_REPO / "scripts" / "crawl_ffpc_sharp.py"),
            "--fixture",
            str(_REPO / "tests" / "platforms" / "ffpc" / "fixtures" / "transactions.html"),
            "--players-fixture",
            str(_REPO / "tests" / "platforms" / "ffpc" / "fixtures" / "players.json"),
            "--source-league",
            "fixture",
            "--dry-run",
        ],
        cwd=_REPO,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "dry_run"
    assert payload["reports"][0]["transactions"] >= 1
    assert payload["reports"][0]["movements"] >= 2
