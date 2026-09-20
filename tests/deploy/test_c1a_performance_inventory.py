"""Execute the safe branch with command sentinels; never access a remote host."""

import os
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/diagnostics/c1a_closure_inventory.sh"


def journal_namespace():
    script = SCRIPT.read_text(encoding="utf-8")
    code = script.split("<<'DLF_JOURNAL_PY'\n", 1)[1].split("\nDLF_JOURNAL_PY", 1)[0]
    namespace = {"__name__": "safe_probe_test"}
    exec(compile(code, "safe_probe", "exec"), namespace)
    return namespace


def journal_row(message, invocation="a" * 32):
    return json.dumps(
        {
            "MESSAGE": message,
            "_SYSTEMD_INVOCATION_ID": invocation,
            "__REALTIME_TIMESTAMP": "1789907256000000",
        }
    )


def test_journal_fixed_markers_suppress_exception_and_unmatched_secrets():
    classify = journal_namespace()["classify"]
    raw = "\n".join(
        journal_row(message)
        for message in [
            "[DLF] dlfSf fetch failed: https://SECRET/?cookie=SECRET",
            "[DLF] dlfIdp: native Value coverage 0/175 SECRET",
            "[DLF] wrote 56 rows → CSVs/site_raw/dlfRookieSf.csv",
            "[DLF] login failed: <html>SECRET password</html>",
            "SECRET arbitrary unmatched content",
        ]
    )
    events, unknown = classify(raw, "a" * 32)
    assert [event[2] for event in events] == [
        "fetch_failed",
        "wrote",
        "login_failed",
    ]
    assert unknown == 2
    assert "SECRET" not in repr((events, unknown))


@pytest.mark.parametrize(
    "raw",
    [
        "{SECRET",
        journal_row("SECRET", "b" * 32),
        json.dumps({"MESSAGE": ["SECRET"]}),
        journal_row("SECRET" * 2000),
        "\n".join(journal_row("SECRET") for _ in range(200)),
    ],
)
def test_journal_malformed_wrong_invocation_and_truncation_fail_closed(raw):
    with pytest.raises((ValueError, TypeError)):
        journal_namespace()["classify"](raw, "a" * 32)


def test_journal_bounded_command_refuses_overflow():
    with pytest.raises(ValueError, match="overflow"):
        journal_namespace()["bounded"]([sys.executable, "-c", "print('SECRET'*100)"], 20)


def test_journal_closed_stdout_live_child_is_cleaned(monkeypatch):
    namespace = journal_namespace()
    original = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", capture)
    # Windows may retain another inherited pipe handle after os.close(1),
    # selecting the read timeout instead of the post-EOF wait timeout.
    with pytest.raises((subprocess.TimeoutExpired, ValueError)):
        namespace["bounded"]([sys.executable, "-c", "import os,time; os.close(1); time.sleep(30)"])
    assert len(children) == 1
    assert children[0].poll() is not None


def test_journal_post_eof_wait_timeout_always_kills(monkeypatch):
    import io

    class Child:
        stdout = io.BytesIO(b"")
        killed = False

        def poll(self):
            return -1 if self.killed else None

        def wait(self, timeout):
            if not self.killed:
                raise subprocess.TimeoutExpired("private", timeout)
            return -1

        def kill(self):
            self.killed = True

    child = Child()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(subprocess.TimeoutExpired):
        journal_namespace()["bounded"](["private"])
    assert child.killed
    assert child.stdout.closed


