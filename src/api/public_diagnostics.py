"""Public diagnostics -- the ONE serialization boundary for anonymous status.

``/api/status`` and ``/api/health`` are anonymous (``server._PUBLIC_API_EXACT``)
and are read by deploy verification, the scheduled health check, the uptime
probe and the frontend status widgets.  Before this module they served the
box's internals verbatim: the absolute path of the board file
(``data_runtime.active_data_source.path``), of the rank-history log and the
playerctx history directory (``rankHistoryCoverage.path`` /
``playerctxHistoryCoverage.path``), every ``dir:<absolute path>`` startup check,
the loopback uptime target (an env value, ``UPTIME_CHECK_URL``), and each
league's raw Sleeper id -- the one identifier ``/api/leagues`` deliberately
never exposes (audit W22-F005).

This is the public projection of those payloads.  It reuses the posture
``src/api/backup_health.py`` set for the backup block (PR #1983,
``backup-health.v3``): withhold, never pretend absent, and SAY it was withheld
(``filesystemPaths: "withheld"``) so a missing path reads as policy rather than
as "no file".  The backup block itself is already public-safe and passes
through untouched apart from the same backstop every other string gets.

Two layers, deliberately:

1. **Named projections** for the fields known to carry internals -- each keeps
   the operational fact (a file name, a relative directory, "the probe targets
   loopback") and drops the internal detail.
2. **A fail-closed backstop over EVERY value**: any key on the withheld list is
   dropped wherever it appears, and any string that still contains an absolute
   filesystem path, a Python traceback, or the value of a secret-shaped
   environment variable is rewritten.  A field added to ``/api/status`` next
   year is therefore public-safe without anyone remembering this module --
   ``tests/api/test_public_diagnostics.py`` walks the WHOLE served response
   for both endpoints and fails on any path-shaped or env-valued string.

The full, unredacted diagnostics stay reachable through the existing
authorized mechanism only: ``GET /api/admin/diagnostics`` (private API gate +
``_require_admin_session``, the same allowlist every ``/api/admin/*`` route
uses).  Nothing here changes a status code, an ``ok`` verdict or an alert:
this is serialization only, applied after the payload is computed.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from src.api.backup_health import FILESYSTEM_PATHS_WITHHELD

SCHEMA_VERSION = "public-diagnostics.v1"

#: Where an operator reads what this projection withheld.  Admin-gated.
PRIVATE_DIAGNOSTICS_ROUTE = "/api/admin/diagnostics"

PATH_PLACEHOLDER = "<path withheld>"
TRACEBACK_PLACEHOLDER = "<traceback withheld>"
ENV_PLACEHOLDER = "<env value withheld>"

#: Keys whose VALUE is internal wherever they appear: filesystem locations,
#: raw external identifiers, and env-derived probe targets.  Dropped, never
#: blanked, so no consumer can mistake ``""`` for a real value.
WITHHELD_KEYS = frozenset(
    {
        # filesystem locations
        "path",
        "paths",
        "cwd",
        "newestBackupPath",
        "directoryInspected",
        "canonicalRoot",
        "blockedAt",
        "backupDir",
        "dataDir",
        "data_dir",
        "base_dir",
        "baseDir",
        # raw external identifiers (``/api/leagues`` never serves these)
        "sleeperLeagueId",
        "sleeper_league_id",
        # env-derived probe target (``UPTIME_CHECK_URL``)
        "target_url",
        "targetUrl",
        # exception internals
        "traceback",
        "stacktrace",
        "stack",
        "exc_info",
    }
)

#: Key suffixes that name a filesystem location (``newestBackupPath``,
#: ``log_path``, ``stateDir`` ...).  ``backupDirUsed`` is a coarse label
#: (``primary`` / ``fallback`` / ``none``) and is explicitly allowed.
_PATH_KEY_SUFFIXES = ("Path", "_path", "_file_path", "Dir", "_dir")
_ALLOWED_PATH_SUFFIX_KEYS = frozenset({"backupDirUsed"})

#: An absolute POSIX path of at least two segments (``/home/x``, ``/var/lib/y``)
#: not preceded by a word character, ``.`` or ``/`` -- so the path part of a URL
#: (``http://h:8000/api/health``) and a ratio (``1/30``) are not paths.  This
#: site's own HTTP routes (``/api/...``, ``/_next/...``) are routes, not
#: filesystem locations, and are the one carve-out.
_POSIX_ABS_PATH = re.compile(r"(?<![\w./~-])/(?!api/|_next/)(?:[\w.@+-]+/)+[\w.@+-]*")
#: ``~/x`` home-relative paths.
_HOME_PATH = re.compile(r"(?<![\w./-])~/[\w.@+/-]+")
#: ``C:\\x`` / ``C:/x`` Windows drive paths and ``\\\\server\\share`` UNC paths.
_WINDOWS_ABS_PATH = re.compile(
    r"(?<![A-Za-z])[A-Za-z]:[\\/][^\s'\"<>|]*|\\\\[^\s'\"<>|\\]+\\[^\s'\"<>|]*"
)
_TRACEBACK = re.compile(r"Traceback \(most recent call last\)|File \"[^\"]+\", line \d+")

#: Env var NAMES whose values are secrets or deployment-specific identifiers,
#: matched on whole ``_``-separated TOKENS (curated, not substrings), so a
#: ``*_LEAGUE_KEY`` / ``*_SESSION_TTL`` / ``*_PASSTHROUGH`` name can never make
#: a legitimate league key or number disappear from status text.
_SECRET_ENV_TOKENS = frozenset(
    {
        "TOKEN",
        "TOKENS",
        "SECRET",
        "SECRETS",
        "PASSWORD",
        "PASSWD",
        "PASS",
        "PASSPHRASE",
        "COOKIE",
        "COOKIES",
        "CREDENTIAL",
        "CREDENTIALS",
        "DSN",
        "WEBHOOK",
        "APIKEY",
        "URL",
        "URI",
        "HOST",
        "USERNAME",
        "USERNAMES",
        "EMAIL",
        "SMTP",
    }
)
#: Two-token suffixes that are secrets although neither token alone is
#: (``KEY`` alone is not: ``LEAGUE_KEY`` names a public league key).
_SECRET_ENV_SUFFIXES = (
    ("API", "KEY"),
    ("PRIVATE", "KEY"),
    ("SECRET", "KEY"),
    ("ACCESS", "KEY"),
    ("SIGNING", "KEY"),
    ("DEPLOY", "KEY"),
    ("LEAGUE", "ID"),
)


def is_secret_env_name(name: str) -> bool:
    """Whether env var ``name`` names a value no public payload may echo."""
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", name.upper()) if t]
    if any(t in _SECRET_ENV_TOKENS for t in tokens):
        return True
    pairs = set(zip(tokens, tokens[1:]))
    return any(suffix in pairs for suffix in _SECRET_ENV_SUFFIXES)


#: Values shorter than this are too generic to scrub (``1``, ``true``, ``8000``).
_MIN_ENV_VALUE_LEN = 6
#: Values that are common words, not secrets, and would scrub real status text.
_ENV_VALUE_ALLOWLIST = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "dynasty", "production"})


def is_path_key(key: str) -> bool:
    """Whether a key names a filesystem location or another withheld value."""
    if key in _ALLOWED_PATH_SUFFIX_KEYS:
        return False
    if key in WITHHELD_KEYS:
        return True
    return key.endswith(_PATH_KEY_SUFFIXES)


def contains_absolute_path(text: str) -> bool:
    """Whether ``text`` carries an absolute filesystem path anywhere in it."""
    return bool(
        _POSIX_ABS_PATH.search(text) or _HOME_PATH.search(text) or _WINDOWS_ABS_PATH.search(text)
    )


def contains_traceback(text: str) -> bool:
    return bool(_TRACEBACK.search(text))


def secret_env_values(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Values of secret-shaped env vars that must never appear in a public payload.

    Longest first, so a value that contains another is scrubbed whole.
    """
    env = os.environ if environ is None else environ
    values = {
        str(v)
        for k, v in env.items()
        if is_secret_env_name(str(k))
        and isinstance(v, str)
        and len(v.strip()) >= _MIN_ENV_VALUE_LEN
        and v.strip().lower() not in _ENV_VALUE_ALLOWLIST
    }
    return tuple(sorted(values, key=len, reverse=True))


