"""scripts/dlf_board_states.py: per-board DLF refresh states, ``since`` kept on no change."""

from __future__ import annotations

import json

from scripts import dlf_board_states as B


def test_merge_keeps_since_while_state_is_unchanged():
    prev = {
        "schema": B.SCHEMA,
        "boards": {
            "dlfRookieSf": {
                "state": "vendor_empty",
                "reason": "r",
                "since": "2026-11-20T10:00:00+00:00",
            }
        },
    }
    doc = B.merge(
        prev,
        {"dlfRookieSf": {"state": "vendor_empty", "reason": "r2"}},
        "2026-11-20T12:00:00+00:00",
    )
    assert doc["boards"]["dlfRookieSf"]["since"] == "2026-11-20T10:00:00+00:00"
    assert doc["boards"]["dlfRookieSf"]["reason"] == "r2"


def test_merge_restarts_since_on_a_transition_and_keeps_unseen_boards():
    prev = {
        "schema": B.SCHEMA,
        "boards": {
            "dlfRookieSf": {
                "state": "vendor_empty",
                "reason": "r",
                "since": "2026-11-20T10:00:00+00:00",
            },
            "dlfSf": {
                "state": "written",
                "reason": "287 rows",
                "since": "2026-11-01T00:00:00+00:00",
            },
        },
    }
    doc = B.merge(
        prev,
        {"dlfRookieSf": {"state": "written", "reason": "61 rows"}},
        "2026-11-21T00:00:00+00:00",
    )
    assert doc["boards"]["dlfRookieSf"] == {
        "state": "written",
        "reason": "61 rows",
        "since": "2026-11-21T00:00:00+00:00",
    }
    assert doc["boards"]["dlfSf"]["since"] == "2026-11-01T00:00:00+00:00"


def test_merge_ignores_malformed_entries():
    doc = B.merge({}, {"x": "nope", "y": {"reason": "no state"}}, "2026-11-21T00:00:00+00:00")
    assert doc["boards"] == {}


def test_cli_merge_writes_only_on_change(tmp_path):
    run = tmp_path / "run.json"
    out = tmp_path / "states.json"
    run.write_text(
        json.dumps({"dlfRookieIdp": {"state": "vendor_empty", "reason": "r"}}), encoding="utf-8"
    )
    assert B.main(["merge", "--run", str(run), "--out", str(out)]) == 0
    first = out.read_text(encoding="utf-8")
    assert B.main(["merge", "--run", str(run), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == first  # same state => byte-identical (no commit)


def test_cli_merge_refuses_an_unreadable_run_file(tmp_path):
    assert (
        B.main(
            ["merge", "--run", str(tmp_path / "missing.json"), "--out", str(tmp_path / "o.json")]
        )
        == 1
    )


def test_load_tolerates_a_corrupt_file(tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text("{not json", encoding="utf-8")
    assert B.load(bad) == {"schema": B.SCHEMA, "boards": {}}