def test_journal_invocation_change_emits_no_events(monkeypatch, capsys, tmp_path):
    namespace = journal_namespace()
    calls = []

    def fake(args, limit=65536):
        calls.append(args)
        if args[0] == "git":
            return "1" * 40
        if "--property=ExecStart" in args:
            return "SECRET unrecognized execution"
        if args[0] == "journalctl":
            return journal_row("[DLF] login failed: SECRET")
        return ("a" if sum("--property=InvocationID" in call for call in calls) == 1 else "b") * 32

    namespace["bounded"] = fake
    monkeypatch.setattr(sys, "argv", ["probe", str(tmp_path), "unit.service"])
    with pytest.raises(ValueError, match="changed_invocation"):
        namespace["main"]()
    output = capsys.readouterr().out
    assert "SECRET" not in output
    assert "dlf.journal.event" not in output
    journal = next(call for call in calls if call[0] == "journalctl")
    assert "_SYSTEMD_INVOCATION_ID=" + "a" * 32 in journal
    assert "-n" in journal and "200" in journal


@pytest.mark.parametrize("failed_probe", ["git", "ExecStart"])
def test_optional_identity_failure_does_not_hide_valid_journal(
    monkeypatch, capsys, tmp_path, failed_probe
):
    namespace = journal_namespace()

    def fake(args, limit=65536):
        if args[0] == "git":
            if failed_probe == "git":
                raise ValueError("SECRET git failure")
            return "1" * 40
        if "--property=ExecStart" in args:
            if failed_probe == "ExecStart":
                raise ValueError("SECRET ExecStart failure")
            return "SECRET unrecognized command"
        if args[0] == "journalctl":
            return journal_row("[DLF] dlfSf fetch failed: SECRET")
        return "a" * 32

    namespace["bounded"] = fake
    monkeypatch.setattr(sys, "argv", ["probe", str(tmp_path), "unit.service"])
    namespace["main"]()
    output = capsys.readouterr().out
    if failed_probe == "git":
        assert "dlf.identity.defaultRevision=unavailable" in output
    shape = "unavailable" if failed_probe == "ExecStart" else "other_or_unverified"
    assert "dlf.identity.wrapperCommand=" + shape in output
    assert "dlf.journal.state=classified" in output
    assert "dlf.journal.event0.stage=fetch_failed" in output
    assert "SECRET" not in output


def dlf_metadata(app):
    script = SCRIPT.read_text(encoding="utf-8")
    code = script.split("<<'DLF_METADATA_PY'\n", 1)[1].split("\nDLF_METADATA_PY", 1)[0]
    return subprocess.run(
        [sys.executable, "-c", code, str(app)], capture_output=True, text=True, timeout=10
    )


def test_dlf_safe_metadata_counts_records_without_disclosing_cells(tmp_path):
    folder = tmp_path / "CSVs/site_raw"
    folder.mkdir(parents=True)
    (folder / "dlfSf.csv").write_text('name,rank,value\n"SECRET\nNAME",1,9999\n', encoding="utf-8")
    stamps = tmp_path / "data/scrape_state"
    stamps.mkdir(parents=True)
    (stamps / "dlf_last_success").write_text("1780000000\n")
    result = dlf_metadata(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "dlf.live.dlfSf.rows=1" in result.stdout
    assert "dlf.live.dlfSf.matchesCurrentWriterSchema=1" in result.stdout
    assert "dlf.live.dlf.lastSuccessEpoch=1780000000" in result.stdout
    assert "dedicated_path=assumed_default" in result.stdout
    assert "SECRET" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "content,state", [("bad-secret", "invalid_epoch"), ("9" * 100, "oversize")]
)
def test_dlf_stamp_refuses_invalid_or_oversized_input(tmp_path, content, state):
    folder = tmp_path / "data/scrape_state"
    folder.mkdir(parents=True)
    (folder / "dlf_last_success").write_text(content)
    result = dlf_metadata(tmp_path)
    assert f"dlf.live.dlf.stampState={state}" in result.stdout
    assert content not in result.stdout + result.stderr


def test_dlf_metadata_refuses_symlink(tmp_path):
    folder = tmp_path / "CSVs/site_raw"
    folder.mkdir(parents=True)
    target = tmp_path / "secret"
    target.write_text("SECRET")
    try:
        (folder / "dlfSf.csv").symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable")
    result = dlf_metadata(tmp_path)
    assert "dlf.live.dlfSf.state=unsafe_path" in result.stdout
    assert "SECRET" not in result.stdout + result.stderr