class _Scrubber:
    """One pass over one payload; counts what it rewrote."""

    def __init__(self, env_values: tuple[str, ...]) -> None:
        self.env_values = env_values
        self.dropped_keys = 0
        self.rewritten_strings = 0

    def string(self, text: str) -> str:
        out = text
        if contains_traceback(out):
            # A traceback carries file paths, source lines and locals' reprs;
            # nothing in it is safe to keep piecemeal.
            out = TRACEBACK_PLACEHOLDER
        for value in self.env_values:
            if value in out:
                out = out.replace(value, ENV_PLACEHOLDER)
        out = _POSIX_ABS_PATH.sub(PATH_PLACEHOLDER, out)
        out = _HOME_PATH.sub(PATH_PLACEHOLDER, out)
        out = _WINDOWS_ABS_PATH.sub(PATH_PLACEHOLDER, out)
        if out != text:
            self.rewritten_strings += 1
        return out

    def value(self, obj: Any) -> Any:
        if isinstance(obj, Mapping):
            out: dict[str, Any] = {}
            for key, val in obj.items():
                skey = str(key)
                if is_path_key(skey):
                    self.dropped_keys += 1
                    continue
                # Keys can carry internals too (a dict keyed by file path).
                out[self.string(skey)] = self.value(val)
            return out
        if isinstance(obj, (list, tuple)):
            return [self.value(v) for v in obj]
        if isinstance(obj, str):
            return self.string(obj)
        return obj


