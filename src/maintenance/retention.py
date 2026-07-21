"""Disk-retention pruner for the generated ``data/`` and ``exports/`` trees.

The scraper writes a fresh raw snapshot for every source every ~2h
(~12 runs/day).  None of those per-run archives are read after the
newest one is consumed, yet they accumulated unbounded — ~2 GB on the
production box, on track to fill the disk and fail scrape writes,
session SQLite, and new logins.

This module prunes ONLY explicitly allow-listed, regenerable archive
locations and hard-refuses to touch anything that is load-bearing or
serves live traffic.  It is called best-effort at the end of a
successful scrape (see ``server.py``).

Retention policy (intentionally generous — these are safety margins,
not tight budgets):

* ``data/canonical/``                  — purge entirely.  The offline
  canonical-build pipeline was retired; nothing writes or reads this
  directory anymore (orphaned snapshots).
* ``data/exports/archive/*.zip`` and
  ``exports/archive/*.zip``            — keep the last 14 days.
* ``data/raw_sources/raw_source_snapshot_*.json``
                                       — keep the newest 30.
* ``data/raw/<source>/<year>/*``       — keep the newest 30 per leaf.
* ``data/dynasty_data_*.json``         — keep the last 45 days (the
  source-history fallback in ``server.py`` mines these when the
  dedicated history log is missing/empty; 45d is well past any window
  the UI reads).

NEVER touched (hard-guarded, not merely un-globbed):
``exports/latest/``, ``data/rank_history.jsonl``, ``data/identity/``,
``data/ros/``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Retention knobs.  Kept as module constants (not env-driven) so the
# behaviour is identical in tests, CI, and prod — there is no reason to
# tune these per-environment and an env override would just be another
# way to accidentally nuke history.
EXPORTS_ARCHIVE_MAX_AGE_DAYS = 14
DYNASTY_DATA_MAX_AGE_DAYS = 45
RAW_SOURCES_KEEP = 30
RAW_PER_SOURCE_KEEP = 30

_DAY_SECONDS = 86_400


@dataclass
class CategoryResult:
    name: str
    deleted: int = 0
    kept: int = 0
    bytes_freed: int = 0
    errors: int = 0


@dataclass
class RetentionReport:
    dry_run: bool = False
    categories: list[CategoryResult] = field(default_factory=list)

    def _cat(self, name: str) -> CategoryResult:
        for c in self.categories:
            if c.name == name:
                return c
        c = CategoryResult(name=name)
        self.categories.append(c)
        return c

    @property
    def total_deleted(self) -> int:
        return sum(c.deleted for c in self.categories)

    @property
    def total_bytes_freed(self) -> int:
        return sum(c.bytes_freed for c in self.categories)

    @property
    def total_errors(self) -> int:
        return sum(c.errors for c in self.categories)

    def summary(self) -> str:
        mb = self.total_bytes_freed / (1024 * 1024)
        prefix = "[dry-run] " if self.dry_run else ""
        parts = [
            f"{c.name}: -{c.deleted} ({c.bytes_freed / (1024 * 1024):.1f}MB)"
            for c in self.categories
            if c.deleted or c.errors
        ]
        detail = ", ".join(parts) if parts else "nothing to prune"
        errs = f", {self.total_errors} errors" if self.total_errors else ""
        return f"{prefix}reclaimed {mb:.1f}MB across {self.total_deleted} entries{errs} — {detail}"


def _protected_paths(base_dir: Path) -> list[Path]:
    base = base_dir.resolve()
    return [
        (base / "exports" / "latest").resolve(),
        (base / "data" / "identity").resolve(),
        (base / "data" / "ros").resolve(),
        (base / "data" / "rank_history.jsonl").resolve(),
    ]


def _is_protected(target: Path, protected: list[Path]) -> bool:
    t = target.resolve()
    for p in protected:
        if t == p:
            return True
        try:
            t.relative_to(p)
            return True
        except ValueError:
            pass
    return False


def _entry_size(path: Path) -> int:
    try:
        if path.is_dir() and not path.is_symlink():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return path.stat().st_size
    except OSError:
        return 0


def _delete(
    target: Path,
    allowed_root: Path,
    protected: list[Path],
    cat: CategoryResult,
    *,
    dry_run: bool,
) -> None:
    """Delete one entry with containment + protected-path guards.

    Containment: the resolved target MUST live inside ``allowed_root``.
    Protected: the resolved target MUST NOT be (or be inside) any
    load-bearing path.  Either guard failing is a bug in a caller's
    glob — we skip and count an error rather than risk live data.
    """
    try:
        resolved = target.resolve()
        root = allowed_root.resolve()
        resolved.relative_to(root)  # raises ValueError if escaped
        if _is_protected(resolved, protected) or _is_protected(root, protected):
            cat.errors += 1
            return
        size = _entry_size(target)
        if dry_run:
            cat.deleted += 1
            cat.bytes_freed += size
            return
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        cat.deleted += 1
        cat.bytes_freed += size
    except (OSError, ValueError):
        cat.errors += 1


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _purge_dir_contents(
    directory: Path, protected: list[Path], cat: CategoryResult, *, dry_run: bool
) -> None:
    if not directory.is_dir():
        return
    for child in sorted(directory.iterdir()):
        if child.name == ".gitkeep":
            cat.kept += 1
            continue
        _delete(child, directory, protected, cat, dry_run=dry_run)


def _prune_by_age(
    directory: Path,
    pattern: str,
    max_age_days: int,
    protected: list[Path],
    cat: CategoryResult,
    *,
    now: float,
    dry_run: bool,
) -> None:
    if not directory.is_dir():
        return
    cutoff = now - max_age_days * _DAY_SECONDS
    for entry in sorted(directory.glob(pattern)):
        if _mtime(entry) < cutoff:
            _delete(entry, directory, protected, cat, dry_run=dry_run)
        else:
            cat.kept += 1


def _prune_keep_newest(
    directory: Path,
    pattern: str,
    keep: int,
    protected: list[Path],
    cat: CategoryResult,
    *,
    dry_run: bool,
) -> None:
    if not directory.is_dir():
        return
    entries = sorted(directory.glob(pattern), key=_mtime, reverse=True)
    for entry in entries[:keep]:
        cat.kept += 1
    for entry in entries[keep:]:
        _delete(entry, directory, protected, cat, dry_run=dry_run)


def prune_data_dir(
    base_dir: Path,
    *,
    now: float | None = None,
    dry_run: bool = False,
) -> RetentionReport:
    """Prune regenerable archives under ``base_dir`` per the module policy.

    Pure with respect to ``now`` (injectable for tests).  Never raises
    for individual entries — failures are counted in the report so a
    flaky unlink can never abort a scrape.
    """
    base_dir = Path(base_dir)
    now = time.time() if now is None else now
    data_dir = base_dir / "data"
    protected = _protected_paths(base_dir)
    report = RetentionReport(dry_run=dry_run)

    # 1. Orphaned retired-pipeline snapshots — purge entirely.
    _purge_dir_contents(
        data_dir / "canonical", protected, report._cat("canonical"), dry_run=dry_run
    )

    # 2. Export archive zips — keep 14 days (both known archive roots).
    arch = report._cat("exports_archive")
    for archive_dir in (data_dir / "exports" / "archive", base_dir / "exports" / "archive"):
        _prune_by_age(
            archive_dir,
            "dynasty_export_*.zip",
            EXPORTS_ARCHIVE_MAX_AGE_DAYS,
            protected,
            arch,
            now=now,
            dry_run=dry_run,
        )

    # 3. Raw source aggregate snapshots — only the newest is ever read.
    _prune_keep_newest(
        data_dir / "raw_sources",
        "raw_source_snapshot_*.json",
        RAW_SOURCES_KEEP,
        protected,
        report._cat("raw_sources"),
        dry_run=dry_run,
    )

    # 4. Per-source raw archives: data/raw/<source>/<year>/<entry>.
    raw_root = data_dir / "raw"
    raw_cat = report._cat("raw_per_source")
    if raw_root.is_dir():
        for source_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()):
            for year_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
                _prune_keep_newest(
                    year_dir,
                    "*",
                    RAW_PER_SOURCE_KEEP,
                    protected,
                    raw_cat,
                    dry_run=dry_run,
                )

    # 5. Daily contract snapshots — keep 45 days (source-history fallback).
    _prune_by_age(
        data_dir,
        "dynasty_data_*.json",
        DYNASTY_DATA_MAX_AGE_DAYS,
        protected,
        report._cat("dynasty_data"),
        now=now,
        dry_run=dry_run,
    )

    return report


# ──────────────────────────────────────────────────────────────────────
# CLI entrypoint
#
# ``server.py`` calls ``prune_data_dir`` best-effort at scrape-end so the
# prod box's local disk stays bounded.  The GitHub Actions
# ``scheduled-refresh.yml`` job, however, scrapes and ``git add -f``s the
# raw trees directly WITHOUT booting the server, so those working-tree
# deletions never reached a commit and the tracked snapshots grew
# unbounded.  This entrypoint lets the workflow run the identical policy
# right before its commit step so the pruned state is what gets recorded.
# ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.maintenance.retention",
        description=(
            "Prune regenerable data/ and exports/ archives per the module "
            "retention policy (keep newest N raw snapshots, age out zips, "
            "etc.).  Never touches load-bearing paths."
        ),
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=_REPO_ROOT,
        help="Repository root containing data/ and exports/ (default: repo root).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be pruned without deleting anything.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any per-entry deletion error was counted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    report = prune_data_dir(args.base_dir, dry_run=args.dry_run)
    print(f"retention: {report.summary()}")
    if args.strict and report.total_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
