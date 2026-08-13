"""The FIRST rollback past the reconciler must still reconcile.

The reconciler ships in the same change that starts reconciling runtime
controls, so the first rollback across it goes to a revision that does
not contain the implementation.  That is exactly the moment it matters:
the failed deploy has already installed the NEWER unit and watchdog, and
restoring old application code while leaving newer runtime controls on
the host is the drift this whole change exists to prevent.

The first version looked for the implementation in the checked-out tree,
found nothing, warned, and restarted anyway.

These tests drive the real ``deploy/rollback.sh`` against a git
repository built to that exact shape: a base commit with no reconciler,
a newer commit that introduces one, and a rollback from the newer to the
base.

``rollback.sh`` is a production entry point and scrubs the reconciler's
test seams, so the harness cannot redirect ``SYSTEMD_UNIT_DIR`` /
``RC_PROC_DIR`` / ``RC_WATCHDOG_OWNER`` into a sandbox — and deliberately
does not try.  The reconciler runs against the production constants
(``/etc/systemd/system``, ``/proc``, ``root:root``) and what is doubled
instead is the PRIVILEGED COMMAND LAYER: ``sudo`` resolves through PATH
to a stand-in that redirects ``systemctl``/``journalctl`` to sandbox
fakes and ``install`` to a recorder which writes nothing outside the
sandbox.  Assertions read that recorder, so they see exactly what a real
rollback would have asked root to do — including the owner it demanded.

A consequence worth stating: live verification cannot pass in a sandbox
(it reads real ``/proc/<MainPID>/limits`` and requires a genuinely
root-owned watchdog), so these runs end non-zero AT VERIFICATION.  That
is the point of interest here — everything the blocker is about has
already happened by then, and the convergence suite covers verification
separately by calling the functions directly.
"""

from __future__ import annotations

import grp
import os
import pwd
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ROLLBACK = REPO / "deploy" / "rollback.sh"
RECONCILER = REPO / "deploy" / "reconcile-runtime-controls.sh"
SYSD = REPO / "deploy" / "systemd"

SERVICE_NAME = "brisket"

WATCHDOG_OWNER = (
    "root:root"
    if os.geteuid() == 0
    else f"{pwd.getpwuid(os.geteuid()).pw_name}:{grp.getgrgid(os.getegid()).gr_name}"
)

# rollback.sh resolves its privileged binaries by ABSOLUTE path
# (/bin/systemctl, /usr/bin/journalctl), which PATH cannot shadow, so the
# sudo double redirects by basename to the sandbox copies.  That is what
# "a privileged systemctl" means in this harness — without it the real
# init system would be asked to daemon-reload.
FAKE_SUDO = """#!/usr/bin/env bash
# FAIL CLOSED.  Every privileged command must resolve to a double.
# Falling through to the real binary is not graceful degradation here:
# the first draft of this harness omitted the `install` double, fell
# through, and wrote real unit files into /etc/systemd/system on the
# machine running the suite.  A missing double is a broken harness.
[[ "${1:-}" == "-n" ]] && shift
bin="$1"; shift
base="$(basename "${bin}")"
if [[ ! -x "${FAKE_BIN_DIR}/${base}" ]]; then
  printf 'harness: no double for privileged command %s — refusing\n' "${base}" >&2
  exit 97
fi
exec "${FAKE_BIN_DIR}/${base}" "$@"
"""

# The privileged installer, recorded rather than performed.
#
# This is the seam the harness uses INSTEAD of the reconciler's test
# overrides: the reconciler asks root to install to the real
# /etc/systemd/system with the real required owner, and this records the
# request and mirrors the content under the sandbox.  Nothing is written
# outside it, and the recording is what the assertions read — so they
# observe exactly what a production rollback would have done.
#
# `-o`/`-g` are recorded and then dropped: honouring them would need
# root, and privilege is precisely what is being doubled.
FAKE_INSTALL = """#!/usr/bin/env bash
set -uo pipefail
printf '%s\n' "$*" >> "${FAKE_INSTALL_LOG}"
mode=""; owner=""; group=""; args=()
while (( $# )); do
  case "$1" in
    -m) mode="$2"; shift 2 ;;
    -o) owner="$2"; shift 2 ;;
    -g) group="$2"; shift 2 ;;
    -D) shift ;;
    *) args+=("$1"); shift ;;
  esac
done
src="${args[0]}"; dest="${args[1]}"
mirror="${FAKE_INSTALL_ROOT}${dest}"
mkdir -p "$(dirname "${mirror}")"
cp "${src}" "${mirror}"
[[ -n "${mode}" ]] && chmod "${mode}" "${mirror}"
exit 0
"""

