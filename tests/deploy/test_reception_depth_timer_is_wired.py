"""The reception-depth timer must be installed AND enabled.

This repo has a recurring shape: a component is built, tested, and never
connected — `src/api/chat.py`, `src/trade/finder.py`, the TE basis
curve. A systemd unit has its own version of that failure, and it is
quieter: a template that exists but no installer block, or an installer
block that writes the unit but never runs `enable --now`. Either way
`systemctl list-timers` is empty and the data just never refreshes.

Nothing about a stale histogram looks like an error. The board keeps
serving last season's reception shapes indefinitely, which is precisely
the thing an in-season refresh exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO / "deploy" / "install-systemd-service.sh"
_SERVICE = _REPO / "deploy" / "systemd" / "dynasty-reception-depth.service.template"
_TIMER = _REPO / "deploy" / "systemd" / "dynasty-reception-depth.timer.template"
_SCRIPT = _REPO / "scripts" / "refresh_reception_depth.py"


def _installer() -> str:
    return _INSTALLER.read_text(encoding="utf-8", errors="replace")


def test_both_templates_exist():
    assert _SERVICE.is_file()
    assert _TIMER.is_file()


def test_the_installer_writes_both_units():
    body = _installer()
    assert "dynasty-reception-depth.service.template" in body
    assert "dynasty-reception-depth.timer.template" in body


def test_the_installer_enables_the_timer():
    """Installing a unit without enabling it is a unit that never runs.

    ``list-timers`` would be empty and the only symptom would be
    histograms quietly frozen at whatever season was last built.
    """
    body = _installer()
    assert 'enable --now "${rd_service_name}.timer"' in body


def test_the_service_points_at_a_script_that_exists():
    """A unit whose ExecStart is a typo fails only on the box, weeks
    later, in a journal nobody is reading."""
    assert _SCRIPT.is_file()
    assert "scripts/refresh_reception_depth.py" in _SERVICE.read_text(encoding="utf-8")


def test_the_offseason_exit_code_counts_as_success():
    """Exit 2 means "the season has not kicked off", which is the normal
    state from March to August.

    Without ``SuccessExitStatus`` the unit sits failed for half the year
    — and a unit that is always red is one nobody looks at, which is
    exactly when the exit-1 case (release path moved) would slip past.
    """
    body = _SERVICE.read_text(encoding="utf-8")
    assert "SuccessExitStatus=0 2" in body


def test_the_timer_does_not_bind_the_service_with_requires():
    """``[Unit] Requires=`` on a timer force-starts the service on every
    boot and lets a service failure deactivate the timer itself.

    The repo's other timers carry this warning in a comment; this one
    must not be the exception that reintroduces it.
    """
    body = _TIMER.read_text(encoding="utf-8")
    # Strip comments first. The template CONTAINS the string
    # "Requires=" inside the comment explaining why there deliberately
    # is not one, and a naive scan reads that prose as the directive —
    # the same false positive that made a documentation comment look
    # like an endpoint caller elsewhere in this repo.
    directives = "\n".join(line for line in body.split("\n") if not line.lstrip().startswith("#"))
    unit_section = directives.split("[Timer]", 1)[0]
    assert "Requires=" not in unit_section, (
        "the [Unit] section binds the service with Requires=, which force-starts "
        "it on every boot and lets a service failure deactivate the timer"
    )
    assert "Persistent=true" in directives, "a missed run must be caught up"


def test_the_timer_names_the_service_it_runs():
    assert "Unit=__SERVICE_NAME__-reception-depth.service" in _TIMER.read_text(encoding="utf-8")
