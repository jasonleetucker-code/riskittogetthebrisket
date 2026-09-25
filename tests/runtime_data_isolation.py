"""Keep gitignored runtime files out of deterministic test results.

Owner decision (2026-09-23): an ignored runtime file must not be able to
change the result of a deterministic unit test.  Two directories broke that
rule, both measured while validating PR #1402:

* ``data/ros/team_strength/`` — ``team_strength.load_or_compute_team_strength``
  serves ``latest.json`` whenever its mtime is under six hours old.  Any rows
  at all make Power's ROS component available, so every "the engine must
  refuse to rank" test flipped to FAIL on a machine that had run the server
  or a scrape recently (7 of 7 reproduced).  The same loader persists what it
  computes, so a test that leaks a real league registry could write the file.
* ``data/public_league/`` — ``server._rebuild_public_snapshot`` persists
  ``snapshot/contract/identity/nfl_players.json`` on every rebuild, and four
  route-test classes cold-rebuild from Sleeper stubs, so every suite run wrote
  fixture league ``L2025`` into the real directory.  ``server`` also loads that
  snapshot at IMPORT time, which is during collection.

This module is the single owner of the redirect.  ``tests/conftest.py``
installs it before any test module is imported and re-points it at a fresh,
empty root before every test; ``tests/test_runtime_data_isolation.py`` proves
it by planting real files and re-running the affected tests.

A third was added with Game Day U5 (2026-09-25):

* ``data/game_day/live/`` — ``src/ros/game_day_live.py``'s observation logs
  and versioned generations.  ``build_matchup_intel`` SERVES a generation
  from there before computing anything, so a real collector generation for
  the same league-week would otherwise replace a test's fixtures with the
  box's (or a developer's) live answer.

Deliberately NARROW: only those directories move.  ``ROS_DATA_DIR`` as a
whole is not redirected, because ``data/ros/aggregate/latest.json`` — read
through the same ``team_strength.ROS_DATA_DIR`` — is TRACKED, and hiding a
tracked input is a different change from hiding an ignored one.  Tests that
already point ``team_strength.ROS_DATA_DIR`` at a temp dir keep working
unchanged: only a path that resolves under the REAL team-strength directory is
remapped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from src.public_league import snapshot_store
from src.ros import game_day_live, team_strength

REPO_ROOT = Path(__file__).resolve().parents[1]

# Captured at import, before anything is redirected.
REAL_PUBLIC_LEAGUE_DIR: Path = snapshot_store.DATA_DIR
REAL_TEAM_STRENGTH_DIR: Path = team_strength.ROS_DATA_DIR / "team_strength"
REAL_GAME_DAY_LIVE_DIR: Path = game_day_live.LIVE_ROOT

#: The directories the guard watches.  ``conduct_registry.json`` (tracked)
#: lives in the first one and is watched too — no test has any business
#: writing it either.
GUARDED_DIRS: tuple[Path, ...] = (
    REAL_PUBLIC_LEAGUE_DIR,
    REAL_TEAM_STRENGTH_DIR,
    REAL_GAME_DAY_LIVE_DIR,
)

_IGNORED_NAMES = frozenset({".gitkeep"})

_ORIGINAL_TEAM_STRENGTH_PATH = team_strength._team_strength_path
_state: dict[str, Path | None] = {"root": None}


def _isolated_team_strength_path(league_key: str | None = None) -> Path:
    path = _ORIGINAL_TEAM_STRENGTH_PATH(league_key)
    root = _state["root"]
    if root is None:
        return path
    try:
        relative = path.relative_to(REAL_TEAM_STRENGTH_DIR)
    except ValueError:
        # The test pointed ``ROS_DATA_DIR`` somewhere itself — honour it.
        return path
    return root / "ros" / "team_strength" / relative


def install() -> None:
    """Route team-strength snapshot paths through the remapper (idempotent)."""
    team_strength._team_strength_path = _isolated_team_strength_path


def activate(root: Path) -> None:
    """Point every guarded runtime directory at ``root``.

    Computes paths only and creates nothing: every writer already creates
    its own parent directory, and a directory that does not exist is the
    honest "no runtime file here" state.
    """
    # A Game Day background compute (Game Day G) still running from the
    # previous test would write into THIS test's root once it is switched,
    # and a failed attempt would make this test's first request read
    # "failed": join it BEFORE re-pointing anything, then forget it.
    game_day_live.wait_for_background(timeout=120.0)
    game_day_live.reset_background_state()
    _state["root"] = root
    public_dir = root / "public_league"
    snapshot_store.DATA_DIR = public_dir
    snapshot_store.SNAPSHOT_PATH = public_dir / "snapshot.json"
    snapshot_store.CONTRACT_PATH = public_dir / "contract.json"
    snapshot_store.IDENTITY_PATH = public_dir / "identity.json"
    snapshot_store.NFL_PLAYERS_PATH = public_dir / "nfl_players.json"
    game_day_live.LIVE_ROOT = root / "game_day" / "live"


def fingerprint(dirs: Iterable[Path] = GUARDED_DIRS) -> dict[str, tuple[int, int]]:
    """``{path: (size, mtime_ns)}`` for every file under ``dirs``."""
    out: dict[str, tuple[int, int]] = {}
    for base in dirs:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.name in _IGNORED_NAMES or not path.is_file():
                continue
            try:
                st = path.stat()
            except OSError:
                continue  # removed between listing and stat — shows as removed
            try:
                key = str(path.relative_to(REPO_ROOT))
            except ValueError:
                key = str(path)
            out[key] = (st.st_size, st.st_mtime_ns)
    return out


def describe_changes(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    changes: list[str] = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            changes.append(f"added    {key}")
        elif key not in after:
            changes.append(f"removed  {key}")
        elif before[key] != after[key]:
            changes.append(f"modified {key}")
    return changes