# `--version` has to succeed: rollback.sh resolves its privileged
# binaries by probing `sudo -n <bin> --version`.
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
set -uo pipefail
state="${FAKE_SYSTEMCTL_STATE}"
mkdir -p "${state}/units"
printf '%s\\n' "$*" >> "${state}/calls.log"
cmd="${1:-}"; shift || true
case "${cmd}" in
  --version) echo "systemd 255 (fake)"; exit 0 ;;
  daemon-reload) exit 0 ;;
  is-active) exit 0 ;;
  restart) printf 'RESTARTED\\n' >> "${state}/calls.log"; exit 0 ;;
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
    printf 'loaded\\n'  > "${state}/units/${unit}.LoadState"
    printf 'enabled\\n' > "${state}/units/${unit}.UnitFileState"
    if [[ "${now}" == "true" ]]; then
      printf 'active\\n' > "${state}/units/${unit}.ActiveState"
      printf '\\n' > "${state}/units/${unit}.NextElapseUSecRealtime"
      printf '2w 3d 2h 8min 32.168902s\\n' > "${state}/units/${unit}.NextElapseUSecMonotonic"
    fi
    svc="${unit%.timer}.service"
    printf 'loaded\\n' > "${state}/units/${svc}.LoadState"
    exit 0
    ;;