def test_dlf_metadata_refuses_fifo_without_opening(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX FIFO unavailable")
    folder = tmp_path / "CSVs/site_raw"
    folder.mkdir(parents=True)
    os.mkfifo(folder / "dlfSf.csv")
    result = dlf_metadata(tmp_path)
    assert "dlf.live.dlfSf.state=not_regular" in result.stdout


@pytest.mark.parametrize(
    "contents,expected",
    [(b"x" * 2097153, "state=oversize"), (b"\xffSECRET", "csvState=invalid_or_over_limit")],
    ids=["oversize", "invalid-utf8"],
)
def test_dlf_csv_bounds_and_encoding_failure_are_sanitized(tmp_path, contents, expected):
    folder = tmp_path / "CSVs/site_raw"
    folder.mkdir(parents=True)
    (folder / "dlfSf.csv").write_bytes(contents)
    result = dlf_metadata(tmp_path)
    assert f"dlf.live.dlfSf.{expected}" in result.stdout
    assert "SECRET" not in result.stdout + result.stderr


def run_inventory(scope="performance-safe", service="dynasty", failure=False, python_probe=None):
    installed = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(installed) if installed.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash unavailable")
    prelude = r"""
APP_DIR="$PWD"
git() { [[ "$*" == *'rev-parse --verify HEAD' ]] || { echo FORBIDDEN_SECRET; return 91; }; printf '%040d\n' 1; }
systemctl() {
  [[ "$1" == show && "$3" == --property=* && "$4" == --value ]] || { echo FORBIDDEN_MUTATION; return 92; }
  [[ "${PROBE_FAILURE:-0}" == 0 ]] || return 1
  case "$3" in
    --property=LoadState) echo loaded ;;
    --property=ActiveState) echo inactive ;;
    --property=SubState) echo dead ;;
    --property=UnitFileState) echo static ;;
    --property=User|--property=Group) echo 'FORBIDDEN_SECRET=/key' ;;
    --property=MainPID) echo 0 ;;
    --property=Result) echo exit-code ;;
    --property=ExecMainStartTimestamp) echo 'Sun 2026-09-20 12:00:00 UTC' ;;
    *) echo '123
FORBIDDEN_SECRET' ;;
  esac
}
journalctl() { echo FORBIDDEN_JOURNAL; return 93; }
sudo() { echo FORBIDDEN_SUDO; return 94; }
hostname() { echo FORBIDDEN_HOSTNAME; return 95; }
"""
    result = subprocess.run(
        [bash, "--noprofile", "--norc"],
        input=prelude + (python_probe or "") + SCRIPT.read_text(encoding="utf-8"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        env={
            **os.environ,
            "INVENTORY_SCOPE": scope,
            "SERVICE_NAME": service,
            "PROBE_FAILURE": "1" if failure else "0",
        },
        timeout=30,
    )
    return result


def test_safe_scope_filters_arbitrary_unit_text_and_never_reaches_legacy():
    result = run_inventory()
    assert result.returncode == 0, result.stderr
    assert "FORBIDDEN" not in result.stdout + result.stderr
    assert "scope=performance-safe" in result.stdout
    assert "unit.dynasty.service.LoadState=loaded" in result.stdout
    assert "unit.dynasty.service.User=unavailable" in result.stdout
    assert "unit.dynasty.service.MemoryCurrent=unavailable" in result.stdout
    assert "unit.dynasty-source-producer.path.LoadState=loaded" in result.stdout
    assert "unit.nginx.service.LoadState=loaded" in result.stdout
    assert "snapshot_only" in result.stdout
    assert "[c1a-inventory]" not in result.stdout
    assert "unit.dynasty-dlf-fetch.service.Result=exit-code" in result.stdout
    assert (
        "unit.dynasty-dlf-fetch.service.ExecMainStartTimestamp=Sun 2026-09-20 12:00:00 UTC"
        in result.stdout
    )
    assert "unit.dynasty-dlf-fetch.service.ExecMainExitTimestamp=unavailable" in result.stdout


@pytest.mark.parametrize("scope", ["restart", "performance-safe;echo SECRET", "unknown"])
def test_unknown_scope_refuses_before_any_inventory(scope):
    result = run_inventory(scope=scope)
    assert result.returncode == 1
    assert result.stdout == "inventory_error=invalid_scope\n"
    assert result.stderr == ""


@pytest.mark.parametrize("service", ["../other", "dynasty.service", "dynasty;restart", "bad\nname"])
def test_invalid_unit_prefix_refuses_without_echoing_input(service):
    result = run_inventory(service=service)
    assert result.returncode == 1
    assert result.stdout == "inventory_error=invalid_service\n"


def test_failed_probe_is_unknown_not_absent_or_denied():
    result = run_inventory(failure=True)
    assert result.returncode == 0
    assert "unit.dynasty.service.LoadState=probe_failed" in result.stdout
    assert "LoadState=not-found" not in result.stdout


def test_existing_workflow_default_and_concurrency_remain():
    workflow = (ROOT / ".github/workflows/c1a-closure-diagnostics.yml").read_text()
    assert "default: closure" in workflow
    assert "group: c1a-closure-diagnostics" in workflow
    assert "cancel-in-progress: false" in workflow
    assert 'INVENTORY_SCOPE=$(printf %q "$INVENTORY_SCOPE")' in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.index('case "${INVENTORY_SCOPE:-closure}"') < script.index('say "host=')
    assert "closure) ;;" in script
    # Existing closure output is still present behind the separate default branch.
    assert 'kv "remote origin"' in script


@pytest.mark.parametrize("exit_code", [0, 17])
def test_python_startup_output_is_private_and_failure_explicit(exit_code):
    fake = (
        "python3() { echo FORBIDDEN_STARTUP; echo FORBIDDEN_STDERR >&2; "
        f"return {exit_code};" + " };\n"
        'timeout() { shift 3; "$@"; }\n'
    )
    result = run_inventory(python_probe=fake)
    assert result.returncode == 0
    assert "FORBIDDEN" not in result.stdout + result.stderr
    assert "dlf.metadata=probe_failed" in result.stdout
    assert "limits=snapshot_only" in result.stdout


def test_legacy_two_column_board_is_not_called_invalid(tmp_path):
    folder = tmp_path / "CSVs/site_raw"
    folder.mkdir(parents=True)
    (folder / "dlfSf.csv").write_text("name,rank\nSECRET,1\n")
    result = dlf_metadata(tmp_path)
    assert "dlf.live.dlfSf.matchesCurrentWriterSchema=0" in result.stdout
    assert "dlf.live.dlfSf.rows=1" in result.stdout
    assert "schemaValid" not in result.stdout


@pytest.mark.parametrize("mode", ["oversize", "timeout", "empty", "allowed"])
def test_python_wrapper_bounds_and_approved_output(mode):
    bodies = {
        "oversize": "printf '%9000s' x; return 0",
        "timeout": "return 124",
        "empty": "return 0",
        "allowed": "echo dlf.live.dlfSf.rows=1; return 0",
    }
    fake = "python3() { " + bodies[mode] + '; };\ntimeout() { shift 3; "$@"; }\n'
    result = run_inventory(python_probe=fake)
    assert result.returncode == 0
    assert result.stderr == ""
    if mode == "allowed":
        assert "dlf.live.dlfSf.rows=1" in result.stdout
        assert "dlf.metadata=probe_failed" not in result.stdout
    else:
        assert "dlf.metadata=probe_failed" in result.stdout
    source = SCRIPT.read_text()
    assert "timeout -k 1s 15s python3" in source and "head -c 8193" in source


def artifact_namespace():
    import runpy

    return runpy.run_path(str(ROOT / "deploy/diagnostics/c1a_safe_artifact.py"))


def native_marker(count="0", rows="300", floor="240"):
    return (
        f"[DLF] dlfSf: native Value coverage {count}/{rows} "
        f"is below required floor {floor}; semantic/parser degradation. "
        "Preserving last-good CSV, NOT overwriting CSVs/site_raw/dlfSf.csv."
    )


@pytest.mark.parametrize("count", ["0", "239"])
def test_exact_native_coverage_retains_bounded_numbers(count):
    events, unknown = journal_namespace()["classify"](journal_row(native_marker(count)), "a" * 32)
    assert unknown == 0
    assert events[0][3] == {"nativeCount": int(count), "parsedRows": 300, "requiredFloor": 240}


@pytest.mark.parametrize(
    "message",
    [
        native_marker("301"),
        native_marker("240"),
        native_marker("-1"),
        native_marker("1e2"),
        native_marker("1.0"),
        native_marker("9999999999"),
        native_marker(floor="0"),
        native_marker() + " SECRET",
        native_marker().replace("dlfSf", "dlfIdp"),
    ],
)
def test_invalid_native_marker_never_becomes_numeric_evidence(message):
    events, unknown = journal_namespace()["classify"](journal_row(message), "a" * 32)
    assert events == [] and unknown == 1


def execution_struct(path, argv):
    return (
        f"{{ path={path} ; argv[]={argv} ; ignore_errors=no ; start_time=[] ; "
        "stop_time=[] ; pid=0 ; code=exited ; status=0 }"
    )


@pytest.mark.parametrize(
    "path,argv,expected",
    [
        (
            "/app/deploy/dlf_fetch_and_push.sh",
            "/app/deploy/dlf_fetch_and_push.sh",
            "expected_direct",
        ),
        ("/bin/bash", "/bin/bash /app/deploy/dlf_fetch_and_push.sh", "expected_bash_wrapper"),
        ("/bin/bash", "/bin/bash -c /app/deploy/dlf_fetch_and_push.sh", "other_or_unverified"),
        ("/bin/bash", "/bin/bash /app/deploy/dlf_fetch_and_push.sh SECRET", "other_or_unverified"),
        ("/bin/bash", "/bin/bash /app/deploy/dlf_fetch_and_push.sh; SECRET", "other_or_unverified"),
        ("/bin/bash", "/bin/bash /app/deploy/dlf_fetch_and_push.sh.extra", "other_or_unverified"),
        ("/usr/bin/bash", "/usr/bin/bash /app/deploy/dlf_fetch_and_push.sh", "other_or_unverified"),
    ],
)
def test_wrapper_shape_requires_exact_fixed_command(path, argv, expected):
    assert (
        journal_namespace()["execution_shape"](
            execution_struct(path, argv), "/app/deploy/dlf_fetch_and_push.sh"
        )
        == expected
    )


@pytest.mark.parametrize("change", ["missing", "wrong_stage", "contradiction", "floor", "oversize"])
def test_artifact_rejects_inconsistent_numeric_groups(change):
    ns = artifact_namespace()
    raw = artifact_payload(ns).replace(b"stage=fetch_failed", b"stage=native_value_floor")
    fields = {"nativeCount": "0", "parsedRows": "300", "requiredFloor": "240"}
    if change == "missing":
        fields.pop("parsedRows")
    if change == "wrong_stage":
        raw = raw.replace(b"stage=native_value_floor", b"stage=wrote")
    if change == "contradiction":
        fields["nativeCount"] = "301"
    if change == "floor":
        fields["requiredFloor"] = "0"
    if change == "oversize":
        fields["parsedRows"] = "9999999999"
    raw += "".join(f"dlf.journal.event0.{key}={value}\n" for key, value in fields.items()).encode()
    with pytest.raises(ValueError):
        ns["validate"](raw)


def test_numeric_emitter_and_runner_allowlists_agree(monkeypatch, capsys, tmp_path):
    remote = journal_namespace()

    def bounded(args, limit=65536):
        if args[0] == "git":
            return "1" * 40
        if "--property=ExecStart" in args:
            return execution_struct(
                "/bin/bash", "/bin/bash " + str(tmp_path / "deploy/dlf_fetch_and_push.sh")
            )
        if args[0] == "journalctl":
            return journal_row(native_marker("239"))
        return "a" * 32

    remote["bounded"] = bounded
    monkeypatch.setattr(sys, "argv", ["probe", str(tmp_path), "unit.service"])
    remote["main"]()
    output = capsys.readouterr().out
    ns = artifact_namespace()
    raw = ("scope=performance-safe\n" + output + "limits=" + ns["LIMITS"] + "\n").encode()
    result = ns["validate"](raw)
    assert result["dlf.journal.event0.nativeCount"] == "239"
    assert result["dlf.journal.event0.requiredFloor"] == "240"
    assert result["dlf.identity.wrapperCommand"] == "expected_bash_wrapper"
    assert "MESSAGE" not in output and str(tmp_path) not in output


def artifact_payload(namespace):
    return (
        "scope=performance-safe\nunit.dynasty.service.User=PRIVATE_USER\n"
        "dlf.live.dlfSf.rows=123\ndlf.dedicated_path=assumed_default\n"
        "dlf.journal.state=classified\ndlf.journal.unclassified=0\n"
        "dlf.journal.event0.timestampUs=1789907256000000\n"
        "dlf.journal.event0.board=dlfSf\ndlf.journal.event0.stage=fetch_failed\n"
        "limits=" + namespace["LIMITS"] + "\n"
    ).encode()


def test_safe_artifact_only_publishes_allowlisted_fields():
    ns = artifact_namespace()
    result = ns["validate"](artifact_payload(ns))
    assert result["dlf.journal.event0.stage"] == "fetch_failed"
    assert "PRIVATE" not in json.dumps(result)
    assert all(key.startswith(("dlf.journal.", "dlf.identity.")) for key in result)


@pytest.mark.parametrize(
    "mutation",
    [
        "noise",
        "oversize",
        "truncated",
        "duplicate",
        "missing_stage",
        "invalid_stage",
        "wrong_scope",
    ],
)
def test_safe_artifact_refuses_incomplete_or_noisy_output(mutation):
    ns = artifact_namespace()
    raw = artifact_payload(ns)
    if mutation == "noise":
        raw += b"SECRET arbitrary raw stderr\n"
    elif mutation == "oversize":
        raw += b"x" * ns["LIMIT"]
    elif mutation == "truncated":
        raw = raw[:-1]
    elif mutation == "duplicate":
        raw += b"dlf.journal.state=classified\n"
    elif mutation == "missing_stage":
        raw = raw.replace(b"dlf.journal.event0.stage=fetch_failed\n", b"")
    elif mutation == "invalid_stage":
        raw = raw.replace(b"stage=fetch_failed", b"stage=SECRET")
    else:
        raw = raw.replace(b"scope=performance-safe", b"scope=closure")
    with pytest.raises((ValueError, UnicodeError)):
        ns["validate"](raw)


def test_safe_artifact_failed_child_suppresses_stdout_stderr(tmp_path):
    script = tmp_path / "stdin.sh"
    script.write_text("")
    out = tmp_path / "artifact.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy/diagnostics/c1a_safe_artifact.py"),
            "--script",
            str(script),
            "--output",
            str(out),
            "--",
            sys.executable,
            "-c",
            "import sys;print('SECRET');print('SECRET',file=sys.stderr);sys.exit(17)",
        ],
        capture_output=True,
    )
    assert result.returncode == 1
    assert result.stdout == result.stderr == b""
    payload = json.loads(out.read_text())
    assert payload["collection"] == "failed"
    assert "SECRET" not in out.read_text()
    assert "fields" not in payload


