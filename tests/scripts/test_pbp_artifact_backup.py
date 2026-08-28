"""Unit tests for ``scripts/pbp_artifact_backup.py``.

Pins the properties the V1-49 activation/rollback workflow depends on:

1. Backup records ``existedBefore`` per season, not just content.
2. Restore correctly puts back a file that existed, and DELETES a file
   that a rebuild created from nothing (the case a plain "overwrite from
   backup" would miss, since there is nothing to overwrite from).
3. Two backups run back-to-back never collide/clobber each other.
4. A season the backup never covered at all is untouched by restore.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "pbp_artifact_backup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("pbp_artifact_backup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()


def _write_season_file(actuals_dir: Path, season: int, content: str) -> Path:
    actuals_dir.mkdir(parents=True, exist_ok=True)
    path = actuals_dir / _mod.pbp_weekly_filename(season)
    path.write_text(content)
    return path


def test_backup_records_existed_before_per_season(tmp_path):
    actuals_dir = tmp_path / "actuals"
    _write_season_file(actuals_dir, 2024, '{"schemaVersion": "x"}\n')
    # 2025 deliberately not created.
    manifest = _mod.create_backup(actuals_dir, [2024, 2025], tmp_path / "backups")
    assert manifest["seasons"]["2024"]["existedBefore"] is True
    assert manifest["seasons"]["2025"]["existedBefore"] is False


def test_restore_puts_back_a_file_that_existed(tmp_path):
    actuals_dir = tmp_path / "actuals"
    original = '{"schemaVersion": "old"}\n'
    _write_season_file(actuals_dir, 2024, original)
    manifest = _mod.create_backup(actuals_dir, [2024], tmp_path / "backups")

    # Simulate a rebuild overwriting the file with new content.
    (actuals_dir / _mod.pbp_weekly_filename(2024)).write_text('{"schemaVersion": "new"}\n')

    result = _mod.restore_backup(Path(manifest["manifestPath"]))
    assert result["restored"] == [_mod.pbp_weekly_filename(2024)]
    assert result["deleted"] == []
    assert (actuals_dir / _mod.pbp_weekly_filename(2024)).read_text() == original


def test_restore_deletes_a_file_the_rebuild_created_from_nothing(tmp_path):
    actuals_dir = tmp_path / "actuals"
    # 2025 does not exist before the backup.
    _write_season_file(actuals_dir, 2024, "{}\n")
    manifest = _mod.create_backup(actuals_dir, [2024, 2025], tmp_path / "backups")

    # Simulate a rebuild that creates 2025 from nothing.
    (actuals_dir / _mod.pbp_weekly_filename(2025)).write_text('{"schemaVersion": "brand-new"}\n')
    assert (actuals_dir / _mod.pbp_weekly_filename(2025)).exists()

    result = _mod.restore_backup(Path(manifest["manifestPath"]))
    assert _mod.pbp_weekly_filename(2025) in result["deleted"]
    assert not (actuals_dir / _mod.pbp_weekly_filename(2025)).exists()
    # 2024 (which existed before) is untouched by the delete branch.
    assert (actuals_dir / _mod.pbp_weekly_filename(2024)).exists()


def test_restore_deleting_an_already_absent_created_file_is_a_noop(tmp_path):
    actuals_dir = tmp_path / "actuals"
    manifest = _mod.create_backup(actuals_dir, [2025], tmp_path / "backups")
    # 2025 was never created by anything downstream either.
    result = _mod.restore_backup(Path(manifest["manifestPath"]))
    assert result["deleted"] == []


def test_two_backups_in_a_row_do_not_collide(tmp_path, monkeypatch):
    actuals_dir = tmp_path / "actuals"
    _write_season_file(actuals_dir, 2024, "{}\n")
    backup_dir = tmp_path / "backups"

    # Force the same wall-clock second for both calls to exercise the
    # disambiguation path deterministically.
    from datetime import datetime, timezone

    fixed_now = datetime(2026, 8, 28, 1, 0, 0, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(_mod, "datetime", _FixedDatetime)

    manifest_1 = _mod.create_backup(actuals_dir, [2024], backup_dir)
    manifest_2 = _mod.create_backup(actuals_dir, [2024], backup_dir)

    assert manifest_1["manifestPath"] != manifest_2["manifestPath"]
    assert manifest_1["tarPath"] != manifest_2["tarPath"]
    assert Path(manifest_1["manifestPath"]).exists()
    assert Path(manifest_2["manifestPath"]).exists()


def test_manifest_is_valid_json_on_disk(tmp_path):
    actuals_dir = tmp_path / "actuals"
    _write_season_file(actuals_dir, 2024, "{}\n")
    manifest = _mod.create_backup(actuals_dir, [2024], tmp_path / "backups")
    on_disk = json.loads(Path(manifest["manifestPath"]).read_text())
    assert on_disk["seasons"]["2024"]["existedBefore"] is True


def test_restore_missing_manifest_raises(tmp_path):
    try:
        _mod.restore_backup(tmp_path / "nope.manifest.json")
        raise AssertionError("expected PbpBackupError")
    except _mod.PbpBackupError:
        pass


def test_cli_backup_then_restore_round_trip(tmp_path, capsys):
    actuals_dir = tmp_path / "actuals"
    original = '{"schemaVersion": "old"}\n'
    _write_season_file(actuals_dir, 2024, original)

    rc = _mod.main(
        [
            "backup",
            "--actuals-dir",
            str(actuals_dir),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--seasons",
            "2024",
            "2025",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    manifest_path = out["manifestPath"]

    (actuals_dir / _mod.pbp_weekly_filename(2024)).write_text("clobbered")
    (actuals_dir / _mod.pbp_weekly_filename(2025)).write_text("clobbered")

    rc = _mod.main(["restore", "--manifest", manifest_path])
    assert rc == 0
    assert (actuals_dir / _mod.pbp_weekly_filename(2024)).read_text() == original
    assert not (actuals_dir / _mod.pbp_weekly_filename(2025)).exists()
