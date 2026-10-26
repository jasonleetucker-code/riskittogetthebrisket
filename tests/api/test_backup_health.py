"""``backup_health`` reports the state-backup directory honestly (RPA-COL-032).

THE DEFECT
----------
``/api/health`` ``backup_health`` scanned only the legacy ``*.sqlite.gz``
directories and answered ``backupDirUsed: "fallback"`` -- a healthy-looking age
for the older ``backup_user_kv.sh`` job -- while the real nightly state backup
lives under the root-only ``/var/backups/riskit-state``, which the backend user
cannot list.  The state backup's coverage was invisible, and the block read as
if it were the backup.

Pinned here: the state backup and the legacy backup are reported separately,
each under its own name; a state root that exists but cannot be listed is
``unverifiable`` / ``permission_denied`` -- never healthy, never missing; the
directory inspected, and why, is always stated; unknown ages and counts are
``None``; and the pre-existing top-level keys the ``health-check.yml`` monitor
reads still describe the legacy backup unchanged.

``/api/health`` and ``/api/status`` are anonymous, so the block they serve is
the PUBLIC projection only: no optional-store names, ledger presence or sizes,
generation date, artifact count or mirror age.  That detail is still computed
(``build_backup_health_detail``) and is tested here, but nothing serves it.
"""

from __future__ import annotations

import asyncio
import errno
import gzip
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import server
from src.api import backup_health as bh

_REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc).timestamp()
HOUR = 3600.0


