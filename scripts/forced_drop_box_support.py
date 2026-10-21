"""Support for ``scripts/forced_drop_fix_replay.py --box`` — stdlib only, import-light.

The production-box replay of the forced-drop fix (record
``docs/trade/FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md``) is READ-ONLY and
publishes AGGREGATES ONLY into a public repository.  This module holds the parts
of that contract that can be tested without the application: the resource caps,
the pin verification and the output-safety check.  The audit-hook write /
network / process guard is ``scripts/research_readonly_guard.py`` (installed by
the replay script before any application import).

Exit codes of the box replay (``EXIT_*``): 0 ok, 2 an input pin did not match
(nothing measured), 3 the guard refused a write / process start, 4 the output
was refused as not aggregate-only (nothing printed), 5 a resource cap stopped
the run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import signal
from pathlib import Path
from typing import Any, Iterable, Mapping

EXIT_OK = 0
EXIT_PIN_MISMATCH = 2
EXIT_GUARD_REFUSED = 3
EXIT_OUTPUT_REFUSED = 4
EXIT_RESOURCE_CAP = 5

#: Same identifier shapes the research scripts refuse
#: (``package_model_phase2_research._ID_LIKE``), plus the ids a replay of
#: rosters could leak: Sleeper numeric ids (9+ digits), canonical asset ids.
ID_LIKE = re.compile(
    r"\d{9,}|utrade:|player:|mpick:|pick:|hostLeagueId|leagueId|ownerId|userId|rosterId"
)
#: Keys that name an identifier or a person / team, whatever their value.
FORBIDDEN_KEY = re.compile(
    r"(?i)^(leagueId|ownerId|userId|rosterId|sleeperLeagueId|hostLeagueId|username|userName|"
    r"displayName|teamName|managerName|ownerName|playerId|sleeperId|playerIds|transactionId|"
    r"txId|email)$"
)
HEX_LONG = re.compile(r"\b[0-9a-fA-F]{32,}\b")
#: The only keys whose value may be a long hex digest (a pin, not an identity).
PROVENANCE_HEX_KEYS = frozenset(
    {
        "sha256",
        "archiveSha256",
        "builtBoardSha256",
        "contentSha256",
        "csvTreeSha256",
        "deployedCodeSha",
        "codeSha",
        "revisionSha",
        "csvRev",
        "configSha256",
        "expectedBoardSha256",
        "archiveMemberSha256",
        "expectedArchiveMemberSha256",
        "expectedArchiveSha256",
        "expectedCsvTreeSha256",
        "expectedCodeSha",
    }
)
MAX_STRING = 700  # a longer string is a dumped payload, not an aggregate note
MIN_FORBIDDEN_TOKEN = 5


class OutputRefused(ValueError):
    """The box output is not aggregate-only.  The message never carries the
    offending value (the report goes to a public repository)."""


# ── output safety ────────────────────────────────────────────────────────


def forbidden_tokens(contract: Mapping[str, Any]) -> set[str]:
    """Identifier / team / manager strings of the loaded contract that must not
    appear anywhere in the output: Sleeper ids, owner and team names, usernames.
    Read at run time from the contract itself, so the check is exact for the
    league that was replayed."""
    out: set[str] = set()
    sleeper = (contract or {}).get("sleeper") or {}
    for key in ("leagueId", "sleeperLeagueId", "draftId"):
        v = sleeper.get(key)
        if isinstance(v, (str, int)) and len(str(v)) >= MIN_FORBIDDEN_TOKEN:
            out.add(str(v))
    for team in sleeper.get("teams") or []:
        if not isinstance(team, Mapping):
            continue
        for key in (
            "name",
            "teamName",
            "ownerId",
            "ownerName",
            "username",
            "userName",
            "displayName",
            "rosterId",
            "userId",
            "avatar",
        ):
            v = team.get(key)
            if isinstance(v, (str, int)) and len(str(v)) >= MIN_FORBIDDEN_TOKEN:
                out.add(str(v))
    return out


def assert_box_output_safe(
    result: Any, *, forbidden: Iterable[str] = (), _path: str = "$", _prov_key: str | None = None
) -> None:
    """Refuse anything that is not an aggregate.

    * keys naming an identifier / person / team (``FORBIDDEN_KEY``) or matching
      an id shape;
    * any string with an id shape, a 32+ hex run outside the explicit
      provenance-digest keys (and there it must be pure hex of a known width),
      or longer than ``MAX_STRING``;
    * any string containing a ``forbidden`` token (the replayed league's ids,
      team and owner names) — a hit is reported by COUNT and path, never value.
    """
    forbidden = tuple(sorted({t for t in forbidden if len(str(t)) >= MIN_FORBIDDEN_TOKEN}))
    _walk(result, forbidden, _path, None)


def _walk(obj: Any, forbidden: tuple[str, ...], path: str, key: str | None) -> None:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            ks = str(k)
            if key in PROVENANCE_HEX_KEYS and isinstance(v, str):
                # a {config path: digest} map: the digest must be pure hex of a
                # known width, the path is only a label.
                if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64}|UNKNOWN|NOT_PROVIDED)", v):
                    raise OutputRefused(f"provenance digest malformed at {path}")
                continue
            if FORBIDDEN_KEY.match(ks) or ID_LIKE.search(ks):
                raise OutputRefused(f"identifier-like key at {path}")
            if any(t in ks for t in forbidden):
                raise OutputRefused(f"forbidden token in a key at {path}")
            _walk(v, forbidden, f"{path}.{ks}", ks)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk(v, forbidden, f"{path}[{i}]", key)
    elif isinstance(obj, str):
        if key in PROVENANCE_HEX_KEYS:
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64}|UNKNOWN|NOT_PROVIDED)", obj):
                raise OutputRefused(f"provenance digest malformed at {path}")
            return
        if len(obj) > MAX_STRING:
            raise OutputRefused(f"over-long string at {path}")
        if ID_LIKE.search(obj):
            raise OutputRefused(f"identifier-like value at {path}")
        if HEX_LONG.search(obj):
            raise OutputRefused(f"unexpected digest-like value at {path}")
        for t in forbidden:
            if t in obj:
                raise OutputRefused(f"a replayed league / team / owner token appears at {path}")


# ── pins ─────────────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_content_sha256(root: Path, paths: Iterable[str]) -> str:
    """sha256 over (relative path, sha256 of bytes) of every file under
    ``paths`` — byte-for-byte the digest ``forced_drop_fix_replay._tree_content_sha256``
    records, so a materialised tree can be compared with the committed one."""
    h = hashlib.sha256()
    for top in paths:
        base = root / top
        if not base.exists():
            continue
        for p in sorted(x for x in base.rglob("*") if x.is_file()):
            h.update(p.relative_to(root).as_posix().encode() + b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def config_hashes(app_dir: Path, rel_paths: Iterable[str]) -> dict[str, str]:
    """sha256 of each config file the verdict depends on (``NOT_PROVIDED`` when
    absent — recorded, never guessed)."""
    out: dict[str, str] = {}
    for rel in rel_paths:
        p = app_dir / rel
        out[rel] = sha256_file(p) if p.is_file() else "NOT_PROVIDED"
    return out


def pin_mismatches(
    observed: Mapping[str, str | None], expected: Mapping[str, str | None]
) -> list[str]:
    """Names of the pins whose observed value differs from the expected one.
    An expected value of ``None`` is not checked; an observed ``None`` against a
    given expectation IS a mismatch (an unreadable pin is not a match)."""
    bad = []
    for name, want in expected.items():
        if want is None:
            continue
        if observed.get(name) != want:
            bad.append(name)
    return sorted(bad)


# ── arguments ────────────────────────────────────────────────────────────


def validate_box_args(ns: Any) -> list[str]:
    """The refusals of ``--box`` mode (empty list = accepted).  Box mode never
    writes a file (the guard would refuse it anyway), so ``--out`` is an error,
    and it requires every pin the runbook names."""
    problems = []
    if getattr(ns, "out", None) not in (None, ""):
        problems.append("--out is not supported with --box (the report goes to stdout)")
    for flag in (
        "archive",
        "archive_sha256",
        "csv_root",
        "csv_rev",
        "csv_tree_sha256",
        "expect_code_sha",
    ):
        if not getattr(ns, flag, None):
            problems.append(f"--{flag.replace('_', '-')} is required with --box")
    root = getattr(ns, "csv_root", None)
    if root and not os.path.isabs(str(root)):
        problems.append("--csv-root must be an ABSOLUTE path (a scratch tree outside the app dir)")
    if getattr(ns, "box_selftest", False) and not getattr(ns, "box", False):
        problems.append("--box-selftest requires --box")
    return problems


# ── resource caps ────────────────────────────────────────────────────────


def apply_resource_caps(
    *, max_mem_gib: float, max_cpu_seconds: int, wall_seconds: int, nice: int = 10
) -> dict[str, Any]:
    """Lower the process priority and cap address space, CPU time and wall
    clock.  Hitting a cap fails the run (``MemoryError`` / ``SIGXCPU`` /
    ``TimeoutError``) — it is never raised later."""
    caps: dict[str, Any] = {}
    try:
        os.nice(nice)
        caps["nice"] = nice
    except OSError:
        caps["nice"] = None
    limit = int(max_mem_gib * (1 << 30))
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    caps["addressSpaceGiB"] = max_mem_gib
    resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds + 30))
    caps["cpuSeconds"] = max_cpu_seconds

    def _timeout(_signum, _frame):
        raise TimeoutError(f"wall-clock cap of {wall_seconds}s reached")

    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(wall_seconds)
    caps["wallSeconds"] = wall_seconds
    return caps


def peak_rss_mb() -> float | None:
    try:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:  # noqa: BLE001
        return None


def dumps_aggregate(result: Mapping[str, Any]) -> str:
    return json.dumps(result, indent=1, default=str, sort_keys=False) + "\n"
