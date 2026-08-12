"""The runtime reconciler must render real units and stay inside its privilege.

Three defects were found by owner review of the first standalone version,
and each of them would have shipped a broken or refused reconciliation
into the deploy path. They are pinned here BEFORE the reconciler is wired
into deploy.sh/rollback.sh.

1. The backend template uses placeholder tokens (``__SERVICE_NAME__``,
   ``__APP_USER__``, ``__APP_DIR__``, ``__VENV_DIR__``) and is rendered by
   ``install-systemd-service.sh``. The hardening units use literal
   path/name substitutions and are rendered by ``apply_hardening.sh``.
   The first version applied the *hardening* substitutions to the
   *backend* template, which installs a unit still containing literal
   ``__APP_DIR__`` — a unit that cannot start, shipped by the very
   mechanism meant to prevent broken runtime state.

2. Verification called ``sudo -n stat`` / ``sudo -n grep`` / ``sudo -n
   cmp``. The NOPASSWD surface is exactly systemctl, journalctl, install
   and chown, so those calls would simply have been refused. They were
   never needed: units are 0644 and the watchdog is root:root 0755.

3. The watchdog was installed as ``${SERVICE_NAME}-healthcheck.sh`` while
   the unit's ExecStart names ``dynasty-healthcheck.sh``. Those agree
   only because production runs ``SERVICE_NAME=dynasty`` — an accidental
   coupling that breaks on any other service name.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RECONCILER = REPO / "deploy" / "reconcile-runtime-controls.sh"
SYSD = REPO / "deploy" / "systemd"

# The only commands the deploy user may run as root, verified on the host.
AUTHORIZED_SUDO = {"systemctl", "journalctl", "install", "chown"}


def _render(kind: str, src: Path, **env) -> str:
    """Run the reconciler's real renderer against a template."""
    fn = "_rc_render_backend_unit" if kind == "backend" else "_rc_render_hardening_unit"
    assigns = "\n".join(f"export {k}={v!r}" for k, v in env.items())
    script = textwrap.dedent(f"""\
        set -uo pipefail
        {assigns}
        source {RECONCILER!s}
        out="$(mktemp)"
        {fn} {src!s} "$out" || exit 1
        cat "$out"
        """)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"render failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


ENV = dict(
    SERVICE_NAME="brisket",  # deliberately NOT "dynasty"
    APP_USER="briskuser",
    APP_DIR="/srv/apps/brisket-calc",
    VENV_DIR="/srv/venvs/brisket",
    RISKIT_LIB_DIR="/usr/local/lib/riskit",
)


class TestTheBackendUnitIsActuallyRendered:
    """Blocker 1. A non-default SERVICE_NAME is used throughout, so a
    renderer that only works for ``dynasty`` cannot pass."""

    @pytest.fixture(scope="class")
    def unit(self):
        return _render("backend", SYSD / "dynasty.service.template", **ENV)

    def test_no_placeholder_survives(self, unit):
        left = sorted(set(re.findall(r"__[A-Z_]+__", unit)))
        assert not left, f"unresolved placeholders in the rendered unit: {left}"

    def test_identity_and_paths_are_substituted(self, unit):
        assert f"User={ENV['APP_USER']}" in unit
        assert f"Group={ENV['APP_USER']}" in unit
        assert f"WorkingDirectory={ENV['APP_DIR']}" in unit

    def test_execstart_names_the_rendered_venv_and_app(self, unit):
        m = re.search(r"^ExecStart=(.+)$", unit, re.M)
        assert m, "rendered unit has no ExecStart"
        exec_line = m.group(1)
        assert ENV["VENV_DIR"] in exec_line, exec_line
        assert ENV["APP_DIR"] in exec_line, exec_line

    def test_the_frontend_dependency_follows_the_service_name(self, unit):
        """A `dynasty-frontend` left hard-coded would point a `brisket`
        install at another service's frontend."""
        assert (
            "dynasty-frontend" not in unit
        ), "the frontend dependency still names dynasty after rendering"
        assert f"{ENV['SERVICE_NAME']}-frontend" in unit

    def test_the_fd_limit_survives_rendering(self, unit):
        """The whole point of reconciling this unit."""
        m = re.search(r"^LimitNOFILE=(\d+):(\d+)\s*$", unit, re.M)
        assert m, "LimitNOFILE did not survive rendering"
        assert (int(m.group(1)), int(m.group(2))) == (8192, 524288)


