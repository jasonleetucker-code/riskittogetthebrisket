"""The playerctx retention push must be installed AND enabled.

Retention has a failure mode with no symptom.  If the dated snapshot is
written locally but never pushed, everything keeps working — the API
reads the live `snapshot.json`, the board is unaffected, and the only
consequence shows up months later when a study asks for a past date and
finds nothing there.  Unlike a stale histogram, there is no recovery: a
day that was not retained cannot be retained afterwards.

So the wiring is asserted rather than assumed, the same way
`test_reception_depth_timer_is_wired.py` asserts its own.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO / "deploy" / "install-systemd-service.sh"
_SERVICE = _REPO / "deploy" / "systemd" / "dynasty-playerctx-history.service.template"
_TIMER = _REPO / "deploy" / "systemd" / "dynasty-playerctx-history.timer.template"
_REFRESH_SERVICE = _REPO / "deploy" / "systemd" / "dynasty-playerctx-refresh.service.template"
_SCRIPT = _REPO / "deploy" / "playerctx_history_push.sh"


def _installer() -> str:
    return _INSTALLER.read_text(encoding="utf-8", errors="replace")


def _directives(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    return "\n".join(line for line in body.split("\n") if not line.lstrip().startswith("#"))


def test_both_templates_exist():
    assert _SERVICE.is_file()
    assert _TIMER.is_file()


def test_the_installer_writes_both_units():
    body = _installer()
    assert "dynasty-playerctx-history.service.template" in body
    assert "dynasty-playerctx-history.timer.template" in body


def test_the_installer_enables_the_timer():
    assert 'enable --now "${pchist_service_name}.timer"' in _installer()


def test_the_new_unit_participates_in_daemon_reload():
    """A unit written to disk without `daemon-reload` is the stale-cached
    failure this installer's own comment documents.  Every other timer's
    flag is in that condition; this one must be too."""
    body = _installer()
    reload_block = body.split("daemon-reload and enable", 1)[1].split("daemon-reload", 1)[0]
    assert "pchist_needs_install" in reload_block


def test_the_service_points_at_a_script_that_exists():
    assert _SCRIPT.is_file()
    assert "deploy/playerctx_history_push.sh" in _SERVICE.read_text(encoding="utf-8")


def test_the_refresh_actually_produces_what_this_pushes():
    """The push is a no-op unless the producer is asked to retain.

    `--retain-history` defaults OFF in `scripts/refresh_playerctx.py`, so
    without it on the ExecStart the retention directory stays empty and
    this timer exits clean every week forever — installed, enabled,
    green, and retaining nothing.
    """
    assert "--retain-history" in _REFRESH_SERVICE.read_text(encoding="utf-8")


def test_the_timer_does_not_bind_the_service_with_requires():
    """`Requires=` in a timer's [Unit] pulls the service in when the
    TIMER starts, so `enable --now` would fire a push on deploy day for a
    file the refresh has not written yet, and every reboot would fire
    another."""
    unit_section = _directives(_TIMER).split("[Timer]", 1)[0]
    assert "Requires=" not in unit_section
    assert "Persistent=true" in _directives(_TIMER)


def test_the_timer_names_the_service_it_runs():
    assert "Unit=__SERVICE_NAME__-playerctx-history.service" in _TIMER.read_text(encoding="utf-8")


def test_the_push_slot_does_not_collide_with_the_other_pushers():
    """Three jobs push to main from prod plus CI's auto-refresh; they hold
    :27, :32 and :42 and are spaced on purpose.  Landing on a taken minute
    turns every run into a rebase race."""
    taken = {":27:", ":32:", ":42:"}
    line = next(ln for ln in _directives(_TIMER).splitlines() if ln.startswith("OnCalendar="))
    assert not any(minute in line for minute in taken), line


def test_the_push_runs_after_the_refresh_that_writes_the_file():
    """05:40 + up to 600s randomized delay + up to 900s runtime ends by
    ~06:05.  A push scheduled before that races the writer."""
    refresh = next(
        ln
        for ln in _directives(_REPO / "deploy" / "systemd" / "dynasty-playerctx-refresh.timer.template")
        .splitlines()
        if ln.startswith("OnCalendar=")
    )
    push = next(ln for ln in _directives(_TIMER).splitlines() if ln.startswith("OnCalendar="))

    def _minutes(line: str) -> int:
        clock = line.split()[-2] if line.split()[-1] == "UTC" else line.split()[-1]
        hour, minute, _ = clock.split(":")
        return int(hour) * 60 + int(minute)

    assert _minutes(push) >= _minutes(refresh) + 45, (refresh, push)


def test_the_installer_reinstalls_on_a_template_change():
    """Gating on "does the timer exist" alone means a template edit is
    silently ignored on an already-provisioned box.  That bit for real
    when `--retain-history` was added to the refresh ExecStart: the unit
    file in the repo said one thing and the unit on the box said
    another."""
    body = _installer()
    assert 'cmp -s "${tmp_playerctx_service}" "${playerctx_service_path}"' in body
    assert 'cmp -s "${tmp_pchist_service}" "${pchist_service_path}"' in body
