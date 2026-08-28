#!/usr/bin/env python3
"""Backup and restore the production PBP-weekly artifacts.

Built for the V1-49 controlled-activation workflow
(``.github/workflows/v1-49-host-native-scoring-activation.yml``), which
rebuilds ``data/nfl_data/actuals/pbp_weekly_<season>.jsonl`` (written by
``scripts/build_pbp_weekly.py``) as part of activating
``RISKIT_FEATURE_HOST_NATIVE_SCORING``, and must be able to restore the
prior artifact state deterministically if anything downstream fails.

A backup captures, for each requested season, whether the file existed
BEFORE the rebuild (``existedBefore``) — not just its content. That
distinction is what lets restore correctly UNDO a rebuild that created a
season file from nothing: overwriting-only would leave behind an
artifact the pre-activation production state never had. Existing files
are archived into one timestamped ``.tar.gz``; a manifest JSON records
per-season existence plus the tar location, and is the single input
``restore`` needs.

Backups never collide: the timestamp used in both filenames is checked
against the backup directory and disambiguated if a prior backup from
the same second is already there, so running the workflow twice in a
row without an intervening restore cannot clobber the previous backup.

Subcommands:

* ``backup``  — archive the named seasons' current artifacts (only the
  ones that exist) and write a manifest. Prints the manifest path.
* ``restore`` — replay a manifest: extract files that existed before the
  backup, and delete files the manifest says did not.

Exit codes: 0 success, 2 usage/IO error.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class PbpBackupError(Exception):
    """Raised on invalid input or a corrupt/missing backup; callers exit 2."""


def default_actuals_dir() -> Path:
    return REPO_ROOT / "data" / "nfl_data" / "actuals"


def default_backup_dir(actuals_dir: Path) -> Path:
    return actuals_dir / ".backups"


def pbp_weekly_filename(season: int) -> str:
    return f"pbp_weekly_{int(season)}.jsonl"


def _unique_backup_stamp(backup_dir: Path) -> str:
    base = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamp = base
    suffix = 1
    while (backup_dir / f"pbp_weekly_backup_{stamp}.manifest.json").exists():
        suffix += 1
        stamp = f"{base}-{suffix}"
    return stamp


def create_backup(actuals_dir: Path, seasons: list[int], backup_dir: Path) -> dict:
    """Archive the current artifacts for ``seasons`` and write a manifest.

    Returns the manifest dict (also written to disk). Seasons whose file
    does not currently exist are recorded as ``existedBefore: False`` and
    are NOT an error — that is the expected state for a season no
    previous rebuild has ever covered.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _unique_backup_stamp(backup_dir)
    manifest_path = backup_dir / f"pbp_weekly_backup_{stamp}.manifest.json"
    tar_path = backup_dir / f"pbp_weekly_backup_{stamp}.tar.gz"

    seasons_info: dict[str, dict] = {}
    existing_files: list[Path] = []
    for season in seasons:
        filename = pbp_weekly_filename(season)
        file_path = actuals_dir / filename
        existed = file_path.is_file()
        seasons_info[str(int(season))] = {"filename": filename, "existedBefore": existed}
        if existed:
            existing_files.append(file_path)

    with tarfile.open(tar_path, "w:gz") as tar:
        for file_path in existing_files:
            tar.add(file_path, arcname=file_path.name)

    manifest = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "actualsDir": str(actuals_dir),
        "tarPath": str(tar_path),
        "seasons": seasons_info,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"manifestPath": str(manifest_path), **manifest}


def restore_backup(manifest_path: Path, actuals_dir: Path | None = None) -> dict:
    """Replay ``manifest_path``: restore files that existed before the
    backup, and delete files the manifest says did not exist before it.

    ``actuals_dir`` overrides the manifest-recorded directory (used only
    when restoring against a different checkout than the one that took
    the backup); defaults to the manifest's own recorded path.
    """
    if not manifest_path.is_file():
        raise PbpBackupError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    target_dir = actuals_dir if actuals_dir is not None else Path(manifest["actualsDir"])
    tar_path = Path(manifest["tarPath"])
    seasons_info: dict[str, dict] = manifest["seasons"]

    to_restore = [info["filename"] for info in seasons_info.values() if info["existedBefore"]]
    to_delete = [info["filename"] for info in seasons_info.values() if not info["existedBefore"]]

    restored: list[str] = []
    if to_restore:
        if not tar_path.is_file():
            raise PbpBackupError(f"backup archive missing, cannot restore: {tar_path}")
        target_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path, "r:gz") as tar:
            members = [tar.getmember(name) for name in to_restore]
            extract_kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
            tar.extractall(path=str(target_dir), members=members, **extract_kwargs)
        restored = list(to_restore)

    deleted: list[str] = []
    for filename in to_delete:
        file_path = target_dir / filename
        if file_path.exists():
            file_path.unlink()
            deleted.append(filename)

    return {"restored": restored, "deleted": deleted}


def _cmd_backup(args: argparse.Namespace) -> int:
    actuals_dir = Path(args.actuals_dir)
    backup_dir = Path(args.backup_dir) if args.backup_dir else default_backup_dir(actuals_dir)
    result = create_backup(actuals_dir, args.seasons, backup_dir)
    print(json.dumps(result))
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    actuals_dir = Path(args.actuals_dir) if args.actuals_dir else None
    result = restore_backup(manifest_path, actuals_dir=actuals_dir)
    print(json.dumps(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="archive the current PBP weekly artifacts")
    backup.add_argument("--actuals-dir", default=str(default_actuals_dir()))
    backup.add_argument("--backup-dir", default=None)
    backup.add_argument("--seasons", type=int, nargs="+", required=True)
    backup.set_defaults(func=_cmd_backup)

    restore = sub.add_parser("restore", help="restore from a backup manifest")
    restore.add_argument("--manifest", required=True)
    restore.add_argument("--actuals-dir", default=None)
    restore.set_defaults(func=_cmd_restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PbpBackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