def _touch_tree(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def make_generation(
    root: Path,
    date: str,
    *,
    mtime: float,
    pointer: bool = False,
    ledgers: tuple[str, ...] = (),
    manifest: str | None = None,
    artifacts: int = 14,
) -> Path:
    gen = root / "daily" / date
    (gen / "sqlite").mkdir(parents=True)
    for name in ("user_kv.sqlite", *ledgers):
        (gen / "sqlite" / f"{name}.gz").write_bytes(gzip.compress(b"x" * 64))
    if manifest is not None:
        (gen / "optional_stores.tsv").write_text(manifest, encoding="utf-8")
    if pointer:
        promoted = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (root / "last_generation").write_text(
            f"schema=1\neffective_root={root}\ngeneration={gen}\ndate_stamp={date}\n"
            f"artifacts={artifacts}\npromoted_at={promoted}\n",
            encoding="utf-8",
        )
    _touch_tree(gen, mtime)
    return gen


def make_legacy(directory: Path, *, mtime: float, stamp: str = "2026-10-26") -> None:
    directory.mkdir(parents=True)
    for name in ("user_kv", "session_store", "guest_passes", "auction"):
        f = directory / f"{name}.{stamp}.sqlite.gz"
        f.write_bytes(gzip.compress(b"db"))
        os.utime(f, (mtime, mtime))


def deny_listing(monkeypatch, *denied: Path | str) -> None:
    """Stat still works, listing is refused -- a 0700 root-owned directory
    as seen by the unprivileged service user."""
    real = bh._listdir
    blocked = {os.path.normpath(str(d)) for d in denied}

    def fake(path):
        if os.path.normpath(path) in blocked:
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return real(path)

    monkeypatch.setattr(bh, "_listdir", fake)


def state(tmp_path: Path, **kw):
    return bh.state_backup_health(
        root=str(tmp_path / "state"),
        fallback_root=str(tmp_path / "state_fb"),
        now_epoch=NOW,
        **kw,
    )


def _paths(tmp_path: Path) -> dict:
    return {
        "state_root": str(tmp_path / "state"),
        "state_fallback_root": str(tmp_path / "state_fb"),
        "legacy_dirs": (
            ("primary", str(tmp_path / "legacy_primary")),
            ("fallback", str(tmp_path / "legacy_fallback")),
        ),
        "now_epoch": NOW,
    }


def build(tmp_path: Path, **kw):
    """The PUBLIC block -- what /api/health and /api/status serve."""
    return bh.build_backup_health(**_paths(tmp_path), **kw)


def detail(tmp_path: Path, **kw):
    """The private full report -- served by no endpoint."""
    return bh.build_backup_health_detail(**_paths(tmp_path), **kw)


# -- readable canonical directory: healthy or stale ---------------------------
def test_readable_state_root_with_a_fresh_generation_is_healthy(tmp_path):
    root = tmp_path / "state"
    make_generation(
        root,
        "2026-10-26",
        mtime=NOW - 10 * HOUR,
        pointer=True,
        ledgers=("temporal_ledger.sqlite",),
        manifest="intel_ledger.sqlite3\tskipped_low_space\t100 KiB free\n",
    )
    out = state(tmp_path)

    assert out["state"] == "healthy"
    assert out["reason"] == "within_threshold"
    assert out["directoryInspected"] == str(root)
    assert out["inspectionReason"] == "canonical_root"
    assert out["evidenceSource"] == "directory_listing"
    assert out["newestGeneration"] == "2026-10-26"
    assert out["newestGenerationAgeHours"] == 10.0
    assert out["ageBasis"] == "pointer_promoted_at"
    assert out["artifactCount"] == 14
    assert out["generationCount"] == 1
    # Coverage is observed, not assumed: one ledger is in, one is not.
    on_disk = (
        (root / "daily" / "2026-10-26" / "sqlite" / "temporal_ledger.sqlite.gz").stat().st_size
    )
    assert out["ledgers"]["temporal_ledger.sqlite"] == {"present": True, "sizeBytes": on_disk}
    assert out["ledgers"]["intel_ledger.sqlite3"] == {"present": False, "sizeBytes": None}
    assert out["optionalStores"] == {
        "manifest": "present",
        "notInGeneration": [{"name": "intel_ledger.sqlite3", "status": "skipped_low_space"}],
    }
    # A readable root with no mirror marker has never completed a mirror.
    assert out["offboxMirror"]["state"] == "none_recorded"


def test_age_falls_back_to_directory_mtime_without_a_pointer(tmp_path):
    make_generation(tmp_path / "state", "2026-10-26", mtime=NOW - 5 * HOUR)
    out = state(tmp_path)
    assert out["state"] == "healthy"
    assert out["newestGenerationAgeHours"] == 5.0
    assert out["ageBasis"] == "directory_mtime"
    # No pointer => the artifact count is unknown, not zero.
    assert out["artifactCount"] is None
    # No manifest is not proof that nothing was shed.
    assert out["optionalStores"] == {"manifest": "absent", "notInGeneration": None}


def test_old_generation_is_stale(tmp_path):
    make_generation(tmp_path / "state", "2026-10-24", mtime=NOW - 60 * HOUR, pointer=True)
    out = state(tmp_path)
    assert out["state"] == "stale"
    assert out["reason"] == "older_than_threshold"
    assert out["newestGenerationAgeHours"] == 60.0


def test_newest_dated_generation_is_the_one_judged(tmp_path):
    root = tmp_path / "state"
    make_generation(root, "2026-10-20", mtime=NOW - 200 * HOUR)
    make_generation(root, "2026-10-26", mtime=NOW - 3 * HOUR)
    out = state(tmp_path)
    assert out["newestGeneration"] == "2026-10-26"
    assert out["generationCount"] == 2
    assert out["state"] == "healthy"


def test_recorded_offbox_mirror_reports_time_but_never_the_destination(tmp_path):
    root = tmp_path / "state"
    make_generation(root, "2026-10-26", mtime=NOW - HOUR)
    (root / "last_mirror").write_text(
        "schema=1\ndest=backup@storagebox.example:riskit-state/\ngenerations=3\n"
        "mirrored_at=2026-10-26T06:00:00Z\n",
        encoding="utf-8",
    )
    mirror = state(tmp_path)["offboxMirror"]
    assert mirror == {"state": "recorded", "mirroredAt": "2026-10-26T06:00:00Z", "ageHours": 6.0}
    assert "storagebox" not in repr(state(tmp_path))


# -- unreadable canonical directory: unverifiable, never healthy, never missing
def test_unreadable_state_root_is_unverifiable_permission_denied(tmp_path, monkeypatch):
    root = tmp_path / "state"
    make_generation(root, "2026-10-26", mtime=NOW - HOUR)  # it IS there and fresh
    deny_listing(monkeypatch, root)

    out = state(tmp_path)

    assert out["state"] == "unverifiable"
    assert out["reason"] == "permission_denied"
    assert out["state"] not in ("healthy", "stale", "missing")
    assert out["directoryInspected"] == str(root)
    assert out["inspectionReason"] == "canonical_root_unreadable"
    assert out["evidenceSource"] is None
    # Nothing was observed, so nothing is claimed -- not zero, not healthy.
    for unknown in (
        "newestGeneration",
        "newestGenerationAgeHours",
        "ageBasis",
        "generationCount",
        "artifactCount",
        "optionalStores",
        "ledgers",
        "offboxMirror",
    ):
        assert out[unknown] is None, unknown
    assert out["roots"][0]["blockedAt"] == str(root)


def test_state_root_stat_denied_is_also_permission_denied(tmp_path, monkeypatch):
    root = tmp_path / "state"
    root.mkdir()
    real = bh._stat

    def fake(path):
        if os.path.normpath(path) == os.path.normpath(str(root)):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return real(path)

    monkeypatch.setattr(bh, "_stat", fake)
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "permission_denied")


