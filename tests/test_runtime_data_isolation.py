"""Proof that gitignored runtime files cannot change deterministic test results.

The isolation itself lives in ``tests/runtime_data_isolation.py`` and is
installed by ``tests/conftest.py``.  This module proves it three ways:

1. **Reproduction, inverted.**  Plant realistic, FRESH runtime files at the
   REAL paths, re-run in a subprocess the seven tests that failed when such
   files were present (PR #1402 validation), plus the route tests that used to
   WRITE ``data/public_league/``.  All must pass, and the planted files must be
   byte-identical afterwards.
2. **Discrimination.**  The same poison, handed to the engine through a path
   the isolation deliberately leaves alone, DOES flip the refusal path — so
   (1) passing means the isolation held, not that the poison was inert.
3. **The guard can see a write.**  ``fingerprint`` / ``describe_changes`` are
   exercised directly, because a guard that cannot fail proves nothing.

Planting touches the real directories, so every original file is moved aside
with ``os.replace`` (which keeps its mtime) and moved back in ``finally``; the
conftest guard then sees exactly the fingerprint it started with.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.public_league import snapshot_store
from src.ros import playoff_sim, power_v2, team_strength
from tests import runtime_data_isolation as isolation
from tests.public_league.fixtures import build_test_snapshot

#: The tests that failed with a fresh ``team_strength/latest.json`` present.
AFFECTED_NODE_IDS = (
    "tests/public_league/test_overview.py::OverviewTests::"
    "test_current_power_leader_withholds_the_whole_card_when_unrankable",
    "tests/ros/test_power_v2_season_scoping.py::TestUnmeasuredAllPlayStaysUnknown::"
    "test_the_refusal_path_serialises_the_unknown_share_as_null",
    "tests/ros/test_power_v2_season_scoping.py::TestUnrankableUnaffected::"
    "test_preseason_forward_looking_still_refuses_rather_than_zero",
    "tests/ros/test_playoff_sim.py::TestRosStrengthLoader::test_returns_empty_when_no_snapshot",
    "tests/ros/test_power_v2_headline_fields.py::"
    "test_record_is_present_even_when_the_engine_refuses_to_rank",
    "tests/ros/test_power_v2_raw_magnitudes.py::"
    "test_raw_fields_are_present_even_when_the_engine_refuses_to_rank",
    "tests/ros/test_power_v2_raw_magnitudes.py::test_games_used_accompanies_every_raw_magnitude",
)

#: Cold-rebuilds the public snapshot from Sleeper stubs and persists it —
#: the suite's own writer of ``data/public_league/``.
PUBLIC_LEAGUE_WRITER = "tests/public_league/test_server_routes.py"


def _poison_files() -> dict[Path, bytes]:
    """Realistic runtime files: what a local server run leaves behind."""
    snapshot = build_test_snapshot()
    owners = sorted(snapshot.managers.by_owner_id)
    strength_rows = [
        {"ownerId": oid, "teamName": oid, "teamRosStrength": 90.0 - 5 * i}
        for i, oid in enumerate(owners)
    ]
    snap_dict = snapshot_store.snapshot_to_dict(snapshot, include_nfl_players=False)

    def enc(payload: object) -> bytes:
        return json.dumps(payload).encode("utf-8")

    public = isolation.REAL_PUBLIC_LEAGUE_DIR
    return {
        isolation.REAL_TEAM_STRENGTH_DIR / "latest.json": enc(strength_rows),
        public / "snapshot.json": enc(snap_dict),
        public / "identity.json": enc(snap_dict["managers"]),
        public / "contract.json": enc({"poisonedByTest": True, "sections": {}}),
        public / "nfl_players.json": enc(snapshot.nfl_players or {}),
    }


@contextlib.contextmanager
def _planted_at_real_paths(files: dict[Path, bytes]):
    backups: dict[Path, Path] = {}
    try:
        for path, payload in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                backup = path.with_name(f"{path.name}.riskit-test-backup-{os.getpid()}")
                os.replace(path, backup)
                backups[path] = backup
            path.write_bytes(payload)
        yield
    finally:
        for path in files:
            path.unlink(missing_ok=True)
            if path in backups:
                os.replace(backups[path], path)


def test_affected_tests_pass_with_runtime_files_present():
    files = _poison_files()
    with _planted_at_real_paths(files):
        proc = subprocess.run(  # noqa: S603 — fixed argv, this interpreter
            [
                sys.executable,
                "-m",
                "pytest",
                *AFFECTED_NODE_IDS,
                PUBLIC_LEAGUE_WRITER,
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=isolation.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        after = {path: path.read_bytes() for path in files}

    assert proc.returncode == 0, (
        "with fresh runtime files at the real paths, tests that must be "
        "hermetic failed:\n" + proc.stdout[-4000:] + proc.stderr[-2000:]
    )
    assert after == files, "the suite rewrote a runtime file at a real path"


def test_the_poison_would_flip_the_refusal_path_without_isolation():
    """Discrimination control for the test above.

    ``build_test_snapshot()`` is preseason and genuinely unrankable, so the
    engine refuses.  Hand it the planted team-strength rows through a
    ``ROS_DATA_DIR`` the isolation leaves alone (it remaps only the REAL
    directory) and it must rank instead — which is exactly the failure the
    real file used to cause.
    """
    snapshot = build_test_snapshot()
    refused = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)
    assert refused["unrankable"] is not None

    poison = _poison_files()[isolation.REAL_TEAM_STRENGTH_DIR / "latest.json"]
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "team_strength").mkdir()
        (Path(tmp) / "team_strength" / "latest.json").write_bytes(poison)
        with patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)):
            flipped = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)
            ros_map = playoff_sim._load_ros_strength_map()

    assert flipped["unrankable"] is None, "the poison must be able to flip the result"
    assert ros_map, "the poison must be able to feed the playoff simulator"


def test_loaders_do_not_see_files_at_the_real_paths():
    with _planted_at_real_paths(_poison_files()):
        assert team_strength.load_team_strength_snapshot() is None
        assert playoff_sim._load_ros_strength_map() == {}
        assert snapshot_store.load_snapshot() is None
        assert snapshot_store.load_contract() is None


def test_isolation_moves_only_the_real_team_strength_directory():
    """Tracked ROS inputs stay visible; a test's own redirect is honoured."""
    remapped = team_strength._team_strength_path()
    assert not remapped.is_relative_to(isolation.REAL_TEAM_STRENGTH_DIR)
    assert remapped.name == "latest.json"
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)):
            assert (
                team_strength._team_strength_path() == Path(tmp) / "team_strength" / "latest.json"
            )
    assert not snapshot_store.SNAPSHOT_PATH.is_relative_to(isolation.REAL_PUBLIC_LEAGUE_DIR)


def test_the_guard_detects_added_modified_and_removed_files():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / ".gitkeep").write_text("")
        (base / "kept.json").write_text("{}")
        (base / "gone.json").write_text("{}")
        before = isolation.fingerprint([base])
        assert set(before) == {str(base / "kept.json"), str(base / "gone.json")}

        (base / "gone.json").unlink()
        (base / "new.json").write_text("{}")
        os.utime(base / "kept.json", ns=(1, 1))
        after = isolation.fingerprint([base])

    assert isolation.describe_changes(before, after) == [
        f"removed  {base / 'gone.json'}",
        f"modified {base / 'kept.json'}",
        f"added    {base / 'new.json'}",
    ]
    assert isolation.describe_changes(after, after) == []
