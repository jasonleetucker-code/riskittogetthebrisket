"""``deploy/apply_hardening.sh`` must not be reachable from CI.

Backlog defect #17. The script installs the repo's nginx site config over
whatever is installed on the box, then reloads nginx. On the production
host that config is not purely repo-managed — certbot edits it in place
when it issues and renews certificates — so a checkout-to-host copy can
revert TLS configuration that no commit in this repo contains.

It is careful about it: ``--dry-run`` shows diffs, the old config is
backed up before the copy, and a failing ``nginx -t`` auto-restores the
backup. Those mitigations are real, and none of them help against the
case that matters, because a config that reverts certbot's edits is
still *valid* nginx. ``nginx -t`` passes and the site comes back up
serving the wrong certificate paths.

So the disposition is: **keep the script, keep it operator-run.** It is
useful, and running it by hand with ``--dry-run`` first is a reasonable
workflow. What must not happen is a deploy pipeline calling it on every
push, where nobody reads the diff.

That is a policy, and policies without a check drift. This is the check.
It is not an argument that wiring the script is wrong forever — it is a
tripwire so that wiring it is a deliberate act that trips a test and
starts a conversation, instead of a line added to a workflow during an
unrelated change.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "apply_hardening.sh"
_WORKFLOWS = _REPO / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    if not _WORKFLOWS.is_dir():
        return []
    return sorted(list(_WORKFLOWS.glob("*.yml")) + list(_WORKFLOWS.glob("*.yaml")))


def test_no_workflow_invokes_the_hardening_script():
    offenders = [
        str(wf.relative_to(_REPO))
        for wf in _workflow_files()
        if "apply_hardening" in wf.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, (
        "a GitHub Actions workflow now references deploy/apply_hardening.sh:\n"
        + "\n".join(f"  {o}" for o in offenders)
        + "\n\nThis script reinstalls the repo's nginx config over the "
        "installed one and reloads nginx. certbot edits that file in place, "
        "so an automated copy can silently revert TLS configuration — and "
        "because the result is still valid nginx, the script's own "
        "`nginx -t` guard will not catch it.\n\n"
        "If running it from CI is genuinely wanted, that is an operator "
        "decision: make it explicitly, and update this test and the #17 "
        "note in UNIMPLEMENTED_BACKLOG.md to record who decided and why."
    )


def test_the_script_is_still_present_and_still_dry_runnable():
    """Non-vacuity in the other direction.

    If the script were deleted, the test above would pass forever while
    describing a file that no longer exists. And the hand-run workflow
    this policy assumes depends on ``--dry-run`` continuing to exist.
    """
    assert _SCRIPT.is_file(), "deploy/apply_hardening.sh is gone — update #17"
    body = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "--dry-run" in body, (
        "the --dry-run path is what makes hand-running this script safe; "
        "it is load-bearing for the disposition recorded in #17"
    )


def test_there_are_workflows_to_scan():
    """Guards the scan itself.

    If ``.github/workflows`` moved, the offender list would be empty for
    the wrong reason and this suite would go quietly green.
    """
    assert _workflow_files(), "no workflow files found — the scan above would pass vacuously"
