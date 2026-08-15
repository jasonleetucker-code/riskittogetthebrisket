"""The C1A state-backup line installs under the deployment privilege model.

Measured on production 2026-08-15 (preflight run 31910753511), the deploy
account's NOPASSWD sudo is exactly::

    /usr/bin/systemctl /bin/systemctl /usr/bin/journalctl /bin/journalctl
    /usr/bin/install   /bin/install   /usr/bin/chown      /bin/chown

No ``bash``.  ``apply_hardening.sh`` requires a full root shell, so it cannot
run there at all — which meant installing a backup timer demanded a human root
session AND an nginx rewrite it had no business performing, nginx being the one
step that can silently revert certbot's TLS edits.

``deploy/backup/install_state_backup.sh`` is the repair: the same four steps,
callable through that allowlist.  These tests run the SHIPPED script against
stub ``sudo``/``install``/``systemctl`` that record an ordered command log, so
what is asserted is what the file actually does rather than what it says.

The stub sudo enforces the production allowlist, which is what makes the first
test a reproduction rather than an assertion.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "deploy" / "backup" / "install_state_backup.sh"
HARDENING = REPO / "deploy" / "apply_hardening.sh"

# Exactly what production permits, measured — not a plausible-looking subset.
PROD_SUDO_ALLOWLIST = ("systemctl", "journalctl", "install", "chown")


def _stub_bin(tmp_path: Path) -> tuple[Path, Path]:
    """A PATH of stubs that log their invocation, plus the log they write to."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "cmd.log"

    # sudo enforces the production allowlist and refuses everything else, so a
    # script that reaches for a root shell FAILS here exactly as it does on the
    # box.
    (bindir / "sudo").write_text(
        "#!/usr/bin/env bash\n"
        'args=(); for a in "$@"; do [[ "$a" == "-n" ]] || args+=("$a"); done\n'
        'cmd="$(basename "${args[0]}")"\n'
        f'case "$cmd" in {"|".join(PROD_SUDO_ALLOWLIST)}) ;; *)\n'
        '  echo "sudo: a password is required" >&2; exit 1 ;; esac\n'
        'exec "${args[@]}"\n'
    )
    for name in ("install", "systemctl", "chown"):
        (bindir / name).write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s %s\\n" "{name}" "$*" >> "$CMD_LOG"\n'
            # `install` must really create the file so idempotence is testable.
            f'if [[ "{name}" == "install" ]]; then\n'
            '  src=""; dest=""; prev=""\n'
            '  for a in "$@"; do\n'
            '    case "$a" in -*) ;; *) if [[ -f "$a" ]]; then src="$a"; else dest="$a"; fi ;; esac\n'
            '    prev="$a"\n'
            "  done\n"
            '  if [[ -n "$src" && -n "$dest" ]]; then mkdir -p "$(dirname "$dest")"; cp "$src" "$dest"; fi\n'
            "fi\n"
            "exit 0\n"
        )
    for f in bindir.iterdir():
        f.chmod(0o755)
    return bindir, log


def _app_dir(tmp_path: Path) -> Path:
    """A minimal checkout carrying only what the installer reads."""
    app = tmp_path / "app"
    (app / "deploy" / "backup").mkdir(parents=True)
    for name in (
        "backup_root_lib.sh",
        "riskit-state-backup.sh",
        "riskit-state-backup.service",
        "riskit-state-backup.timer",
    ):
        shutil.copy(REPO / "deploy" / "backup" / name, app / "deploy" / "backup" / name)
    return app


def _run(tmp_path: Path, app: Path, bindir: Path, log: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bindir}:{env['PATH']}",
            "CMD_LOG": str(log),
            "APP_DIR": str(app),
            "RISKIT_LIB_DIR": str(tmp_path / "lib"),
            "STATE_BACKUP_UNIT_DIR": str(tmp_path / "units"),
        }
    )
    return subprocess.run(
        ["bash", str(INSTALLER)], env=env, capture_output=True, text=True, timeout=120
    )


