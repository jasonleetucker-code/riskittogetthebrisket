"""Structural pins for the V1-49 host-native-scoring activation workflow.

Two things are load-bearing and easy to break silently while editing
either the YAML or the remote script, so this test is a structural
guard rather than a functional one (functional coverage for the actual
flag/backup logic lives in ``tests/scripts/test_prod_env_flag_ops.py``,
``tests/scripts/test_pbp_artifact_backup.py`` and
``tests/scripts/test_diff_bdvm_snapshots.py``):

1. This workflow must never become a general remote-command runner. The
   only thing ever piped over SSH is the ONE fixed, checked-in script
   (``deploy/diagnostics/v1_49_host_native_activation.sh``), and the
   only values threaded into its environment are a small, named,
   non-command set (ACTION, APP_DIR, PYTHON_BIN, EXPECTED_SHA,
   ACTIVATION_ID, BDVM_SEASON, REASON). REASON in particular is
   free-text operator input — it must reach the remote script only as
   an environment value, never concatenated into the command string
   itself or into inline Python source.
2. There is exactly one rollback code path
   (``do_rollback()`` in the shell script), called from exactly the two
   places the design requires: the automatic in-script failure handler,
   and the explicit ``ACTION=rollback`` dispatch branch. A second
   rollback implementation appearing anywhere would mean the two could
   drift out of sync with each other.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_WORKFLOW_PATH = _REPO / ".github" / "workflows" / "v1-49-host-native-scoring-activation.yml"
_SCRIPT_PATH = _REPO / "deploy" / "diagnostics" / "v1_49_host_native_activation.sh"

_ALLOWED_REMOTE_ENV_KEYS = {
    "ACTION",
    "APP_DIR",
    "PYTHON_BIN",
    "EXPECTED_SHA",
    "ACTIVATION_ID",
    "BDVM_SEASON",
    "REASON",
}
_EXPECTED_INPUT_NAMES = {
    "action",
    "confirm_activation",
    "expected_sha",
    "bdvm_season",
    "activation_id",
    "reason",
}


def _load_workflow() -> dict:
    return yaml.safe_load(_WORKFLOW_PATH.read_text())


def _on_block(document: dict) -> dict:
    # ``on:`` is a YAML 1.1 boolean, so safe_load keys it as True. Accept
    # either in case a future loader is configured differently — same
    # idiom as tests/deploy/test_e2e_workflow_triggers.py::_triggers.
    return document.get("on", document.get(True))


def _inputs(document: dict) -> dict:
    return _on_block(document)["workflow_dispatch"]["inputs"]


def _job(document: dict) -> dict:
    jobs = document["jobs"]
    assert len(jobs) == 1, f"expected exactly one job, found {list(jobs)}"
    return next(iter(jobs.values()))


def test_workflow_file_exists_and_parses():
    assert _WORKFLOW_PATH.is_file()
    document = _load_workflow()
    assert "jobs" in document


def test_concurrency_shares_the_production_deploy_group():
    document = _load_workflow()
    concurrency = document["concurrency"]
    assert concurrency["group"] == "production-deploy"
    assert concurrency["cancel-in-progress"] is False


def test_job_runs_in_the_production_environment():
    document = _load_workflow()
    job = _job(document)
    assert job["environment"] == "production"


def test_typed_inputs_are_exactly_the_expected_set():
    document = _load_workflow()
    inputs = _inputs(document)
    assert set(inputs.keys()) == _EXPECTED_INPUT_NAMES


def test_action_input_is_a_closed_choice_with_no_default():
    document = _load_workflow()
    inputs = _inputs(document)
    action_input = inputs["action"]
    assert action_input["type"] == "choice"
    assert set(action_input["options"]) == {"activate", "rollback"}
    assert action_input["required"] is True
    assert "default" not in action_input


def test_no_input_looks_like_a_generic_command_field():
    document = _load_workflow()
    inputs = _inputs(document)
    for name, spec in inputs.items():
        lowered = f"{name} {spec.get('description', '')}".lower()
        assert "command" not in lowered, f"input {name!r} looks like a generic command field"
        assert "shell" not in lowered, f"input {name!r} looks like a generic shell field"


def test_every_remote_ssh_invocation_pipes_the_one_fixed_script():
    """Every SSH call must end in `bash -s" < deploy/diagnostics/v1_49_host_native_activation.sh`
    — never a caller-constructed command string.
    """
    text = _WORKFLOW_PATH.read_text()
    ssh_invocations = re.findall(r'"\$DEPLOY_USER@\$DEPLOY_HOST"\s*\\\n(.*?)\n', text)
    assert ssh_invocations, "expected at least one SSH invocation in the workflow"
    fixed_script_pipes = re.findall(
        r'bash -s"\s*\\\n\s*< deploy/diagnostics/v1_49_host_native_activation\.sh',
        text,
    )
    # One pipe-in per SSH step (preflight, activate, safety-net rollback,
    # explicit rollback) — never a bare `bash -s"` with no fixed script
    # following it, and never a second script path.
    assert len(fixed_script_pipes) >= 4
    assert "deploy/diagnostics/v1_49_host_native_activation.sh" in text
    other_scripts = re.findall(r"< deploy/diagnostics/(\S+\.sh)", text)
    assert set(other_scripts) == {"v1_49_host_native_activation.sh"}


def test_only_the_allowed_env_keys_are_threaded_into_the_remote_command():
    text = _WORKFLOW_PATH.read_text()
    keys = set(
        re.findall(r"([A-Z_][A-Z0-9_]*)=(?:preflight|activate|rollback|\$\(printf %q)", text)
    )
    assert keys, "expected to find at least one remote env-key assignment"
    assert (
        keys <= _ALLOWED_REMOTE_ENV_KEYS
    ), f"unexpected remote env keys: {keys - _ALLOWED_REMOTE_ENV_KEYS}"


def test_reason_is_never_interpolated_directly_as_a_bash_or_python_expression():
    """REASON is free-text operator input. It must only ever appear as a
    shell-quoted environment VALUE (via `printf %q`) — never spliced
    directly into a command string or Python source, which is exactly
    what would let it break out and execute as code.
    """
    workflow_text = _WORKFLOW_PATH.read_text()
    assert 'REASON=$(printf %q "${{ inputs.reason }}")' in workflow_text
    # No other raw appearance of the reason input outside the guarded
    # printf-%q assignment and the human-readable job-summary echo.
    raw_reason_uses = re.findall(r"\$\{\{\s*inputs\.reason\s*\}\}", workflow_text)
    assert len(raw_reason_uses) <= 3  # printf %q, safety-net synthetic reason text, job summary

    script_text = _SCRIPT_PATH.read_text()
    assert "'''${REASON}'''" not in script_text
    assert "REPORT_REASON" in script_text
    assert "os.environ['REPORT_REASON']" in script_text


def test_flag_key_is_a_hardcoded_constant_not_an_input():
    script_text = _SCRIPT_PATH.read_text()
    assert 'FLAG_KEY="RISKIT_FEATURE_HOST_NATIVE_SCORING"' in script_text

    # The flag name may appear in the workflow's prose comments (it does,
    # in the header) but must never appear in anything that actually
    # executes: no input, and no `env:` value on any step.
    document = _load_workflow()
    inputs = _inputs(document)
    assert not any("RISKIT_FEATURE" in name for name in inputs)
    job = _job(document)
    for step in job["steps"]:
        for value in (step.get("env") or {}).values():
            assert "RISKIT_FEATURE" not in str(value)


def test_exactly_one_rollback_implementation():
    script_text = _SCRIPT_PATH.read_text()
    definitions = re.findall(r"^do_rollback\(\)\s*\{", script_text, flags=re.MULTILINE)
    assert len(definitions) == 1, "there must be exactly one do_rollback() implementation"


def test_do_rollback_is_called_from_exactly_the_two_expected_sites():
    script_text = _SCRIPT_PATH.read_text()
    calls = re.findall(r'do_rollback "\$\{state_dir\}"', script_text)
    # Once from the automatic ERR trap handler, once from the explicit
    # rollback action branch.
    assert len(calls) == 2


def test_script_syntax_is_valid_bash():
    result = subprocess.run(["bash", "-n", str(_SCRIPT_PATH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_stdin_piped_invocation_runs_main_without_unbound_variable_crash():
    """Regression pin for a real production incident (first live activation
    dispatch, 2026-08-28): piping the script via stdin into `bash -s` — the
    exact shape
    `ssh ... "bash -s" < deploy/diagnostics/v1_49_host_native_activation.sh`
    uses in the real workflow — leaves BASH_SOURCE with no entry at all
    (no named file is involved), and the bare `${BASH_SOURCE[0]}` guard
    threw "unbound variable" under `set -u` before main() ever ran. Every
    real dispatch failed at that line regardless of ACTION or inputs; the
    bug was invisible to `bash -n` (syntax-valid) and to the sourced-file
    unit tests below (a real named path populates BASH_SOURCE correctly,
    so sourcing never exercised this branch).

    Reproduces the exact invocation shape here — stdin, no filename — and
    asserts main() actually reaches its own dispatch logic rather than
    crashing on the unset guard variable.
    """
    with open(_SCRIPT_PATH, "rb") as script_file:
        result = subprocess.run(
            ["bash", "-s"],
            stdin=script_file,
            capture_output=True,
            text=True,
            env={**os.environ, "ACTION": ""},
            timeout=30,
        )
    assert "unbound variable" not in result.stderr, result.stderr
    assert "ACTION must be one of" in result.stderr, result.stderr
    assert result.returncode == 1


def _source_script_and_run(app_dir: Path, bash_code: str) -> subprocess.CompletedProcess:
    """Source the real script with APP_DIR pointed at a scratch directory,
    then run `bash_code`. main() never auto-runs when sourced (the
    BASH_SOURCE guard at the script's end). ENV_FILE is derived from
    APP_DIR INSIDE the script (`ENV_FILE="${APP_DIR}/.env"`, not read
    from a pre-set env var) — so APP_DIR is the only lever that controls
    which .env the sourced functions see.
    """
    script = f'source "{_SCRIPT_PATH}" >/dev/null 2>&1; {bash_code}'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "APP_DIR": str(app_dir)},
        timeout=30,
    )


def test_env_file_is_never_sourced_as_bash(tmp_path):
    """Regression pin for a real production incident (second live
    activation attempt, run 33176834694, 2026-08-28): production's real
    `.env` contains a line that is not valid `KEY=VALUE` bash syntax (a
    bare hex string, believed to be a wrapped/partial secret), and the
    old `source`-based loader tried to execute it as a command (exit 127,
    `command not found`). `env_sourced_python` must parse `.env` as plain
    KEY=VALUE text and never hand any of it to bash for execution.
    """
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / ".env").write_text(
        "FOO=bar\n"
        "RISKIT_FEATURE_HOST_NATIVE_SCORING=0\n"
        "c503b850537d737346e1f321b73ed2c9d889e0cde5636bf008985dfa1c17feaf\n"
        "BAZ=qux with spaces\n"
        "# a comment\n"
        "\n"
        "EMPTY_VALUE=\n"
    )
    result = _source_script_and_run(
        app_dir,
        'env_sourced_python -c "import os; '
        "print('FOO=' + os.environ.get('FOO', 'MISSING')); "
        "print('BAZ=' + os.environ.get('BAZ', 'MISSING')); "
        "print('RISKIT=' + os.environ.get('RISKIT_FEATURE_HOST_NATIVE_SCORING', 'MISSING')); "
        "print('EMPTY=[' + os.environ.get('EMPTY_VALUE', 'MISSING') + ']')\"",
    )
    assert result.returncode == 0, result.stderr
    assert "command not found" not in result.stderr, result.stderr
    assert "FOO=bar" in result.stdout
    assert "BAZ=qux with spaces" in result.stdout
    assert "RISKIT=0" in result.stdout
    assert "EMPTY=[]" in result.stdout


def test_env_sourced_python_env_args_skips_malformed_lines_silently(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / ".env").write_text("A=1\nnot a key value line\nB=2\n")
    result = _source_script_and_run(app_dir, "env_sourced_python_env_args")
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines == ["A=1", "B=2"]


def test_env_sourced_python_tolerates_a_missing_env_file(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()  # deliberately no .env written
    result = _source_script_and_run(app_dir, "env_sourced_python -c \"print('ok')\"")
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def _run_validate_activation_id(value: str) -> subprocess.CompletedProcess:
    """Source the script (never runs main(), see the BASH_SOURCE guard at
    its end) and call validate_activation_id in isolation — the actual
    behavioral check for the path-traversal guard on ACTIVATION_ID,
    which for `action=rollback` is free-text operator input threaded
    straight into a filesystem path (STATE_ROOT/${ACTIVATION_ID}).
    """
    script = f'source "{_SCRIPT_PATH}" && validate_activation_id "$1" && echo VALID'
    return subprocess.run(
        ["bash", "-c", script, "bash", value],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_validate_activation_id_accepts_realistic_ids():
    for value in ["33066619784", "v149_pre_123", "activation-id.2026", "A"]:
        result = _run_validate_activation_id(value)
        assert result.returncode == 0, f"{value!r}: {result.stderr}"
        assert "VALID" in result.stdout


def test_validate_activation_id_rejects_path_traversal_and_empty_values():
    for value in ["../../etc", "..", ".", "foo/bar", "foo bar", "", "$(rm -rf /)"]:
        result = _run_validate_activation_id(value)
        assert result.returncode != 0, f"expected rejection for {value!r}"
        assert "VALID" not in result.stdout


def test_do_activate_and_do_rollback_action_both_validate_activation_id():
    script_text = _SCRIPT_PATH.read_text()
    do_activate_body = script_text.split("do_activate() {", 1)[1].split(
        "\ndo_rollback_action()", 1
    )[0]
    do_rollback_action_body = script_text.split("do_rollback_action() {", 1)[1]
    assert "validate_activation_id" in do_activate_body
    assert "validate_activation_id" in do_rollback_action_body


def test_workflow_only_references_the_established_ssh_secrets():
    text = _WORKFLOW_PATH.read_text()
    expected_secrets = {
        "DEPLOY_SSH_PRIVATE_KEY",
        "DEPLOY_KNOWN_HOSTS",
        "DEPLOY_PORT",
        "DEPLOY_HOST",
        "DEPLOY_USER",
    }
    used_secrets = set(re.findall(r"secrets\.([A-Z_]+)", text))
    assert used_secrets == expected_secrets


def test_merging_this_workflow_never_dispatches_it():
    document = _load_workflow()
    assert set(_on_block(document).keys()) == {"workflow_dispatch"}