esac
exit 0
"""

FAKE_JOURNALCTL = """#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && { echo "systemd 255 (fake)"; exit 0; }
exit 0
"""

LIMITS = """Limit                     Soft Limit           Hard Limit           Units
Max open files            8192                 524288               files
"""


class RollbackWorld:
    """A git repo shaped like the first deploy of the reconciler."""

    MAIN_PID = "4242"

    def __init__(self, root: Path):
        self.root = root
        self.app = root / "srv" / "app"
        self.unit_dir = root / "etc" / "systemd" / "system"
        self.lib_dir = root / "usr" / "local" / "lib" / "riskit"
        self.proc = root / "proc" / self.MAIN_PID
        self.bin = root / "bin"
        self.state = root / "systemctl-state"
        self.install_log = root / "install.log"
        self.mirror = root / "mirror"
        for d in (self.app, self.unit_dir, self.lib_dir, self.proc, self.bin, self.state / "units"):
            d.mkdir(parents=True, exist_ok=True)

        for name, body in (
            ("sudo", FAKE_SUDO),
            ("systemctl", FAKE_SYSTEMCTL),
            ("journalctl", FAKE_JOURNALCTL),
            ("install", FAKE_INSTALL),
        ):
            p = self.bin / name
            p.write_text(body)
            p.chmod(0o755)

        (self.proc / "limits").write_text(LIMITS)
        self._seed_units()
        self.base_rev = ""
        self.new_rev = ""

    def _seed_units(self):
        for unit, props in (
            (
                "dynasty-healthcheck.timer",
                {"LoadState": "not-found", "ActiveState": "inactive", "UnitFileState": ""},
            ),
            ("dynasty-healthcheck.service", {"LoadState": "not-found"}),
            (
                SERVICE_NAME,
                {"MainPID": self.MAIN_PID, "LimitNOFILESoft": "8192", "LimitNOFILE": "524288"},
            ),
        ):
            for k, v in props.items():
                (self.state / "units" / f"{unit}.{k}").write_text(v + "\n")

    # ── repository construction ─────────────────────────────────────
    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self.app, check=True, capture_output=True, text=True)

    def _copy_systemd(self):
        d = self.app / "deploy" / "systemd"
        d.mkdir(parents=True, exist_ok=True)
        for name in (
            "dynasty.service.template",
            "dynasty-healthcheck.sh",
            "dynasty-healthcheck.service",
            "dynasty-healthcheck.timer",
        ):
            shutil.copy2(SYSD / name, d / name)

    def build(self, *, target_keeps_artifacts: bool = True):
        """Base commit WITHOUT the reconciler, newer commit WITH it."""
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")
        # rollback.sh fetches `origin` before resolving the target.
        self._git("remote", "add", "origin", str(self.app))

        self._copy_systemd()
        if not target_keeps_artifacts:
            # A genuinely ancient target: no runtime artifacts at all.
            shutil.rmtree(self.app / "deploy" / "systemd")
            (self.app / "deploy").mkdir(exist_ok=True)
        (self.app / "app.txt").write_text("old application code\n")
        self._git("add", "-A")
        self._git("commit", "-qm", "base: before the reconciler existed")
        self.base_rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.app, capture_output=True, text=True, check=True
        ).stdout.strip()

        # The newer revision introduces the reconciler (this PR).
        self._copy_systemd()
        shutil.copy2(RECONCILER, self.app / "deploy" / "reconcile-runtime-controls.sh")
        (self.app / "app.txt").write_text("new application code\n")
        self._git("add", "-A")
        self._git("commit", "-qm", "new: introduces the runtime reconciler")
        self.new_rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.app, capture_output=True, text=True, check=True
        ).stdout.strip()

    def install_newer_runtime_controls(self):
        """What the failed deploy already did to the host."""
        (self.unit_dir / f"{SERVICE_NAME}.service").write_text(
            "[Unit]\nDescription=NEWER unit from the failed deploy\n"
            "[Service]\nLimitNOFILE=8192:524288\n"
        )
        for u in ("dynasty-healthcheck.service", "dynasty-healthcheck.timer"):
            (self.unit_dir / u).write_text(f"# NEWER {u} from the failed deploy\n")
        # The failed deploy installed ITS watchdog, which differs from the
        # target's.  Identical copies would make the reconciler report
        # "up-to-date" and never exercise the install path at all.
        newer = SYSD.joinpath("dynasty-healthcheck.sh").read_text()
        newer = newer.replace(
            "#!/usr/bin/env bash", "#!/usr/bin/env bash\n# NEWER watchdog from the failed deploy", 1
        )
        (self.lib_dir / "dynasty-healthcheck.sh").write_text(newer)

    # ── running the real script ─────────────────────────────────────
    def rollback(self, extra_env: dict[str, str] | None = None):
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "APP_DIR": str(self.app),
            "APP_USER": pwd.getpwuid(os.geteuid()).pw_name,
            "SERVICE_NAME": SERVICE_NAME,
            "VENV_DIR": str(self.root / "venv"),
            "RISKIT_LIB_DIR": str(self.lib_dir),
            "RUN_FRONTEND_BUILD": "false",
            "STRICT_LOCAL_HEALTH": "false",
            "FAKE_SYSTEMCTL_STATE": str(self.state),
            "FAKE_BIN_DIR": str(self.bin),
            "FAKE_INSTALL_LOG": str(self.install_log),
            "FAKE_INSTALL_ROOT": str(self.mirror),
            # NO reconciler test seams.  rollback.sh scrubs them, and the
            # harness does not try to smuggle them back in: the doubles
            # above are what make production constants observable.
            **(extra_env or {}),
        }
        return subprocess.run(
            ["bash", str(ROLLBACK), self.base_rev],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    @property
    def calls(self) -> list[str]:
        log = self.state / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    @property
    def installs(self) -> list[str]:
        """Every `install` the reconciler asked root to perform."""
        return self.install_log.read_text().splitlines() if self.install_log.exists() else []

    def installed_content(self, dest: str) -> str:
        """What WOULD have landed at an absolute destination."""
        return (self.mirror / dest.lstrip("/")).read_text()


@pytest.fixture
def world(tmp_path):
    return RollbackWorld(tmp_path)


class TestTheFirstRollbackPastTheReconciler:
    """The scenario that motivated the repair, end to end.

    Every run here ends non-zero at LIVE VERIFICATION — a sandbox cannot
    satisfy a real ``/proc/<MainPID>/limits`` or a genuinely root-owned
    watchdog.  Everything the blocker concerns has already happened by
    then, and the assertions target that, not the exit status.
    """

    def test_the_target_really_lacks_the_reconciler(self, world):
        """Guard on the fixture itself — if this stops being true the
        rest of the class proves nothing."""
        world.build()
        r = subprocess.run(
            ["git", "show", f"{world.base_rev}:deploy/reconcile-runtime-controls.sh"],
            cwd=world.app,
            capture_output=True,
            text=True,
        )
        assert r.returncode != 0, "the base commit contains the reconciler; scenario invalid"

    def test_the_implementation_is_preserved_before_the_checkout(self, world):
        world.build()
        world.install_newer_runtime_controls()

        r = world.rollback()

        assert "Preserved the current revision's runtime reconciler" in r.stdout
        assert "Reconciling runtime controls to the rollback revision" in r.stdout

    def test_the_target_revisions_unit_is_what_gets_installed(self, world):
        """The blocker: old code must not be restored under the newer
        deploy's runtime controls."""
        world.build()
        world.install_newer_runtime_controls()

        world.rollback()

        dest = f"/etc/systemd/system/{SERVICE_NAME}.service"
        assert any(
            dest in line for line in world.installs
        ), f"nothing was installed to {dest}; requests were: {world.installs}"
        rendered = world.installed_content(dest)
        assert "NEWER unit from the failed deploy" not in rendered
        assert f"User={pwd.getpwuid(os.geteuid()).pw_name}" in rendered

    def test_it_demands_the_production_owner_for_the_watchdog(self, world):
        """Read off what root was actually asked to do."""
        world.build()
        world.install_newer_runtime_controls()

        world.rollback()

        watchdog = [ln for ln in world.installs if "dynasty-healthcheck.sh" in ln]
        assert watchdog, f"watchdog never installed; requests were: {world.installs}"
        assert "-o root -g root" in watchdog[0], watchdog[0]
        assert "-m 0755" in watchdog[0], watchdog[0]

    def test_it_reconciles_before_restarting(self, world):
        """A unit installed after the restart is one the restored process
        never got."""
        world.build()
        world.install_newer_runtime_controls()

        world.rollback()

        calls = world.calls
        assert "RESTARTED" in calls
        assert calls.index("daemon-reload") < calls.index("RESTARTED")

    def test_verification_is_what_stops_it_not_reconciliation(self, world):
        """Distinguishes 'the sandbox cannot verify' from 'the repair
        does not work' — without this the non-zero exit is ambiguous."""
        world.build()
        world.install_newer_runtime_controls()

        r = world.rollback()

        assert r.returncode != 0
        assert "Runtime control reconciliation failed" not in r.stderr
        assert "Verifying LIVE runtime controls after rollback" in r.stdout

    def test_it_no_longer_warns_and_proceeds(self, world):
        """The blessed warn-path is gone for targets that CAN be
        reconciled by the preserved implementation."""
        world.build()
        world.install_newer_runtime_controls()

        r = world.rollback()

        assert "Runtime controls are NOT being converged" not in r.stderr
        assert "NOT converged" not in r.stderr

    def test_the_preserved_copy_is_cleaned_up(self, world):
        world.build()
        world.install_newer_runtime_controls()

        world.rollback()

        leftovers = list(Path(os.environ.get("TMPDIR", "/tmp")).glob("riskit-rollback-*"))
        assert not leftovers, f"temporary reconciler copies not cleaned up: {leftovers}"

    def test_a_target_without_runtime_artifacts_fails_loudly(self, world):
        """Nothing can reconcile a revision that does not carry the
        templates.  Restarting onto controls that belong to the revision
        being rolled back FROM is the failure being fixed."""
        world.build(target_keeps_artifacts=False)
        world.install_newer_runtime_controls()

        r = world.rollback()

        assert r.returncode != 0, r.stdout
        assert "missing runtime artifacts" in r.stderr
        assert "Manual intervention required" in r.stderr
        assert "RESTARTED" not in world.calls, "restarted onto unreconciled runtime state"


