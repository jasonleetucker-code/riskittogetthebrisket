"""Backup health -- what this process can honestly say about the backups.

There are TWO backups on the box, written by two different units into two
different places, and ``/api/health`` used to report only one of them while
naming it "the backup":

* the **state backup** -- ``riskit-state-backup.service`` (nightly 02:30 UTC,
  ``deploy/backup/riskit-state-backup.sh``).  Every irreplaceable store: the
  SQLite ledgers, the scraper sessions, the box-local evidence directories.
  Writes dated generations under ``/var/backups/riskit-state/daily/`` -- a
  root-only (0700) directory, so the backend user (``dynasty``) cannot list it.
* the **legacy SQLite backup** -- ``riskit-backup.timer``
  (``deploy/backup_user_kv.sh``): ``user_kv`` / ``session_store`` /
  ``guest_passes`` and the rookie-auction store, as ``<name>.<date>.sqlite.gz``
  under ``/var/backups/riskit/daily`` or, when that needs root, the
  dynasty-owned ``/home/dynasty/backups/riskit/daily``.

The old stamp scanned only the legacy directories, so on production it
answered ``backupDirUsed: "fallback"`` -- a healthy-looking age for a job that
is NOT the state backup -- while the state backup's real coverage was invisible
from the app.  This module keeps the two apart, names each, and says what it
could not see:

* ``stateBackup``       -- the canonical state-backup root.  A root that
  exists but cannot be listed by this process is ``unverifiable`` /
  ``permission_denied``: never healthy, and never missing (it is there; we
  are not allowed to look).
* ``legacySqliteBackup`` -- the legacy directories, under their own name.

Missing is never zero.  An age or count that was not observed is ``None``.

The four pre-existing top-level keys (``newestBackupAgeHours``,
``newestBackupPath``, ``backupDirUsed``, ``dbCount``) are kept because
``.github/workflows/health-check.yml`` reads them from ``/api/status``; they
describe the LEGACY backup only and the payload says so
(``legacyKeysDescribe``).

Reporting only.  Nothing here changes ``/api/health``'s status code, ``is_ok``
or the alert the endpoint sends.

``deploy/backup/backup_root_lib.sh`` is the single owner of "where does the
state backup live"; the constants below mirror its defaults and
``tests/api/test_backup_health.py`` fails if they drift.
"""

from __future__ import annotations

import errno
import fnmatch
import os
import re
import stat as stat_mod
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

SCHEMA_VERSION = "backup-health.v2"

#: Newest backup older than this is ``stale``.  Same figure the alert in
#: ``server.get_health`` uses ("anything older than 36h"): a nightly job that
#: has not landed in a day and a half has missed a run.
STALE_AFTER_HOURS = 36.0

# -- state backup (mirrors deploy/backup/backup_root_lib.sh) -----------------
STATE_BACKUP_ROOT = "/var/backups/riskit-state"
STATE_BACKUP_FALLBACK_ROOT = "/home/dynasty/backups/riskit-state"
#: A generation dated further ahead than this is a wrong clock, not a newer
#: backup (``BACKUP_ROOT_FUTURE_TOLERANCE_DAYS``).
FUTURE_TOLERANCE_DAYS = 1
POINTER_NAME = "last_generation"
MIRROR_MARKER_NAME = "last_mirror"
OPTIONAL_MANIFEST_NAME = "optional_stores.tsv"
#: The two ledgers whose coverage the audit could not confirm (RPA-F-009).
#: Present in a generation as ``sqlite/<name>.gz``.
LEDGER_ARTIFACTS = ("temporal_ledger.sqlite", "intel_ledger.sqlite3")

# -- legacy SQLite backup (mirrors deploy/backup_user_kv.sh) -----------------
LEGACY_PRIMARY_DIR = "/var/backups/riskit/daily"
LEGACY_FALLBACK_DIR = "/home/dynasty/backups/riskit/daily"
_LEGACY_PATTERN = "*.sqlite.gz"

_DATED_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STATE_BACKUP_DESCRIBES = (
    "riskit-state-backup.service nightly generation (deploy/backup/riskit-state-backup.sh)"
)
LEGACY_DESCRIBES = (
    "riskit-backup.timer nightly SQLite backup of user_kv, session_store, "
    "guest_passes and the rookie-auction store (deploy/backup_user_kv.sh) -- "
    "NOT the state backup"
)


