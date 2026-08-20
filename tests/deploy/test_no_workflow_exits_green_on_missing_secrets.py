"""A workflow may not report success because its credentials are absent.

CI reliability lane, 2026-08-20.

``.github/workflows/trigger-sharp-no-environment.yml`` contained, verbatim::

    if [[ -z "$HOST" || -z "$USER" || -z "$KEY" || -z "$HOSTS" ]]; then
      python - "$RESULT" <<'PY'
      ...data["phase"]="missing_repository_secrets"...
      PY
        exit 0
    fi

That is an unconditional-success path.  A run with no credentials cannot
have verified anything, and reporting it green is indistinguishable — on
the checks UI, in an email, in a merge decision — from a run that looked
and found production healthy.  "We could not look" and "we looked and it
was fine" must not render the same.

The compliant shape is already in the tree, in
``sharp-records-bootstrap.yml``::

    for name in DEPLOY_HOST DEPLOY_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_KNOWN_HOSTS; do
      if [[ -z "${!name:-}" ]]; then
        echo "::error title=Missing production SSH configuration::${name} is empty or unset."
        exit 1
      fi
    done

so this guard asserts a shape the repository already uses rather than
inventing one.

SCOPE, deliberately narrow.  ``exit 0`` is a perfectly good thing for a
workflow to do — fourteen steps across this repo use it for
"nothing-to-close", "nothing-stranded", "already at this commit".  The
guard fires only on an ``exit 0`` reached from a branch whose CONDITION
tests a secret-derived variable for emptiness, which is the one case
where exiting zero is a claim the run is not entitled to make.

COMMENT LINES ARE STRIPPED, and that is load-bearing rather than
tidiness — the same lesson ``test_sharp_smoke_commit_order.py`` records.
A workflow comment quoting ``exit 0`` while explaining why a step does
NOT do that would otherwise be read as the code doing it.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

# ``KEY: ${{ secrets.DEPLOY_SSH_PRIVATE_KEY }}`` in a step or job ``env:``.
_SECRET_EXPR = re.compile(r"\$\{\{\s*secrets\.", re.IGNORECASE)

# ``-z "$KEY"`` / ``-z "${KEY}"`` / ``-z "${KEY:-}"`` / ``-z "${!name:-}"``.
_EMPTINESS_TEST = re.compile(r"-z\s+\"?\$\{?!?([A-Za-z_][A-Za-z0-9_]*)")

_BLOCK_OPEN = re.compile(r"(^|;|\s)(if|for|while|until|case)\s")
_BLOCK_CLOSE = re.compile(r"(^|;|\s)(fi|done|esac)(\s|;|$)")


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, "no workflow files found — this guard would pass vacuously"
    return files


def _runnable(script: str) -> list[str]:
    """Script lines with comment-only lines removed.  See the module docstring."""
    return [line for line in script.splitlines() if not line.lstrip().startswith("#")]


def _secret_names(document: dict, job: dict, step: dict) -> set[str]:
    """Every env name in scope for ``step`` whose value reads a secret."""
    names: set[str] = set()
    for scope in (document, job, step):
        env = (scope or {}).get("env") or {}
        if not isinstance(env, dict):
            continue
        for name, value in env.items():
            if isinstance(value, str) and _SECRET_EXPR.search(value):
                names.add(str(name))
    return names


def _steps(document: dict):
    for job_name, job in (document.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                yield job_name, job, step


def _offending_blocks(lines: list[str], secrets: set[str]) -> list[str]:
    """Blocks guarded on an empty secret that can reach ``exit 0``."""
    offences: list[str] = []
    for index, line in enumerate(lines):
        tested = {name for name in _EMPTINESS_TEST.findall(line)}
        # ``${!name}`` indirection: the loop variable holds the secret NAME,
        # so treat any emptiness test inside a step that reads secrets as
        # in scope when the tested identifier is not itself a secret name.
        if not tested or not secrets:
            continue
        if not (tested & secrets) and not any(s in line for s in secrets):
            continue
        depth = 0
        body: list[str] = []
        for candidate in lines[index:]:
            body.append(candidate)
            depth += len(_BLOCK_OPEN.findall(candidate))
            depth -= len(_BLOCK_CLOSE.findall(candidate))
            if depth <= 0 and len(body) > 1:
                break
        text = "\n".join(body)
        exits_green = re.search(r"(^|\s|;)exit\s+0(\s|;|$)", text, re.MULTILINE)
        refuses = re.search(r"(^|\s|;)exit\s+[1-9]", text, re.MULTILINE)
        if exits_green and not refuses:
            offences.append(text)
    return offences


def test_no_workflow_reports_success_when_its_secrets_are_missing():
    failures: list[str] = []
    for path in _workflow_files():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(document, dict):
            continue
        for job_name, job, step in _steps(document):
            secrets = _secret_names(document, job, step)
            if not secrets:
                continue
            for block in _offending_blocks(_runnable(step["run"]), secrets):
                failures.append(
                    f"{path.name} :: job {job_name} :: step "
                    f"{step.get('name', '<unnamed>')!r}\n{block}"
                )
    assert not failures, (
        "a workflow exits GREEN from a branch that fired because its credentials "
        "were absent — 'we could not look' must not render the same as 'we looked "
        "and it was fine'.  Refuse with `::error` + `exit 1`, the shape "
        "sharp-records-bootstrap.yml already uses:\n\n" + "\n\n".join(failures)
    )


def test_the_compliant_shape_is_recognised_as_compliant():
    """Non-vacuity: the guard must PASS the repo's own correct pattern.

    Without this, a guard that simply never matches anything would look
    identical to a guard that found nothing wrong.
    """
    bootstrap = WORKFLOWS / "sharp-records-bootstrap.yml"
    assert bootstrap.exists(), "the compliant reference workflow is gone"
    document = yaml.safe_load(bootstrap.read_text(encoding="utf-8"))
    checked = 0
    for _job_name, job, step in _steps(document):
        secrets = _secret_names(document, job, step)
        if not secrets:
            continue
        lines = _runnable(step["run"])
        if not any(_EMPTINESS_TEST.search(line) for line in lines):
            continue
        checked += 1
        assert not _offending_blocks(lines, secrets)
    assert checked, (
        "no secret-emptiness check was found in sharp-records-bootstrap.yml — "
        "the guard's calibration reference has moved and it may now be vacuous"
    )
