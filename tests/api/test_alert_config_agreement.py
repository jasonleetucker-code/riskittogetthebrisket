"""``ALERT_ENABLED`` must mean the same thing in both processes.

``server.py`` and ``Dynasty Scraper.py`` both read this variable and
both act on it, but they disagreed on its default: the server treated
an unset value as OFF (``_env_bool("ALERT_ENABLED", False)``) while the
scraper treated it as ON (``_env_str("ALERT_ENABLED", "true")``).  One
variable, two processes, opposite meanings — so "alerting is off"
depended on which half of the stack you asked.

Everything written about the setting says opt-in: ``.env.example``
carries it commented out under "Email alerting (all required for alerts
to work)", and ``/api/alerts`` refuses with "Set environment variable
ALERT_ENABLED=true".  OFF is the default that agrees with the docs.

Parsed as text rather than imported: ``Dynasty Scraper.py`` is not a
valid module name and importing ``server`` for a constant would drag in
the whole app.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SERVER = _ROOT / "server.py"
_SCRAPER = _ROOT / "Dynasty Scraper.py"


def _assignment(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name} ="):
            return line
    raise AssertionError(f"{name} is not assigned at module level in {path.name}")


def test_alert_enabled_defaults_off_in_the_server():
    line = _assignment(_SERVER, "ALERT_ENABLED")
    assert "False" in line, f"server.py must default ALERT_ENABLED off; got: {line}"


def test_alert_enabled_defaults_off_in_the_scraper():
    line = _assignment(_SCRAPER, "ALERT_ENABLED")
    default = re.search(r'_env_str\(\s*"ALERT_ENABLED"\s*,\s*"([^"]*)"', line)
    assert default, f"could not read the scraper's ALERT_ENABLED default from: {line}"
    assert default.group(1).lower() not in {"1", "true", "yes", "on"}, (
        "Dynasty Scraper.py defaults ALERT_ENABLED ON while server.py defaults it OFF. "
        "Alerting is opt-in per .env.example and the /api/alerts error string."
    )


def test_no_personal_email_is_hardcoded_as_a_default():
    """A real address as a default is both a data leak and a live gate.

    The scraper's send gate is ``not ALERT_ENABLED or not ALERT_EMAIL``,
    so a hardcoded recipient satisfied half of it on every checkout —
    in a repository that is currently public.
    """
    line = _assignment(_SCRAPER, "ALERT_EMAIL")
    assert "@" not in line, f"ALERT_EMAIL must not default to a literal address; got: {line}"


def test_scraper_accepts_the_canonical_recipient_name():
    """``ALERT_TO`` is what server.py and .env.example use."""
    line = _assignment(_SCRAPER, "ALERT_EMAIL")
    assert (
        '"ALERT_TO"' in line
    ), "the scraper should read ALERT_TO (canonical) with ALERT_EMAIL as the alias"


@pytest.mark.parametrize("path", [_SERVER, _SCRAPER])
def test_alert_modules_are_still_present(path):
    assert path.is_file(), f"{path} vanished; this test's premise needs rechecking"
