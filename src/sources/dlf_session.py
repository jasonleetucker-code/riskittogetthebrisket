"""Where the DLF login-cookie jar lives -- ONE resolver, shared with the timer.

The DLF fetch timer (``deploy/systemd/dynasty-dlf-fetch.*`` ->
``deploy/dlf_fetch_and_push.sh``) keeps its cookie jar in a dedicated work
directory, NOT in the live repo checkout::

    WORK_DIR="${DLF_FETCH_WORK_DIR:-/var/lib/dlf-fetch}"
    SESSION_FILE="${WORK_DIR}/dlf_session.json"

It copies that file into its private clone before ``scripts/fetch_dlf.py``
runs and copies the (possibly re-minted) jar back afterwards, so the
work-dir file is the one that moves.  ``<APP_DIR>/dlf_session.json`` is only
the one-time bootstrap seed ``deploy/install-systemd-service.sh`` copies
across when the work dir has no jar yet; nothing on the box ever refreshes it.

``/api/health`` used to read ``BASE_DIR / "dlf_session.json"`` -- the seed --
and reported a session that was in fact refreshed the same day as 96.6 days
old (2026-10-26).  A freshness probe pointed at a file nothing updates is a
false alarm that cannot be told apart from a real one, so the probe now asks
THIS module where the jar is, and the module resolves it exactly the way the
script does.

The shell script is the source of truth.  ``tests/sources/test_dlf_session_path.py``
parses it and fails if the env var name, the default directory or the file
name here ever drift from it.

Scope: only DLF.  The other sessions ``/api/health`` reports
(``draftsharks_session.json``, ``idpshow_session.json``) are unchanged and keep
resolving against the app directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

#: Environment variable ``deploy/dlf_fetch_and_push.sh`` reads for its work dir.
DLF_FETCH_WORK_DIR_ENV = "DLF_FETCH_WORK_DIR"

#: The script's default (``${DLF_FETCH_WORK_DIR:-/var/lib/dlf-fetch}``).
DLF_FETCH_DEFAULT_WORK_DIR = "/var/lib/dlf-fetch"

#: The jar's file name inside the work dir -- and the key ``/api/health`` reports it under.
DLF_SESSION_FILENAME = "dlf_session.json"


def dlf_fetch_work_dir(env: Mapping[str, str] | None = None) -> Path:
    """The timer's work directory.

    Mirrors bash ``${VAR:-default}``: an UNSET *or EMPTY* variable falls back
    to the default (``or`` rather than a ``None`` check -- ``DLF_FETCH_WORK_DIR=``
    in an EnvironmentFile must not resolve to the current directory).
    ``env`` is injectable for tests; the default reads ``os.environ`` at call
    time, so it sees the same value the timer's own ``EnvironmentFile`` gives it.
    """
    source = os.environ if env is None else env
    return Path(source.get(DLF_FETCH_WORK_DIR_ENV) or DLF_FETCH_DEFAULT_WORK_DIR)


def dlf_session_path(env: Mapping[str, str] | None = None) -> Path:
    """The cookie jar the DLF fetch timer actually reads and refreshes."""
    return dlf_fetch_work_dir(env) / DLF_SESSION_FILENAME


def health_session_path(
    filename: str,
    base_dir: Path,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Where ``/api/health`` should look for the session file named ``filename``.

    DLF resolves through :func:`dlf_session_path`.  Every other session keeps
    its existing ``base_dir / filename`` resolution, so this is a no-op for them.

    No fallback from the DLF work-dir path to ``base_dir``: when the jar is
    absent the timer logs in afresh and writes one, so the honest answer is
    "missing" -- not the age of a bootstrap copy nothing maintains.
    """
    if filename == DLF_SESSION_FILENAME:
        return dlf_session_path(env)
    return base_dir / filename
