"""Convergence and live-verification, exercised against a temporary host.

This is the RED→GREEN suite for the deployment-truth gap: a fully green
deploy of #812 left production on soft ``LimitNOFILE`` 1024 and left
``dynasty-healthcheck.timer`` at ``LoadState=not-found``.  Both controls
shipped in Git; neither reached the host; the deploy reported success.

Everything here drives the **real** functions in
``deploy/reconcile-runtime-controls.sh`` — sourced, not reimplemented.
The only things faked are the two commands that would otherwise touch a
real init system:

* ``sudo`` — a pass-through, because these tests already run as root.
  Faking it here rather than bypassing ``_rc_sudo`` keeps the real
  allowlist in the path, so an unauthorized binary is still refused.
* ``systemctl`` — a small state machine over a directory.  ``show``
  answers from seeded files, ``enable --now`` refuses a unit that is not
  installed (as systemd does) and otherwise records enabled+active, and
  every invocation is logged so ``daemon-reload`` can be asserted on.

``install``, ``sed``, ``grep``, ``cmp`` and ``stat`` are the real
binaries writing to a real (temporary) filesystem tree, so ownership and
mode assertions mean what they say.

The unit directory, ``/proc``, the library directory and the required
watchdog owner are redirected through ``SYSTEMD_UNIT_DIR`` /
``RC_PROC_DIR`` / ``RISKIT_LIB_DIR`` / ``RC_WATCHDOG_OWNER`` — all of
which the reconciler ignores unless the harness sets
``RC_ALLOW_TEST_OVERRIDES=1``.  Production takes constants, and
``tests/deploy/test_rollback_first_deploy.py`` pins that.
"""

from __future__ import annotations

import grp
import os
import pwd
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RECONCILER = REPO / "deploy" / "reconcile-runtime-controls.sh"
SYSD = REPO / "deploy" / "systemd"

SERVICE_NAME = "brisket"  # deliberately not "dynasty"
APP_USER = "briskuser"

# The watchdog must be owned by the user that EXECUTES it — root in
# production.  CI runs as an unprivileged user and cannot create a
# root-owned file, so the suite tells the reconciler which owner to
# require rather than skipping the install/verify path that matters.
# ``TestProductionCannotBeWeakenedByInheritedEnvironment`` (in
# test_rollback_first_deploy.py) pins that production takes root:root
# regardless of what is exported.
WATCHDOG_OWNER = (
    "root:root"
    if os.geteuid() == 0
    else f"{pwd.getpwuid(os.geteuid()).pw_name}:{grp.getgrgid(os.getegid()).gr_name}"
)

FAKE_SUDO = """#!/usr/bin/env bash
# Passwordless sudo stand-in.  These tests run as root, so the faithful
# behaviour of `sudo -n <bin> ...` is simply to run it.
[[ "${1:-}" == "-n" ]] && shift
exec "$@"
"""

# What production's systemd reports for the loaded monotonic schedule.
# Two entries, one per timer directive in dynasty-healthcheck.timer, each
# printed on its own line by `systemctl show --value`.  The recurring one
# is OnUnitActiveUSec; OnBootUSec fires once per boot and re-arms nothing.
FAKE_TIMERS_MONOTONIC = (
    "{ OnBootUSec=3min ; next_elapse=Thu 2026-08-13 08:39:21 CEST }\n"
    "{ OnUnitActiveUSec=1min ; next_elapse=Thu 2026-08-13 08:39:21 CEST }"
)

