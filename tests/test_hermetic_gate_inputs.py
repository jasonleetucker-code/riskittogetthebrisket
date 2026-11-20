"""The blocking gate must not depend on rolling checkout data.

``exports/archive`` is a rolling window: ``src/maintenance/retention.py`` keeps each
zip 14 days and then only the newest per calendar day, and the scheduled refresh
runs that pass.  Two research tests named ``dynasty_export_20261107_063955.zip``
(not the newest of its day) and would have started skipping on ~2026-11-21, pushing
the suite past its skip budget (``config/ci/test_shards.json::max_skipped``) and
turning every PR and deploy gate red at once -- the same class as the data-refresh
freezes ``tests/test_pinned_board.py`` closed for board builds.

This guard keeps the class closed.  It statically scans every blocking-gate test
module (``tests/hermetic_gate_scan.py``) and fails on a NEW

* literal naming a specific ``exports/archive/<file>.zip`` outside ``tests/fixtures``,
* ``skip`` / ``skipif`` / ``skipTest`` whose reason says the data is absent from the
  checkout (archive, absent, missing, shallow, ...).

Existing cases are inventoried in ``tests/hermetic_gate_allowlist.json``, each with
a reason, so only new ones fail.  The fix for a hit is to pin the input under
``tests/fixtures`` (see ``tests/fixtures/pinned_board`` and
``tests/fixtures/bdvm_saturation_outcome_archives``), or to mark a test that is
genuinely about the latest refresh ``@pytest.mark.livedata``.  A ``livedata`` scope
is outside the gate and never reported.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from src.maintenance import retention
from tests import hermetic_gate_scan as scan
from tests.conftest import _LIVEDATA_MODULES

ALLOWLIST = scan.TESTS / "hermetic_gate_allowlist.json"
SELF = "tests/test_hermetic_gate_inputs.py"

#: How far ahead the early warning looks: an allowlisted read of an export the
#: retention pass will delete within this window fails NOW, not on the day it skips.
RETENTION_WARNING_DAYS = 90
#: Allowlist flag for an entry whose archive literals name an export it never needs
#: (a provenance string, or a re-verification that passes when the zip is gone).
NOT_READ_FLAG = "archiveLiteralsNotRead"


def _allowlist() -> dict[str, dict]:
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))["files"]


def _current_hits() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for path in scan.gate_test_files(frozenset(_LIVEDATA_MODULES)):
        rel = path.relative_to(scan.REPO).as_posix()
        if rel == SELF:
            continue
        counts: dict[str, int] = {}
        for hit in scan.scan_source(path.read_text(encoding="utf-8")):
            counts[hit.kind] = counts.get(hit.kind, 0) + 1
        if counts:
            out[rel] = counts
    return out


def test_no_new_gate_test_depends_on_rolling_archive_or_skips_on_missing_data():
    allowed = _allowlist()
    offenders = []
    for rel, counts in sorted(_current_hits().items()):
        budget = allowed.get(rel, {}).get("maxHits", {})
        for kind, n in sorted(counts.items()):
            if n > budget.get(kind, 0):
                offenders.append(f"{rel}: {n} x {kind} (allowlisted: {budget.get(kind, 0)})")
    assert not offenders, (
        "blocking-gate tests depend on rolling checkout data (a retention pass or a "
        "shallow clone turns each into a skip, and past the skip budget the whole gate "
        f"goes red): {offenders}. Pin the input under tests/fixtures, mark a test about "
        "the latest refresh @pytest.mark.livedata, or -- last resort -- add a reasoned "
        "entry to tests/hermetic_gate_allowlist.json."
    )


def test_the_allowlist_has_no_stale_or_unreasoned_entry():
    hits = _current_hits()
    stale, unreasoned = [], []
    for rel, entry in _allowlist().items():
        if not (scan.REPO / rel).is_file():
            stale.append(f"{rel} (file is gone)")
        elif rel not in hits:
            stale.append(f"{rel} (no longer has any hit: delete the entry)")
        if len(str(entry.get("reason", "")).strip()) < 40:
            unreasoned.append(rel)
    assert not stale, f"stale allowlist entries: {stale}"
    assert not unreasoned, f"allowlist entries without a real reason: {unreasoned}"


# ── early warning: an allowlisted archive read must outlive retention ───────


def _tracked_archive_names() -> set[str]:
    """Names of the exports git tracks in ``exports/archive`` (the listing only)."""
    out = subprocess.run(
        ["git", "-C", str(scan.REPO), "ls-files", "--", "exports/archive"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return {PurePosixPath(line).name for line in out.splitlines() if line.strip()}


def _doomed_by_retention(names, now: float, workdir: Path, monkeypatch) -> set[str]:
    """The exports among ``names`` the retention pass would delete at ``now``.

    Runs the real ``retention._prune_thin_to_daily`` (the exports policy) in dry-run
    over EMPTY stand-in files named like the listing, in ``workdir``: retention ages a
    zip by its filename stamp, so the stand-ins age exactly like the real zips, and
    nothing in the checkout is opened or touched."""
    archive_dir = workdir / "exports" / "archive"
    archive_dir.mkdir(parents=True)
    for name in names:
        (archive_dir / name).touch()
    doomed: set[str] = set()
    real_delete = retention._delete

    def record(target, allowed_root, protected, cat, *, dry_run):
        assert dry_run, "the early warning must never delete"
        doomed.add(Path(target).name)
        real_delete(target, allowed_root, protected, cat, dry_run=True)

    monkeypatch.setattr(retention, "_delete", record)
    retention._prune_thin_to_daily(
        archive_dir,
        "dynasty_export_*.zip",
        retention.EXPORTS_ARCHIVE_MAX_AGE_DAYS,
        retention.EXPORTS_ARCHIVE_DAILY_MAX_AGE_DAYS,
        retention._protected_paths(workdir),
        retention.CategoryResult(name="exports_archive"),
        now=now,
        dry_run=True,
    )
    return doomed


def _allowlisted_archive_reads(tracked: set[str]) -> dict[str, set[str]]:
    """Tracked exports each allowlisted test names, unless it declares them not read."""
    reads: dict[str, set[str]] = {}
    for rel, entry in _allowlist().items():
        if entry.get(NOT_READ_FLAG) or not (scan.REPO / rel).is_file():
            continue
        source = (scan.REPO / rel).read_text(encoding="utf-8")
        named = {
            PurePosixPath(hit.detail).name
            for hit in scan.scan_source(source)
            if hit.kind == "archive-literal"
        }
        if named & tracked:
            reads[rel] = named & tracked
    return reads


def test_allowlisted_archive_reads_survive_retention(tmp_path, monkeypatch):
    """Fails ``RETENTION_WARNING_DAYS`` before an allowlisted test loses its export.

    Retention keeps every export 14 days, then the newest per day for 365 days.  A
    test that still reads a specific tracked export would turn into a skip (and,
    past the skip budget, a red gate) the day the scheduled refresh prunes it; this
    says so a quarter ahead.  The fix is to pin the input under ``tests/fixtures``."""
    tracked = _tracked_archive_names()
    reads = _allowlisted_archive_reads(tracked)
    needed = set().union(*reads.values()) if reads else set()
    now = time.time() + RETENTION_WARNING_DAYS * 86_400
    doomed = _doomed_by_retention(sorted(tracked), now, tmp_path, monkeypatch) & needed
    offenders = sorted(
        f"{rel}: {sorted(names & doomed)}" for rel, names in reads.items() if names & doomed
    )
    assert not offenders, (
        f"retention deletes these allowlisted archive reads within {RETENTION_WARNING_DAYS} "
        f"days: {offenders}. Pin the inputs under tests/fixtures (see "
        "tests/fixtures/te_skew_20261106) and drop the archive-literal allowlist entry."
    )


def test_not_read_flag_is_only_on_entries_that_name_an_archive():
    flagged_without_literal = [
        rel
        for rel, entry in _allowlist().items()
        if entry.get(NOT_READ_FLAG) and not entry.get("maxHits", {}).get("archive-literal")
    ]
    assert (
        not flagged_without_literal
    ), f"`{NOT_READ_FLAG}` on entries with no archive-literal budget: {flagged_without_literal}"


def test_retention_early_warning_sees_a_doomed_read(tmp_path, monkeypatch):
    """Guard on the guard: the dry-run helper flags exactly what retention would delete."""
    now = datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc).timestamp()
    names = [
        "dynasty_export_20270228_230000.zip",  # inside the 14-day full window: kept
        "dynasty_export_20270228_010000.zip",  # same day, inside the full window: kept
        "dynasty_export_20261201_230000.zip",  # newest of its day: kept
        "dynasty_export_20261201_010000.zip",  # not the newest of its day: deleted
        "dynasty_export_20260101_230000.zip",  # past the 365-day tail: deleted
    ]
    doomed = _doomed_by_retention(names, now, tmp_path, monkeypatch)
    assert doomed == {"dynasty_export_20261201_010000.zip", "dynasty_export_20260101_230000.zip"}
    assert sorted(p.name for p in (tmp_path / "exports" / "archive").glob("*.zip")) == sorted(names)


# ── guard on the guard: the scanner must fire on a seeded violation ─────────


def test_scanner_flags_an_archive_zip_literal():
    src = 'ARCHIVE = "exports/archive/dynasty_export_20991231_235959.zip"\n'
    hits = scan.scan_source(src)
    assert [(h.kind, h.line) for h in hits] == [("archive-literal", 1)]


def test_scanner_flags_a_bare_export_name_whether_or_not_the_file_exists():
    """Data-independent: the verdict never depends on what is in exports/archive."""
    src = 'NAME = "dynasty_export_20991231_235959.zip"\n'
    assert [h.kind for h in scan.scan_source(src)] == ["archive-literal"]


def test_scanner_folds_string_concatenation_and_path_joins():
    for src in (
        'A = "exports/archive/" + "dynasty_export_20991231_235959.zip"\n',
        'A = REPO / "exports" / "archive" / "dynasty_export_20991231_235959.zip"\n',
        'A = Path("exports") / "archive" / "dynasty_export_20991231_235959.zip"\n',
    ):
        hits = scan.scan_source(src)
        assert [(h.kind, h.line) for h in hits] == [("archive-literal", 1)], src


def test_scanner_flags_listing_the_archive_directory():
    for src in (
        'for p in (REPO / "exports" / "archive").glob("*.zip"):\n    pass\n',
        'os.listdir(os.path.join(REPO, "exports", "archive"))\n',
    ):
        kinds = [h.kind for h in scan.scan_source(src)]
        assert kinds == ["archive-listing"], src


def test_scanner_flags_missing_data_skips_in_every_spelling():
    src = (
        "import pytest, unittest\n"
        "def test_a():\n    pytest.skip('tracked archive not in this checkout')\n"
        "@pytest.mark.skipif(not X.exists(), reason='pinned archive bundle absent')\n"
        "def test_b():\n    pass\n"
        "class T(unittest.TestCase):\n"
        "    def test_c(self):\n        self.skipTest('No complete archived board')\n"
        "def test_d():\n    pytest.skip(f'{name} is missing from the clone')\n"
    )
    assert [(h.kind, h.line) for h in scan.scan_source(src)] == [
        ("missing-data-skip", 3),
        ("missing-data-skip", 4),
        ("missing-data-skip", 9),
        ("missing-data-skip", 11),
    ]


def test_scanner_flags_the_broadened_missing_data_phrases():
    for why in ("fixture not found", "no data for this week", "file does not exist", "unavailable"):
        src = f"import pytest\ndef test_a():\n    pytest.skip({why!r})\n"
        assert [h.kind for h in scan.scan_source(src)] == ["missing-data-skip"], why


def test_scanner_ignores_livedata_scopes_docstrings_and_unrelated_skips():
    src = (
        '"""Mentions exports/archive/dynasty_export_20991231_235959.zip in prose."""\n'
        "import pytest\n"
        "@pytest.mark.livedata\n"
        "def test_live():\n    pytest.skip('archive absent')\n"
        "def test_platform():\n    pytest.skip('POSIX only')\n"
    )
    assert scan.scan_source(src) == []
    live_module = (
        "import pytest\npytestmark = pytest.mark.livedata\npytest.skip('archive absent')\n"
    )
    assert scan.scan_source(live_module) == []