# -- filesystem seams ---------------------------------------------------------
# Every filesystem touch goes through one of these so a test can make a path
# unreadable (a 0700 root-owned directory cannot be built portably, and a test
# run as root would read it anyway).
def _stat(path: str) -> os.stat_result:
    return os.stat(path)


def _listdir(path: str) -> list[str]:
    return os.listdir(path)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read(65536)


def _classify_oserror(exc: OSError) -> tuple[str, str]:
    """``(state, reason)`` for a failed stat/list.

    ENOENT and EACCES are different facts and must never be conflated: a
    directory that is not there is ``absent``; one that is there but closed to
    this process is ``unreadable``.
    """
    if isinstance(exc, PermissionError) or exc.errno in (errno.EACCES, errno.EPERM):
        return "unreadable", "permission_denied"
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return "absent", "not_found"
    if isinstance(exc, NotADirectoryError) or exc.errno == errno.ENOTDIR:
        return "absent", "not_a_directory"
    return "unreadable", "io_error"


def _probe_dir(path: str) -> dict[str, Any]:
    """Can this process stat AND list ``path``?

    ``state`` is ``readable`` / ``absent`` / ``unreadable``.  ``entries`` is
    the directory listing when readable, else ``None``.
    """
    try:
        st = _stat(path)
    except OSError as exc:
        state, reason = _classify_oserror(exc)
        return {"state": state, "reason": reason, "entries": None}
    if not stat_mod.S_ISDIR(st.st_mode):
        return {"state": "absent", "reason": "not_a_directory", "entries": None}
    try:
        entries = _listdir(path)
    except OSError as exc:
        state, reason = _classify_oserror(exc)
        return {"state": state, "reason": reason, "entries": None}
    return {"state": "readable", "reason": None, "entries": entries}


def _read_kv(path: str) -> dict[str, str] | None:
    """Parse a ``KEY=VALUE`` file (first ``=`` splits, first key wins, nothing
    is evaluated).  ``None`` when absent or unreadable."""
    try:
        text = _read_text(path)
    except OSError:
        return None
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        out.setdefault(key.strip(), value.strip())
    return out


def _parse_utc(stamp: str) -> float | None:
    try:
        return (
            datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        )
    except (TypeError, ValueError):
        return None


def _age_hours(then_epoch: float, now_epoch: float) -> float:
    return round(max(0.0, (now_epoch - then_epoch) / 3600.0), 2)


def _verdict(age_hours: float | None) -> tuple[str, str]:
    """``(state, reason)`` for a located backup of the given age."""
    if age_hours is None:
        return "unverifiable", "age_unknown"
    if age_hours > STALE_AFTER_HOURS:
        return "stale", "older_than_threshold"
    return "healthy", "within_threshold"


# -- state backup -------------------------------------------------------------
def _coverage(gen_path: str, pointer_matches: bool, pointer: dict | None) -> dict:
    """What the newest generation positively contains.

    Every field is ``None`` when it could not be observed -- an absent manifest
    is NOT evidence that nothing was shed (an older root-owned writer copy
    never wrote one), so the ledger artifacts are checked directly.
    """
    artifact_count: int | None = None
    if pointer_matches and pointer is not None:
        raw = pointer.get("artifacts", "")
        artifact_count = int(raw) if raw.isdigit() else None

    manifest_path = os.path.join(gen_path, OPTIONAL_MANIFEST_NAME)
    optional: dict[str, Any] = {"manifest": "unreadable", "notInGeneration": None}
    try:
        text = _read_text(manifest_path)
    except FileNotFoundError:
        # The writer appends a row only for an optional store that is NOT in
        # the generation, so no file means "none recorded" -- not "all present".
        optional = {"manifest": "absent", "notInGeneration": None}
    except OSError:
        pass
    else:
        rows = []
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].strip():
                rows.append({"name": parts[0].strip(), "status": parts[1].strip()})
        optional = {"manifest": "present", "notInGeneration": rows}

    ledgers: dict[str, Any] = {}
    for name in LEDGER_ARTIFACTS:
        artifact = os.path.join(gen_path, "sqlite", f"{name}.gz")
        try:
            size = _stat(artifact).st_size
        except FileNotFoundError:
            ledgers[name] = {"present": False, "sizeBytes": None}
        except OSError:
            ledgers[name] = {"present": None, "sizeBytes": None}
        else:
            ledgers[name] = {"present": True, "sizeBytes": size}

    return {"artifactCount": artifact_count, "optionalStores": optional, "ledgers": ledgers}