def test_listable_root_with_a_closed_daily_dir_is_still_unverifiable(tmp_path, monkeypatch):
    root = tmp_path / "state"
    make_generation(root, "2026-10-26", mtime=NOW - HOUR)
    deny_listing(monkeypatch, root / "daily")
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "permission_denied")
    assert out["roots"][0]["blockedAt"] == str(root / "daily")


def test_other_os_errors_are_unverifiable_not_missing(tmp_path, monkeypatch):
    root = tmp_path / "state"
    root.mkdir()
    real = bh._listdir

    def fake(path):
        if os.path.normpath(path) == os.path.normpath(str(root)):
            raise OSError(errno.EIO, "input/output error", path)
        return real(path)

    monkeypatch.setattr(bh, "_listdir", fake)
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "io_error")


def test_unreadable_writer_fallback_makes_a_readable_canonical_root_unverifiable(
    tmp_path, monkeypatch
):
    """A newer generation may sit behind the closed door; certifying the older
    one from the readable root would be a fail-open."""
    make_generation(tmp_path / "state", "2026-10-26", mtime=NOW - HOUR)
    (tmp_path / "state_fb").mkdir()
    deny_listing(monkeypatch, tmp_path / "state_fb")
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "permission_denied")
    assert out["inspectionReason"] == "writer_fallback_root_unreadable"
    assert out["directoryInspected"] == str(tmp_path / "state_fb")


def test_generation_dated_beyond_the_clock_skew_bound_is_unverifiable(tmp_path):
    make_generation(tmp_path / "state", "2099-03-04", mtime=NOW - HOUR)
    make_generation(tmp_path / "state", "2026-10-26", mtime=NOW - HOUR)
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "generation_clock_skew")


def test_newest_entry_that_is_not_a_directory_is_unverifiable(tmp_path):
    root = tmp_path / "state"
    make_generation(root, "2026-10-25", mtime=NOW - 30 * HOUR)
    (root / "daily" / "2026-10-26").write_text("not a generation", encoding="utf-8")
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "generation_unresolvable")


# -- writer fallback root -----------------------------------------------------
def test_absent_canonical_root_uses_the_writer_fallback_and_says_so(tmp_path):
    fb = tmp_path / "state_fb"
    make_generation(fb, "2026-10-26", mtime=NOW - 2 * HOUR)
    out = state(tmp_path)
    assert out["state"] == "healthy"
    assert out["directoryInspected"] == str(fb)
    assert out["inspectionReason"] == "canonical_root_absent_writer_fallback"
    assert [r["verdict"] for r in out["roots"]] == ["absent", "generation"]


def test_newest_of_two_readable_roots_wins(tmp_path):
    make_generation(tmp_path / "state", "2026-10-22", mtime=NOW - 90 * HOUR)
    make_generation(tmp_path / "state_fb", "2026-10-26", mtime=NOW - 2 * HOUR)
    out = state(tmp_path)
    assert out["directoryInspected"] == str(tmp_path / "state_fb")
    assert out["inspectionReason"] == "writer_fallback_root_newer"
    assert out["state"] == "healthy"


# -- no directory: missing ----------------------------------------------------
def test_no_state_directory_is_missing_with_unknowns_null(tmp_path):
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("missing", "directory_not_found")
    assert out["inspectionReason"] == "no_candidate_root_exists"
    assert out["directoryInspected"] == str(tmp_path / "state")
    assert out["newestGenerationAgeHours"] is None
    assert out["generationCount"] is None
    assert out["artifactCount"] is None


