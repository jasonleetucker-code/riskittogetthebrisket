"""Deploy and rollback both go through the one shared reconciler.

The deployment-truth gap was not that the reconciliation logic was
wrong — there was none.  ``deploy.sh`` checked that a unit *existed* and
returned, so a revision whose required runtime controls lived only in
Git deployed green.  These tests pin the wiring itself: that both paths
call the shared implementation, in the order where it can actually work,
and that sourcing it cannot quietly disarm the caller.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "deploy.sh"
ROLLBACK = REPO / "deploy" / "rollback.sh"
RECONCILER = REPO / "deploy" / "reconcile-runtime-controls.sh"


def _main_body(script: Path) -> str:
    text = script.read_text()
    start = text.index("\nmain() {")
    return text[start:]


class TestTheForwardDeployReconcilesAndThenProves:
    def test_deploy_sources_the_shared_reconciler(self):
        assert "reconcile-runtime-controls.sh" in DEPLOY.read_text()

    def test_it_reconciles_before_restarting(self):
        """A unit installed after the restart is a unit the running
        process never got.  That ordering IS the feature."""
        body = _main_body(DEPLOY)
        assert body.index("reconcile_runtime_state") < body.index("restart_service")

    def test_it_verifies_after_restarting(self):
        """/proc/<MainPID>/limits is only true of the process actually
        running, so the live check has to follow the restart."""
        body = _main_body(DEPLOY)
        assert body.index("restart_service") < body.index("verify_runtime_state")

    def test_verification_runs_before_the_deploy_is_called_successful(self):
        body = _main_body(DEPLOY)
        assert body.index("verify_runtime_state") < body.index("record_success_state")
        assert body.index("verify_runtime_state") < body.index("Deployment succeeded")

    def test_both_steps_are_fatal(self):
        """A warning would reproduce the original defect exactly: a
        deploy that reports success while the controls are absent."""
        text = DEPLOY.read_text()
        for fn in ("reconcile_runtime_state", "verify_runtime_state"):
            block = text[text.index(f"{fn}() {{") :]
            block = block[: block.index("\n}\n")]
            assert "exit 1" in block, f"{fn} does not fail the deploy"
            assert "warn " not in block, f"{fn} downgrades a missing control to a warning"

    def test_a_missing_reconciler_is_fatal_not_skipped(self):
        """Forward deploys always come from a revision that has it."""
        text = DEPLOY.read_text()
        block = text[text.index("reconcile_runtime_state() {") :]
        block = block[: block.index("\n}\n")]
        assert "Missing runtime reconciler" in block
        assert "exit 1" in block


class TestRollbackUsesTheSameImplementation:
    def test_rollback_sources_the_shared_reconciler(self):
        assert "reconcile-runtime-controls.sh" in ROLLBACK.read_text()

    def test_neither_script_reimplements_the_renderer(self):
        """One renderer.  Two copies is how the forward and backward
        paths drift apart."""
        for script in (DEPLOY, ROLLBACK):
            text = script.read_text()
            assert (
                "__SERVICE_NAME__/" not in text
            ), f"{script.name} renders the backend template itself"
            assert "_rc_render_backend_unit()" not in text
            assert "_rc_install_if_different()" not in text

    def test_it_reconciles_to_the_rollback_revision_before_restarting(self):
        body = _main_body(ROLLBACK)
        assert body.index("reconcile_runtime_controls") < body.index('restart "${SERVICE_NAME}"')

    def test_a_failed_reconciliation_stops_the_rollback(self):
        body = _main_body(ROLLBACK)
        window = body[body.index("reconcile_runtime_controls") :]
        window = window[: window.index("Restarting service")]
        assert "exit 1" in window

    def test_a_rollback_target_without_the_reconciler_says_so(self):
        """Refusing to roll back at all would be worse than the drift —
        last-known-good is this script's whole job — but the operator
        must not be left thinking the controls were converged."""
        body = _main_body(ROLLBACK)
        assert "NOT being converged" in body
        assert "verify them manually" in body


class TestSourcingCannotDisarmTheCaller:
    """`set -uo pipefail` at the top of a sourced file turns errexit OFF
    for the rest of the sourcing script.  Both callers run under
    `set -Eeuo pipefail`, so that would silently remove failure handling
    from every remaining step of a production deploy — a far worse
    version of the defect this file exists to fix, and invisible."""

    def test_the_reconciler_sets_no_global_shell_options(self):
        code = re.sub(r"#.*", "", RECONCILER.read_text())
        top_level = [ln for ln in code.splitlines() if re.match(r"^set\s+[-+]", ln)]
        assert not top_level, f"global `set` at file scope: {top_level}"

    def test_the_callers_options_survive_sourcing_and_both_entry_points(self):
        # `[[ -o … ]]`, not `$(set +o | grep …)`: bash runs command
        # substitutions without errexit unless `inherit_errexit` is set,
        # so the obvious probe reports it off no matter what.
        script = f"""
            set -Eeuo pipefail
            report() {{
              local out=""
              if [[ -o errexit  ]]; then out+="e"; fi
              if [[ -o nounset  ]]; then out+="u"; fi
              if [[ -o pipefail ]]; then out+="p"; fi
              echo "$1=${{out}}"
            }}
            source {RECONCILER}
            report after-source
            SERVICE_NAME=x APP_DIR=/nonexistent RISKIT_LIB_DIR=/nonexistent \\
              reconcile_runtime_controls /nonexistent >/dev/null 2>&1 || true
            report after-reconcile
            SERVICE_NAME=x APP_DIR=/nonexistent \\
              verify_runtime_controls /nonexistent >/dev/null 2>&1 || true
            report after-verify
        """
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        for stage in ("after-source", "after-reconcile", "after-verify"):
            assert f"{stage}=eup" in r.stdout, f"{stage} lost a shell option; got:\n{r.stdout}"

    def test_the_callers_still_declare_errexit(self):
        """If either script ever drops it, the property above stops
        mattering and this test should be the thing that notices."""
        for script in (DEPLOY, ROLLBACK):
            assert "set -Eeuo pipefail" in script.read_text().splitlines()[1]


class TestScopeIsHeld:
    def test_no_unrelated_hardening_is_invoked_by_either_path(self):
        """The owner's boundary: nginx, backups, uptime and the full
        hardening installer stay operator-owned."""
        for script in (DEPLOY, ROLLBACK):
            body = _main_body(script)
            assert (
                "apply_hardening.sh" not in body
            ), f"{script.name} runs the full hardening installer"
            for unrelated in ("nginx", "riskit-backup", "riskit-uptime", "certbot"):
                assert unrelated not in body, f"{script.name} touches {unrelated}"
