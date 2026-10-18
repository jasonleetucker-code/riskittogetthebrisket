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

Two TRACKED scraper artifacts are WATCHED, never redirected (2026-10-18):
``data/scrape_state/`` and ``data/sleeper_last_good.json``.  They are
production state the scheduled refresh commits and deploy dispatch keys on
(CLAUDE.md, W31-F001), so a unit test writing them is a defect whatever it
wrote.  Measured under ``pytest -n 6``: a TestClient held open past the
lifespan's 3 s startup-scrape delay ran the real scraper, which rewrote
both.  The scheduler is now off for the suite (``tests/conftest.py``); this
watch makes any future writer fail loudly, serially as much as in parallel.

The real paths are a resource SHARED by every process running the suite
on one checkout (pytest-xdist workers, and the subprocess suite
``tests/test_runtime_data_isolation.py`` runs).  That module plants poison
at the real paths on purpose, so planting and every guard check serialise
on one cross-process lock (``real_paths_lock``) — otherwise another
worker's guard, comparing mid-plant, reported the poison as a write it
never made.

Deliberately NARROW: only those directories move.  ``ROS_DATA_DIR`` as a
whole is not redirected, because ``data/ros/aggregate/latest.json`` — read
through the same ``team_strength.ROS_DATA_DIR`` — is TRACKED, and hiding a
tracked input is a different change from hiding an ignored one.  Tests that
already point ``team_strength.ROS_DATA_DIR`` at a temp dir keep working
unchanged: only a path that resolves under the REAL team-strength directory is
remapped.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Iterable, Iterator

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

#: Tracked production artifacts the scraper writes.  Watched, not
#: redirected: no unit test may write them at all.
TRACKED_SCRAPER_ARTIFACTS: tuple[Path, ...] = (
    REPO_ROOT / "data" / "scrape_state",
    REPO_ROOT / "data" / "sleeper_last_good.json",
)

#: Everything the per-test guard fingerprints (directories and files).
GUARDED_PATHS: tuple[Path, ...] = GUARDED_DIRS + TRACKED_SCRAPER_ARTIFACTS

_IGNORED_NAMES = frozenset({".gitkeep"})

#: Set in the environment of a subprocess started INSIDE ``real_paths_lock``
#: (the planting test's inner suite): the parent already holds the lock, so
#: the child must not wait for it.
LOCK_HELD_ENV = "RISKIT_REAL_RUNTIME_LOCK_HELD"
_LOCK_PATH = Path(tempfile.gettempdir()) / (
    "riskit-real-runtime-data-"
    + hashlib.sha256(str(REPO_ROOT).encode("utf-8")).hexdigest()[:16]
    + ".lock"
)
#: Long enough to outlast the planting test's inner suite; a timeout is a
#: loud failure, never a silent skip of the guard.
LOCK_TIMEOUT_S = 900.0

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


@contextlib.contextmanager
def real_paths_lock(timeout: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """Cross-process exclusive lock over the real guarded paths (flock / msvcrt).

    Held while poison is planted at the real paths and while a guard
    fingerprints them, so one never observes the other half-done.  A no-op
    in a subprocess whose parent holds it (``LOCK_HELD_ENV``).
    """
    if os.environ.get(LOCK_HELD_ENV) == "1":
        yield
        return
    fd = os.open(_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "posix":
                    import fcntl  # noqa: PLC0415

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt  # noqa: PLC0415

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"could not take the real-runtime-data lock {_LOCK_PATH} "
                        f"within {timeout:.0f}s"
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "posix":
                import fcntl  # noqa: PLC0415

                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                import msvcrt  # noqa: PLC0415

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def fingerprint(dirs: Iterable[Path] = GUARDED_PATHS) -> dict[str, tuple[int, int]]:
    """``{path: (size, mtime_ns)}`` for every file under ``dirs``.

    An entry that is itself a FILE is fingerprinted directly.
    """
    out: dict[str, tuple[int, int]] = {}
    for base in dirs:
        if base.is_file():
            candidates = [base]
        elif base.is_dir():
            candidates = sorted(base.rglob("*"))
        else:
            continue
        for path in candidates:
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