def test_readable_but_empty_state_root_is_missing_no_generations(tmp_path):
    (tmp_path / "state" / "daily").mkdir(parents=True)
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("missing", "no_generations")
    assert out["generationCount"] == 0
    assert out["newestGenerationAgeHours"] is None


def test_hidden_staging_directories_are_not_generations(tmp_path):
    (tmp_path / "state" / "daily" / ".staging-2026-10-26-123").mkdir(parents=True)
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("missing", "no_generations")


# -- legacy backup is reported separately, under its own name -----------------
def test_legacy_backup_is_reported_under_its_own_name_not_as_the_state_backup(
    tmp_path, monkeypatch
):
    """Production on 2026-10-26: the state root exists but is closed, the legacy
    dynasty-owned directory is fresh."""
    state_root = tmp_path / "state"
    state_root.mkdir()
    make_legacy(tmp_path / "legacy_fallback", mtime=NOW - 10.24 * HOUR)
    deny_listing(monkeypatch, state_root)

    out = build(tmp_path)

    assert out["stateBackup"]["state"] == "unverifiable"
    assert out["stateBackup"]["reason"] == "permission_denied"
    assert out["legacySqliteBackup"] == {
        "state": "healthy",
        "reason": "within_threshold",
        "ageHours": 10.24,
    }
    assert out["backupDirUsed"] == "fallback"
    assert out["newestBackupAgeHours"] == 10.24
    assert out["dbCount"] == 4
    # The legacy directory never appears among the state backup's roots.
    assert [r["directoryInspected"] for r in out["stateBackup"]["roots"]] == [
        str(tmp_path / "state"),
        str(tmp_path / "state_fb"),
    ]
    assert out["legacyKeysDescribe"] == "legacySqliteBackup"
    assert out["schemaVersion"] == bh.SCHEMA_VERSION
    # The private report still names it, and says it is NOT the state backup.
    legacy = detail(tmp_path)["legacySqliteBackup"]
    assert legacy["name"] == "legacy_sqlite_backup"
    assert "NOT the state backup" in legacy["describes"]


def test_legacy_directories_are_listed_with_their_own_states(tmp_path):
    make_legacy(tmp_path / "legacy_primary", mtime=NOW - 30 * HOUR, stamp="2026-10-25")
    make_legacy(tmp_path / "legacy_fallback", mtime=NOW - 4 * HOUR)
    legacy = detail(tmp_path)["legacySqliteBackup"]
    assert [(d["label"], d["state"], d["backupFileCount"]) for d in legacy["directories"]] == [
        ("primary", "readable", 4),
        ("fallback", "readable", 4),
    ]
    assert legacy["backupDirUsed"] == "fallback"  # the newer file wins
    assert legacy["newestBackupPath"].endswith("2026-10-26.sqlite.gz")


def test_stale_legacy_backup_is_stale(tmp_path):
    make_legacy(tmp_path / "legacy_primary", mtime=NOW - 48 * HOUR)
    out = build(tmp_path)
    legacy = out["legacySqliteBackup"]
    assert (legacy["state"], legacy["reason"]) == ("stale", "older_than_threshold")
    assert out["backupDirUsed"] == "primary"


def test_unreadable_legacy_directory_with_no_other_backup_is_unverifiable(tmp_path, monkeypatch):
    (tmp_path / "legacy_primary").mkdir()
    deny_listing(monkeypatch, tmp_path / "legacy_primary")
    out = build(tmp_path)
    legacy = out["legacySqliteBackup"]
    assert (legacy["state"], legacy["reason"]) == ("unverifiable", "permission_denied")
    assert legacy["ageHours"] is None
    assert out["newestBackupAgeHours"] is None
    assert out["dbCount"] is None


def test_no_legacy_directory_is_missing_with_unknowns_null(tmp_path):
    out = build(tmp_path)
    legacy = out["legacySqliteBackup"]
    assert (legacy["state"], legacy["reason"]) == ("missing", "directory_not_found")
    assert out["stateBackup"]["state"] == "missing"
    # Top-level keys the monitor reads: unknown is None, never 0.
    assert out["newestBackupAgeHours"] is None
    assert out["newestBackupPath"] is None
    assert out["backupDirUsed"] == "none"
    assert out["dbCount"] is None


