"""Every shipped timer template must actually be installed.

There are per-timer versions of this file already — reception-depth,
consensus-edge, ffpc-sharp — each written after that particular timer was
found unwired. Writing one guard per incident does not close the hole: it
closes the last one and waits for the next. On 2026-08-05 the next three
were already sitting in the tree.

``deploy/install-systemd-service.sh`` installs each timer from a
hand-written block. ``deploy/systemd/`` shipped 16 timer templates and
only 13 blocks existed, so **crowd-faab, sharp-activity and
board-snapshot had no installer at all** — templates committed, reviewed,
merged, and never once rendered onto the box. Their producers never ran
and every deploy reported success.

That is bad on its own. What makes it a *loop* is the other end:
``deploy.sh`` decides whether to run the installer by globbing this same
directory and asking systemd whether each unit is installed **and**
enabled. An unwired template is therefore reported missing on every
deploy, which runs the installer to add it, which does not add it —
forever, and quietly, because the report is a warning.

So the invariant this file pins is not "these three specific timers are
wired". It is:

* every ``*.timer.template`` is reached by SOME install route, and
* every ``*_needs_install`` flag reaches the ``daemon-reload`` chain.

Both are derived from what the tree actually contains, so adding a timer
updates the expectation automatically and forgetting to wire it fails
here instead of on the box six weeks later.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SYSTEMD = _REPO / "deploy" / "systemd"
_INSTALLER = _REPO / "deploy" / "install-systemd-service.sh"
_DEPLOY_SH = _REPO / "deploy" / "deploy.sh"


def _installer() -> str:
    return _INSTALLER.read_text(encoding="utf-8", errors="replace")


def _timer_stems() -> list[str]:
    """``dynasty-crowd-faab.timer.template`` -> ``crowd-faab``."""
    return sorted(
        p.name[len("dynasty-") : -len(".timer.template")]
        for p in _SYSTEMD.glob("dynasty-*.timer.template")
    )


# ── The invariant ────────────────────────────────────────────────────


def test_there_are_timer_templates_to_check() -> None:
    """Non-vacuity.

    Every assertion below is a loop over the glob. If the glob ever
    returns nothing — directory renamed, naming convention changed — all
    of them pass while checking nothing at all.
    """
    assert len(_timer_stems()) >= 10


def test_every_timer_template_is_installed_by_something() -> None:
    """A template nothing installs is a producer that never runs.

    Two accepted routes: a dedicated block (needed when the install has
    real special cases — credential gating, an initial kick, seeding a
    session file into /var/lib) or the shared ``install_simple_timer``
    helper. Which one does not matter here; having neither does.
    """
    body = _installer()
    unwired = [
        stem
        for stem in _timer_stems()
        if f"dynasty-{stem}.timer.template" not in body
        and f'install_simple_timer "{stem}"' not in body
    ]
    assert not unwired, (
        f"timer templates that nothing installs: {unwired}. "
        "deploy.sh will report these missing on EVERY deploy, run this "
        "installer to fix it, and the installer will not install them. "
        "Add a dedicated block, or one install_simple_timer line."
    )


def test_every_needs_install_flag_reaches_the_daemon_reload() -> None:
    """Enabling a unit systemd has not re-read starts the STALE one.

    This is recorded in the installer's own comment for
    ``ce_needs_install`` — the fix deployed, reported as deployed, and
    not running. Fixing the one instance left ``sharpros_needs_install``
    and ``sharptx_needs_install`` with the same hole, because the chain
    is a hand-maintained line of ``||``. Derive the expectation instead.
    """
    body = _installer()
    declared = set(re.findall(r"^\s*local\s+(\w+)_needs_install=false\s*$", body, re.M))
    assert declared, "no *_needs_install flags found — has the installer been restructured?"

    reload_line = next(
        line
        for line in body.split("\n")
        if line.lstrip().startswith("if [[") and line.count("_needs_install}") > 1
    )

    missing = sorted(name for name in declared if f"${{{name}_needs_install}}" not in reload_line)
    assert not missing, (
        f"flags gate an install but never trigger daemon-reload: {missing}. "
        "A run that installs only that unit will enable it against a "
        "systemd that has never read it."
    )


# ── The helper's own contract ────────────────────────────────────────


def test_the_helper_installs_service_and_timer_and_enables_it() -> None:
    """Three separate steps, each of which has been forgotten before."""
    body = _installer()
    helper = body.split("install_simple_timer() {", 1)[1].split("\nmain() {", 1)[0]
    assert 'INSTALL_BIN}" -m 0644 "${tmp_service}" "${service_path}"' in helper
    assert 'INSTALL_BIN}" -m 0644 "${tmp_timer}" "${timer_path}"' in helper
    assert "daemon-reload" in helper
    assert 'enable --now "${unit_name}.timer"' in helper


def test_the_helper_enables_even_when_the_unit_was_already_on_disk() -> None:
    """installed-but-disabled is the same permanent loop as not installed.

    ``deploy.sh``'s detector requires BOTH ``cat`` and ``is-enabled`` to
    succeed, so short-circuiting the enable behind "did we just write the
    files" would leave a half-installed unit re-reported every deploy.
    """
    body = _installer()
    helper = body.split("install_simple_timer() {", 1)[1].split("\nmain() {", 1)[0]
    enable_block = helper.split('if [[ "${needs_install}" == "true" ]]; then', 1)[1]
    # The is-enabled check must sit OUTSIDE the needs_install branch.
    tail = enable_block.split("\n  fi\n", 1)[1]
    assert "is-enabled" in tail, "the enable check is nested inside the install branch"


def test_every_simple_timer_call_has_both_templates() -> None:
    """``install_simple_timer`` silently returns when a template is
    missing, so a typo'd stem is indistinguishable from a timer that is
    deliberately absent on this host."""
    for stem in re.findall(r'install_simple_timer "([\w-]+)"', _installer()):
        assert (_SYSTEMD / f"dynasty-{stem}.service.template").is_file(), stem
        assert (_SYSTEMD / f"dynasty-{stem}.timer.template").is_file(), stem


# ── What the units point at ──────────────────────────────────────────


def test_every_service_execstart_points_at_a_file_that_exists() -> None:
    """An ExecStart typo fails only on the box, weeks later, in a journal
    nobody is reading. Generalises the per-timer check that already
    existed for reception-depth."""
    missing: list[str] = []
    for template in sorted(_SYSTEMD.glob("dynasty-*.service.template")):
        for line in template.read_text(encoding="utf-8").split("\n"):
            if not line.startswith("ExecStart="):
                continue
            for rel in re.findall(r"__APP_DIR__/(\S+)", line):
                if not (_REPO / rel).exists():
                    missing.append(f"{template.name} -> {rel}")
    assert not missing, f"ExecStart targets that do not exist: {missing}"


def test_every_timer_resolves_to_a_service_that_ships() -> None:
    """A timer whose target does not exist fires into nothing.

    Two spellings are legal and both are in the tree. Most templates name
    the target explicitly with ``Unit=__SERVICE_NAME__-<stem>.service``;
    ``dlf-fetch`` and ``idpshow-fetch`` omit it and take systemd's
    implicit default, which is the service sharing the timer's name. The
    check is that the target RESOLVES, not that it is spelled one way —
    pinning the spelling would fail two working timers and teach the next
    person to edit the guard.
    """
    for stem in _timer_stems():
        body = (_SYSTEMD / f"dynasty-{stem}.timer.template").read_text(encoding="utf-8")
        explicit = f"Unit=__SERVICE_NAME__-{stem}.service" in body
        implicit = not re.search(r"^Unit=", body, re.M)
        assert explicit or implicit, (
            f"{stem}: Unit= names something other than its own service, "
            "so the timer fires a unit that may not exist"
        )
        assert (_SYSTEMD / f"dynasty-{stem}.service.template").is_file(), stem


# ── The other end of the loop ────────────────────────────────────────


def test_deploy_sh_still_derives_missing_timers_from_this_directory() -> None:
    """This is what turns an unwired template into a permanent loop
    rather than a dormant file, and it is the reason the guard above is
    worth having.

    If deploy.sh ever stops globbing the templates, the failure mode
    changes shape and this file's docstring stops being true — better to
    fail here and have someone re-read it.
    """
    body = _DEPLOY_SH.read_text(encoding="utf-8", errors="replace")
    assert "deploy/systemd/*.timer.template" in body
    assert "is-enabled" in body, "deploy.sh must treat installed-but-disabled as missing"