def test_safe_artifact_timeout_and_oversize_cleanup(tmp_path):
    ns = artifact_namespace()
    script = tmp_path / "stdin.sh"
    script.write_text("")
    for code in ["import time;time.sleep(10)", "print('x'*100000)"]:
        with pytest.raises((ValueError, subprocess.TimeoutExpired)):
            ns["capture"]([sys.executable, "-c", code], script, timeout=0.1)


def test_safe_artifact_workflow_scope_and_blocking_upload():
    source = (ROOT / ".github/workflows/c1a-closure-diagnostics.yml").read_text()
    assert 'if [[ "$INVENTORY_SCOPE" == performance-safe ]]' in source
    assert "c1a_safe_artifact.py" in source
    assert "always() && inputs.scope == 'performance-safe'" in source
    assert "path: ${{ runner.temp }}/c1a-performance-safe.json" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 3" in source
    entries = json.loads((ROOT / "config/ci/release_gate_classification.json").read_text())[
        "entries"
    ]
    assert (
        entries["c1a-closure-diagnostics.yml::inventory::Upload sanitized performance inventory"][
            "category"
        ]
        == "blocking"
    )


def test_safe_artifact_success_ignores_child_stderr(tmp_path):
    ns = artifact_namespace()
    script = tmp_path / "stdin.sh"
    script.write_text("")
    raw = artifact_payload(ns)
    fields = ns["capture"](
        [
            sys.executable,
            "-c",
            "import sys;sys.stdout.buffer.write(" + repr(raw) + ");print('SECRET',file=sys.stderr)",
        ],
        script,
    )
    assert fields["dlf.journal.state"] == "classified"
    assert "SECRET" not in json.dumps(fields)


