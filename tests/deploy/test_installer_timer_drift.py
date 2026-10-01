"""Every timer block in the installer reinstalls on TEMPLATE DRIFT.

Measured on production 2026-10-01 (read-only): rendering every timer
template with the box's own SERVICE_NAME / APP_USER / APP_DIR / VENV_DIR
and comparing it with ``/etc/systemd/system`` found two units frozen at
their first-install content —

* ``dynasty-bdvm-refresh.service`` lacked the stage-0
  ``refresh_bdvm_inputs.py`` ExecStart added on 2026-08-20, so the BDVM
  player context had never been materialised and ``/api/bdvm/*`` ran on
  neutral priors;
* ``dynasty-consensus-edge-snapshot.service`` lacked ``User=``/``Group=``,
  so it ran as root and left a root-owned ``data/consensus_edge.sqlite``.

Both came from the same shape: twelve dedicated per-timer blocks asked
"does the timer exist?" and, when it did, logged "already installed;
skipping" — so a template edit never reached the box, and every deploy
reported success. ``install_simple_timer`` had already been fixed for the
simple timers; the dedicated blocks had not.

This file drives the REAL installer end to end against a throwaway host.
The only things faked are the commands that would touch a real init
system or real ownership:

* ``sudo`` — enforces the production NOPASSWD allowlist (systemctl,
  journalctl, install, chown; anything else is refused with "a password
  is required"), redirects ``/etc/…`` and ``/var/lib/…`` into the
  temporary root, and records every invocation in order;
* ``cmp`` — the real cmp, with ``/etc/…`` relocated into the temporary
  root (path translation only; it is never reachable through sudo);
* ``systemctl`` — ``cat`` answers from the temporary unit directory,
  ``enable`` records enablement, everything is logged;
* ``install`` — copies into the temporary root, ignoring ``-o``/``-g``;
* ``chown`` / ``stat`` — an ownership ledger, because an unprivileged test
  cannot actually make a file root-owned and then give it away.

``sed``, ``mktemp`` and ``grep`` are the real binaries and ``cmp`` is the
real comparison, so the render-and-compare logic under test is the
production logic.

These tests need bash plus a real ``systemctl`` and ``install`` binary on
disk (the installer's sudo-binary resolver checks ``-x`` on absolute
paths before it ever calls sudo). That holds on the Linux CI runners and
not on Windows dev machines, where the module skips.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "deploy" / "install-systemd-service.sh"
SYSTEMD = REPO / "deploy" / "systemd"

if os.name == "nt":
    pytest.skip("drives the installer through bash with Unix paths", allow_module_level=True)
if shutil.which("bash") is None:
    pytest.skip("bash is required", allow_module_level=True)
if not any(os.access(p, os.X_OK) for p in ("/bin/systemctl", "/usr/bin/systemctl")):
    pytest.skip(
        "the installer's resolver requires /bin/systemctl or /usr/bin/systemctl on disk",
        allow_module_level=True,
    )
if not any(os.access(p, os.X_OK) for p in ("/usr/bin/install", "/bin/install")):
    pytest.skip("the installer's resolver requires an install binary", allow_module_level=True)

SERVICE_NAME = "brisket"  # deliberately not "dynasty": units must follow SERVICE_NAME
APP_USER = "ceowner"  # not the test user, so "already owned" is the ledger's call

# The thirteen dedicated blocks that used to be presence-only, and the
# gate (if any) each one keeps.  ffpc-sharp had the same hole with no log
# line, so it was converted with the others.
LEGACY_STEMS = (
    "signal-alerts",
    "custom-alerts",
    "bdvm-refresh",
    "consensus-edge-snapshot",
    "sharp-discovery",
    "sharp-records",
    "sharp-rosters",
    "ffpc-sharp",
    "sharp-transactions",
    "reception-depth",
    "pbp-weekly",
    "dlf-fetch",
    "idpshow-fetch",
)
GATED_STEMS = ("signal-alerts", "custom-alerts", "dlf-fetch", "idpshow-fetch", "ffpc-sharp")


# The production NOPASSWD surface, and nothing wider: the box user may sudo
# exactly these four binaries (deploy/reconcile-runtime-controls.sh's
# _RC_SUDO_ALLOWED).  Anything else is refused the way real sudo refuses
# it under -n.  A pass-through sudo is what let `sudo -n cmp` ship: the
# refusal read as drift on the box and rewrote every unit every deploy,
# while this harness happily ran cmp and reported "current".
FAKE_SUDO = r"""#!/usr/bin/env bash
[[ "${1:-}" == "-n" ]] && shift
printf '%s\n' "$*" >> "${FAKE_STATE}/sudo.log"
cmd="${1:-}"; shift || true
case "${cmd##*/}" in
  systemctl|journalctl|install|chown) ;;
  *)
    printf '%s\n' "${cmd}" >> "${FAKE_STATE}/sudo_refused.log"
    echo "sudo: a password is required" >&2
    exit 1 ;;
