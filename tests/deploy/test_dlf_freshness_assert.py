"""'Assert DLF freshness' names the boards and points at the box (CI-3c).

DLF is NOT fetched by ``scheduled-refresh.yml``: Cloudflare refuses GitHub's
IP range, so the production box's ``dynasty-dlf-fetch.timer`` fetches it with
the box's own ``.env`` credentials and pushes the stamps.  The assertion's
message still said "check the [DLF] log lines in 'Run scraper' and verify
DLF_USERNAME/DLF_PASSWORD repo secrets" -- two places the cause cannot be --
and it read only the aggregate stamp, which is written when ALL four rank
boards refresh, so one refusing board read as "DLF is down" while three were
fresh.

The ASSERTION is unchanged and pinned here: the aggregate stamp, 24 h, missing
or unparseable fails.  Only the message and the stale-board hand-off to the
failure alert are new.  The step's real shell runs against fixture stamps in a
scratch directory -- never the repository's live ``data/``.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-refresh.yml"
BOARDS = ("dlfSf", "dlfIdp", "dlfRookieSf", "dlfRookieIdp")


def _script() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in doc["jobs"]["refresh"]["steps"]:
        if step.get("name") == "Assert DLF freshness":
            assert step.get("if") == "always()"
            return step["run"]
    raise AssertionError("the DLF assertion step is gone")


def _run(tmp_path: Path, ages_hours: dict[str, float | None | str]):
    """``None`` = stamp missing; a string = literal stamp content."""
    state = tmp_path / "data" / "scrape_state"
    state.mkdir(parents=True)
    runner_temp = tmp_path / "rt"
    runner_temp.mkdir()
    now = int(time.time())
    for key, age in ages_hours.items():
        if age is None:
            continue
        content = age if isinstance(age, str) else str(now - int(age * 3600))
        (state / f"{key}_last_success").write_text(content + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c", _script()],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "RUNNER_TEMP": str(runner_temp)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    stale_file = runner_temp / "dlf_stale_boards.txt"
    stale = stale_file.read_text(encoding="utf-8").strip() if stale_file.exists() else None
    return proc, stale


def test_the_assertion_itself_is_unchanged():
    script = _script()
    assert "THRESHOLD_HOURS=24" in script
    assert 'STAMP="data/scrape_state/dlf_last_success"' in script
    assert "(( AGE_HOURS > THRESHOLD_HOURS ))" in script


def test_all_fresh_passes(tmp_path):
    proc, stale = _run(tmp_path, {"dlf": 2, **{b: 2 for b in BOARDS}})
    assert proc.returncode == 0, proc.stdout
    assert "ok: last successful DLF fetch was 2h ago" in proc.stdout
    assert stale == ""


def test_exactly_at_the_threshold_still_passes_and_one_hour_past_fails(tmp_path):
    ok, _ = _run(tmp_path / "a", {"dlf": 24.2, **{b: 1 for b in BOARDS}})
    assert ok.returncode == 0
    bad, _ = _run(tmp_path / "b", {"dlf": 25.2, **{b: 25.2 for b in BOARDS}})
    assert bad.returncode == 1


def test_a_stale_aggregate_names_every_board_and_points_at_the_box(tmp_path):
    ages = {"dlf": 70, "dlfSf": 1, "dlfIdp": 1, "dlfRookieSf": 70, "dlfRookieIdp": 70}
    proc, stale = _run(tmp_path, ages)
    assert proc.returncode == 1
    out = proc.stdout
    assert "::error title=DLF freshness::" in out
    for key, age in (("dlfSf", 1), ("dlfIdp", 1), ("dlfRookieSf", 70), ("dlfRookieIdp", 70)):
        assert f"data/scrape_state/{key}_last_success={age}h" in out
    assert "Stale board(s): dlfRookieSf dlfRookieIdp" in out
    assert "journalctl -u dynasty-dlf-fetch.service" in out
    assert "dlf-diagnostics.yml" in out
    assert "box .env" in out
    # The two places the cause cannot be.
    assert "repo secrets" not in out
    assert "'Run scraper'" not in out
    assert stale == "dlfRookieSf dlfRookieIdp"


def test_a_missing_aggregate_fails_and_still_names_the_boards(tmp_path):
    proc, stale = _run(tmp_path, {"dlf": None, "dlfSf": 3, "dlfIdp": None})
    assert proc.returncode == 1
    assert "dlf_last_success missing" in proc.stdout
    assert "data/scrape_state/dlfIdp_last_success=missing" in proc.stdout
    assert "data/scrape_state/dlfRookieSf_last_success=missing" in proc.stdout
    assert stale == "dlfIdp dlfRookieSf dlfRookieIdp"


def test_a_corrupt_aggregate_fails(tmp_path):
    proc, _ = _run(tmp_path, {"dlf": "not-a-number", **{b: 1 for b in BOARDS}})
    assert proc.returncode == 1
    assert "no parseable epoch" in proc.stdout


@pytest.mark.parametrize("bad", ["", "garbage"])
def test_an_unparseable_board_stamp_is_named_not_treated_as_fresh(tmp_path, bad):
    ages = {"dlf": 70, "dlfSf": bad, "dlfIdp": 1, "dlfRookieSf": 1, "dlfRookieIdp": 1}
    proc, stale = _run(tmp_path, ages)
    assert proc.returncode == 1
    assert "data/scrape_state/dlfSf_last_success=unparseable" in proc.stdout
    assert stale == "dlfSf"