def _offbox_mirror(root: str, now_epoch: float) -> dict[str, Any]:
    """The off-box mirror as recorded in ``<root>/last_mirror``.

    The destination is deliberately never reported (it can carry a host and a
    user).  ``none_recorded`` means this readable root holds no mirror marker:
    no mirror has ever completed from here.
    """
    marker = _read_kv(os.path.join(root, MIRROR_MARKER_NAME))
    if marker is None:
        if os.path.exists(os.path.join(root, MIRROR_MARKER_NAME)):
            return {"state": "unverifiable", "mirroredAt": None, "ageHours": None}
        return {"state": "none_recorded", "mirroredAt": None, "ageHours": None}
    at = marker.get("mirrored_at")
    epoch = _parse_utc(at) if at else None
    return {
        "state": "recorded",
        "mirroredAt": at if epoch is not None else None,
        "ageHours": None if epoch is None else _age_hours(epoch, now_epoch),
    }


def _inspect_state_root(path: str, role: str, now_epoch: float) -> dict[str, Any]:
    """Everything observable about one candidate state-backup root.

    ``verdict`` is one of ``absent`` / ``unreadable`` / ``none`` (readable,
    holds no dated generation) / ``unverifiable`` (readable, but the newest
    entry cannot be trusted) / ``generation``.
    """
    rep: dict[str, Any] = {
        "role": role,
        "path": path,
        "state": None,
        "reason": None,
        "blockedAt": None,
        "verdict": None,
        "generationCount": None,
        "newestGeneration": None,
        "newestGenerationAgeHours": None,
        "ageBasis": None,
        "artifactCount": None,
        "optionalStores": None,
        "ledgers": None,
        "offboxMirror": None,
    }
    root = _probe_dir(path)
    rep["state"], rep["reason"] = root["state"], root["reason"]
    if root["state"] != "readable":
        rep["verdict"] = "absent" if root["state"] == "absent" else "unreadable"
        rep["blockedAt"] = path if root["state"] == "unreadable" else None
        return rep

    daily_path = os.path.join(path, "daily")
    daily = _probe_dir(daily_path)
    if daily["state"] == "unreadable":
        # The root and daily/ are permissioned independently, so a listable
        # root with a closed daily/ is still a root we cannot see into.
        rep.update(state="unreadable", reason=daily["reason"], blockedAt=daily_path)
        rep["verdict"] = "unreadable"
        return rep
    if daily["state"] == "absent":
        rep["generationCount"] = 0
        rep["verdict"] = "none"
        return rep

    dated = sorted((n for n in daily["entries"] if _DATED_NAME.match(n)), reverse=True)
    rep["generationCount"] = len(dated)
    if not dated:
        rep["verdict"] = "none"
        return rep

    # Newest-first, and an unresolvable NEWEST entry stops the walk: it may
    # itself be the newer generation, so falling back to an older sibling would
    # be a substitution (same rule as backup_root_scan_generation).
    name = dated[0]
    gen_path = os.path.join(path, "daily", name)
    rep["newestGeneration"] = name
    try:
        gen_stat = _stat(gen_path)
    except OSError:
        rep.update(verdict="unverifiable", reason="generation_unresolvable")
        return rep
    if not stat_mod.S_ISDIR(gen_stat.st_mode):
        rep.update(verdict="unverifiable", reason="generation_unresolvable")
        return rep
    latest_plausible = (
        datetime.fromtimestamp(now_epoch, tz=timezone.utc).date()
        + timedelta(days=FUTURE_TOLERANCE_DAYS)
    ).isoformat()
    if name > latest_plausible:
        rep.update(verdict="unverifiable", reason="generation_clock_skew")
        return rep

    pointer = _read_kv(os.path.join(path, POINTER_NAME))
    pointer_matches = bool(
        pointer
        and pointer.get("schema") == "1"
        and os.path.normpath(pointer.get("generation", "")) == os.path.normpath(gen_path)
    )
    promoted = _parse_utc(pointer.get("promoted_at", "")) if pointer_matches and pointer else None
    if promoted is not None:
        rep["newestGenerationAgeHours"] = _age_hours(promoted, now_epoch)
        rep["ageBasis"] = "pointer_promoted_at"
    else:
        rep["newestGenerationAgeHours"] = _age_hours(gen_stat.st_mtime, now_epoch)
        rep["ageBasis"] = "directory_mtime"

    rep["verdict"] = "generation"
    rep.update(_coverage(gen_path, pointer_matches, pointer))
    rep["offboxMirror"] = _offbox_mirror(path, now_epoch)
    return rep