def _log_lines(log: Path) -> list[str]:
    return [ln for ln in log.read_text().splitlines() if ln.strip()] if log.exists() else []


# ── the reproduction ──────────────────────────────────────────────────────


def test_full_hardening_installer_cannot_run_under_the_production_allowlist(tmp_path):
    """RED: `sudo bash apply_hardening.sh` is refused by production's sudoers.

    This is the whole reason the bounded path exists. If this ever starts
    passing, the allowlist has been widened to include a root shell and the
    justification for a separate entry point should be revisited — the test
    would then be reporting a real change in the privilege model.
    """
    bindir, log = _stub_bin(tmp_path)
    env = dict(os.environ)
    env.update({"PATH": f"{bindir}:{env['PATH']}", "CMD_LOG": str(log)})
    proc = subprocess.run(
        ["sudo", "-n", "bash", str(HARDENING), "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "password is required" in proc.stderr


def test_bounded_installer_runs_under_the_same_allowlist(tmp_path):
    """GREEN: the bounded path completes using only allowlisted binaries."""
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    proc = _run(tmp_path, app, bindir, log)
    assert proc.returncode == 0, proc.stderr
    for line in _log_lines(log):
        assert line.split()[0] in PROD_SUDO_ALLOWLIST, f"used a non-allowlisted binary: {line}"


# ── the four steps, in order and with the right modes ─────────────────────


def test_library_is_installed_before_the_writer(tmp_path):
    """Ordering is load-bearing: the writer sources the library and dies without it.

    Writer-first leaves a window in which the 02:30 timer can fire against a
    writer whose library is absent — a silently lost generation. A library
    without the writer is harmless.
    """
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    assert _run(tmp_path, app, bindir, log).returncode == 0
    installs = [ln for ln in _log_lines(log) if ln.startswith("install ")]
    lib_at = next(i for i, ln in enumerate(installs) if "backup_root_lib.sh" in ln)
    writer_at = next(i for i, ln in enumerate(installs) if "riskit-state-backup.sh" in ln)
    assert lib_at < writer_at, "writer installed before its library:\n" + "\n".join(installs)


def test_ownership_and_modes(tmp_path):
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    assert _run(tmp_path, app, bindir, log).returncode == 0
    installs = [ln for ln in _log_lines(log) if ln.startswith("install ")]
    lib = next(ln for ln in installs if "backup_root_lib.sh" in ln)
    writer = next(ln for ln in installs if "riskit-state-backup.sh" in ln)
    # Sourced, never executed -> 0644. Executed -> 0755.
    assert "-o root -g root -m 0644" in lib, lib
    assert "-o root -g root -m 0755" in writer, writer


def test_units_are_installed_and_the_service_is_rendered(tmp_path):
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    assert _run(tmp_path, app, bindir, log).returncode == 0
    units = tmp_path / "units"
    service = units / "riskit-state-backup.service"
    timer = units / "riskit-state-backup.timer"
    assert service.is_file() and timer.is_file()
    # The timer is copied verbatim; it names neither path.
    assert (
        timer.read_text() == (app / "deploy" / "backup" / "riskit-state-backup.timer").read_text()
    )
    # The service is rendered onto this install's directories.
    assert str(tmp_path / "lib") in service.read_text()


def test_execstart_points_at_the_root_owned_copy_not_the_checkout(tmp_path):
    """The nightly must run the root-owned copy, never the deploy-user-writable
    checkout. A checkout ExecStart would mean anyone who can edit the checkout
    can choose what runs as root every night."""
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    assert _run(tmp_path, app, bindir, log).returncode == 0
    service = (tmp_path / "units" / "riskit-state-backup.service").read_text()
    exec_lines = [ln for ln in service.splitlines() if ln.startswith("ExecStart=")]
    assert exec_lines, service
    for ln in exec_lines:
        assert str(tmp_path / "lib") in ln, ln
        assert str(app) not in ln, f"ExecStart points into the checkout: {ln}"


def test_daemon_reload_precedes_enable_and_the_timer_is_armed(tmp_path):
    """systemd serves a cached unit otherwise, so enabling a freshly written
    unit without reloading arms the OLD one."""
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    assert _run(tmp_path, app, bindir, log).returncode == 0
    sysctl = [ln for ln in _log_lines(log) if ln.startswith("systemctl ")]
    reload_at = next(i for i, ln in enumerate(sysctl) if "daemon-reload" in ln)
    enable_at = next(i for i, ln in enumerate(sysctl) if "enable --now" in ln)
    assert reload_at < enable_at, sysctl
    assert "riskit-state-backup.timer" in sysctl[enable_at]


def test_state_backup_only_touches_nothing_else(tmp_path):
    """No nginx, no app units, no certificates, no healthcheck, no uptime."""
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    proc = _run(tmp_path, app, bindir, log)
    assert proc.returncode == 0
    # The COMMAND LOG, not stdout. The script's own banner says "no nginx, no
    # app units, no certificates", and scanning that would let a script pass
    # this test by claiming innocence. What it RAN is the evidence.
    executed = "\n".join(_log_lines(log))
    for forbidden in (
        "nginx",
        "sites-available",
        "sites-enabled",
        "letsencrypt",
        "certbot",
        "dynasty-frontend",
        "dynasty-healthcheck",
        "riskit-uptime",
    ):
        assert forbidden not in executed, f"bounded install touched {forbidden}"
    # And only the four intended destinations were written.
    written = sorted(p.name for p in (tmp_path / "lib").iterdir()) + sorted(
        p.name for p in (tmp_path / "units").iterdir()
    )
    assert written == [
        "backup_root_lib.sh",
        "riskit-state-backup.sh",
        "riskit-state-backup.service",
        "riskit-state-backup.timer",
    ], written


def test_rerunning_is_idempotent(tmp_path):
    """A second run must not rewrite identical files — re-running an installer
    is how an operator checks state, and it should not churn root-owned files."""
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    assert _run(tmp_path, app, bindir, log).returncode == 0
    log.write_text("")
    proc = _run(tmp_path, app, bindir, log)
    assert proc.returncode == 0
    assert not [ln for ln in _log_lines(log) if ln.startswith("install ")], _log_lines(log)
    assert "up-to-date" in proc.stdout


# ── one owner, structurally ───────────────────────────────────────────────


def test_apply_hardening_delegates_instead_of_carrying_its_own_copy(tmp_path):
    """Two copies of "which files, in which order, with which modes" drift, and
    drift here installs a writer without its library."""
    text = HARDENING.read_text()
    assert "install_state_backup.sh" in text, "apply_hardening.sh no longer sources the owner"
    assert "state_backup_install_scripts" in text
    assert "state_backup_install_units" in text
    # The install calls themselves must be gone, not merely supplemented.
    assert 'install_priv_script "${APP_DIR}/deploy/backup/backup_root_lib.sh"' not in text
    assert 'install_priv_script "${APP_DIR}/deploy/backup/riskit-state-backup.sh"' not in text
    assert '"/etc/systemd/system/riskit-state-backup.service"' not in text
    assert '"/etc/systemd/system/riskit-state-backup.timer"' not in text


@pytest.mark.parametrize("name", ["backup_root_lib.sh", "riskit-state-backup.sh"])
def test_installed_sources_are_the_canonical_checkout_copies(tmp_path, name):
    """What lands under the lib dir must be byte-identical to the checkout, so
    a hash comparison on production is a meaningful check rather than a
    coincidence."""
    app = _app_dir(tmp_path)
    bindir, log = _stub_bin(tmp_path)
    assert _run(tmp_path, app, bindir, log).returncode == 0
    assert (tmp_path / "lib" / name).read_bytes() == (
        REPO / "deploy" / "backup" / name
    ).read_bytes()
