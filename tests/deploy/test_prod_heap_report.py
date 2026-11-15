"""The production heap report is read-only and prints only validated numbers
and code identifiers (WA-17).

``deploy/diagnostics/prod_heap_report.sh`` reads the box-local log that
``src/diagnostics/heap_report.py`` writes and summarises it.  Pinned: it
works on real records, a tampered line cannot carry text into the job log,
"could not look" fails closed (exit 5), and the workflow is dispatch-only,
read-only, and never holds the deploy concurrency group.
"""

from __future__ import annotations

import functools
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


@functools.lru_cache(maxsize=1)
def _real_records() -> str:
    """Three real records, built once per process with a small deep-census
    budget (CI shard processes hold millions of objects)."""
    budget = heap_report.DEEP_BUDGET
    heap_report.DEEP_BUDGET = 200_000
    try:
        held = [{"k": i} for i in range(5000)]
        a = heap_report.snapshot("startup", include_types=True)
        b = heap_report.snapshot("periodic")
        c = heap_report.snapshot(
            "post_publish",
            include_types=True,
            extra={"trimRssBeforeMib": 900, "trimRssAfterMib": 700},
        )
        del held
    finally:
        heap_report.DEEP_BUDGET = budget
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


def test_series_separates_python_memory_from_glibc():
    """other_anon = anonymous RSS - glibc arena - glibc mmap, per record."""
    rec = json.loads(_real_records().splitlines()[0])
    rec["rss_anon_mib"], rec["rss_file_mib"] = 900, 120
    rec["malloc"].update(arena_mib=300, mmap_mib=50)
    rec["gc"]["allocated_blocks"] = 2_345_678
    res = _filter(json.dumps(rec) + "\n")
    assert res.returncode == 0, res.stderr
    row = next(ln for ln in res.stdout.splitlines() if " startup " in ln).split()
    header = next(ln for ln in res.stdout.splitlines() if ln.startswith("ts_utc")).split()
    cols = dict(zip(header, row))
    assert cols["anon"] == "900" and cols["file"] == "120"
    assert cols["o_anon"] == "550"  # 900 - 300 - 50
    assert cols["kblocks"] == "2345"
    assert "other anonymous 550 MiB" in res.stdout


def test_containers_come_from_the_last_full_snapshot():
    """A light record (scrape path) carries no containers; the section must
    not go blank when it is the newest line."""
    full = json.loads(_real_records().splitlines()[0])
    light = dict(full, reason="post_trim", containers=[], types=None, deep=None)
    light["malloc"] = {k: None for k in full["malloc"]}
    res = _filter(json.dumps(full) + "\n" + json.dumps(light) + "\n")
    assert res.returncode == 0, res.stderr
    section = res.stdout.split("== largest containers", 1)[1]
    assert "(startup)" in section.splitlines()[0]
    assert "len=" in section


def test_sections_follow_the_highest_rss_process():
    """A restart starts a new, small heap; the census and growth sections
    must describe the process that climbed, not the newest one."""
    full = json.loads(_real_records().splitlines()[0])
    climbed = dict(
        full, pid=111, process_rss_mib=1200, ts="2026-11-12T20:25:40+00:00", reason="periodic"
    )
    climbed["containers"] = [{"name": "src.x.CLIMBER", "kind": "dict", "len": 999}]
    fresh = dict(
        full, pid=222, process_rss_mib=500, ts="2026-11-12T20:52:37+00:00", reason="startup"
    )
    fresh["containers"] = [{"name": "src.y.FRESH", "kind": "dict", "len": 5}]
    res = _filter(json.dumps(climbed) + "\n" + json.dumps(fresh) + "\n")
    assert res.returncode == 0, res.stderr
    assert "focus: pid 111 (highest RSS in the window: 1200 MiB" in res.stdout
    section = res.stdout.split("== largest containers", 1)[1]
    assert "src.x.CLIMBER" in section and "src.y.FRESH" not in section


def test_the_census_at_the_peak_is_printed_beside_the_latest():
    """Production 2026-11-12 21:07: the census at 2,151 MiB held the burst
    (2.1 M tracked objects); 15 min later the latest held 0.6 M.  Both
    must be readable, and type growth must run to the peak."""
    base = json.loads(_real_records().splitlines()[0])

    def rec(ts, rss, count):
        r = json.loads(json.dumps(base))
        r.update(pid=7, ts=ts, process_rss_mib=rss, reason="periodic_high_rss")
        r["types"] = {
            "tracked_objects": count,
            "top": [{"type": "dict", "count": count, "mib": 1.0}],
        }
        return r

    lines = [
        rec("2026-11-12T20:52:37+00:00", 535, 100),
        rec("2026-11-12T21:07:42+00:00", 2151, 9000),
        rec("2026-11-12T21:22:57+00:00", 1779, 300),
    ]
    res = _filter("\n".join(json.dumps(r) for r in lines) + "\n")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert (
        "== type census at peak 2026-11-12T21:07:42 (periodic_high_rss) rss=2151 objects=9000"
        in out
    )
    assert (
        "== type census latest 2026-11-12T21:22:57 (periodic_high_rss) rss=1779 objects=300" in out
    )
    assert "to the peak census" in out
    assert "d_count=+8900" in out


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


def test_malformed_values_drop_the_record_not_the_report():
    """Non-finite numbers and wrong shapes are dropped; the report still runs."""
    good = _real_records().splitlines()[-1]
    nan_count = json.loads(good)
    nan_count["types"]["top"].append({"type": "dict", "count": float("nan"), "mib": 1.0})
    shape = json.loads(good)
    shape["containers"] = 5
    inf = json.loads(good)
    inf["malloc"]["in_use_mib"] = float("inf")
    float_len = json.loads(good)
    float_len["containers"].append({"name": "src.a.B", "kind": "dict", "len": 1.5})
    text = "\n".join(json.dumps(r) for r in (nan_count, shape, inf, float_len)) + "\n"
    res = _filter(text)
    assert res.returncode == 0, res.stderr
    assert "Traceback" not in res.stderr
    assert "records=" in res.stdout
    assert "nan" not in res.stdout.lower() and "inf " not in res.stdout.lower()


def test_skipped_deep_census_is_reported():
    rec = json.loads(_real_records().splitlines()[-1])
    rec["deep"] = None
    rec["deep_skipped"] = "low_headroom"
    rec["headroom_mib"] = 140
    res = _filter(json.dumps(rec) + "\n")
    assert res.returncode == 0, res.stderr
    assert "deep census skipped 1 time(s) for low headroom" in res.stdout
    assert "headroom 140 MiB" in res.stdout


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