def test_safe_artifact_unavailable_journal_is_not_success(tmp_path):
    ns = artifact_namespace()
    script = tmp_path / "stdin.sh"
    script.write_text("")
    out = tmp_path / "artifact.json"
    raw = (
        "scope=performance-safe\ndlf.journal.state=unavailable\nlimits=" + ns["LIMITS"] + "\n"
    ).encode()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy/diagnostics/c1a_safe_artifact.py"),
            "--script",
            str(script),
            "--output",
            str(out),
            "--",
            sys.executable,
            "-c",
            "import sys;sys.stdout.buffer.write(" + repr(raw) + ")",
        ],
        capture_output=True,
    )
    assert result.returncode == 1
    assert result.stdout == result.stderr == b""
    assert json.loads(out.read_text())["collection"] == "incomplete"


@pytest.mark.parametrize("case", ["missing_count", "empty_nonzero", "empty_event"])
def test_safe_artifact_requires_complete_journal_record(case):
    ns = artifact_namespace()
    raw = artifact_payload(ns)
    if case == "missing_count":
        raw = raw.replace(b"dlf.journal.unclassified=0\n", b"")
    elif case == "empty_nonzero":
        raw = (
            "scope=performance-safe\ndlf.journal.state=empty\ndlf.journal.unclassified=1\nlimits="
            + ns["LIMITS"]
            + "\n"
        ).encode()
    else:
        raw = raw.replace(b"state=classified", b"state=empty")
    with pytest.raises(ValueError):
        ns["validate"](raw)


def test_safe_artifact_classified_requires_observed_row():
    ns = artifact_namespace()
    raw = (
        "scope=performance-safe\ndlf.journal.state=classified\ndlf.journal.unclassified=0\nlimits="
        + ns["LIMITS"]
        + "\n"
    ).encode()
    with pytest.raises(ValueError):
        ns["validate"](raw)
    empty = raw.replace(b"state=classified", b"state=empty")
    assert ns["validate"](empty)["dlf.journal.state"] == "empty"
    unknown = raw.replace(b"unclassified=0", b"unclassified=1")
    assert ns["validate"](unknown)["dlf.journal.state"] == "classified"
