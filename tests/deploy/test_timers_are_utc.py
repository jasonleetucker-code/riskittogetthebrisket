"""Every ``OnCalendar=`` in deploy/systemd must be explicitly UTC.

systemd resolves a bare ``OnCalendar=*-*-* 15:00:00`` in the HOST
timezone.  On a UTC fleet that reads identically to the UTC form —
until someone sets a local timezone on a box, or the host tracks a
zone that observes DST.  Then the schedule silently walks an hour
twice a year, and the changeover day either skips a tick or fires one
twice.

Nothing about that looks like a failure.  ``dynasty-signal-alerts``
sends the digest an hour off; ``dynasty-custom-alerts`` doubles or
drops one sweep.  Both surface as "the email came at a weird time",
which nobody files a bug for.

Eight of the ten timers already carried the suffix.  This pins the
convention so the next timer added to the directory cannot be the
one that quietly forgets it.
"""

from __future__ import annotations

import re
from pathlib import Path

_SYSTEMD_DIRS = (
    Path(__file__).resolve().parents[2] / "deploy" / "systemd",
    Path(__file__).resolve().parents[2] / "deploy" / "backup",
)

_ONCALENDAR = re.compile(r"^\s*OnCalendar\s*=\s*(?P<value>.+?)\s*$")


def _oncalendar_lines() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for directory in _SYSTEMD_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if ".timer" not in path.name:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                # Comments mention OnCalendar in prose; only directives count.
                if line.lstrip().startswith("#"):
                    continue
                match = _ONCALENDAR.match(line)
                if match:
                    found.append((path, match.group("value")))
    return found


def test_there_are_timers_to_check():
    """Guard against the scan silently matching nothing."""
    assert len(_oncalendar_lines()) >= 8


def test_every_oncalendar_is_explicitly_utc():
    offenders = [
        f"{path.name}: OnCalendar={value}"
        for path, value in _oncalendar_lines()
        if not value.endswith(" UTC")
    ]
    assert not offenders, (
        "OnCalendar without an explicit UTC suffix resolves in the host "
        "timezone and DST-shifts: " + "; ".join(offenders)
    )