# -- named projections ---------------------------------------------------------
_SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _safe_file_name(path: Any) -> str | None:
    """The bare file name of ``path`` when it is a plain, boring name."""
    if not isinstance(path, str) or not path:
        return None
    name = PureWindowsPath(path).name if "\\" in path else PurePosixPath(path).name
    return name if _SAFE_FILE_NAME.match(name) else None


def _relative_to(path: str, base_dir: str | None) -> str | None:
    """``path`` relative to the app's own checkout, POSIX-style, or ``None``."""
    if not base_dir:
        return None
    try:
        rel = os.path.relpath(os.path.normpath(path), os.path.normpath(base_dir))
    except ValueError:  # different drive on Windows
        return None
    if rel == os.curdir:
        return "."
    if rel.startswith(os.pardir) or os.path.isabs(rel):
        return None
    return rel.replace(os.sep, "/")


def public_check_name(name: Any, base_dir: str | None) -> Any:
    """``dir:/home/x/app/data`` -> ``dir:data`` (relative to the checkout).

    A directory outside the checkout keeps only its kind: ``dir:<path withheld>``.
    """
    if not isinstance(name, str) or ":" not in name:
        return name
    kind, _, target = name.partition(":")
    if not (contains_absolute_path(target) or os.path.isabs(target)):
        return name
    rel = _relative_to(target, base_dir)
    return f"{kind}:{rel}" if rel is not None else f"{kind}:{PATH_PLACEHOLDER}"


def _project_data_source(source: Any) -> Any:
    if not isinstance(source, Mapping):
        return source
    out = dict(source)
    if "path" in out:
        out["fileName"] = _safe_file_name(out.get("path"))
        out["filesystemPaths"] = FILESYSTEM_PATHS_WITHHELD
    return out


def _project_coverage(block: Any) -> Any:
    """History-coverage blocks: the counts stay, the location is withheld."""
    if not isinstance(block, Mapping):
        return block
    out = dict(block)
    if "path" in out:
        out["filesystemPaths"] = FILESYSTEM_PATHS_WITHHELD
    return out


def _target_kind(url: Any) -> str:
    if not isinstance(url, str) or not url.strip():
        return "unset"
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url.strip(), flags=re.I).split("/", 1)[0]
    host = host.rsplit("@", 1)[-1].split(":", 1)[0].strip("[]").lower()
    return "loopback" if host in {"127.0.0.1", "localhost", "::1"} else "external"


def _project_uptime(block: Any) -> Any:
    if not isinstance(block, Mapping):
        return block
    out = dict(block)
    if "target_url" in out:
        out["targetKind"] = _target_kind(out.get("target_url"))
    return out


def _project_startup_checks(summary: Any, base_dir: str | None) -> Any:
    if not isinstance(summary, Mapping):
        return summary
    out = dict(summary)
    checks = out.get("checks")
    if isinstance(checks, list):
        out["checks"] = [
            {**c, "name": public_check_name(c.get("name"), base_dir)}
            if isinstance(c, Mapping)
            else c
            for c in checks
        ]
    return out


