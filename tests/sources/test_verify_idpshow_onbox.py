"""IDP Show on-box verifier: session facts without secrets, content-change detection."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "verify_idpshow_onbox", REPO / "scripts" / "verify_idpshow_onbox.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load()
SECRET = "s%3AsuperSecretSessionValue0123456789abcdef"


def _jar(tmp_path: Path, cookies: list[dict]) -> Path:
    (tmp_path / "idpshow_session.json").write_text(json.dumps({"cookies": cookies}))
    return tmp_path


def test_absent_jar_is_absent_not_expired(tmp_path):
    assert V.check_session(tmp_path)["state"] == "absent"


def test_malformed_jar_is_named(tmp_path):
    (tmp_path / "idpshow_session.json").write_text("{not json")
    assert V.check_session(tmp_path)["state"] == "malformed"


def test_session_reports_names_and_expiry_never_values(tmp_path):
    now = 2_000_000_000.0
    work = _jar(
        tmp_path,
        [
            {"name": "substack.sid", "value": SECRET, "expires": now - 60},
            {"name": "substack.lli", "value": "1", "expires": now + 86_400},
            {"name": "_comment_how_to", "value": "paste cookies here"},
            {"name": "session_cookie_no_expiry", "value": "x"},
        ],
    )
    out = V.check_session(work, now=now)
    assert out["state"] == "present"
    assert out["cookieCount"] == 3  # the _comment entry is not a cookie
    assert out["expiredCookies"] == ["substack.sid"]
    by_name = {c["name"]: c for c in out["cookies"]}
    assert by_name["substack.lli"]["expired"] is False
    # Unknown expiry stays unknown — never "valid" and never "expired".
    assert by_name["session_cookie_no_expiry"]["expired"] is None
    assert SECRET not in json.dumps(out)


def test_public_guard_refuses_a_cookie_value(tmp_path):
    with pytest.raises(SystemExit):
        V.assert_public_safe({"journal": [f"cookie={SECRET}"]}, [SECRET], [])


def test_public_guard_refuses_a_player_name():
    with pytest.raises(SystemExit):
        V.assert_public_safe({"x": "Aidan Hutchinson moved"}, [], ["Aidan Hutchinson"])


def test_journal_scrub_redacts_long_tokens():
    line = f"[idpshow] cookie header {SECRET} attached"
    assert SECRET not in V._scrub(line)
    assert "[idpshow]" in V._scrub(line)


def test_fingerprint_detects_content_not_order():
    a = [{"name": "A", "position": "LB", "rank": 1}, {"name": "B", "position": "DE", "rank": 2}]
    b = list(reversed(a))
    assert V.content_fingerprint(a) == V.content_fingerprint(b)
    moved = [{"name": "A", "position": "LB", "rank": 2}, {"name": "B", "position": "DE", "rank": 1}]
    assert V.content_fingerprint(a) != V.content_fingerprint(moved)


def test_committed_csv_round_trips_the_fetcher_columns(tmp_path):
    p = tmp_path / "board.csv"
    p.write_text("name,position,rank\nA,LB,1\nB,DE,2\n")
    rows = V.committed_rows(p)
    assert V.content_fingerprint(rows) == V.content_fingerprint(
        [{"name": "A", "position": "LB", "rank": 1}, {"name": "B", "position": "DE", "rank": 2}]
    )
    assert V.committed_rows(tmp_path / "missing.csv") is None


def test_workflow_is_dispatch_only_and_prints_only_the_script_output():
    wf = (REPO / ".github" / "workflows" / "idpshow-onbox-verification.yml").read_text()
    assert "workflow_dispatch" in wf
    assert "push:" not in wf and "schedule:" not in wf
    assert "verify_idpshow_onbox.py" in wf
    # The session jar is never copied off the host or into the artifact.
    assert "idpshow_session.json" not in wf.split("jobs:", 1)[1]