FAKE_SYSTEMCTL = """#!/usr/bin/env bash
# Minimal systemctl state machine.  State lives in $FAKE_SYSTEMCTL_STATE.
set -uo pipefail
state="${FAKE_SYSTEMCTL_STATE}"
mkdir -p "${state}/units"
printf '%s\\n' "$*" >> "${state}/calls.log"

cmd="${1:-}"; shift || true
case "${cmd}" in
  daemon-reload)
    exit 0
    ;;
  show)
    unit="${1:-}"; shift || true
    prop=""
    while (( $# )); do
      case "$1" in
        -p) prop="${2:-}"; shift 2 ;;
        --value) shift ;;
        *) shift ;;
      esac
    done
    f="${state}/units/${unit}.${prop}"
    if [[ -f "${f}" ]]; then cat "${f}"; else printf '\\n'; fi
    # One-step transition: a `.next` file makes THIS read return the
    # current value and every later read return the queued one, so a
    # test can model a state that resolves while the verifier re-reads.
    if [[ -f "${f}.next" ]]; then mv "${f}.next" "${f}"; fi
    exit 0
    ;;
  enable)
    now=false; unit=""
    while (( $# )); do
      case "$1" in
        --now) now=true; shift ;;
        *) unit="$1"; shift ;;
      esac
    done
    # systemd refuses to enable a unit file that is not installed.
    if [[ ! -f "${SYSTEMD_UNIT_DIR}/${unit}" ]]; then
      printf 'Failed to enable unit: Unit file %s does not exist.\\n' "${unit}" >&2
      exit 1
    fi
    printf 'loaded\\n'  > "${state}/units/${unit}.LoadState"
    printf 'enabled\\n' > "${state}/units/${unit}.UnitFileState"
    if [[ "${now}" == "true" ]]; then
      printf 'active\\n' > "${state}/units/${unit}.ActiveState"
      # A monotonic-base timer (OnBootSec/OnUnitActiveSec) leaves the
      # REALTIME field empty and populates the MONOTONIC one, pretty-
      # printed as a timespan.  Measured on production 2026-08-13.
      printf '\\n' > "${state}/units/${unit}.NextElapseUSecRealtime"
      printf '2w 3d 2h 8min 32.168902s\\n' > "${state}/units/${unit}.NextElapseUSecMonotonic"
      printf 'Thu 2026-08-13 04:16:02 CEST\\n' > "${state}/units/${unit}.LastTriggerUSec"
      printf '%s\\n' "${FAKE_TIMERS_MONOTONIC}" > "${state}/units/${unit}.TimersMonotonic"
    fi
    svc="${unit%.timer}.service"
    if [[ -f "${SYSTEMD_UNIT_DIR}/${svc}" ]]; then
      printf 'loaded\\n' > "${state}/units/${svc}.LoadState"
      # A Type=oneshot triggered unit at rest between firings.
      printf 'inactive\\n' > "${state}/units/${svc}.ActiveState"
      printf 'dead\\n'     > "${state}/units/${svc}.SubState"
    fi
    exit 0
    ;;
esac
exit 0
"""

# sed that emits a plausible-looking partial unit and then FAILS.  It has
# to look plausible: no placeholder survives and the file is non-empty,
# so nothing except an explicit exit-status check can catch it.
FAKE_FAILING_SED = """#!/usr/bin/env bash
printf '[Unit]\\nDescription=truncated render\\n'
exit 2
"""

LIMITS_TEMPLATE = """Limit                     Soft Limit           Hard Limit           Units
Max open files            {soft}                 {hard}               files
"""