# -- monitor compatibility ----------------------------------------------------
def test_top_level_keys_health_check_reads_are_unchanged_for_the_legacy_backup(tmp_path):
    make_legacy(tmp_path / "legacy_fallback", mtime=NOW - 22.71 * HOUR, stamp="2026-10-25")
    out = build(tmp_path)
    # .github/workflows/health-check.yml: age, backupDirUsed, dbCount.
    assert out["newestBackupAgeHours"] == 22.71
    assert out["backupDirUsed"] == "fallback"
    assert out["dbCount"] == 4
    assert out["newestBackupPath"].startswith(str(tmp_path / "legacy_fallback"))
    assert out["newestBackupPath"].endswith("2026-10-25.sqlite.gz")
    # An unreadable state root does not touch what the legacy monitor sees.
    assert out["newestBackupAgeHours"] == out["legacySqliteBackup"]["ageHours"]


def test_health_check_workflow_reads_only_keys_that_are_still_published():
    workflow = (_REPO / ".github" / "workflows" / "health-check.yml").read_text(encoding="utf-8")
    block = workflow[workflow.index('bh = data.get("backup_health")') :]
    block = block[: block.index("PY")]
    read = set(re.findall(r'bh\.get\("([A-Za-z]+)"', block))
    assert read, "the workflow no longer reads backup_health; update this guard"
    published = set(bh.build_backup_health(now_epoch=NOW))
    assert (
        read <= published
    ), f"health-check.yml reads keys backup_health dropped: {read - published}"


def test_a_probe_failure_is_unverifiable_never_an_exception(tmp_path, monkeypatch):
    def boom(**_kw):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(bh, "state_backup_health", boom)
    out = build(tmp_path)
    assert out["stateBackup"]["state"] == "unverifiable"
    assert out["stateBackup"]["reason"] == "probe_error"
    assert out["legacySqliteBackup"]["state"] == "missing"  # the other half still answers


def test_server_helper_serves_the_new_block_and_never_raises(monkeypatch):
    block = server._backup_freshness_uncached()
    assert block["legacyKeysDescribe"] == "legacySqliteBackup"
    assert "stateBackup" in block and "legacySqliteBackup" in block
    for key in ("newestBackupAgeHours", "newestBackupPath", "backupDirUsed", "dbCount"):
        assert key in block

    def boom(**_kw):
        raise RuntimeError("module unavailable")

    monkeypatch.setattr(bh, "build_backup_health", boom)
    fallback = server._backup_freshness_uncached()
    assert fallback["stateBackup"] == {"state": "unverifiable", "reason": "probe_error"}
    assert fallback["newestBackupAgeHours"] is None
    assert fallback["dbCount"] is None


# -- /api/health semantics are unchanged -------------------------------------
def _run_health(monkeypatch, block):
    alerts: list[str] = []
    monkeypatch.setattr(server, "_backup_freshness", lambda: block)
    monkeypatch.setattr(server, "send_alert", lambda subject, body: alerts.append(subject))
    response = asyncio.run(server.get_health())
    return response.status_code, alerts