esac
case "${cmd}" in
  /bin/systemctl|/usr/bin/systemctl|systemctl) cmd="${FAKE_BIN}/systemctl" ;;
  /usr/bin/install|/bin/install|install) cmd="${FAKE_BIN}/install" ;;
  /bin/chown|/usr/bin/chown|chown) cmd="${FAKE_BIN}/chown" ;;
esac
args=()
for a in "$@"; do
  case "${a}" in
    /etc/*|/var/lib/*) a="${FAKE_ROOT}${a}" ;;
  esac
  args+=("${a}")
done
exec "${cmd}" "${args[@]}"
"""

FAKE_SYSTEMCTL = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FAKE_STATE}/systemctl.log"
unit_dir="${FAKE_ROOT}/etc/systemd/system"
case "${1:-}" in
  --version) exit 0 ;;
  cat)
    u="${2:-}"; [[ "${u}" == *.* ]] || u="${u}.service"
    [[ -f "${unit_dir}/${u}" ]] ;;
  is-enabled) [[ -f "${FAKE_STATE}/enabled/${2:-}" ]] ;;
  enable)
    shift
    mkdir -p "${FAKE_STATE}/enabled"
    for a in "$@"; do
      [[ "${a}" == --* ]] && continue
      [[ -f "${unit_dir}/${a}" ]] || { echo "unit ${a} not installed" >&2; exit 1; }
      touch "${FAKE_STATE}/enabled/${a}"
    done ;;
  *) exit 0 ;;
esac
"""

FAKE_INSTALL = r"""#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && exit 0  # the installer's sudo-binary resolver probe
printf '%s\n' "$*" >> "${FAKE_STATE}/install.log"
make_dir=false; files=()
while (( $# )); do
  case "$1" in
    -d) make_dir=true; shift ;;
    -m|-o|-g) shift 2 ;;
    *) files+=("$1"); shift ;;
  esac
done
if [[ "${make_dir}" == "true" ]]; then mkdir -p "${files[@]}"; exit 0; fi
mkdir -p "$(dirname "${files[1]}")"
cp "${files[0]}" "${files[1]}"
"""

# Ownership ledger: unknown paths read as root:root (what production had),
# chown records the new owner, stat reads it back.
FAKE_CHOWN = r"""#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && exit 0  # the installer's sudo-binary resolver probe
printf '%s\n' "$*" >> "${FAKE_STATE}/chown.log"
[[ -n "${FAKE_CHOWN_FAIL:-}" ]] && exit 1
owner="$1"; shift
for p in "$@"; do printf '%s\t%s\n' "${p}" "${owner}" >> "${FAKE_STATE}/owners"; done
"""

FAKE_STAT = r"""#!/usr/bin/env bash
if [[ "${1:-}" == "-c" && "${2:-}" == "%U:%G" && $# -eq 3 ]]; then
  owner="$(awk -F'\t' -v p="$3" '$1 == p { o = $2 } END { print o }' "${FAKE_STATE}/owners" 2>/dev/null)"
  printf '%s\n' "${owner:-root:root}"
  exit 0
fi
exec /usr/bin/stat "$@"
"""

# The installer compares rendered units against the installed ones with an
# UNPRIVILEGED `cmp` (the box refuses `sudo -n cmp`).  The only thing this
# wrapper changes is WHERE `/etc/…` lives — it relocates into the temporary
# root, exactly as the fake sudo does for privileged writes — then runs the
# real cmp.  It grants no privilege: a `sudo -n cmp` still hits the
# allowlist above and is refused.
FAKE_CMP = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FAKE_STATE}/cmp.log"
args=()
for a in "$@"; do
  case "${a}" in
    /etc/*|/var/lib/*) a="${FAKE_ROOT}${a}" ;;
  esac
  args+=("${a}")
done
for real in /usr/bin/cmp /bin/cmp; do
  [[ -x "${real}" ]] && exec "${real}" "${args[@]}"
done
exit 2
"""


class Host:
    """A temporary box: app checkout, unit dir, fake privileged binaries."""

    def __init__(self, root: Path):
        self.root = root
        self.app = root / "srv" / "app"
        self.fake_root = root / "fakeroot"
        self.unit_dir = self.fake_root / "etc" / "systemd" / "system"
        self.bin = root / "bin"
        self.state = root / "state"
        for d in (self.app / "deploy", self.unit_dir, self.bin, self.state, root / "home"):
            d.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SYSTEMD, self.app / "deploy" / "systemd")
        (self.state / "owners").write_text("", encoding="utf-8")
        for name, body in (
            ("sudo", FAKE_SUDO),
            ("systemctl", FAKE_SYSTEMCTL),
            ("install", FAKE_INSTALL),
            ("chown", FAKE_CHOWN),
            ("stat", FAKE_STAT),
            ("cmp", FAKE_CMP),
        ):
            path = self.bin / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        # The backend/frontend blocks are out of scope here; present units
        # make them take their (unchanged) "already installed" branch.
        for unit in (f"{SERVICE_NAME}.service", f"{SERVICE_NAME}-frontend.service"):
            (self.unit_dir / unit).write_text("[Unit]\n", encoding="utf-8")

    # ── gates ──
    def open_all_gates(self) -> None:
        (self.app / ".env").write_text(
            "SIGNAL_ALERT_CRON_TOKEN=tok\nDLF_USERNAME=u\nDLF_PASSWORD=p\n", encoding="utf-8"
        )
        (self.app / "idpshow_session.json").write_text("{}", encoding="utf-8")
        ffpc = self.app / "config" / "sharp" / "ffpc_sources.json"
        ffpc.parent.mkdir(parents=True, exist_ok=True)
        ffpc.write_text('{"enabled": true}', encoding="utf-8")

    def close_all_gates(self) -> None:
        for p in (
            self.app / ".env",
            self.app / "idpshow_session.json",
            self.app / "config" / "sharp" / "ffpc_sources.json",
        ):
            if p.exists():
                p.unlink()

    # ── running ──
    def run(self, **extra_env: str) -> subprocess.CompletedProcess:
        for log in (
            "sudo.log",
            "sudo_refused.log",
            "systemctl.log",
            "install.log",
            "chown.log",
            "cmp.log",
        ):
            (self.state / log).write_text("", encoding="utf-8")
        env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.root / "home"),
            "FAKE_ROOT": str(self.fake_root),
            "FAKE_BIN": str(self.bin),
            "FAKE_STATE": str(self.state),
            "APP_DIR": str(self.app),
            "APP_USER": APP_USER,
            "VENV_DIR": str(self.root / "venv"),
            "SERVICE_NAME": SERVICE_NAME,
            "SERVICE_TEMPLATE_PATH": str(SYSTEMD / "dynasty.service.template"),
            "FORCE_SERVICE_INSTALL": "false",
            **extra_env,
        }
        return subprocess.run(
            ["bash", str(INSTALLER)], env=env, capture_output=True, text=True, timeout=120
        )

    def log(self, name: str) -> list[str]:
        return (self.state / name).read_text(encoding="utf-8").splitlines()

    # ── units ──
    def service(self, stem: str) -> Path:
        return self.unit_dir / f"{SERVICE_NAME}-{stem}.service"

    def timer(self, stem: str) -> Path:
        return self.unit_dir / f"{SERVICE_NAME}-{stem}.timer"

    def rendered_service(self, stem: str) -> str:
        text = (SYSTEMD / f"dynasty-{stem}.service.template").read_text(encoding="utf-8")
        for token, value in (
            ("__SERVICE_NAME__", SERVICE_NAME),
            ("__APP_USER__", APP_USER),
            ("__APP_DIR__", str(self.app)),
            ("__VENV_DIR__", str(self.root / "venv")),
        ):
            text = text.replace(token, value)
        return text


def _ok(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


# ── Drift: every dedicated block rewrites a changed unit ─────────────────


@pytest.fixture(scope="module")
def drifted_host(tmp_path_factory):
    """Install everything, corrupt every legacy unit, run the installer again."""
    host = Host(tmp_path_factory.mktemp("drift"))
    host.open_all_gates()
    _ok(host.run())
    for stem in LEGACY_STEMS:
        assert host.service(stem).is_file(), f"{stem} was not installed on a fresh box"
        # Service drift for every unit, timer drift for half: the compare
        # must catch either file changing.
        with host.service(stem).open("a", encoding="utf-8") as fh:
            fh.write("# stale first-install content\n")
    for stem in LEGACY_STEMS[::2]:
        with host.timer(stem).open("a", encoding="utf-8") as fh:
            fh.write("# stale schedule\n")
    output = _ok(host.run())
    return host, output


@pytest.mark.parametrize("stem", LEGACY_STEMS)
def test_a_drifted_unit_is_rewritten_to_its_template(drifted_host, stem):
    host, output = drifted_host
    assert host.service(stem).read_text(encoding="utf-8") == host.rendered_service(stem)
    assert "# stale" not in host.timer(stem).read_text(encoding="utf-8")
    assert f"{SERVICE_NAME}-{stem} differs from its template; updating." in output


@pytest.mark.parametrize("stem", LEGACY_STEMS)
def test_the_rewrite_is_reloaded_and_enabled(drifted_host, stem):
    """A rewritten file systemd has not re-read is the stale unit running."""
    host, _ = drifted_host
    calls = host.log("systemctl.log")
    assert "daemon-reload" in calls
    assert any(c.startswith("enable") and f"{SERVICE_NAME}-{stem}.timer" in c for c in calls)


def test_the_bdvm_rewrite_carries_the_stage0_input_warm(drifted_host):
    """The exact production defect: the installed unit never got stage 0."""
    host, _ = drifted_host
    text = host.service("bdvm-refresh").read_text(encoding="utf-8")
    assert (
        f"ExecStart=-{host.root / 'venv'}/bin/python {host.app}/scripts/refresh_bdvm_inputs.py"
        in text
    )


def test_the_consensus_edge_rewrite_runs_as_the_app_user(drifted_host):
    host, _ = drifted_host
    lines = host.service("consensus-edge-snapshot").read_text(encoding="utf-8").splitlines()
    assert f"User={APP_USER}" in lines
    assert f"Group={APP_USER}" in lines


@pytest.fixture(scope="module")
def current_host(tmp_path_factory):
    """Install everything, then run the installer again with nothing changed."""
    host = Host(tmp_path_factory.mktemp("current"))
    host.open_all_gates()
    _ok(host.run())
    output = _ok(host.run())
    return host, output


def test_a_current_unit_is_left_alone(current_host):
    """Reconciling every deploy must be a no-op on an up-to-date box: no
    rewrite, no reload, no enable, no kick for any legacy unit."""
    host, output = current_host
    installs = "\n".join(host.log("install.log"))
    calls = host.log("systemctl.log")
    for stem in LEGACY_STEMS:
        unit = f"{SERVICE_NAME}-{stem}"
        assert f"{unit}.service" not in installs, f"{stem} rewritten with no drift"
        assert f"{unit}.timer" not in installs, f"{stem} timer rewritten with no drift"
        assert f"{unit} already installed and current." in output
        assert f"{unit} differs from its template" not in output
        assert not any(c.startswith("enable") and f"{unit}.timer" in c for c in calls), stem
        assert not any(c.startswith("start") and f"{unit}." in c for c in calls), stem
    assert "daemon-reload" not in calls


def test_an_up_to_date_box_writes_nothing_and_kicks_nothing(current_host):
    """The whole installer, not just the legacy blocks: zero rewrites.

    Production regression this pins: `sudo -n cmp` is refused on the box,
    the refusal read as drift, and every deploy rewrote and daemon-reloaded
    ~16 simple timers — and, once the legacy blocks shared that compare,
    would have re-kicked the Consensus Edge snapshot (overwriting the day's
    07:30 board) and a 30-minute sharp-discovery crawl on every deploy."""
    host, output = current_host
    assert host.log("install.log") == [], "an up-to-date box had files (re)installed"
    calls = host.log("systemctl.log")
    assert "daemon-reload" not in calls
    assert [c for c in calls if c.startswith(("enable", "start", "restart"))] == []
    assert "differs from its template" not in output
    assert "changed; rewriting" not in output


def test_no_comparison_asks_sudo_for_a_refused_command(current_host, drifted_host):
    """Every privileged call stays inside the NOPASSWD allowlist — on the
    steady-state run and on the drift run alike."""
    for host, _ in (current_host, drifted_host):
        assert host.log("sudo_refused.log") == []
        assert host.log("cmp.log"), "the unprivileged compare never ran"


def test_a_target_the_compare_cannot_read_still_counts_as_drift(tmp_path):
    """The safe direction survives the move off sudo: a target the compare
    cannot read (here: gone, with its timer still registered) is
    reinstalled, never assumed current."""
    host = Host(tmp_path)
    host.open_all_gates()
    _ok(host.run())
    host.service("sharp-discovery").unlink()
    output = _ok(host.run())
    assert f"{SERVICE_NAME}-sharp-discovery differs from its template; updating." in output
    assert host.service("sharp-discovery").read_text(encoding="utf-8") == host.rendered_service(
        "sharp-discovery"
    )


# ── Gates are unchanged ──────────────────────────────────────────────────


def test_gated_timers_are_not_installed_without_their_gate(tmp_path):
    host = Host(tmp_path)
    output = _ok(host.run())
    for stem in GATED_STEMS:
        assert not host.service(stem).exists(), f"{stem} installed with its gate absent"
        assert not host.timer(stem).exists(), f"{stem} timer installed with its gate absent"
    assert "Signal-alerts timer skipped: SIGNAL_ALERT_CRON_TOKEN not set" in output
    assert "DLF-fetch timer skipped: DLF_USERNAME / DLF_PASSWORD not set" in output
    assert "IDP Show fetch timer skipped:" in output
    # Ungated legacy timers still install on the same run.
    for stem in set(LEGACY_STEMS) - set(GATED_STEMS):
        assert host.service(stem).is_file(), stem


def test_a_closed_gate_also_blocks_a_drift_rewrite(tmp_path):
    """The gate decides whether the installer touches the unit at all —
    drift-awareness must not become a way around it."""
    host = Host(tmp_path)
    host.open_all_gates()
    _ok(host.run())
    for stem in GATED_STEMS:
        with host.service(stem).open("a", encoding="utf-8") as fh:
            fh.write("# operator-edited\n")
    host.close_all_gates()
    _ok(host.run())
    for stem in GATED_STEMS:
        assert "# operator-edited" in host.service(stem).read_text(encoding="utf-8"), stem
    installs = "\n".join(host.log("install.log"))
    for stem in GATED_STEMS:
        assert f"{SERVICE_NAME}-{stem}." not in installs, stem


def test_credential_seeding_still_follows_an_install(tmp_path):
    """The DLF / IDP Show blocks keep their post-install provisioning."""
    host = Host(tmp_path)
    host.open_all_gates()
    (host.app / "dlf_session.json").write_text("{}", encoding="utf-8")
    _ok(host.run())
    assert (host.fake_root / "var" / "lib" / "dlf-fetch" / "dlf_session.json").is_file()
    assert (host.fake_root / "var" / "lib" / "idpshow-fetch" / "idpshow_session.json").is_file()


# ── Consensus Edge store ownership migration ─────────────────────────────


def _seed_store(host: Host, *names: str) -> None:
    data = host.app / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in names:
        (data / name).write_bytes(b"x")


def _chowned_paths(host: Host) -> list[str]:
    return [line.split(" ", 1)[1] for line in host.log("chown.log")]


def test_root_owned_store_files_are_handed_to_the_app_user(tmp_path):
    host = Host(tmp_path)
    _seed_store(
        host,
        "consensus_edge.sqlite",
        "consensus_edge.sqlite-wal",
        "consensus_edge.sqlite-shm",
        "other.sqlite",
        "consensus_edge.sqlite.bak",
    )
    _ok(host.run())
    data = host.app / "data"
    assert sorted(_chowned_paths(host)) == sorted(
        str(data / n)
        for n in ("consensus_edge.sqlite", "consensus_edge.sqlite-wal", "consensus_edge.sqlite-shm")
    )
    assert all(line.startswith(f"{APP_USER}:{APP_USER} ") for line in host.log("chown.log"))


def test_chown_is_invoked_by_absolute_path(tmp_path):
    """The NOPASSWD rule names a binary; a bare `sudo -n chown` relies on
    sudo's secure_path lookup landing on that exact binary."""
    host = Host(tmp_path)
    _seed_store(host, "consensus_edge.sqlite")
    _ok(host.run())
    chowns = [c for c in host.log("sudo.log") if c.split(" ", 1)[0].endswith("chown")]
    assert chowns, "no chown reached sudo"
    assert all(c.split(" ", 1)[0] in ("/bin/chown", "/usr/bin/chown") for c in chowns), chowns


def test_the_migration_is_idempotent(tmp_path):
    host = Host(tmp_path)
    _seed_store(host, "consensus_edge.sqlite", "consensus_edge.sqlite-wal")
    _ok(host.run())
    assert len(host.log("chown.log")) == 2
    _ok(host.run())
    assert host.log("chown.log") == [], "already-owned files were chowned again"


def test_absent_files_are_neither_created_nor_chowned(tmp_path):
    host = Host(tmp_path)
    _ok(host.run())
    assert host.log("chown.log") == []
    assert not (host.app / "data" / "consensus_edge.sqlite").exists()


def test_a_symlink_is_never_followed(tmp_path):
    host = Host(tmp_path)
    _seed_store(host, "consensus_edge.sqlite")
    target = tmp_path / "elsewhere"
    target.write_bytes(b"x")
    (host.app / "data" / "consensus_edge.sqlite-shm").symlink_to(target)
    output = _ok(host.run())
    assert _chowned_paths(host) == [str(host.app / "data" / "consensus_edge.sqlite")]
    assert "is not a regular file; ownership left unchanged" in output


def test_a_failed_chown_is_loud_but_does_not_fail_the_install(tmp_path):
    host = Host(tmp_path)
    _seed_store(host, "consensus_edge.sqlite")
    output = _ok(host.run(FAKE_CHOWN_FAIL="1"))
    assert "could not chown" in output


def test_ownership_is_fixed_before_the_first_run_as_the_app_user(tmp_path):
    """The initial kick starts the unit as APP_USER; it must find a store
    it can write, so the chown has to precede it."""
    host = Host(tmp_path)
    _seed_store(host, "consensus_edge.sqlite")
    _ok(host.run())
    sudo = host.log("sudo.log")
    chown_at = next(
        i
        for i, c in enumerate(sudo)
        if c.split(" ", 1)[0].endswith("/chown") and "--version" not in c
    )
    kick_at = next(
        i
        for i, c in enumerate(sudo)
        if "start --no-block" in c and f"{SERVICE_NAME}-consensus-edge-snapshot.service" in c
    )
    assert chown_at < kick_at