class Host:
    """A throwaway host: unit dir, lib dir, /proc, fake binaries, repo."""

    MAIN_PID = "4242"

    def __init__(self, root: Path):
        self.root = root
        self.repo = root / "srv" / "app"
        self.sysd = self.repo / "deploy" / "systemd"
        self.unit_dir = root / "etc" / "systemd" / "system"
        self.lib_dir = root / "usr" / "local" / "lib" / "riskit"
        self.proc = root / "proc"
        self.bin = root / "bin"
        self.state = root / "systemctl-state"

        for d in (
            self.sysd,
            self.unit_dir,
            self.lib_dir,
            self.proc,
            self.bin,
            self.state / "units",
        ):
            d.mkdir(parents=True, exist_ok=True)

        for name in (
            "dynasty.service.template",
            "dynasty-healthcheck.sh",
            "dynasty-healthcheck.service",
            "dynasty-healthcheck.timer",
        ):
            shutil.copy2(SYSD / name, self.sysd / name)

        self._write_exe(self.bin / "sudo", FAKE_SUDO)
        self._write_exe(self.bin / "systemctl", FAKE_SYSTEMCTL)

        # Production's observed pre-repair state, unless a test changes it.
        self.set_unit_state(
            "dynasty-healthcheck.timer",
            LoadState="not-found",
            ActiveState="inactive",
            UnitFileState="",
        )
        self.set_unit_state("dynasty-healthcheck.service", LoadState="not-found")
        self.set_unit_state(SERVICE_NAME, MainPID=self.MAIN_PID)
        self.set_limits(soft="8192", hard="524288")

    # ── fixture plumbing ────────────────────────────────────────────
    @staticmethod
    def _write_exe(path: Path, body: str) -> None:
        path.write_text(body)
        path.chmod(0o755)

    def set_unit_state(self, unit: str, **props: str) -> None:
        for prop, value in props.items():
            (self.state / "units" / f"{unit}.{prop}").write_text(value + "\n")

    def queue_unit_state(self, unit: str, **props: str) -> None:
        """Value the NEXT read of this property switches to."""
        for prop, value in props.items():
            (self.state / "units" / f"{unit}.{prop}.next").write_text(value + "\n")

    def set_limits(
        self, *, soft: str, hard: str, proc_soft: str | None = None, proc_hard: str | None = None
    ) -> None:
        """Seed what systemd DECLARES and what the kernel reports."""
        self.set_unit_state(SERVICE_NAME, LimitNOFILESoft=soft, LimitNOFILE=hard)
        pid_dir = self.proc / self.MAIN_PID
        pid_dir.mkdir(parents=True, exist_ok=True)
        (pid_dir / "limits").write_text(
            LIMITS_TEMPLATE.format(soft=proc_soft or soft, hard=proc_hard or hard)
        )

    @property
    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "SERVICE_NAME": SERVICE_NAME,
            "APP_USER": APP_USER,
            "APP_DIR": str(self.repo),
            "VENV_DIR": str(self.root / "srv" / "venv"),
            "RISKIT_LIB_DIR": str(self.lib_dir),
            "SYSTEMD_UNIT_DIR": str(self.unit_dir),
            "RC_PROC_DIR": str(self.proc),
            "SYSTEMCTL_BIN": str(self.bin / "systemctl"),
            "INSTALL_BIN": "/usr/bin/install",
            # Production ignores these unless the harness opts in.
            "RC_ALLOW_TEST_OVERRIDES": "1",
            "RC_WATCHDOG_OWNER": WATCHDOG_OWNER,
            "FAKE_SYSTEMCTL_STATE": str(self.state),
            "FAKE_TIMERS_MONOTONIC": FAKE_TIMERS_MONOTONIC,
        }

    def run(self, func: str, env_extra: dict[str, str] | None = None):
        """Call one of the reconciler's entry points against this host."""
        return self.run_snippet(f"{func} {self.repo!s}", env_extra)

    def run_snippet(self, body: str, env_extra: dict[str, str] | None = None):
        """Source the real reconciler and run `body` against this host."""
        script = textwrap.dedent(f"""\
            set -uo pipefail
            source {RECONCILER!s}
            {body}
            """)
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            env={**self.env, **(env_extra or {})},
        )

    # ── inspection ──────────────────────────────────────────────────
    @property
    def backend_unit(self) -> Path:
        return self.unit_dir / f"{SERVICE_NAME}.service"

    @property
    def watchdog(self) -> Path:
        return self.lib_dir / "dynasty-healthcheck.sh"

    @property
    def calls(self) -> list[str]:
        log = self.state / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def converge(self):
        """Bring the host to a fully reconciled state (the happy path)."""
        r = self.run("reconcile_runtime_controls")
        assert r.returncode == 0, r.stdout + r.stderr
        return r


@pytest.fixture
def host(tmp_path):
    return Host(tmp_path)


# ═══ convergence ════════════════════════════════════════════════════


