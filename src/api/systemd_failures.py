"""Failed systemd units on this host, for the operator ops-alert sweep (MD-103).

THE GAP.  38 ``dynasty-*`` timers run the box's ingestion, snapshots and backups,
and none carries ``OnFailure=``.  A timer whose service exits non-zero is
visible in ``systemctl --failed`` and the journal and nowhere else, so a source
fetch, a snapshot or the nightly backup can fail for days without the operator
hearing of it.  Adding ``OnFailure=`` to the service templates is a production
infrastructure change (``deploy.sh`` re-renders shipped service templates and
reinstalls them on the next deploy), so it is written up as operator steps in
``docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md`` section 7 and not done here.

WHAT THIS DOES INSTEAD, with no new privilege and no unit change: it reads the
failed-unit list that ``systemctl`` already answers to an unprivileged user and
hands it to ``src/api/ops_alerts.py`` -- the existing alert path (SMTP, per-
category cooldown, recovery notice) driven by the daily signal-alerts sweep.
A oneshot service that failed stays ``failed`` until its next successful run, so
"failed now" is exactly "the latest run failed".

Never raises.  ``None`` means NOT CHECKED (no ``systemctl``, a timeout, an
unparseable answer, a sandbox that cannot reach the manager) -- unknown, never
"no failures".
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable

#: Only the units this repository ships.  Anything else on the host (an
#: operator's own units, a distro service) is not this sweep's business.
UNIT_PREFIXES = ("dynasty", "riskit")
_UNIT_NAME = re.compile(r"^(?:dynasty|riskit)[A-Za-z0-9@._:\\-]*\.service$")
#: Bounded: a runaway list must not become an unbounded email.
MAX_UNITS = 50
_TIMEOUT_SECONDS = 10.0


def _run_systemctl(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        argv, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
    )


def parse_failed_units(output: str) -> list[str]:
    """Unit names from ``systemctl list-units --failed --plain --no-legend``.

    First whitespace-separated column of each line, kept only if it is a
    ``dynasty-*`` / ``riskit-*`` service by name.  Sorted and de-duplicated, so
    the alert categories are stable between sweeps.
    """
    names: set[str] = set()
    for line in output.splitlines():
        parts = line.strip().lstrip("*● ").split()
        if parts and _UNIT_NAME.match(parts[0]):
            names.add(parts[0])
    return sorted(names)[:MAX_UNITS]


def failed_units(
    run: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> list[str] | None:
    """The shipped units currently in the ``failed`` state, or ``None`` = not checked."""
    runner = run or _run_systemctl
    try:
        proc = runner(
            [
                "systemctl",
                "list-units",
                "--failed",
                "--type=service",
                "--plain",
                "--no-legend",
                "--no-pager",
            ]
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return parse_failed_units(proc.stdout or "")
    except Exception:  # noqa: BLE001 -- an unparseable answer is unknown, not clean
        return None
