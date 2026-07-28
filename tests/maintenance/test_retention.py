"""Tests for the disk-retention pruner.

Safety-critical: this code deletes files on the production box.  The
suite pins both the retention math AND the hard guarantee that
load-bearing paths are never touched even when they superficially
match a glob.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.maintenance import retention
from src.maintenance.retention import prune_data_dir

NOW = 1_750_000_000.0  # fixed reference instant for deterministic ages


def _touch(path: Path, *, age_days: float = 0.0, size: int = 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    ts = NOW - age_days * 86_400
    os.utime(path, (ts, ts))
    return path


def _build_tree(base: Path) -> None:
    data = base / "data"
    # canonical — orphaned, must be fully purged (keep .gitkeep)
    _touch(data / "canonical" / "canonical_snapshot_old.json", age_days=1)
    _touch(data / "canonical" / "nested" / "blob.json", age_days=1)
    (data / "canonical" / ".gitkeep").parent.mkdir(parents=True, exist_ok=True)
    (data / "canonical" / ".gitkeep").write_text("")
    # exports archive (both roots) — every zip for 14d, then one per
    # day out to a year, nothing beyond.
    _touch(data / "exports" / "archive" / "dynasty_export_old.zip", age_days=30)
    _touch(data / "exports" / "archive" / "dynasty_export_new.zip", age_days=2)
    _touch(data / "exports" / "archive" / "dynasty_export_expired.zip", age_days=400)
    _touch(base / "exports" / "archive" / "dynasty_export_ancient.zip", age_days=99)
    _touch(base / "exports" / "archive" / "dynasty_export_fresh.zip", age_days=1)
    _touch(base / "exports" / "archive" / "dynasty_export_prehistoric.zip", age_days=999)
    # raw_sources — keep newest 30
    for i in range(40):
        _touch(
            data / "raw_sources" / f"raw_source_snapshot_{i:03d}.json",
            age_days=40 - i,
        )
    # raw/<source>/<year> — keep newest 30 per leaf, sources independent
    for src in ("ktc", "fantasycalc"):
        for i in range(35):
            _touch(
                data / "raw" / src / "2026" / f"{src}_2026_{i:03d}",
                age_days=35 - i,
            )
    # dynasty_data — 45d age cutoff
    _touch(data / "dynasty_data_2026-01-01.json", age_days=120)
    _touch(data / "dynasty_data_2026-05-10.json", age_days=3)
    # protected — must survive untouched
    _touch(base / "exports" / "latest" / "dynasty_data.js", age_days=999)
    _touch(base / "exports" / "latest" / "dynasty_export_latest.zip", age_days=999)
    _touch(data / "rank_history.jsonl", age_days=999)
    _touch(data / "identity" / "player_map.json", age_days=999)
    _touch(data / "ros" / "aggregate" / "history" / "old.json", age_days=999)


def test_canonical_fully_purged_but_gitkeep_survives(tmp_path):
    _build_tree(tmp_path)
    prune_data_dir(tmp_path, now=NOW)
    canonical = tmp_path / "data" / "canonical"
    assert canonical.is_dir()
    assert (canonical / ".gitkeep").exists()
    assert not (canonical / "canonical_snapshot_old.json").exists()
    assert not (canonical / "nested").exists()


def test_exports_archive_keeps_a_daily_tail_in_both_roots(tmp_path):
    """The archive is the only thing that can repair a gap in
    ``data/rank_history.jsonl``, and ``backfill_rank_history.py`` can
    only replay what is still here.  A flat 14-day cutoff made any
    stall longer than a fortnight permanently unrecoverable, so
    single-per-day entries survive out to a year.
    """
    _build_tree(tmp_path)
    prune_data_dir(tmp_path, now=NOW)
    data_arch = tmp_path / "data" / "exports" / "archive"
    base_arch = tmp_path / "exports" / "archive"

    # Inside the full-fidelity window.
    assert (data_arch / "dynasty_export_new.zip").exists()
    assert (base_arch / "dynasty_export_fresh.zip").exists()
    # Inside the daily window — one per date, and these are the only
    # entry for theirs, so they survive where the old policy deleted them.
    assert (data_arch / "dynasty_export_old.zip").exists()
    assert (base_arch / "dynasty_export_ancient.zip").exists()
    # Past the daily window — gone, in both roots.
    assert not (data_arch / "dynasty_export_expired.zip").exists()
    assert not (base_arch / "dynasty_export_prehistoric.zip").exists()


def test_archive_age_derived_from_filename_not_mtime(tmp_path):
    """Age-based pruning must use the embedded filename timestamp, not
    mtime.

    A fresh ``actions/checkout`` in CI stamps every tracked file with the
    checkout time, so mtime-only pruning would leave every committed
    archive in place forever.  The archive names embed the write time
    (``dynasty_export_YYYYMMDD_HHMMSS.zip``); that must drive the cutoff.
    """
    arch = tmp_path / "exports" / "archive"
    # Old by NAME (well past the one-year tail; NOW is 2025-06-15) but
    # FRESH mtime — the CI fresh-checkout case.  Must be pruned on the
    # strength of the name.
    stale = _touch(arch / "dynasty_export_20230101_000000.zip", age_days=0)
    # Fresh by NAME (1 day before NOW) but ANCIENT mtime — embedded
    # timestamp must win and keep it.
    fresh = _touch(arch / "dynasty_export_20250614_000000.zip", age_days=999)

    prune_data_dir(tmp_path, now=NOW)

    assert not stale.exists(), "old embedded timestamp must prune despite fresh mtime"
    assert fresh.exists(), "recent embedded timestamp must survive despite ancient mtime"


def test_keep_newest_ranks_by_filename_timestamp_not_mtime(tmp_path):
    """Keep-newest must rank by embedded filename timestamp, not mtime.

    In a fresh CI checkout every snapshot shares the checkout-time mtime,
    so mtime-only ranking could keep an arbitrary N and delete the
    newest-by-name raw history.  Here mtimes are shuffled INVERSELY to the
    embedded timestamps: if ranking followed mtime the wrong files would
    survive.
    """
    d = tmp_path / "data" / "raw_sources"
    # 35 snapshots, embedded timestamps ascending 2026-06-01..2026-07-05.
    # Give the NEWEST-named files the OLDEST mtimes to prove name wins.
    for i in range(35):
        day = 1 + i
        month, dom = (6, day) if day <= 30 else (7, day - 30)
        name = f"raw_source_snapshot_2026{month:02d}{dom:02d}T120000Z.json"
        _touch(d / name, age_days=i)  # higher i (newer name) => older mtime

    prune_data_dir(tmp_path, now=NOW)
    remaining = sorted(p.name for p in d.glob("*.json"))
    assert len(remaining) == retention.RAW_SOURCES_KEEP
    # The 30 newest by embedded date (2026-06-06 .. 2026-07-05) survive;
    # the 5 oldest by name (2026-06-01 .. 2026-06-05) are pruned.
    assert "raw_source_snapshot_20260705T120000Z.json" in remaining
    assert "raw_source_snapshot_20260601T120000Z.json" not in remaining


def test_raw_sources_keep_newest_30(tmp_path):
    _build_tree(tmp_path)
    prune_data_dir(tmp_path, now=NOW)
    remaining = sorted((tmp_path / "data" / "raw_sources").glob("*.json"))
    assert len(remaining) == retention.RAW_SOURCES_KEEP
    # newest (highest index) must survive; oldest must be gone
    names = {p.name for p in remaining}
    assert "raw_source_snapshot_039.json" in names
    assert "raw_source_snapshot_000.json" not in names


def test_raw_per_source_keep_newest_30_independently(tmp_path):
    _build_tree(tmp_path)
    prune_data_dir(tmp_path, now=NOW)
    for src in ("ktc", "fantasycalc"):
        leaf = tmp_path / "data" / "raw" / src / "2026"
        assert len(list(leaf.iterdir())) == retention.RAW_PER_SOURCE_KEEP
        assert (leaf / f"{src}_2026_034").exists()
        assert not (leaf / f"{src}_2026_000").exists()


def test_dynasty_data_age_cutoff(tmp_path):
    _build_tree(tmp_path)
    prune_data_dir(tmp_path, now=NOW)
    data = tmp_path / "data"
    assert not (data / "dynasty_data_2026-01-01.json").exists()
    assert (data / "dynasty_data_2026-05-10.json").exists()


def test_protected_paths_never_touched(tmp_path):
    _build_tree(tmp_path)
    prune_data_dir(tmp_path, now=NOW)
    assert (tmp_path / "exports" / "latest" / "dynasty_data.js").exists()
    assert (tmp_path / "exports" / "latest" / "dynasty_export_latest.zip").exists()
    assert (tmp_path / "data" / "rank_history.jsonl").exists()
    assert (tmp_path / "data" / "identity" / "player_map.json").exists()
    assert (tmp_path / "data" / "ros" / "aggregate" / "history" / "old.json").exists()


def test_dry_run_deletes_nothing_but_reports(tmp_path):
    _build_tree(tmp_path)
    report = prune_data_dir(tmp_path, now=NOW, dry_run=True)
    # everything that would be removed is still present
    assert (tmp_path / "data" / "canonical" / "canonical_snapshot_old.json").exists()
    assert (tmp_path / "data" / "dynasty_data_2026-01-01.json").exists()
    assert report.dry_run is True
    assert report.total_deleted > 0
    assert report.total_bytes_freed > 0


def test_report_accounting_matches_real_run(tmp_path):
    _build_tree(tmp_path)
    report = prune_data_dir(tmp_path, now=NOW)
    assert report.total_errors == 0
    assert report.total_deleted > 0
    # 40 raw_sources - 30 kept = 10 deleted
    rs = next(c for c in report.categories if c.name == "raw_sources")
    assert rs.deleted == 10
    assert "reclaimed" in report.summary()


def test_missing_dirs_are_noops(tmp_path):
    report = prune_data_dir(tmp_path, now=NOW)
    assert report.total_deleted == 0
    assert report.total_errors == 0
    assert report.summary().endswith("nothing to prune")


def test_symlink_escape_is_refused(tmp_path):
    _build_tree(tmp_path)
    outside = tmp_path / "OUTSIDE_secret.txt"
    outside.write_text("must survive")
    # An attacker-ish symlink inside a pruned leaf pointing out of root.
    leaf = tmp_path / "data" / "raw" / "ktc" / "2026"
    link = leaf / "ktc_2026_999_link"
    link.symlink_to(outside)
    os.utime(link, (NOW - 999 * 86_400, NOW - 999 * 86_400), follow_symlinks=False)
    prune_data_dir(tmp_path, now=NOW)
    assert outside.exists()
    assert outside.read_text() == "must survive"


def test_containment_guard_blocks_protected_root(tmp_path):
    # Direct guard check: deleting something resolving into a protected
    # dir is refused even if a caller passes it.
    protected = retention._protected_paths(tmp_path)
    cat = retention.CategoryResult(name="x")
    target = tmp_path / "data" / "identity" / "player_map.json"
    _touch(target, age_days=999)
    retention._delete(target, tmp_path / "data" / "identity", protected, cat, dry_run=False)
    assert target.exists()
    assert cat.errors == 1
    assert cat.deleted == 0


# ── the daily-thinning band ─────────────────────────────────────────────


def _archive_day(base: Path, day: str, times: list[str]) -> list[Path]:
    """Several zips stamped on one UTC date, oldest first."""
    arch = base / "exports" / "archive"
    return [_touch(arch / f"dynasty_export_{day}_{t}.zip", age_days=0) for t in times]


def test_only_one_zip_per_day_survives_beyond_the_full_window(tmp_path):
    """THE POINT OF THE BAND.

    ~9 zips land per day. Keeping all of them for a year would cost
    ~700 MB for no additional repair capability, because
    ``backfill_rank_history.py`` replays one snapshot per date.
    """
    # NOW is 2025-06-15; these are ~5 months back, inside the daily band.
    made = _archive_day(tmp_path, "20250115", ["010000", "090000", "170000"])
    prune_data_dir(tmp_path, now=NOW)
    survivors = sorted(p.name for p in made if p.exists())
    assert survivors == ["dynasty_export_20250115_170000.zip"]


def test_the_survivor_is_the_newest_of_the_day_not_the_oldest(tmp_path):
    """``append_snapshot`` is idempotent per UTC date — a same-day re-run
    OVERWRITES the entry. So the board the log held for a date is the
    one from that day's LAST scrape. Backfilling from the day's first
    zip would write a board the log never had.
    """
    made = _archive_day(tmp_path, "20250210", ["000500", "235500"])
    prune_data_dir(tmp_path, now=NOW)
    assert not made[0].exists()
    assert made[1].exists()


def test_the_recent_window_keeps_every_zip_from_the_same_day(tmp_path):
    """Debugging one bad scrape needs the specific zip, and which one
    depends on when it went wrong. That only matters for a fortnight,
    which is why the full-fidelity band still exists."""
    made = _archive_day(tmp_path, "20250614", ["010000", "090000", "170000"])
    prune_data_dir(tmp_path, now=NOW)
    assert all(p.exists() for p in made), "recent same-day zips must not be thinned"


def test_days_are_kept_independently(tmp_path):
    """One survivor PER DATE, not one survivor overall."""
    a = _archive_day(tmp_path, "20250301", ["010000", "020000"])
    b = _archive_day(tmp_path, "20250302", ["010000", "020000"])
    prune_data_dir(tmp_path, now=NOW)
    assert [p.exists() for p in a] == [False, True]
    assert [p.exists() for p in b] == [False, True]


def test_a_dry_run_deletes_nothing_in_the_daily_band(tmp_path):
    made = _archive_day(tmp_path, "20250115", ["010000", "170000"])
    report = prune_data_dir(tmp_path, now=NOW, dry_run=True)
    assert all(p.exists() for p in made)
    assert report.dry_run is True