class TestItConvergesTheHost:
    def test_absent_state_converges(self, host):
        """Nothing installed at all — the greenfield case."""
        assert not host.backend_unit.exists()
        assert not host.watchdog.exists()

        r = host.converge()

        assert host.backend_unit.exists()
        assert host.watchdog.exists()
        assert "LimitNOFILE=8192:524288" in host.backend_unit.read_text()
        assert "__APP_DIR__" not in host.backend_unit.read_text()
        assert f"User={APP_USER}" in host.backend_unit.read_text()
        assert (host.unit_dir / "dynasty-healthcheck.service").exists()
        assert (host.unit_dir / "dynasty-healthcheck.timer").exists()
        assert "reconciled" in r.stdout

    def test_a_stale_backend_unit_converges(self, host):
        """THE PRODUCTION SHAPE: the unit exists, so the old deploy
        returned — while it still carried the 1024 default that EMFILE
        was raised against."""
        host.backend_unit.write_text(
            "[Unit]\nDescription=old\n[Service]\n" f"User={APP_USER}\nExecStart=/bin/true\n"
        )
        stale = host.backend_unit.read_text()

        host.converge()

        assert host.backend_unit.read_text() != stale
        assert "LimitNOFILE=8192:524288" in host.backend_unit.read_text()

    def test_a_stale_watchdog_converges(self, host):
        """An installed watchdog from before the FD watch existed."""
        host.watchdog.write_text("#!/bin/sh\n# old watchdog, no fd_watch\nexit 0\n")
        host.watchdog.chmod(0o755)

        host.converge()

        text = host.watchdog.read_text()
        assert "fd_watch" in text
        for threshold in ("FD_WARN:-256", "FD_CRIT:-512", "FD_EMERG:-768"):
            assert threshold in text
        stat = host.watchdog.stat()
        owner = f"{pwd.getpwuid(stat.st_uid).pw_name}:{grp.getgrgid(stat.st_gid).gr_name}"
        assert owner == WATCHDOG_OWNER
        assert oct(stat.st_mode)[-3:] == "755"

    def test_absent_healthcheck_units_converge(self, host):
        host.converge()

        svc = (host.unit_dir / "dynasty-healthcheck.service").read_text()
        assert f"HEALTH_SERVICE={SERVICE_NAME}" in svc, "watchdog targets the wrong backend"
        assert svc.count(f"ExecStart={host.lib_dir}/dynasty-healthcheck.sh") == 1

    def test_a_disabled_inactive_timer_ends_enabled_and_active(self, host):
        """`LoadState=not-found` is exactly what production reported."""
        host.converge()

        assert any(c.startswith("enable --now") for c in host.calls)
        r = host.run("verify_runtime_controls")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "active" in r.stdout

    def test_a_converged_host_is_idempotent(self, host):
        host.converge()
        before = {
            p: p.read_bytes()
            for p in (
                host.backend_unit,
                host.watchdog,
                host.unit_dir / "dynasty-healthcheck.service",
                host.unit_dir / "dynasty-healthcheck.timer",
            )
        }

        second = host.run("reconcile_runtime_controls")

        assert second.returncode == 0, second.stdout + second.stderr
        assert "installing" not in second.stdout, "reinstalled an already-correct artifact"
        assert second.stdout.count("up-to-date") == 4
        for path, content in before.items():
            assert path.read_bytes() == content

    def test_daemon_reload_happens_only_when_a_unit_changed(self, host):
        host.converge()
        assert sum(c == "daemon-reload" for c in host.calls) == 1

        (host.state / "calls.log").unlink()
        host.run("reconcile_runtime_controls")
        assert "daemon-reload" not in host.calls, "reloaded systemd with nothing changed"

        # ...and it comes BACK when something drifts again.
        (host.state / "calls.log").unlink()
        host.backend_unit.write_text("[Unit]\nDescription=drifted\n")
        host.run("reconcile_runtime_controls")
        reload_at = host.calls.index("daemon-reload")
        enable_at = next(i for i, c in enumerate(host.calls) if c.startswith("enable"))
        assert reload_at < enable_at, "started a unit before reloading its new definition"


# ═══ live verification ══════════════════════════════════════════════


