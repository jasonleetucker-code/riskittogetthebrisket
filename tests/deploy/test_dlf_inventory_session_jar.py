"""The DLF inventory's session-jar section reads the jar fetch_dlf.py writes.

Diagnostics runs 44810158859 and 44815264693 printed "cookies : 2" and then
``AttributeError: 'str' object has no attribute 'get'``: the jar is an object
(``{"_comment_", "cookies"}``), so iterating it yielded key strings.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "deploy/diagnostics/dlf_fetch_inventory.sh"
SECRET = "SESSION-VALUE-NEVER-PRINTED"


def _section_python() -> str:
    text = INVENTORY.read_text(encoding="utf-8")
    start = text.index("\"${SESSION_FILE}\" <<'PY'")
    body = text[text.index("\n", start) + 1 :]
    return body[: body.index("\nPY\n")]


def _run(tmp_path: Path, jar: object) -> subprocess.CompletedProcess:
    path = tmp_path / "dlf_session.json"
    path.write_text(json.dumps(jar), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-", str(path)],
        input=_section_python(),
        capture_output=True,
        text=True,
        timeout=30,
    )


COOKIE = {
    "name": "wordpress_logged_in_x",
    "value": SECRET,
    "domain": ".example.invalid",
    "path": "/",
}


@pytest.mark.parametrize(
    "jar",
    [
        {
            "_comment_": "written by scripts/fetch_dlf.py",
            "cookies": [COOKIE, {**COOKIE, "name": "b"}],
        },
        [COOKIE, {**COOKIE, "name": "b", "expires": 1800000000}],
    ],
    ids=["fetch_dlf_object", "legacy_list"],
)
def test_the_jar_fetch_dlf_writes_is_listed_by_name_without_values(tmp_path, jar):
    res = _run(tmp_path, jar)
    assert res.returncode == 0, res.stderr
    assert "Traceback" not in res.stderr
    assert "cookies : 2" in res.stdout
    assert "wordpress_logged_in_x" in res.stdout
    assert SECRET not in res.stdout + res.stderr


def test_a_jar_without_a_cookie_list_says_so_without_a_traceback(tmp_path):
    res = _run(tmp_path, {"_comment_": "no cookies key"})
    assert res.returncode != 0
    assert "no cookie list" in res.stderr + res.stdout
    assert "Traceback" not in res.stderr