def state_backup_health(
    *,
    root: str = STATE_BACKUP_ROOT,
    fallback_root: str = STATE_BACKUP_FALLBACK_ROOT,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Health of the nightly state backup, from what this process can read.

    Resolution mirrors the writer: the canonical root, then the service-user
    fallback it falls back to when the canonical root is not writable.  A root
    that exists but is closed to this process makes the whole answer
    ``unverifiable`` -- a newer generation may sit behind the closed door, so
    certifying an older one from the other root would be a fail-open.
    """
    now = time.time() if now_epoch is None else now_epoch
    reports = [_inspect_state_root(root, "canonical", now)]
    if os.path.normpath(fallback_root) != os.path.normpath(root):
        reports.append(_inspect_state_root(fallback_root, "writer_fallback", now))
    canonical = reports[0]

    out: dict[str, Any] = {
        "name": "state_backup",
        "describes": STATE_BACKUP_DESCRIBES,
        "state": None,
        "reason": None,
        "evidenceSource": None,
        "directoryInspected": root,
        "inspectionReason": None,
        "canonicalRoot": root,
        "staleAfterHours": STALE_AFTER_HOURS,
        "newestGeneration": None,
        "newestGenerationAgeHours": None,
        "ageBasis": None,
        "generationCount": None,
        "artifactCount": None,
        "optionalStores": None,
        "ledgers": None,
        "offboxMirror": None,
        "roots": reports,
    }

    blocked = next((r for r in reports if r["verdict"] == "unreadable"), None)
    if blocked is not None:
        out.update(state="unverifiable", reason=blocked["reason"])
        out["directoryInspected"] = blocked["path"]
        out["inspectionReason"] = (
            "canonical_root_unreadable"
            if blocked["role"] == "canonical"
            else "writer_fallback_root_unreadable"
        )
        return out

    doubtful = next((r for r in reports if r["verdict"] == "unverifiable"), None)
    if doubtful is not None:
        out.update(state="unverifiable", reason=doubtful["reason"])
        out["directoryInspected"] = doubtful["path"]
        out["inspectionReason"] = "newest_generation_untrustworthy"
        return out

    located = [r for r in reports if r["verdict"] == "generation"]
    if not located:
        gone = all(r["verdict"] == "absent" for r in reports)
        if gone:
            why = "no_candidate_root_exists"
        elif canonical["verdict"] == "none":
            why = "canonical_root"
        else:
            why = "writer_fallback_root"
            out["directoryInspected"] = reports[-1]["path"]
        observed = [r["generationCount"] for r in reports if r["verdict"] == "none"]
        out.update(
            state="missing",
            reason="directory_not_found" if gone else "no_generations",
            inspectionReason=why,
            generationCount=observed[0] if observed else None,
        )
        return out

    # Newest wins; the canonical root wins a tie.
    chosen = min(located, key=lambda r: (r["newestGenerationAgeHours"], r["role"] != "canonical"))
    if chosen["role"] == "canonical":
        why = "canonical_root"
    elif canonical["verdict"] == "absent":
        why = "canonical_root_absent_writer_fallback"
    elif canonical["verdict"] == "none":
        why = "canonical_root_empty_writer_fallback"
    else:
        why = "writer_fallback_root_newer"
    state, reason = _verdict(chosen["newestGenerationAgeHours"])
    out.update(
        state=state,
        reason=reason,
        evidenceSource="directory_listing",
        directoryInspected=chosen["path"],
        inspectionReason=why,
        newestGeneration=chosen["newestGeneration"],
        newestGenerationAgeHours=chosen["newestGenerationAgeHours"],
        ageBasis=chosen["ageBasis"],
        generationCount=chosen["generationCount"],
        artifactCount=chosen["artifactCount"],
        optionalStores=chosen["optionalStores"],
        ledgers=chosen["ledgers"],
        offboxMirror=chosen["offboxMirror"],
    )
    return out


# -- legacy SQLite backup -----------------------------------------------------
def legacy_sqlite_backup_health(
    *,
    dirs: tuple[tuple[str, str], ...] = (
        ("primary", LEGACY_PRIMARY_DIR),
        ("fallback", LEGACY_FALLBACK_DIR),
    ),
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """The legacy ``*.sqlite.gz`` backups, reported under their own name.

    Same newest-file rule the stamp always used (primary wins a tie), now with
    each directory's own state beside it.
    """
    now = time.time() if now_epoch is None else now_epoch
    directories: list[dict[str, Any]] = []
    newest_epoch: float | None = None
    newest_path: str | None = None
    newest_label = "none"
    newest_dir_entries: list[str] = []

    for label, path in dirs:
        probe = _probe_dir(path)
        entry: dict[str, Any] = {
            "label": label,
            "path": path,
            "state": probe["state"],
            "reason": probe["reason"],
            "backupFileCount": None,
        }
        directories.append(entry)
        if probe["state"] != "readable":
            continue
        names = [n for n in probe["entries"] if fnmatch.fnmatch(n, _LEGACY_PATTERN)]
        entry["backupFileCount"] = len(names)
        for name in names:
            full = os.path.join(path, name)
            try:
                mtime = _stat(full).st_mtime
            except OSError:
                continue
            if newest_epoch is None or mtime > newest_epoch:
                newest_epoch = mtime
                newest_path = full
                newest_label = label
                newest_dir_entries = probe["entries"]

    age: float | None = None
    db_count: int | None = None
    if newest_epoch is not None and newest_path is not None:
        age = _age_hours(newest_epoch, now)
        parts = os.path.basename(newest_path).split(".")
        stamp = parts[1] if len(parts) >= 3 else ""
        if stamp:
            suffix = f".{stamp}.sqlite.gz"
            db_count = len({n.split(".")[0] for n in newest_dir_entries if n.endswith(suffix)})

    if newest_epoch is not None:
        state, reason = _verdict(age)
    else:
        unreadable = next((d for d in directories if d["state"] == "unreadable"), None)
        if unreadable is not None:
            state, reason = "unverifiable", unreadable["reason"]
        elif any(d["state"] == "readable" for d in directories):
            state, reason = "missing", "no_backups"
        else:
            state, reason = "missing", "directory_not_found"

    return {
        "name": "legacy_sqlite_backup",
        "describes": LEGACY_DESCRIBES,
        "state": state,
        "reason": reason,
        "staleAfterHours": STALE_AFTER_HOURS,
        "newestBackupAgeHours": age,
        "newestBackupPath": newest_path,
        "backupDirUsed": newest_label,
        "dbCount": db_count,
        "directories": directories,
    }


# -- the payload --------------------------------------------------------------
def _probe_failed(name: str, describes: str) -> dict[str, Any]:
    return {"name": name, "describes": describes, "state": "unverifiable", "reason": "probe_error"}


def _guarded(builder: Callable[[], dict[str, Any]], name: str, describes: str) -> dict[str, Any]:
    # A monitoring helper must never take /api/health down with it.
    try:
        return builder()
    except Exception:  # noqa: BLE001
        return _probe_failed(name, describes)


def build_backup_health(
    *,
    state_root: str = STATE_BACKUP_ROOT,
    state_fallback_root: str = STATE_BACKUP_FALLBACK_ROOT,
    legacy_dirs: tuple[tuple[str, str], ...] | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """The ``backup_health`` block served by ``/api/health`` and ``/api/status``."""
    now = time.time() if now_epoch is None else now_epoch
    legacy_kwargs: dict[str, Any] = {"now_epoch": now}
    if legacy_dirs is not None:
        legacy_kwargs["dirs"] = legacy_dirs
    legacy = _guarded(
        lambda: legacy_sqlite_backup_health(**legacy_kwargs),
        "legacy_sqlite_backup",
        LEGACY_DESCRIBES,
    )
    state = _guarded(
        lambda: state_backup_health(
            root=state_root, fallback_root=state_fallback_root, now_epoch=now
        ),
        "state_backup",
        STATE_BACKUP_DESCRIBES,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        # Pre-existing keys, kept for health-check.yml.  They describe the
        # LEGACY backup only; the state backup is ``stateBackup``.
        "newestBackupAgeHours": legacy.get("newestBackupAgeHours"),
        "newestBackupPath": legacy.get("newestBackupPath"),
        "backupDirUsed": legacy.get("backupDirUsed", "none"),
        "dbCount": legacy.get("dbCount"),
        "legacyKeysDescribe": "legacySqliteBackup",
        "legacySqliteBackup": legacy,
        "stateBackup": state,
    }