class TestVerificationReadsLiveStateNotRepositoryIntent:
    def test_a_correctly_converged_host_verifies(self, host):
        host.converge()
        r = host.run("verify_runtime_controls")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "live runtime controls verified" in r.stdout

    def test_a_systemd_limit_mismatch_fails(self, host):
        """The exact production state: unit shipped, process on 1024."""
        host.converge()
        host.set_limits(soft="1024", hard="524288")

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "systemd limits 1024:524288, expected 8192:524288" in r.stderr

    def test_a_proc_limit_mismatch_fails(self, host):
        """systemd can declare one thing while the process runs another —
        a drop-in, or simply not having been restarted.  EMFILE follows
        the process."""
        host.converge()
        host.set_limits(soft="8192", hard="524288", proc_soft="1024")

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "/limits 1024:524288, expected 8192:524288" in r.stderr

    def test_an_unreadable_installed_watchdog_fails(self, host):
        host.converge()
        host.watchdog.unlink()

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "cannot verify the watchdog that actually runs" in r.stderr

    def test_a_missing_fd_threshold_fails(self, host):
        """Verification must read the INSTALLED executable, not the
        template — that conflation is the whole defect."""
        host.converge()
        host.watchdog.write_text(
            host.watchdog.read_text().replace("FD_EMERG:-768", "FD_EMERG:-99999")
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "missing threshold FD_EMERG:-768" in r.stderr

    def test_an_inactive_timer_cannot_silently_pass(self, host):
        host.converge()
        host.set_unit_state("dynasty-healthcheck.timer", ActiveState="inactive")

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "ActiveState=inactive" in r.stderr

    def test_a_missing_desired_limitnofile_fails(self, host):
        """Not a warning.  'Nothing to verify' and 'verified' must not
        read the same, and a rollback to a pre-#812 revision must refuse
        rather than quietly restore the limit that failed.

        Converge FIRST so every other check is green: otherwise the
        missing limit is not what makes this fail, and the test would
        pass against the warn-only version for the wrong reason.
        """
        host.converge()
        template = host.sysd / "dynasty.service.template"
        template.write_text(
            "\n".join(
                ln for ln in template.read_text().splitlines() if not ln.startswith("LimitNOFILE=")
            )
            + "\n"
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "declares no LimitNOFILE" in r.stderr
        assert "nothing to verify" not in (r.stdout + r.stderr).lower()

    def test_a_mangled_desired_limitnofile_fails(self, host):
        host.converge()
        template = host.sysd / "dynasty.service.template"
        template.write_text(
            template.read_text().replace("LimitNOFILE=8192:524288", "LimitNOFILE=infinity")
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "not a systemd soft[:hard] value" in r.stderr


# ═══ fail-closed edges ══════════════════════════════════════════════


class TestAFailedRenderIsNeverInstalled:
    """`set -uo pipefail` without errexit means a failing command inside
    a function returns whatever ran last.  The original renderer ran
    `sed`, then an unresolved-placeholder `if`; a failing `sed` left a
    truncated file, the `if` found no placeholders, and the function
    returned 0.  A broken render reported success."""

    @pytest.fixture
    def broken_sed(self, host):
        Host._write_exe(host.bin / "sed", FAKE_FAILING_SED)
        return host

    def test_the_backend_renderer_returns_nonzero(self, broken_sed):
        r = broken_sed.run_snippet(
            "out=$(mktemp); _rc_render_backend_unit "
            f'{broken_sed.sysd}/dynasty.service.template "$out"; echo "rc=$?"'
        )
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "refusing to install a partial unit" in r.stderr

    def test_the_hardening_renderer_returns_nonzero(self, broken_sed):
        r = broken_sed.run_snippet(
            "out=$(mktemp); _rc_render_hardening_unit "
            f'{broken_sed.sysd}/dynasty-healthcheck.timer "$out"; echo "rc=$?"'
        )
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "refusing to install a partial unit" in r.stderr

    def test_reconciliation_fails_and_installs_no_unit(self, broken_sed):
        r = broken_sed.run("reconcile_runtime_controls")

        assert r.returncode != 0, r.stdout
        assert "runtime reconciliation FAILED" in r.stderr
        assert (
            not broken_sed.backend_unit.exists()
        ), "a partial render reached the systemd unit directory"
        assert not (broken_sed.unit_dir / "dynasty-healthcheck.timer").exists()
        assert not (broken_sed.unit_dir / "dynasty-healthcheck.service").exists()
        assert (
            f"installing: {broken_sed.unit_dir}" not in r.stdout
        ), "install was invoked for a unit whose render failed"

    def test_a_previously_good_unit_is_not_overwritten_by_a_failed_render(self, broken_sed):
        """Fail closed means the host keeps working, not that it is left
        holding two lines of truncated unit file."""
        broken_sed.backend_unit.write_text(
            "[Unit]\nDescription=good\n[Service]\nExecStart=/bin/true\n"
        )
        good = broken_sed.backend_unit.read_bytes()

        r = broken_sed.run("reconcile_runtime_controls")

        assert r.returncode != 0
        assert broken_sed.backend_unit.read_bytes() == good

    def test_an_empty_staged_file_is_refused_even_if_the_renderer_passed(self, host):
        """Structural backstop, independent of who staged the file."""
        r = host.run_snippet(
            'empty=$(mktemp); _rc_install_if_different "$empty" '
            f'"{host.unit_dir}/never.service" 0644; echo "rc=$?"'
        )
        assert "rc=1" in r.stdout, r.stdout + r.stderr
        assert "empty/missing source" in r.stderr
        assert not (host.unit_dir / "never.service").exists()


class TestUnauthorizedPrivilegeIsRefusedBeforeSudo:
    def test_reconciliation_refuses_an_unauthorized_install_binary(self, host):
        """`_rc_sudo` is enforcement, not documentation: point the
        install step at a binary outside the NOPASSWD set and the
        reconciler must refuse it rather than discover it at runtime as
        'a password is required'."""
        r = host.run("reconcile_runtime_controls", env_extra={"INSTALL_BIN": "/bin/cp"})

        assert r.returncode != 0
        assert "refusing to sudo 'cp'" in r.stderr
        assert not host.backend_unit.exists()

    def test_the_helper_itself_exits_126(self, host):
        r = host.run_snippet('_rc_sudo /usr/bin/stat -c %U /etc/hostname; echo "rc=$?"')
        assert "rc=126" in r.stdout, r.stdout + r.stderr
        assert "not in the authorized set" in r.stderr


class TestTheTimerGateReadsTheRightNextElapseProperty:
    """The #813 deploy failed here, on a perfectly scheduled watchdog.

    systemd exposes two next-elapse properties and populates the one
    matching the timer's BASE.  ``dynasty-healthcheck.timer`` ships
    ``OnBootSec`` + ``OnUnitActiveSec`` — both MONOTONIC — so
    ``NextElapseUSecRealtime`` is empty by construction and
    ``NextElapseUSecMonotonic`` carries the schedule.  Measured on
    production 2026-08-13, an hour into the timer firing every 60 s:

        timer.NextElapseUSecRealtime    (empty)
        timer.NextElapseUSecMonotonic   2w 3d 2h 8min 32.168902s
        timer.LastTriggerUSec           Thu 2026-08-13 04:16:02 CEST

    So this was never a first-activation race — the realtime field never
    becomes non-empty for this unit.
    """

    def test_realtime_zero_with_a_monotonic_next_passes(self, host):
        host.converge()
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            NextElapseUSecRealtime="0",
            NextElapseUSecMonotonic="2w 3d 2h 8min 32.168902s",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "live runtime controls verified" in r.stdout

    def test_realtime_empty_with_a_monotonic_next_passes(self, host):
        """Production's actual shape."""
        host.converge()
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            NextElapseUSecRealtime="",
            NextElapseUSecMonotonic="2w 3d 2h 8min 32.168902s",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode == 0, r.stdout + r.stderr

    def test_no_monotonic_next_fails_after_the_bounded_retry(self, host):
        """The retry is defense in depth for an activation-settling
        window, not a way to eventually accept nothing."""
        host.converge()
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            NextElapseUSecRealtime="",
            NextElapseUSecMonotonic="0",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr

    def test_an_empty_monotonic_next_also_fails(self, host):
        host.converge()
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            NextElapseUSecRealtime="",
            NextElapseUSecMonotonic="",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr

    def test_loaded_enabled_active_is_not_enough_without_a_future_run(self, host):
        """A timer can be all three and still have nothing scheduled."""
        host.converge()
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            LoadState="loaded",
            ActiveState="active",
            UnitFileState="enabled",
            NextElapseUSecMonotonic="0",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr

    def test_a_past_trigger_is_not_accepted_as_future_scheduling(self, host):
        """LastTriggerUSec says the timer HAS run, not that it WILL."""
        host.converge()
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            NextElapseUSecMonotonic="0",
            LastTriggerUSec="Thu 2026-08-13 04:16:02 CEST",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0, "a past trigger was accepted as proof of future scheduling"

    def test_the_verifier_never_gates_on_the_realtime_property(self):
        """Read as code: the realtime value may be logged, never tested."""
        code = re.sub(r"#.*", "", RECONCILER.read_text())
        gating = [
            ln
            for ln in code.splitlines()
            if "NextElapseUSecRealtime" in ln and ("rc=1" in ln or "_rc_err" in ln)
        ]
        assert not gating, f"realtime property still gates: {gating}"


class TestTheInfinityTransitionIsDecidedNotSlept:
    """A running watchdog has no next activation, and that is not a fault.

    While the ``Type=oneshot`` healthcheck executes, systemd has nothing
    to compute a next elapse from and answers ``infinity``.  Observed on
    production 2026-08-13T06:29:24Z, six seconds after a LastTriggerUSec
    of 08:29:18 CEST, on a timer that had been firing every 60 s for
    hours::

        timer.NextElapseUSecMonotonic   infinity
        service.ActiveState/SubState    activating/start

    The #814 gate rejected ``infinity`` outright, so a healthy deploy
    could be failed by where its read landed in the cadence.  Waiting it
    out is the wrong fix — ``TimeoutStartSec=90`` bounds the window at
    far longer than any deploy should sleep — so the state is decided
    from live properties instead.

    The excuse is narrow by construction: ``infinity`` passes ONLY while
    the triggered unit is genuinely executing AND the timer's recurring
    monotonic schedule is still loaded.  Neither is inferred from the
    unit file in this checkout.
    """

    EXECUTING = {"ActiveState": "activating", "SubState": "start"}
    AT_REST = {"ActiveState": "inactive", "SubState": "dead"}
    FAILED = {"ActiveState": "failed", "SubState": "failed"}
    # A schedule with no recurring base: fires once per boot, then never.
    BOOT_ONLY = "{ OnBootUSec=3min ; next_elapse=Thu 2026-08-13 08:39:21 CEST }"

    @staticmethod
    def _seed(host, *, next_mono, service, timers_monotonic=FAKE_TIMERS_MONOTONIC):
        host.converge()
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            NextElapseUSecRealtime="",
            NextElapseUSecMonotonic=next_mono,
            TimersMonotonic=timers_monotonic,
        )
        host.set_unit_state("dynasty-healthcheck.service", **service)

    # 1 ─────────────────────────────────────────────────────────────────
    def test_finite_next_with_the_service_at_rest_passes(self, host):
        """The steady state: between firings, nothing is running."""
        self._seed(host, next_mono="2w 3d 2h 8min 32.168902s", service=self.AT_REST)

        r = host.run("verify_runtime_controls")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "live runtime controls verified" in r.stdout

    # 2 ─────────────────────────────────────────────────────────────────
    def test_infinity_while_the_service_executes_passes(self, host):
        """Production's observed transition, reproduced verbatim."""
        self._seed(host, next_mono="infinity", service=self.EXECUTING)

        r = host.run("verify_runtime_controls")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "live runtime controls verified" in r.stdout
        assert "no next activation while" in r.stdout, (
            "the transition passed silently — a reader cannot tell this run "
            "from one with a real next elapse"
        )

    # 3 ─────────────────────────────────────────────────────────────────
    def test_infinity_with_the_service_inactive_fails(self, host):
        """Nothing running and nothing scheduled is a dead watchdog."""
        self._seed(host, next_mono="infinity", service=self.AT_REST)

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr
        assert "inactive/dead" in r.stderr

    # 4 ─────────────────────────────────────────────────────────────────
    def test_infinity_with_the_service_failed_fails(self, host):
        """A failed unit is emphatically not 'currently executing'."""
        self._seed(host, next_mono="infinity", service=self.FAILED)

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr

    # 5 ─────────────────────────────────────────────────────────────────
    def test_infinity_while_executing_without_a_recurring_schedule_fails(self, host):
        """Executing excuses a missing next elapse only if another one
        is coming.  With no recurring base, this run is the last one."""
        self._seed(
            host,
            next_mono="infinity",
            service=self.EXECUTING,
            timers_monotonic=self.BOOT_ONLY,
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no recurring monotonic schedule" in r.stderr

    # 6 ─────────────────────────────────────────────────────────────────
    def test_zero_next_with_the_service_inactive_fails(self, host):
        self._seed(host, next_mono="0", service=self.AT_REST)

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr

    # 7 ─────────────────────────────────────────────────────────────────
    def test_empty_next_with_the_service_inactive_fails(self, host):
        self._seed(host, next_mono="", service=self.AT_REST)

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr

    # 8 ─────────────────────────────────────────────────────────────────
    def test_a_past_trigger_does_not_independently_create_a_pass(self, host):
        """A recent LastTriggerUSec is the most tempting wrong answer:
        it is present, it looks like health, and it says only that the
        timer HAS run.  Paired here with the strongest possible context —
        a live recurring schedule — so nothing but the executing check
        can be what fails it."""
        self._seed(host, next_mono="infinity", service=self.AT_REST)
        host.set_unit_state(
            "dynasty-healthcheck.timer",
            LastTriggerUSec="Thu 2026-08-13 08:38:21 CEST",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0, "a past trigger was accepted as proof of future scheduling"

    # 9 ─────────────────────────────────────────────────────────────────
    def test_zero_next_while_executing_still_fails(self, host):
        """Only `infinity` is a transition.  A zero next-elapse is not
        excused by a running service — that pairing is not something a
        healthy timer produces, and widening the excuse to cover it would
        make the gate unfalsifiable during any execution."""
        self._seed(host, next_mono="0", service=self.EXECUTING)

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no future monotonic activation" in r.stderr

    # 10 ────────────────────────────────────────────────────────────────
    def test_a_finite_next_does_not_excuse_a_missing_recurring_schedule(self, host):
        """The schedule is checked whatever the next-elapse says: a timer
        that lost its recurring base reports a perfectly finite next
        elapse right up until the last time it ever fires."""
        self._seed(
            host,
            next_mono="2w 3d 2h 8min 32.168902s",
            service=self.AT_REST,
            timers_monotonic=self.BOOT_ONLY,
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no recurring monotonic schedule" in r.stderr

    # 11 ────────────────────────────────────────────────────────────────
    def test_a_transition_that_resolves_passes_on_the_real_next_elapse(self, host):
        """The ordinary case must not need the excuse at all.

        A real execution is ~0.2 s wide, so by the time the verifier
        re-reads, the timer has re-armed.  This models exactly that: the
        first read sees the transition, the next sees a live next-elapse.
        It must pass as branch A — silently, on the real value — rather
        than as an accepted transition, because that is what keeps the
        common path off `TimersMonotonic`'s behaviour mid-execution,
        which was never captured.
        """
        self._seed(host, next_mono="infinity", service=self.EXECUTING)
        host.queue_unit_state(
            "dynasty-healthcheck.timer",
            NextElapseUSecMonotonic="2w 3d 2h 8min 32.168902s",
        )
        host.queue_unit_state(
            "dynasty-healthcheck.service", ActiveState="inactive", SubState="dead"
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "live runtime controls verified" in r.stdout
        assert (
            "no next activation while" not in r.stdout
        ), "passed via the transition excuse when a real next-elapse was available"

    # 12 ────────────────────────────────────────────────────────────────
    def test_executing_with_a_stale_finite_next_elapse_passes(self, host):
        """Executing does not imply `infinity`, which is easy to get
        backwards.  Observed on the host at 2026-08-13T07:50:45Z: the
        service was `activating/start` while the timer still advertised
        the PREVIOUS finite next-elapse, systemd not having recomputed
        it yet.  A gate keyed on 'executing means no next elapse' would
        have been wrong about that row; a finite value is a finite
        value."""
        self._seed(host, next_mono="2w 3d 7h 42min 14.209473s", service=self.EXECUTING)

        r = host.run("verify_runtime_controls")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "no next activation while" not in r.stdout

    # 13 ────────────────────────────────────────────────────────────────
    def test_an_empty_timers_monotonic_fails(self, host):
        """Missing is never healthy: a systemd that reports no monotonic
        timers at all has not told us the schedule is fine."""
        self._seed(
            host,
            next_mono="2w 3d 2h 8min 32.168902s",
            service=self.AT_REST,
            timers_monotonic="",
        )

        r = host.run("verify_runtime_controls")

        assert r.returncode != 0
        assert "no recurring monotonic schedule" in r.stderr
