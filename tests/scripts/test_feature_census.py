"""Pin scripts/feature_census.py on synthetic fixtures (offline, no live repo scan)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import feature_census as fc

SERVER = """
from fastapi import FastAPI
app = FastAPI()
_PUBLIC_API_EXACT = frozenset({"/api/health"})

@app.get("/api/health")
def health():
    return {}

@app.post("/api/widgets/trade")
def post_trade():
    if is_enabled("shiny_flag"):
        return 1

@app.get("/api/widgets/list")
def list_widgets():
    return []

@app.get("/api/widgets/{wid}/detail")
def widget_detail(wid):
    return {}

@app.get("/api/admin/tools")
def admin_tools(request):
    _require_admin_session(request)
"""
FLAGS = """
from typing import Final
LIVE: Final[str] = "LIVE"
_DEFAULTS: Final[dict[str, bool]] = {
    "shiny_flag": True,
    "dark_flag": False,
}
_GATE_STATUS: Final[dict[str, str]] = {"shiny_flag": LIVE, "dark_flag": LIVE}
"""
TIMER = "[Timer]\nOnCalendar=*-*-* 01:00:00 UTC\n"
SERVICE = "[Service]\nExecStart=/x/bin/python /app/scripts/nightly_job.py\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_repo(root: Path) -> Path:
    _write(root / "server.py", SERVER)
    _write(root / "src" / "api" / "feature_flags.py", FLAGS)
    _write(root / "deploy" / "systemd" / "dynasty-nightly.timer.template", TIMER)
    _write(root / "deploy" / "systemd" / "dynasty-nightly.service.template", SERVICE)
    _write(root / "frontend" / "app" / "rankings" / "page.jsx", "export default 1")
    _write(
        root / "frontend" / "app" / "api" / "widgets" / "route.js",
        "export async function POST() {}",
    )
    _write(
        root / "tests" / "test_widgets.py",
        'def test_list(c):\n    c.get("/api/widgets/list")\n'
        '    c.get(f"/api/widgets/{x}/detail")\n    flag = "dark_flag"\n',
    )
    _write(
        root / "frontend" / "__tests__" / "r.test.js",
        'goto("/rankings"); fetch("/api/widgets", {method:"POST"});',
    )
    return root


def _item(census: dict, item_id: str) -> dict:
    return next(i for i in census["items"] if i["id"] == item_id)


def test_referenced_route_matched_and_unreferenced_not(tmp_path):
    census = fc.build_census(_make_repo(tmp_path))
    listed = _item(census, "GET /api/widgets/list")
    assert listed["testRefCount"] == 1
    assert listed["testRefs"][0] == {"file": "tests/test_widgets.py", "kinds": ["literal-path"]}
    assert _item(census, "GET /api/health")["testRefCount"] == 0
    assert _item(census, "GET /api/health")["auth"] == "public"
    detail = _item(census, "GET /api/widgets/{wid}/detail")
    assert detail["testRefs"][0]["kinds"] == ["template-pattern"]
    assert _item(census, "GET /api/admin/tools")["auth"] == "admin"


def test_unreferenced_post_ranks_above_unreferenced_get(tmp_path):
    census = fc.build_census(_make_repo(tmp_path))
    ids = census["rankedGapIds"]
    assert "POST /api/widgets/trade" in ids and "GET /api/health" in ids
    assert ids.index("POST /api/widgets/trade") < ids.index("GET /api/health")
    post = _item(census, "POST /api/widgets/trade")
    assert post["riskClass"] == "a"
    assert post["flagGate"]["direct"] == ["shiny_flag"]


def test_flag_default_and_gate_read_from_registry(tmp_path):
    census = fc.build_census(_make_repo(tmp_path))
    shiny = _item(census, "FLAG shiny_flag")
    dark = _item(census, "FLAG dark_flag")
    assert shiny["default"] is True and shiny["gateStatus"] == "LIVE"
    assert dark["default"] is False
    assert shiny["testRefCount"] == 0 and shiny["riskClass"] == "c"
    assert dark["testRefs"][0]["kinds"] == ["quoted-flag-name"]


def test_pages_bridges_and_jobs(tmp_path):
    census = fc.build_census(_make_repo(tmp_path))
    assert _item(census, "PAGE /rankings")["testRefCount"] == 1
    assert _item(census, "PAGE /rankings")["riskClass"] == "b"
    bridge = _item(census, "BRIDGE POST /api/widgets")
    assert bridge["testRefCount"] == 1 and bridge["riskClass"] == "a"
    job = _item(census, "JOB systemd-timer dynasty-nightly")
    assert job["testRefCount"] == 0 and job["riskClass"] == "d"
    assert job["execScripts"] == ["scripts/nightly_job.py"]


def test_output_is_byte_identical_and_check_mode(tmp_path):
    root = _make_repo(tmp_path)
    out = root / "out"
    argv = ["--root", str(root), "--out-dir", str(out)]
    assert fc.main(argv) == 0
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    assert fc.main(argv) == 0
    assert first == {p.name: p.read_bytes() for p in out.iterdir()}
    assert fc.main([*argv, "--check"]) == 0
    assert str(root) not in first["FEATURE_CENSUS.md"].decode("utf-8")
    assert str(root) not in first["feature_census.json"].decode("utf-8")
    data = json.loads(first["feature_census.json"])
    data["asOfCommit"] = "different"
    (out / "feature_census.json").write_text(json.dumps(data), encoding="utf-8")
    assert fc.main([*argv, "--check"]) == 0
    _write(root / "tests" / "test_new.py", 'x = "/api/health"\n')
    assert fc.main([*argv, "--check"]) == 1