def _project_leagues(leagues: Any) -> Any:
    if not isinstance(leagues, list):
        return leagues
    out = []
    for entry in leagues:
        if isinstance(entry, Mapping) and "sleeperLeagueId" in entry:
            entry = {**entry, "externalIds": "withheld"}
        out.append(entry)
    return out


def _stamp(payload: dict[str, Any], scrubber: _Scrubber) -> dict[str, Any]:
    payload["publicDiagnostics"] = {
        "schemaVersion": SCHEMA_VERSION,
        "filesystemPaths": FILESYSTEM_PATHS_WITHHELD,
        "externalIds": "withheld",
        "envValues": "withheld",
        "tracebacks": "withheld",
        "droppedKeys": scrubber.dropped_keys,
        "rewrittenStrings": scrubber.rewritten_strings,
        "fullDiagnostics": PRIVATE_DIAGNOSTICS_ROUTE,
    }
    return payload


def _finish(projected: dict[str, Any], environ: Mapping[str, str] | None) -> dict[str, Any]:
    scrubber = _Scrubber(secret_env_values(environ))
    out = scrubber.value(projected)
    return _stamp(out, scrubber)


def public_status_payload(
    payload: Mapping[str, Any],
    *,
    base_dir: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The anonymous-safe projection of the full ``/api/status`` content.

    Never mutates ``payload`` (it holds references to live module globals).
    """
    out = dict(payload)
    runtime = out.get("data_runtime")
    if isinstance(runtime, Mapping):
        runtime = dict(runtime)
        runtime["active_data_source"] = _project_data_source(runtime.get("active_data_source"))
        out["data_runtime"] = runtime
    for key in ("rankHistoryCoverage", "playerctxHistoryCoverage"):
        if key in out:
            out[key] = _project_coverage(out[key])
    if "uptime" in out:
        out["uptime"] = _project_uptime(out["uptime"])
    if "leagues" in out:
        out["leagues"] = _project_leagues(out["leagues"])
    if "startupChecks" in out:
        out["startupChecks"] = _project_startup_checks(
            out["startupChecks"], os.fspath(base_dir) if base_dir else None
        )
    return _finish(out, environ)


def public_health_payload(
    payload: Mapping[str, Any],
    *,
    base_dir: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The anonymous-safe projection of the full ``/api/health`` content."""
    out = dict(payload)
    if "startupChecks" in out:
        out["startupChecks"] = _project_startup_checks(
            out["startupChecks"], os.fspath(base_dir) if base_dir else None
        )
    if "uptime_watchdog" in out:
        out["uptime_watchdog"] = _project_uptime(out["uptime_watchdog"])
    return _finish(out, environ)


def public_uptime_payload(
    payload: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """The anonymous-safe projection of ``/api/uptime`` (the ``uptime_status``
    global): ``target_url`` becomes ``targetKind``; ``last_error`` (free-form
    exception text that can carry the URL or a path) goes through the backstop."""
    return _finish(_project_uptime(dict(payload)), environ)


def unsafe_public_values(
    payload: Any, *, environ: Mapping[str, str] | None = None
) -> list[tuple[str, str]]:
    """Every ``(json path, reason)`` in ``payload`` that a public payload may not carry.

    The guard the tests (and an operator) run over a SERVED response: a
    withheld key, an absolute path, a traceback, or a secret env value, at any
    depth, in a key or a value.  Empty means safe.
    """
    env_values = secret_env_values(environ)
    problems: list[tuple[str, str]] = []

    def check_text(where: str, text: str) -> None:
        if contains_absolute_path(text):
            problems.append((where, "absolute_path"))
        if contains_traceback(text):
            problems.append((where, "traceback"))
        if any(v in text for v in env_values):
            problems.append((where, "env_value"))

    def walk(obj: Any, where: str) -> None:
        if isinstance(obj, Mapping):
            for key, val in obj.items():
                skey = str(key)
                here = f"{where}.{skey}"
                if is_path_key(skey):
                    problems.append((here, "withheld_key"))
                check_text(f"{here}<key>", skey)
                walk(val, here)
        elif isinstance(obj, (list, tuple)):
            for i, val in enumerate(obj):
                walk(val, f"{where}[{i}]")
        elif isinstance(obj, str):
            check_text(where, obj)

    walk(payload, "$")
    return problems
