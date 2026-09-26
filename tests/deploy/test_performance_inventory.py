"""Privacy and failure boundaries of the opt-in read-only SSH inventory."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "performance_inventory", ROOT / "deploy/diagnostics/performance_inventory.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def report():
    p = {k: None for k in probe.PROCESS_NUMBERS}
    p.update(state="unavailable", cwdMatchesCheckout=None)
    u = {k: None for k in probe.UNIT_NUMBERS}
    u.update(state="unavailable", load=None, active=None, memoryUnlimited=False, process=p)
    return {
        "schema": 1,
        "state": "partial",
        "checkoutBefore": None,
        "checkoutAfter": None,
        "checkoutStable": False,
        "loadedProcessRevision": None,
        "rows": [
            {
                "sequence": 0,
                "observedAtEpochSeconds": 100.0,
                "elapsedSeconds": 0.1,
                "host": dict.fromkeys(probe.HOST_NUMBERS),
                "units": {k: u for k in probe.ROLES},
            }
        ],
    }


def test_exact_schema_accepts_missing_as_unknown_not_zero():
    value = report()
    assert probe.validate(json.dumps(value).encode(), 1) == value


@pytest.mark.parametrize(
    "mutation", ["extra", "secret", "nan", "bool", "missing", "identity", "order"]
)
def test_external_data_cannot_extend_schema(mutation):
    value = report()
    if mutation == "extra":
        value["credential"] = "SECRET_SENTINEL"
    elif mutation == "secret":
        value["rows"][0]["units"]["web"]["active"] = "SECRET_SENTINEL"
    elif mutation == "nan":
        value["rows"][0]["host"]["cpuCount"] = float("nan")
    elif mutation == "bool":
        value["rows"][0]["host"]["cpuCount"] = True
    elif mutation == "missing":
        value["rows"].clear()
    elif mutation == "identity":
        value["loadedProcessRevision"] = "a" * 40
    else:
        value["rows"][0]["sequence"] = 2
    with pytest.raises(probe.ProbeError):
        probe.validate(json.dumps(value).encode(), 1)


def test_duplicate_and_oversize_refused():
    with pytest.raises(probe.ProbeError):
        probe.validate(b'{"schema":1,"schema":1}', 1)
    with pytest.raises(probe.ProbeError):
        probe.validate(b"x" * (probe.CAP + 1), 1)


def test_false_complete_refused_and_identity_change_is_partial():
    from copy import deepcopy

    value = report()
    value["state"] = "complete"
    with pytest.raises(probe.ProbeError):
        probe.validate(json.dumps(value).encode(), 1)
    value["checkoutBefore"] = value["checkoutAfter"] = "a" * 40
    value["checkoutStable"] = True
    row = value["rows"][0]
    row["host"] = dict.fromkeys(probe.HOST_NUMBERS, 1)
    web = row["units"]["web"]
    web.update(state="observed", load="loaded", active="active", MainPID=1)
    web["process"] = dict.fromkeys(probe.PROCESS_NUMBERS, 1)
    web["process"].update(state="observed", cwdMatchesCheckout=True)
    assert probe.validate(json.dumps(value).encode(), 1)["state"] == "complete"
    second = deepcopy(row)
    second.update(sequence=1, elapsedSeconds=1)
    second["units"]["web"]["process"]["startTicks"] = 2
    value["rows"].append(second)
    with pytest.raises(probe.ProbeError):
        probe.validate(json.dumps(value).encode(), 2)
    value["state"] = "partial"
    assert probe.validate(json.dumps(value).encode(), 2)["state"] == "partial"


def test_parser_rejects_values_without_echoing_them(capsys):
    parser = probe.Parser()
    parser.add_argument("--count", type=int)
    with pytest.raises(probe.ProbeError):
        parser.parse_args(["--count", "SECRET_SENTINEL"])
    assert "SECRET" not in capsys.readouterr().err


def test_stderr_never_in_capture():
    out = probe.bounded([sys.executable, "-c", "import sys;sys.stderr.write('SECRET');print('ok')"])
    assert out.strip() == b"ok"


@pytest.mark.parametrize(
    "body",
    ["print('x'*20000)", "import time;time.sleep(5)", "import os,time;os.close(1);time.sleep(5)"],
)
def test_capture_bounds_and_closed_stdout_cleanup(body, monkeypatch):
    children = []
    original = probe.subprocess.Popen

    def record(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(probe.subprocess, "Popen", record)
    with pytest.raises(probe.ProbeError):
        probe.bounded([sys.executable, "-c", body], timeout=0.3, cap=4096)
    assert children[0].poll() is not None


def test_unit_unknown_and_unlimited_are_distinct(monkeypatch):
    monkeypatch.setattr(
        probe,
        "bounded",
        lambda *a,
        **k: b"LoadState=loaded\nActiveState=inactive\nMainPID=0\nMemoryMax=infinity\nPrivate=SECRET\n",
    )
    value = probe.unit("fixture.service", "/fixture")
    assert value["state"] == "observed"
    assert value["memoryUnlimited"] is True
    assert value["MemoryMax"] is None
    assert value["process"]["state"] == "not-running"
    assert "SECRET" not in json.dumps(value)
    monkeypatch.setattr(probe, "bounded", lambda *a, **k: b"LoadState=SECRET\nActiveState=active\n")
    assert probe.unit("fixture.service", "/fixture")["state"] == "unavailable"


def test_missing_pid_is_not_observed_stopped_process():
    assert probe.process(None, "/fixture")["state"] == "unavailable"
    assert probe.process(0, "/fixture")["state"] == "not-running"


@pytest.mark.parametrize("partial", [False, True])
def test_unreadable_fds_are_unknown_even_after_partial_iteration(monkeypatch, partial):
    stat = "1 (fixture) " + " ".join(["1"] * 22)

    def read(path, **kwargs):
        return (
            "Uid:\t1\nGid:\t1\nVmRSS:\t2 kB\nThreads:\t1\n"
            if str(path).endswith("status")
            else stat
        )

    def denied(path):
        if partial:
            yield Path("one")
        raise PermissionError("SECRET")

    monkeypatch.setattr(probe, "read_text", read)
    monkeypatch.setattr(Path, "iterdir", denied)
    value = probe.process(1, "/fixture")
    assert value["state"] == "observed"
    assert value["fdCount"] is None


def test_transport_failure_only_writes_fixed_failure(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise probe.ProbeError("SECRET_SENTINEL")

    monkeypatch.setattr(probe, "bounded", fail)
    monkeypatch.setenv("DEPLOY_HOST", "example.invalid")
    monkeypatch.setenv("DEPLOY_USER", "fixture")
    output = tmp_path / "safe.json"
    monkeypatch.setattr(sys, "argv", ["probe", "--output", str(output)])
    assert probe.main() == 1
    value = json.loads(output.read_text())
    assert value["state"] == "probe-failed"
    assert "SECRET" not in output.read_text()


def test_workflow_scope_is_separate_from_legacy_and_deploy():
    workflow = (ROOT / ".github/workflows/c1a-closure-diagnostics.yml").read_text()
    assert 'default: "closure"' in workflow
    assert "inputs.scope == 'closure' || inputs.scope == ''" in workflow
    assert "group: c1a-closure-diagnostics" in workflow
    assert "path: performance-safe.json" in workflow
    assert "--output performance-safe.json" in workflow


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux proc observation")
def test_current_process_identity_and_descriptors():
    import os

    value = probe.process(os.getpid(), os.getcwd())
    assert value["state"] == "observed"
    assert value["pid"] == os.getpid()
    assert value["startTicks"] > 0
    assert value["fdCount"] >= 3
    assert value["cwdMatchesCheckout"] is True


def test_unit_diagnostics_are_categorical_and_numeric(monkeypatch):
    monkeypatch.setattr(
        probe,
        "bounded",
        lambda *a, **k: (
            b"LoadState=loaded\nActiveState=failed\nMainPID=0\nResult=exit-code\n"
            b"ExecMainCode=1\nExecMainStartTimestampMonotonic=1200\n"
            b"SuccessExitStatus=2 0 2\nPrivate=SECRET\n"
        ),
    )
    unit = probe.unit("fixture.service", "/fixture")
    assert unit["diagnostics"]["result"] == "exit-code"
    assert unit["diagnostics"]["successExitStatuses"] == [0, 2]
    assert unit["diagnostics"]["ExecMainStartTimestampMonotonic"] == 1200
    value = report()
    value["rows"][0]["units"]["dlf"] = unit
    assert probe.validate(json.dumps(value).encode(), 1) == value
    assert "SECRET" not in json.dumps(value)
    unit["diagnostics"]["result"] = "SECRET"
    with pytest.raises(probe.ProbeError):
        probe.validate(json.dumps(value).encode(), 1)


@pytest.mark.parametrize("status", ["SIGTERM", "256", "2 SECRET", "-1"])
def test_unparseable_success_status_unknown(monkeypatch, status):
    monkeypatch.setattr(
        probe,
        "bounded",
        lambda *a, **k: (
            "LoadState=loaded\nActiveState=inactive\nSuccessExitStatus=" + status
        ).encode(),
    )


@pytest.mark.parametrize("bad", [True, 1.5, -1, "SECRET"])
def test_diagnostic_timestamp_rejects_non_integer_and_private_values(monkeypatch, bad):
    monkeypatch.setattr(
        probe, "bounded", lambda *a, **k: b"LoadState=loaded\nActiveState=inactive\n"
    )
    value = report()
    unit = probe.unit("fixture.service", "/fixture")
    unit["diagnostics"]["ExecMainStartTimestampMonotonic"] = bad
    value["rows"][0]["units"]["dlf"] = unit
    with pytest.raises(probe.ProbeError):
        probe.validate(json.dumps(value).encode(), 1)
    assert probe.unit("fixture.service", "/fixture")["diagnostics"]["successExitStatuses"] is None


@pytest.mark.parametrize("body", ['["dlfSf","dlfIdp"]', "[]"])
def test_manifest_fixed_keys_and_old_schema_compatible(tmp_path, body):
    path = tmp_path / "manifest.json"
    path.write_text(body)
    observed = probe.dlf_manifest(path)
    assert observed["state"] == "observed"
    assert observed["assumedDefaultPath"] is True
    assert observed["written"]["dlfSf"] == ("dlfSf" in body)
    value = report()
    assert probe.validate(json.dumps(value).encode(), 1) == value
    value["dlfManifest"] = observed
    assert probe.validate(json.dumps(value).encode(), 1) == value


@pytest.mark.parametrize("body", ['["SECRET"]', '["dlfSf","dlfSf"]', "{}", "x" * 4097])
def test_manifest_malformed_or_private_data_stays_unknown(tmp_path, body):
    path = tmp_path / "manifest.json"
    path.write_text(body)
    value = probe.dlf_manifest(path)
    assert value["state"] == "unavailable"
    assert all(x is None for x in value["written"].values())
    assert "SECRET" not in json.dumps(value)


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX FIFO and symlink semantics")
def test_manifest_rejects_fifo_and_symlink(tmp_path):
    import os

    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    assert probe.dlf_manifest(fifo)["state"] == "unavailable"
    target = tmp_path / "target"
    target.write_text("[]")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert probe.dlf_manifest(link)["state"] == "unavailable"
