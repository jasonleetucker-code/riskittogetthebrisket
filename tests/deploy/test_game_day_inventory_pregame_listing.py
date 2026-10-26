"""AL-P8: the read-only Game Day inventory lists the pregame projection archives.

The first ``pregame_projections.json.gz`` is written only when an NFL week's raw
``observations/`` are about to be pruned (``src/ros/game_day_live.py``
``ensure_pregame_archive``), so the inventory must be able to SHOW it -- or show
that none exists yet -- before Week 1's raw logs prune (~2026-10-13).

The section is executed out of the shipped script (not re-implemented) against a
fake ``data/game_day/live`` tree.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "diagnostics" / "game_day_live_inventory.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")

_START = 'section "pregame projection archive (AL-P8)"'


def _section() -> str:
    body = SCRIPT.read_text(encoding="utf-8")
    start = body.index(_START)
    end = body.index('\nsection "', start + len(_START))
    return body[start:end]


def _run(live: Path) -> str:
    harness = (
        "set -Euo pipefail\n"
        "section() { printf '\\n### %s\\n' \"$*\"; }\n"
        f"LIVE='{live.as_posix()}'\n" + _section()
    )
    proc = subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_section_exists_and_globs_the_canonical_archive_name():
    from src.ros.game_day_live import PREGAME_ARCHIVE_FAILURE_NAME, PREGAME_ARCHIVE_NAME

    section = _section()
    assert '"${LIVE}"/_nfl/*/week_*/pregame_projections*' in section
    # The glob covers both the archive and its failure record.
    assert PREGAME_ARCHIVE_NAME.startswith("pregame_projections")
    assert PREGAME_ARCHIVE_FAILURE_NAME.startswith("pregame_projections")


def test_no_archive_yet_is_reported_not_an_error(tmp_path):
    live = tmp_path / "live"
    (live / "_nfl" / "2026" / "week_3" / "observations").mkdir(parents=True)
    (live / "_nfl" / "2026" / "week_3" / "observations" / "a.jsonl").write_text("{}\n")
    out = _run(live)
    assert "pregame_projections*: NONE" in out
    assert "weeks still holding raw observations/: 1" in out
    assert "_nfl/2026/week_3/observations (1 files)" in out


def test_archives_are_listed_per_week(tmp_path):
    live = tmp_path / "live"
    w3 = live / "_nfl" / "2026" / "week_3"
    w4 = live / "_nfl" / "2026" / "week_4"
    w3.mkdir(parents=True)
    w4.mkdir(parents=True)
    (w3 / "pregame_projections.json.gz").write_bytes(b"\x1f\x8b" + b"x" * 10)
    (w4 / "pregame_projections.retained.json").write_text("{}")
    out = _run(live)
    assert "NONE" not in out
    assert "week_3/pregame_projections.json.gz" in out
    assert "week_4/pregame_projections.retained.json" in out
    assert "weeks still holding raw observations/: 0" in out


def test_inventory_stays_read_only():
    code = "\n".join(line for line in _section().splitlines() if not line.lstrip().startswith("#"))
    for verb in ("rm ", "mv ", "touch ", " > ", ">>", "tee ", "mkdir", "systemctl start"):
        assert verb not in code, verb
