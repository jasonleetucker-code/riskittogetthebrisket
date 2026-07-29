"""``tzdata`` must stay declared for Windows, and CI cannot notice if it goes.

``src/nfl_data/freshness.py`` evaluates ``ZoneInfo("America/New_York")``
at module import time and ``src/news/usage_signals.py`` imports it.  On
Linux and macOS ``zoneinfo`` reads the OS tz database and needs nothing
extra; Windows ships none, so CPython falls back to the ``tzdata`` PyPI
package.  Without it the import raises ``ZoneInfoNotFoundError``.

This is a STATIC manifest check rather than a behavioural one on
purpose.  Every workflow runs ``ubuntu-latest``, where the import
succeeds whether or not ``tzdata`` is installed — so a behavioural test
would pass on the exact platform that cannot detect the problem.  That
blind spot is what let the gap survive: measured 2026-07-29, a Windows
``python -m pytest tests/`` aborted with 3 collection errors and ran
nothing at all, while CI stayed green.

If this test fails, do not delete it.  Restore the declaration in
``requirements.txt`` instead, or Windows development breaks silently
again.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "requirements.txt"

# Matches e.g. ``tzdata~=2026.1; sys_platform == "win32"`` with flexible
# whitespace, quote style, and version-specifier operator.
_TZDATA_LINE = re.compile(
    r"""^\s*tzdata\s*             # package name
        (?:[~>=<!]=[^;]+)?        # optional version specifier
        \s*;\s*                   # environment-marker separator
        sys_platform\s*==\s*      # the marker we require
        ['"]win32['"]\s*$""",
    re.VERBOSE,
)


def _declared_lines() -> list[str]:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_tzdata_is_declared_for_win32() -> None:
    matches = [line for line in _declared_lines() if _TZDATA_LINE.match(line)]
    assert matches, (
        "requirements.txt must declare tzdata with a win32 environment "
        "marker, e.g.\n\n"
        '    tzdata~=2026.1; sys_platform == "win32"\n\n'
        "Without it, ZoneInfo('America/New_York') raises "
        "ZoneInfoNotFoundError on Windows at import time and the test "
        "suite cannot be collected there. CI runs Linux and will not "
        "reproduce the failure."
    )
    assert len(matches) == 1, f"tzdata declared more than once: {matches!r}"


def test_tzdata_marker_keeps_it_off_linux() -> None:
    """The marker is what protects the production dependency graph.

    Production is Linux, where the OS tz database already answers the
    lookup.  An unmarked ``tzdata`` would install there too — harmless
    but untrue to why the package is present, and it would quietly
    become a runtime dependency nobody could justify from the code.
    """
    unmarked = [
        line
        for line in _declared_lines()
        if re.match(r"^\s*tzdata\s*(?:[~>=<!]=\S+)?\s*$", line)
    ]
    assert not unmarked, (
        "tzdata is declared without an environment marker "
        f"({unmarked!r}); it must be constrained to "
        'sys_platform == "win32" so Linux/macOS installs are unchanged.'
    )
