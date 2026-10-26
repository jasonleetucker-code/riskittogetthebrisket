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

The pre-existing top-level keys ``newestBackupAgeHours``, ``backupDirUsed`` and
``dbCount`` are kept because ``.github/workflows/health-check.yml`` reads them
from ``/api/status``; they describe the LEGACY backup only and the payload says
so (``legacyKeysDescribe``).  The fourth, ``newestBackupPath``, is a filesystem
path and is PRIVATE (below).

**Public vs private.**  ``/api/health`` and ``/api/status`` are anonymous, and
neither has an authenticated or detail mode, so the block they serve is the
PUBLIC projection only (``build_backup_health``): per root and for the top-level
``stateBackup``, just ``state`` / ``reason`` / ``ageHours`` / ``generationCount``
/ ``directoryRole`` / ``inspectionReason`` / ``evidenceSource``.  The
coverage detail -- which optional stores a generation shed, whether each ledger
is in it and how large, the generation date, the artifact count, the off-box
mirror's age -- is operational intelligence about where the data is NOT
protected.  It is still computed (``build_backup_health_detail`` /
``python -m src.api.backup_health``, for an operator on the box) and is served by
no endpoint; a future admin-gated surface may call the detail builder.

**No filesystem path is public.**  The detail names the directory it inspected
(``directoryInspected``, each root's ``path``) and the newest legacy file
(``newestBackupPath``); the public block carries only the coarse, path-free
``directoryRole`` (``canonical`` / ``writer_fallback``) and the legacy
``backupDirUsed`` label, and says the paths were withheld on purpose
(``filesystemPaths: "withheld"``) so their absence cannot read as "no backup".
The stale-backup alert e-mail, which goes to the operator, still names the file
(``newest_legacy_backup_path``).

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

#: v3: filesystem paths left the public block (``newestBackupPath`` and every
#: ``directoryInspected``); ``directoryRole`` and ``filesystemPaths`` joined it.
SCHEMA_VERSION = "backup-health.v3"

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
#: A stamp this far ahead of "now" is a probe race (the backup landed while we
#: were reading), not a wrong clock; beyond it the age is unknowable and is
#: reported as clock skew rather than clamped to a fresh-looking 0.  Precision
#: slack, not policy.
CLOCK_SKEW_TOLERANCE_SECONDS = 300.0
POINTER_NAME = "last_generation"
MIRROR_MARKER_NAME = "last_mirror"
OPTIONAL_MANIFEST_NAME = "optional_stores.tsv"
#: The two ledgers whose coverage the audit could not confirm (RPA-F-009).
#: Present in a generation as ``sqlite/<name>.gz``.
LEDGER_ARTIFACTS = ("temporal_ledger.sqlite", "intel_ledger.sqlite3")

# -- legacy SQLite backup (mirrors deploy/backup_user_kv.sh) -----------------
LEGACY_PRIMARY_DIR = "/var/backups/riskit/daily"
LEGACY_FALLBACK_DIR = "/home/dynasty/backups/riskit/daily"
#: ``(label, directory)`` in resolution order; the label is ``backupDirUsed``.
LEGACY_DIRS: tuple[tuple[str, str], ...] = (
    ("primary", LEGACY_PRIMARY_DIR),
    ("fallback", LEGACY_FALLBACK_DIR),
)
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
    """Age clamped at 0.  ONLY the legacy top-level keys use this (their
    pre-existing behaviour, which ``health-check.yml`` and the stale-backup
    alert are calibrated against); the new block uses ``_observed_age_hours``."""
    return round(max(0.0, (now_epoch - then_epoch) / 3600.0), 2)


def _observed_age_hours(then_epoch: float, now_epoch: float) -> float | None:
    """Age in hours, or ``None`` when the stamp is in the future.

    A timestamp ahead of this process's clock is a wrong clock somewhere, not a
    backup newer than now; clamping it to 0 would report it as freshly made.
    """
    delta = now_epoch - then_epoch
    if delta < -CLOCK_SKEW_TOLERANCE_SECONDS:
        return None
    return round(max(0.0, delta / 3600.0), 2)


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
        artifact_count = int(raw) if raw.isascii() and raw.isdigit() else None

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
    age = None if epoch is None else _observed_age_hours(epoch, now_epoch)
    return {
        "state": "clock_skew" if epoch is not None and age is None else "recorded",
        "mirroredAt": at if epoch is not None else None,
        "ageHours": age,
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
        basis_epoch, rep["ageBasis"] = promoted, "pointer_promoted_at"
    else:
        basis_epoch, rep["ageBasis"] = gen_stat.st_mtime, "directory_mtime"
    age = _observed_age_hours(basis_epoch, now_epoch)
    if age is None:
        # Stamped in the future: a wrong clock, not a fresh backup.  Never 0.
        rep.update(verdict="unverifiable", reason="generation_clock_skew")
        return rep
    rep["newestGenerationAgeHours"] = age

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
        # The same root as ``directoryInspected``, without the path: the
        # public block carries this one.
        "directoryRole": canonical["role"],
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
        out["directoryRole"] = blocked["role"]
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
        out["directoryRole"] = doubtful["role"]
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
            out["directoryRole"] = reports[-1]["role"]
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
        directoryRole=chosen["role"],
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
    dirs: tuple[tuple[str, str], ...] = LEGACY_DIRS,
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
    observed_age: float | None = None
    db_count: int | None = None
    if newest_epoch is not None and newest_path is not None:
        # ``age`` feeds the legacy top-level keys and keeps its clamp;
        # ``observed_age`` is what the new block's verdict and ageHours say.
        age = _age_hours(newest_epoch, now)
        observed_age = _observed_age_hours(newest_epoch, now)
        parts = os.path.basename(newest_path).split(".")
        stamp = parts[1] if len(parts) >= 3 else ""
        if stamp:
            suffix = f".{stamp}.sqlite.gz"
            db_count = len({n.split(".")[0] for n in newest_dir_entries if n.endswith(suffix)})

    if newest_epoch is not None:
        if observed_age is None:
            state, reason = "unverifiable", "newest_backup_clock_skew"
        else:
            state, reason = _verdict(observed_age)
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
        "ageHours": observed_age,
        "newestBackupAgeHours": age,
        "newestBackupPath": newest_path,
        "backupDirUsed": newest_label,
        "dbCount": db_count,
        "directories": directories,
    }


# -- the payload --------------------------------------------------------------
#: The only keys the PUBLIC state-backup block (top level and each root) may
#: carry.  Everything else ``state_backup_health`` computes is private detail.
PUBLIC_STATE_KEYS = (
    "state",
    "reason",
    "ageHours",
    "generationCount",
    "directoryRole",
    "inspectionReason",
    "evidenceSource",
)
#: ... and the legacy block's (its detail -- per-directory states and file
#: counts -- stays private too).
PUBLIC_LEGACY_KEYS = ("state", "reason", "ageHours")

#: Stated in place of the paths the public block withholds, so a path that is
#: not there reads as policy, never as "no backup".
FILESYSTEM_PATHS_WITHHELD = "withheld"

_ROLE_INSPECTION_REASON = {
    "canonical": "canonical_root",
    "writer_fallback": "writer_fallback_root",
}

# -- the public value vocabulary ----------------------------------------------
#: Every value an enumerated field of the PUBLIC block may take.  Closed on
#: both sides: ``tests/api/test_backup_health.py`` drives every branch and fails
#: on a value missing here AND on a value listed here that no branch produces.
PUBLIC_STATES = frozenset({"healthy", "stale", "missing", "unverifiable"})
PUBLIC_REASONS = frozenset(
    {
        # a located backup (``_verdict``)
        "within_threshold",
        "older_than_threshold",
        # ``_verdict(None)``: defensive -- every caller passes an observed age
        "age_unknown",
        # a directory this process may not list (``_classify_oserror``)
        "permission_denied",
        "io_error",
        # nothing located
        "directory_not_found",
        "no_generations",
        "no_backups",
        # located, but not trustworthy
        "generation_unresolvable",
        "generation_clock_skew",
        "newest_backup_clock_skew",
        # the probe itself failed (``_probe_failed``)
        "probe_error",
    }
)
PUBLIC_INSPECTION_REASONS = frozenset(
    {
        *_ROLE_INSPECTION_REASON.values(),
        "canonical_root_unreadable",
        "writer_fallback_root_unreadable",
        "newest_generation_untrustworthy",
        "no_candidate_root_exists",
        "canonical_root_absent_writer_fallback",
        "canonical_root_empty_writer_fallback",
        "writer_fallback_root_newer",
    }
)
PUBLIC_EVIDENCE_SOURCES = frozenset({"directory_listing"})
PUBLIC_DIRECTORY_ROLES = frozenset(_ROLE_INSPECTION_REASON)
PUBLIC_LEGACY_DIR_LABELS = frozenset({label for label, _ in LEGACY_DIRS} | {"none"})
PUBLIC_VALUE_VOCABULARY: dict[str, frozenset[str]] = {
    "schemaVersion": frozenset({SCHEMA_VERSION}),
    "state": PUBLIC_STATES,
    "reason": PUBLIC_REASONS,
    "inspectionReason": PUBLIC_INSPECTION_REASONS,
    "evidenceSource": PUBLIC_EVIDENCE_SOURCES,
    "directoryRole": PUBLIC_DIRECTORY_ROLES,
    "backupDirUsed": PUBLIC_LEGACY_DIR_LABELS,
    "legacyKeysDescribe": frozenset({"legacySqliteBackup"}),
    "filesystemPaths": frozenset({FILESYSTEM_PATHS_WITHHELD}),
}
#: Enumerated fields that may be ``None``: not observed, or not applicable
#: (no evidence for an unverifiable root; no root when the probe itself
#: failed).  Every other enumerated field always carries a listed value.
PUBLIC_NULLABLE_FIELDS = frozenset({"evidenceSource", "inspectionReason", "directoryRole"})


def _public_root(rep: dict[str, Any]) -> dict[str, Any]:
    """One root's own health, in the same vocabulary as the top-level block."""
    verdict = rep.get("verdict")
    age: float | None = None
    evidence: str | None = None
    if verdict == "generation":
        age = rep.get("newestGenerationAgeHours")
        state, reason = _verdict(age)
        evidence = "directory_listing"
    elif verdict in ("unreadable", "unverifiable"):
        state, reason = "unverifiable", rep.get("reason")
    elif verdict == "none":
        state, reason = "missing", "no_generations"
    else:  # absent
        state, reason = "missing", "directory_not_found"
    return {
        "state": state,
        "reason": reason,
        "ageHours": age,
        "generationCount": rep.get("generationCount"),
        "directoryRole": rep.get("role"),
        "inspectionReason": _ROLE_INSPECTION_REASON.get(rep.get("role")),
        "evidenceSource": evidence,
    }


def public_state_backup(detail: dict[str, Any]) -> dict[str, Any]:
    """The anonymous-safe projection of ``state_backup_health``.

    An allow-list, not a deny-list: a field added to the detail later is
    private until someone adds it here on purpose.
    """
    out = {
        "state": detail.get("state"),
        "reason": detail.get("reason"),
        "ageHours": detail.get("newestGenerationAgeHours"),
        "generationCount": detail.get("generationCount"),
        "directoryRole": detail.get("directoryRole"),
        "inspectionReason": detail.get("inspectionReason"),
        "evidenceSource": detail.get("evidenceSource"),
    }
    roots = detail.get("roots")
    if isinstance(roots, list):
        out["roots"] = [_public_root(r) for r in roots if isinstance(r, dict)]
    return out


def public_legacy_backup(detail: dict[str, Any]) -> dict[str, Any]:
    """The anonymous-safe projection of ``legacy_sqlite_backup_health``."""
    return {key: detail.get(key) for key in PUBLIC_LEGACY_KEYS}


def _probe_failed(name: str, describes: str) -> dict[str, Any]:
    return {"name": name, "describes": describes, "state": "unverifiable", "reason": "probe_error"}


def _guarded(builder: Callable[[], dict[str, Any]], name: str, describes: str) -> dict[str, Any]:
    # A monitoring helper must never take /api/health down with it.
    try:
        return builder()
    except Exception:  # noqa: BLE001
        return _probe_failed(name, describes)


def build_backup_health_detail(
    *,
    state_root: str = STATE_BACKUP_ROOT,
    state_fallback_root: str = STATE_BACKUP_FALLBACK_ROOT,
    legacy_dirs: tuple[tuple[str, str], ...] | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """The FULL backup-health report, coverage detail included.

    PRIVATE: no anonymous endpoint may serve this (see the module docstring).
    ``build_backup_health`` is the public projection of it.
    """
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
        # LEGACY backup only; the state backup is ``stateBackup``.  The public
        # block drops ``newestBackupPath`` (a filesystem path).
        "newestBackupAgeHours": legacy.get("newestBackupAgeHours"),
        "newestBackupPath": legacy.get("newestBackupPath"),
        "backupDirUsed": legacy.get("backupDirUsed", "none"),
        "dbCount": legacy.get("dbCount"),
        "legacyKeysDescribe": "legacySqliteBackup",
        "legacySqliteBackup": legacy,
        "stateBackup": state,
    }


def build_backup_health(
    *,
    state_root: str = STATE_BACKUP_ROOT,
    state_fallback_root: str = STATE_BACKUP_FALLBACK_ROOT,
    legacy_dirs: tuple[tuple[str, str], ...] | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """The ``backup_health`` block served by ``/api/health`` and ``/api/status``.

    Anonymous-safe: the detail is projected away (``PUBLIC_*_KEYS``), and so is
    every filesystem path -- ``newestBackupPath`` stays in the detail, and
    ``filesystemPaths`` says it was withheld rather than not found.
    """
    detail = build_backup_health_detail(
        state_root=state_root,
        state_fallback_root=state_fallback_root,
        legacy_dirs=legacy_dirs,
        now_epoch=now_epoch,
    )
    return {
        "schemaVersion": detail["schemaVersion"],
        "newestBackupAgeHours": detail["newestBackupAgeHours"],
        "backupDirUsed": detail["backupDirUsed"],
        "dbCount": detail["dbCount"],
        "legacyKeysDescribe": detail["legacyKeysDescribe"],
        "filesystemPaths": FILESYSTEM_PATHS_WITHHELD,
        "legacySqliteBackup": public_legacy_backup(detail["legacySqliteBackup"]),
        "stateBackup": public_state_backup(detail["stateBackup"]),
    }


def newest_legacy_backup_path(
    *,
    dirs: tuple[tuple[str, str], ...] = LEGACY_DIRS,
    now_epoch: float | None = None,
) -> str | None:
    """PRIVATE: the newest legacy ``*.sqlite.gz`` file, or ``None`` when none
    was observed.

    For the operator's stale-backup alert e-mail (``server.get_health``) only;
    no endpoint serves it.
    """
    return legacy_sqlite_backup_health(dirs=dirs, now_epoch=now_epoch).get("newestBackupPath")


def main() -> int:
    """Print the FULL report (operator on the box; run as root to see the
    root-only state directory)."""
    import json

    print(json.dumps(build_backup_health_detail(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