def test_unverifiable_state_backup_does_not_change_health_status_or_alerting(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    state_root.mkdir()
    make_legacy(tmp_path / "legacy_fallback", mtime=NOW - HOUR)
    deny_listing(monkeypatch, state_root)
    # Real clock for the legacy age so the stale-backup alert logic sees a fresh backup.
    new_block = bh.build_backup_health(
        state_root=str(state_root),
        state_fallback_root=str(tmp_path / "state_fb"),
        legacy_dirs=(("fallback", str(tmp_path / "legacy_fallback")),),
        now_epoch=NOW,
    )
    assert new_block["stateBackup"]["state"] == "unverifiable"
    legacy_only = {
        k: new_block[k]
        for k in ("newestBackupAgeHours", "newestBackupPath", "backupDirUsed", "dbCount")
    }

    status_new, alerts_new = _run_health(monkeypatch, new_block)
    status_old, alerts_old = _run_health(monkeypatch, legacy_only)

    assert status_new == status_old
    assert alerts_new == alerts_old == []


def test_missing_legacy_backup_still_alerts_exactly_as_before(monkeypatch):
    block = {
        "newestBackupAgeHours": None,
        "newestBackupPath": None,
        "backupDirUsed": "none",
        "dbCount": None,
        "stateBackup": {"state": "unverifiable", "reason": "permission_denied"},
    }
    _status, alerts = _run_health(monkeypatch, block)
    assert alerts == ["Risk It: SQLite backups stale"]


# -- the paths mirror the shell scripts that own them ---------------------------
def test_state_root_defaults_mirror_backup_root_lib():
    lib = (_REPO / "deploy" / "backup" / "backup_root_lib.sh").read_text(encoding="utf-8")
    primary = re.search(r'"\$\{BACKUP_ROOT:-([^}]+)\}"', lib)
    fallback = re.search(r'"\$\{BACKUP_FALLBACK_ROOT:-([^}]+)\}"', lib)
    assert primary and fallback, "backup_root_lib.sh defaults moved; update backup_health"
    assert primary.group(1) == bh.STATE_BACKUP_ROOT
    assert fallback.group(1) == bh.STATE_BACKUP_FALLBACK_ROOT
    unit = (_REPO / "deploy" / "backup" / "riskit-state-backup.service").read_text(encoding="utf-8")
    assert f'Environment="BACKUP_ROOT={bh.STATE_BACKUP_ROOT}"' in unit


def test_legacy_dirs_mirror_backup_user_kv():
    script = (_REPO / "deploy" / "backup_user_kv.sh").read_text(encoding="utf-8")
    primary = re.search(r'BACKUP_DIR="\$\{BACKUP_DIR:-([^}]+)\}"', script)
    fallback = re.search(r'BACKUP_FALLBACK_DIR="\$\{BACKUP_FALLBACK_DIR:-([^}]+)\}"', script)
    assert primary and fallback, "backup_user_kv.sh defaults moved; update backup_health"
    assert primary.group(1) + "/daily" == bh.LEGACY_PRIMARY_DIR
    assert fallback.group(1) + "/daily" == bh.LEGACY_FALLBACK_DIR


def test_stale_threshold_matches_the_health_endpoint_alert():
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert f"_bage > {int(bh.STALE_AFTER_HOURS)}" in source


@pytest.mark.parametrize("age,expected", [(0.0, "healthy"), (36.0, "healthy"), (36.01, "stale")])
def test_threshold_boundary(age, expected):
    assert bh._verdict(age)[0] == expected
    assert bh._verdict(None) == ("unverifiable", "age_unknown")


# -- the public/private boundary ---------------------------------------------
#: Every key the detail carries that an anonymous caller must never see: which
#: stores a generation shed, which ledgers are in it and how big, when the
#: generation was made, how many artifacts it held, how stale the mirror is.
_DETAIL_ONLY_KEYS = frozenset(
    {
        "optionalStores",
        "notInGeneration",
        "manifest",
        "ledgers",
        "present",
        "sizeBytes",
        "artifactCount",
        "newestGeneration",
        "newestGenerationAgeHours",
        "ageBasis",
        "offboxMirror",
        "mirroredAt",
        "blockedAt",
        "verdict",
        "role",
        "path",
        "canonicalRoot",
        "staleAfterHours",
        "describes",
        "directories",
        "backupFileCount",
    }
)
_DETAIL_MARKERS = (
    "intel_ledger",
    "temporal_ledger",
    "skipped_low_space",
    "storagebox",
    "mirrored_at",
)


def _all_keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _all_keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _all_keys(v)}
    return set()


def _rich_tree(tmp_path: Path) -> None:
    """Every kind of detail the report can hold, so a leak has something to leak."""
    root = tmp_path / "state"
    make_generation(
        root,
        "2026-10-26",
        mtime=NOW - 10 * HOUR,
        pointer=True,
        ledgers=("temporal_ledger.sqlite",),
        manifest="intel_ledger.sqlite3\tskipped_low_space\t100 KiB free\n",
    )
    make_generation(root, "2026-10-25", mtime=NOW - 34 * HOUR)
    (root / "last_mirror").write_text(
        "schema=1\ndest=backup@storagebox.example:riskit-state/\ngenerations=3\n"
        "mirrored_at=2026-10-26T06:00:00Z\n",
        encoding="utf-8",
    )
    make_legacy(tmp_path / "legacy_fallback", mtime=NOW - 5 * HOUR)


