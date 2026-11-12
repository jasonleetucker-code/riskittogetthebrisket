"""The production heap report is read-only and prints only validated numbers
and code identifiers (WA-17).

``deploy/diagnostics/prod_heap_report.sh`` reads the box-local log that
``src/diagnostics/heap_report.py`` writes and summarises it.  Pinned: it
works on real records, a tampered line cannot carry text into the job log,
"could not look" fails closed (exit 5), and the workflow is dispatch-only,
read-only, and never holds the deploy concurrency group.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from src.diagnostics import heap_report

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "diagnostics" / "prod_heap_report.sh"
WORKFLOW = REPO / ".github" / "workflows" / "prod-heap-report.yml"
SECRET = "sk-live-SECRET-TOKEN-0123456789"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash script")


def _filter(text: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), "--filter", *args],
        input=text,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _real_records() -> str:
    held = [{"k": i} for i in range(5000)]
    a = heap_report.snapshot("startup", include_types=True)
    b = heap_report.snapshot("periodic")
    c = heap_report.snapshot(
        "post_publish", include_types=True, extra={"trimRssBeforeMib": 900, "trimRssAfterMib": 700}
    )
    del held
    return "\n".join(json.dumps(r) for r in (a, b, c)) + "\n"


def test_script_parses_and_is_executable():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0
    assert os.access(SCRIPT, os.X_OK)


def test_report_on_real_records():
    res = _filter(_real_records())
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "== series (MiB) == records=3 dropped=0" in out
    assert re.search(r"^\S+ +startup +\d+", out, re.M)
    assert "900->700" in out
    assert "== type census" in out and "census_ms=" in out
    assert "== deep census" in out
    assert "== growth by type" in out
    assert "== growth by deep root" in out
    assert "== growth by container" in out


def test_tampered_lines_cannot_carry_text():
    rec = json.loads(_real_records().splitlines()[-1])
    rec["reason"] = f"periodic {SECRET}"  # not an identifier: whole record dropped
    bad_reason = json.dumps(rec)
    rec2 = json.loads(_real_records().splitlines()[-1])
    rec2["containers"].append({"name": f"src.x.{SECRET}; rm -rf /", "kind": "dict", "len": 1})
    rec2["containers"].append({"name": "src.ok.NAME", "kind": "dict", "len": SECRET})
    rec2["types"]["top"].append({"type": "str", "count": 1, "mib": SECRET})
    rec2["deep"]["top"].append(
        {"name": f"src.y\n{SECRET}", "kind": "dict", "mib": 1.0, "objects": 1}
    )
    rec2["malloc"]["in_use_mib"] = SECRET
    rec2["extra"] = {"trimRssBeforeMib": SECRET}
    text = (
        "\n".join([bad_reason, json.dumps(rec2), "not json " + SECRET, json.dumps(SECRET)]) + "\n"
    )
    res = _filter(text)
    assert res.returncode == 0, res.stderr
    assert SECRET not in res.stdout + res.stderr
    assert "records=1 dropped=3" in res.stdout
    assert "rm -rf" not in res.stdout


def test_no_valid_record_fails_closed():
    res = _filter("")
    assert res.returncode == 5
    res = _filter("garbage\n{}\n")
    assert res.returncode == 5
    assert "no valid heap record" in res.stderr


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1;id", "123456"])
def test_bad_max_records_is_refused(bad):
    res = _filter(_real_records(), bad)
    assert res.returncode == 2


def test_max_records_keeps_the_newest():
    res = _filter(_real_records(), "1")
    assert res.returncode == 0
    assert "records=1" in res.stdout
    assert "post_publish" in res.stdout and " startup " not in res.stdout


def _box_run(app_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "APP_DIR": str(app_dir)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_box_mode_reads_the_app_log(tmp_path):
    log = tmp_path / "data" / "diagnostics" / "heap_reports.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(_real_records(), encoding="utf-8")
    res = _box_run(tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stdout.startswith("log: ")
    assert "records=3" in res.stdout


def test_box_mode_missing_log_fails_closed(tmp_path):
    res = _box_run(tmp_path)
    assert res.returncode == 5
    assert "not readable" in res.stderr


def test_script_never_acts_on_the_host():
    """The shell around the embedded reader runs no service, network or
    file-changing command, and redirects only to stderr or /dev/null."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("python3 -c '")
    end = text.index('\' "${max_records}"', start)
    shell = text[:start] + text[end:]
    code = "\n".join(ln for ln in shell.splitlines() if not ln.lstrip().startswith("#"))
    for forbidden in (
        "systemctl",
        "sudo",
        "kill",
        "rm ",
        "curl",
        "wget",
        "git ",
        "tee ",
        "mv ",
        "cp ",
    ):
        assert forbidden not in code, forbidden
    for target in re.findall(r">{1,2}\s*(\S+)", code):
        assert target.startswith("&") or target == "/dev/null", target
    reader = text[start:end]
    for forbidden in ("open(", "subprocess", "os.system", "write("):
        assert forbidden not in reader, forbidden


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_is_dispatch_only_read_only_and_off_the_deploy_group():
    doc = _workflow()
    on = doc[True]  # PyYAML reads the bare key `on` as True
    assert set(on) == {"workflow_dispatch"}
    assert doc["permissions"] == {"contents": "read"}
    assert doc["concurrency"] == {"group": "production-diagnostics", "cancel-in-progress": False}


def test_workflow_runs_this_script_over_strict_ssh_and_propagates_its_status():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "< deploy/diagnostics/prod_heap_report.sh" in text
    assert "-o BatchMode=yes" in text and "-o StrictHostKeyChecking=yes" in text
    step = next(
        s
        for s in _workflow()["jobs"]["heap-report"]["steps"]
        if s.get("name") == "Read the heap report"
    )
    runnable = [ln for ln in step["run"].splitlines() if not ln.lstrip().startswith("#")]
    assert not any("|| true" in ln for ln in runnable)
    assert any("printf %q" in ln for ln in runnable)