class TestARollbackIgnoresInheritedTestSeams:
    """rollback.sh is a production entry point.

    No combination of exported variables may activate the reconciler's
    test behaviour during a real rollback — not even one that would
    announce itself.  These drive the real script with a hostile
    environment and read what root was asked to do.
    """

    HOSTILE = {
        "RC_ALLOW_TEST_OVERRIDES": "1",
        "RC_WATCHDOG_OWNER": "nobody:nobody",
        "SYSTEMD_UNIT_DIR": "/tmp/evil-units",
        "RC_PROC_DIR": "/tmp/evil-proc",
    }

    def test_an_inherited_owner_override_is_ignored(self, world):
        world.build()
        world.install_newer_runtime_controls()

        world.rollback(extra_env=self.HOSTILE)

        watchdog = [ln for ln in world.installs if "dynasty-healthcheck.sh" in ln]
        assert watchdog, f"watchdog never installed; requests were: {world.installs}"
        assert "-o root -g root" in watchdog[0], watchdog[0]
        assert "nobody" not in watchdog[0], watchdog[0]

    def test_an_inherited_unit_directory_is_ignored(self, world):
        world.build()
        world.install_newer_runtime_controls()

        world.rollback(extra_env=self.HOSTILE)

        assert any(f"/etc/systemd/system/{SERVICE_NAME}.service" in ln for ln in world.installs)
        assert not any("/tmp/evil-units" in ln for ln in world.installs), world.installs

    def test_an_inherited_proc_directory_is_ignored(self, world):
        world.build()
        world.install_newer_runtime_controls()

        r = world.rollback(extra_env=self.HOSTILE)

        assert "/tmp/evil-proc" not in (r.stdout + r.stderr)
        assert "/proc/" in (r.stdout + r.stderr), "verification did not read the real /proc"

    def test_the_test_mode_banner_never_appears_in_a_rollback(self, world):
        """Announcing the escape is not the same as closing it."""
        world.build()
        world.install_newer_runtime_controls()

        r = world.rollback(extra_env=self.HOSTILE)

        assert "TEST OVERRIDES ACTIVE" not in (r.stdout + r.stderr)

    def test_production_rollback_still_requires_root_root(self, world):
        """The verification arm, under the hostile environment."""
        world.build()
        world.install_newer_runtime_controls()

        r = world.rollback(extra_env=self.HOSTILE)

        assert r.returncode != 0
        if os.geteuid() != 0:
            assert "expected root:root" in r.stderr, r.stderr