def test_the_detail_report_still_carries_the_coverage_it_always_computed(tmp_path):
    """Trimming the public payload must not delete the evidence: it is still
    computed, for an operator on the box."""
    _rich_tree(tmp_path)
    block = detail(tmp_path)["stateBackup"]
    assert block["ledgers"]["temporal_ledger.sqlite"]["present"] is True
    assert block["optionalStores"]["notInGeneration"] == [
        {"name": "intel_ledger.sqlite3", "status": "skipped_low_space"}
    ]
    assert block["artifactCount"] == 14
    assert block["newestGeneration"] == "2026-10-26"
    assert block["offboxMirror"]["ageHours"] == 6.0
    # ... and it is exactly what the public payload must not carry.
    assert _all_keys(block) & _DETAIL_ONLY_KEYS


def test_public_payload_carries_none_of_the_detail_keys(tmp_path):
    _rich_tree(tmp_path)
    public = build(tmp_path)

    leaked = _all_keys(public) & _DETAIL_ONLY_KEYS
    assert not leaked, f"anonymous backup_health leaks private detail keys: {sorted(leaked)}"
    text = json.dumps(public)
    for marker in _DETAIL_MARKERS:
        assert marker not in text, marker
    # The generation date is detail too (the pre-existing legacy file path keeps
    # its own stamp, so look only at the new state block).
    assert "2026-10-26" not in json.dumps(public["stateBackup"])


def test_public_blocks_carry_exactly_the_allowed_keys(tmp_path):
    _rich_tree(tmp_path)
    public = build(tmp_path)
    state_block = public["stateBackup"]

    assert set(state_block) == set(bh.PUBLIC_STATE_KEYS) | {"roots"}
    assert state_block["state"] == "healthy"
    assert state_block["ageHours"] == 10.0
    assert state_block["generationCount"] == 2  # a count, nothing more
    assert state_block["evidenceSource"] == "directory_listing"
    assert [set(r) for r in state_block["roots"]] == [set(bh.PUBLIC_STATE_KEYS)] * 2
    assert set(public["legacySqliteBackup"]) == set(bh.PUBLIC_LEGACY_KEYS)
    # The four keys health-check.yml reads, unchanged.
    for key in ("newestBackupAgeHours", "newestBackupPath", "backupDirUsed", "dbCount"):
        assert key in public


def test_each_root_states_its_own_health_in_the_public_vocabulary(tmp_path, monkeypatch):
    fb = tmp_path / "state_fb"
    make_generation(fb, "2026-10-26", mtime=NOW - 2 * HOUR)
    (tmp_path / "state").mkdir()
    deny_listing(monkeypatch, tmp_path / "state")
    roots = build(tmp_path)["stateBackup"]["roots"]

    canonical, fallback = roots
    assert (canonical["state"], canonical["reason"]) == ("unverifiable", "permission_denied")
    assert canonical["directoryInspected"] == str(tmp_path / "state")
    assert canonical["inspectionReason"] == "canonical_root"
    assert canonical["ageHours"] is None and canonical["evidenceSource"] is None
    assert (fallback["state"], fallback["reason"]) == ("healthy", "within_threshold")
    assert fallback["inspectionReason"] == "writer_fallback_root"
    assert fallback["ageHours"] == 2.0 and fallback["generationCount"] == 1


def test_a_field_added_to_the_detail_later_is_private_until_allow_listed(tmp_path):
    _rich_tree(tmp_path)
    block = detail(tmp_path)["stateBackup"]
    block["somethingNewAndInteresting"] = "x"
    block["roots"][0]["somethingElse"] = "y"
    projected = bh.public_state_backup(block)
    assert "somethingNewAndInteresting" not in projected
    assert "somethingElse" not in projected["roots"][0]


def test_a_probe_failure_projects_to_the_same_public_shape(tmp_path, monkeypatch):
    def boom(**_kw):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(bh, "state_backup_health", boom)
    block = build(tmp_path)["stateBackup"]
    assert set(block) == set(bh.PUBLIC_STATE_KEYS)
    assert (block["state"], block["reason"]) == ("unverifiable", "probe_error")


def _served(monkeypatch, tmp_path, handler):
    """Drive a real handler with the REAL (public) builder over the rich tree."""
    _rich_tree(tmp_path)
    monkeypatch.setattr(server, "_backup_freshness", lambda: build(tmp_path))
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)
    response = asyncio.run(handler())
    return json.loads(response.body)