class TestTheWatchdogTargetAgreesWithItsUnit:
    """Blocker 3. Installed path and ExecStart must match by contract,
    not by both happening to say `dynasty`."""

    def test_execstart_path_is_what_the_reconciler_installs(self):
        svc = _render("hardening", SYSD / "dynasty-healthcheck.service", **ENV)
        m = re.search(r"^ExecStart=(\S+)", svc, re.M)
        assert m, "healthcheck unit has no ExecStart"
        exec_path = m.group(1)

        installed = re.search(
            r'_rc_install_if_different "\$\{sysd\}/dynasty-healthcheck\.sh" \\\s*\n\s*"([^"]+)"',
            RECONCILER.read_text(),
        )
        assert installed, "could not find the watchdog install target in the reconciler"
        target = (
            installed.group(1)
            .replace("${RISKIT_LIB_DIR}", ENV["RISKIT_LIB_DIR"])
            .replace("${SERVICE_NAME}", ENV["SERVICE_NAME"])
        )
        assert target == exec_path, (
            f"reconciler installs {target} but the unit executes {exec_path} — "
            "these agree only when SERVICE_NAME=dynasty"
        )

    def test_the_service_name_reaches_the_watchdog_config(self):
        """The watchdog must watch THIS backend, not a literal dynasty."""
        svc = _render("hardening", SYSD / "dynasty-healthcheck.service", **ENV)
        assert f"HEALTH_SERVICE={ENV['SERVICE_NAME']}" in svc


class TestItStaysInsideTheAuthorizedPrivilege:
    """Blocker 2. Any sudo outside the verified NOPASSWD set is a call
    that will be refused at runtime — a reconciler that cannot run."""

    def test_every_privileged_call_goes_through_the_allowlist(self):
        """No bare `sudo` anywhere — indirection made the old audit blind.

        `sudo -n "$SC"` passed a regex audit while saying nothing about
        which binary ran. One helper makes the property both enforceable
        at runtime and readable statically.
        """
        code = re.sub(r"#.*", "", RECONCILER.read_text())
        bare = re.findall(r"(?<!_rc_)\bsudo -n\b", code)
        # exactly one: the call inside _rc_sudo itself
        assert len(bare) == 1, f"{len(bare)} bare sudo call(s) bypass _rc_sudo"

    def test_the_allowlist_is_the_verified_nopasswd_surface(self):
        m = re.search(r"_RC_SUDO_ALLOWED=\(([^)]*)\)", RECONCILER.read_text())
        assert m, "no _RC_SUDO_ALLOWED allowlist"
        assert set(m.group(1).split()) == AUTHORIZED_SUDO

    def test_an_unauthorized_binary_is_refused_before_sudo(self):
        """Runtime proof, not just a static read."""
        r = subprocess.run(
            [
                "bash",
                "-c",
                f"set -uo pipefail; source {RECONCILER}; _rc_sudo /usr/bin/stat -c %U /etc/hostname",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 126, f"expected refusal, got {r.returncode}: {r.stdout}{r.stderr}"
        assert "not in the authorized set" in r.stderr

    def test_unreadable_state_fails_rather_than_escalating(self):
        """If the installed artifact cannot be read, say so — do not try
        to reach it with privilege we do not have."""
        text = RECONCILER.read_text()
        assert "cannot prove convergence" in text
        assert "cannot verify the watchdog that actually runs" in text


class TestScopeIsHeld:
    def test_it_does_not_run_the_full_hardening_installer(self):
        text = RECONCILER.read_text()
        assert "apply_hardening.sh" not in re.sub(
            r"#.*", "", text
        ), "reconciler invokes the full hardening installer"

    def test_it_touches_no_unrelated_hardening(self):
        code = re.sub(r"#.*", "", RECONCILER.read_text())
        for unrelated in ("nginx", "riskit-backup", "riskit-uptime", "certbot"):
            assert unrelated not in code, f"reconciler touches unrelated {unrelated}"