class TestProductionCannotBeWeakenedByInheritedEnvironment:
    """The gate is the mechanism; deploy.sh scrubs on top of it.

    An inherited ``RC_WATCHDOG_OWNER`` alone is inert — the values are
    constants unless a harness explicitly sets
    ``RC_ALLOW_TEST_OVERRIDES=1``.  BOTH production entry points —
    deploy.sh and rollback.sh — additionally unset the flag and every
    override before sourcing, so the override branch is unreachable
    during a real deploy or rollback.  This suite drives rollback.sh end
    to end against those production constants and doubles the privileged
    command layer instead.
    """

    def test_an_inherited_override_does_not_reach_the_reconciler(self):
        script = f"""
            export RC_WATCHDOG_OWNER=nobody:nobody
            export SYSTEMD_UNIT_DIR=/tmp/evil
            export RC_PROC_DIR=/tmp/evil-proc
            source {RECONCILER}
            echo "owner=${{RC_WATCHDOG_OWNER}}"
            echo "unitdir=${{SYSTEMD_UNIT_DIR}}"
            echo "procdir=${{RC_PROC_DIR}}"
        """
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "owner=root:root" in r.stdout
        assert "unitdir=/etc/systemd/system" in r.stdout
        assert "procdir=/proc" in r.stdout

    def test_the_test_mode_gate_is_what_enables_the_override(self):
        script = f"""
            export RC_ALLOW_TEST_OVERRIDES=1
            export RC_WATCHDOG_OWNER=nobody:nobody
            source {RECONCILER}
            echo "owner=${{RC_WATCHDOG_OWNER}}"
        """
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        assert "owner=nobody:nobody" in r.stdout, r.stdout + r.stderr

    def test_using_the_gate_is_announced_in_the_log(self):
        """'Only a harness sets it' is a claim; the log is where an
        operator can falsify it."""
        script = f"export RC_ALLOW_TEST_OVERRIDES=1\nsource {RECONCILER}\n"
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        assert "TEST OVERRIDES ACTIVE" in r.stderr

    def test_deploy_scrubs_the_seams_before_it_sources(self):
        text = (REPO / "deploy" / "deploy.sh").read_text()
        block = text[text.index("reconcile_runtime_state() {") :]
        block = block[: block.index("\n}\n")]
        assert (
            "unset RC_ALLOW_TEST_OVERRIDES RC_WATCHDOG_OWNER SYSTEMD_UNIT_DIR RC_PROC_DIR" in block
        )
        assert block.index("unset RC_ALLOW_TEST_OVERRIDES") < block.index('source "${reconciler}"')

    def test_neither_script_sets_an_override_itself(self):
        for name in ("deploy.sh", "rollback.sh"):
            script = (REPO / "deploy" / name).read_text()
            for var in ("RC_WATCHDOG_OWNER=", "RC_ALLOW_TEST_OVERRIDES="):
                assignments = [
                    ln
                    for ln in script.splitlines()
                    if var in ln and not ln.lstrip().startswith("#") and "unset" not in ln
                ]
                assert not assignments, f"{name} assigns {var}: {assignments}"

    def test_live_verification_requires_root_root_in_production(self, tmp_path):
        """The verification arm, not just the install arm."""
        lib = tmp_path / "lib"
        lib.mkdir()
        shutil.copy2(SYSD / "dynasty-healthcheck.sh", lib / "dynasty-healthcheck.sh")
        script = f"""
            export RC_WATCHDOG_OWNER=nobody:nobody   # inherited, must be ignored
            source {RECONCILER}
            owner="$(stat -c '%U:%G' "{lib}/dynasty-healthcheck.sh")"
            echo "required=${{RC_WATCHDOG_OWNER}}"
            if [[ "$owner" != "${{RC_WATCHDOG_OWNER}}" ]]; then
              echo "verdict=fail owner=$owner"
            else
              echo "verdict=pass owner=$owner"
            fi
        """
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        assert "required=root:root" in r.stdout, r.stdout + r.stderr
        if os.geteuid() != 0:
            assert (
                "verdict=fail" in r.stdout
            ), "an unprivileged-owned watchdog passed a production verify"