@pytest.mark.parametrize("handler_name", ["get_health", "get_status"])
def test_the_anonymous_endpoints_serve_no_coverage_detail(monkeypatch, tmp_path, handler_name):
    body = _served(monkeypatch, tmp_path, getattr(server, handler_name))
    served = body["backup_health"]
    assert served["stateBackup"]["state"] == "healthy"  # it really is the rich tree
    assert not (_all_keys(served) & _DETAIL_ONLY_KEYS)
    text = json.dumps(served)
    for marker in _DETAIL_MARKERS:
        assert marker not in text, marker


def test_server_helper_serves_the_public_projection_not_the_detail():
    block = server._backup_freshness_uncached()
    assert not (_all_keys(block) & _DETAIL_ONLY_KEYS)


def test_no_endpoint_serves_the_detail_builder():
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "build_backup_health_detail" not in source
    assert "state_backup_health" not in source


def test_operator_cli_prints_the_full_report(capsys):
    assert bh.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert {"stateBackup", "legacySqliteBackup", "schemaVersion"} <= set(report)


# -- clock skew: a future stamp is not a fresh backup ------------------------
def _write_pointer(root: Path, gen: Path, date: str, promoted_at: str) -> None:
    (root / "last_generation").write_text(
        f"schema=1\neffective_root={root}\ngeneration={gen}\ndate_stamp={date}\n"
        f"artifacts=14\npromoted_at={promoted_at}\n",
        encoding="utf-8",
    )


def test_future_pointer_timestamp_is_clock_skew_not_age_zero(tmp_path):
    root = tmp_path / "state"
    gen = make_generation(root, "2026-10-26", mtime=NOW - HOUR)
    _write_pointer(root, gen, "2026-10-26", "2026-10-27T12:00:00Z")  # a day ahead
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "generation_clock_skew")
    assert out["inspectionReason"] == "newest_generation_untrustworthy"
    assert out["newestGenerationAgeHours"] is None
    public = build(tmp_path)["stateBackup"]
    assert (public["state"], public["reason"], public["ageHours"]) == (
        "unverifiable",
        "generation_clock_skew",
        None,
    )
    assert public["roots"][0]["state"] == "unverifiable"


def test_future_directory_mtime_is_clock_skew_not_healthy(tmp_path):
    make_generation(tmp_path / "state", "2026-10-26", mtime=NOW + 3 * HOUR)
    out = state(tmp_path)
    assert (out["state"], out["reason"]) == ("unverifiable", "generation_clock_skew")
    assert out["newestGenerationAgeHours"] is None


def test_a_stamp_a_moment_ahead_is_a_probe_race_not_skew(tmp_path):
    make_generation(tmp_path / "state", "2026-10-26", mtime=NOW + 60)
    out = state(tmp_path)
    assert (out["state"], out["newestGenerationAgeHours"]) == ("healthy", 0.0)


def test_future_mirror_timestamp_is_reported_as_skew(tmp_path):
    root = tmp_path / "state"
    make_generation(root, "2026-10-26", mtime=NOW - HOUR)
    (root / "last_mirror").write_text(
        "schema=1\nmirrored_at=2026-10-28T06:00:00Z\n", encoding="utf-8"
    )
    mirror = state(tmp_path)["offboxMirror"]
    assert mirror["state"] == "clock_skew" and mirror["ageHours"] is None


def test_future_legacy_file_is_skew_in_the_new_block_but_legacy_keys_are_unchanged(tmp_path):
    make_legacy(tmp_path / "legacy_fallback", mtime=NOW + 5 * HOUR)
    out = build(tmp_path)
    # The legacy top-level keys keep their historical clamp: health-check.yml
    # and the stale-backup alert are calibrated against it.
    assert out["newestBackupAgeHours"] == 0.0
    assert out["dbCount"] == 4
    # The new block refuses to call it fresh.
    legacy = out["legacySqliteBackup"]
    assert (legacy["state"], legacy["reason"], legacy["ageHours"]) == (
        "unverifiable",
        "newest_backup_clock_skew",
        None,
    )


def test_a_non_ascii_digit_artifact_count_is_unknown_not_a_crash(tmp_path):
    root = tmp_path / "state"
    gen = make_generation(root, "2026-10-26", mtime=NOW - HOUR)
    (root / "last_generation").write_text(
        f"schema=1\ngeneration={gen}\nartifacts=²\npromoted_at=2026-10-26T11:00:00Z\n",
        encoding="utf-8",
    )
    out = state(tmp_path)
    assert out["state"] == "healthy"
    assert out["artifactCount"] is None
