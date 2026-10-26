"""Pin the claim checker's row parsing and open-status recognition.

Every case here failed against the pre-2026-10-07 checker, which treated only
statuses starting with ``open`` as live, split rows on every ``|`` (escaped or
not), and compared backtick-decorated path cells against plain paths.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_work_claims", REPO / "scripts" / "check_work_claims.py"
)
cwc = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(cwc)

HEADER = "| Claim | Paths | Defect ids | Branch | Status |\n|---|---|---|---|---|\n"


def _write(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "WORK_CLAIMS.md"
    path.write_text("# Work Claims\n\n" + HEADER + rows, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "status",
    [
        "open",
        "open — PR pending review",
        "active — PR open",
        "Active. Agent-OS-Receipt: x",
        "in progress — targeted tests green",
        "in-progress",
        "pending integration",
        "FEATURE_GREEN — ready",
        "`FEATURE_GREEN` locally",
        "implemented locally; not pushed",
        "reviewed — tests pass",
        "routed — awaiting a session",
        "**active** — bold",
    ],
)
def test_in_flight_spellings_are_open(status: str) -> None:
    assert cwc.is_open_status(status)


@pytest.mark.parametrize(
    "status",
    [
        "done — merged #1 (`abc`)",
        "**done** — merged",
        "merged — #1618",
        "closed — PR closed unmerged",
        "**stale — swept 2026-08-25 (Integration):** branch deleted",
        "superseded by main",
        "",
        "#722",
    ],
)
def test_finished_or_unknown_statuses_are_not_open(status: str) -> None:
    assert not cwc.is_open_status(status)


def test_active_row_overlapping_requested_file_is_reported(tmp_path, capsys) -> None:
    claims = _write(
        tmp_path,
        "| Some work | `src/api/foo.py` (call site only), `tests/api/test_foo.py` | W1 "
        "| `claude/foo` | active — PR open |\n",
    )
    rc = cwc.main(["--claims-file", str(claims), "--files", "src/api/foo.py"])
    out = capsys.readouterr().out
    assert rc == 0  # advisory by default
    assert "OPEN CLAIM — Some work" in out
    assert "src/api/foo.py" in out
    rc = cwc.main(["--claims-file", str(claims), "--files", "src/api/foo.py", "--strict"])
    assert rc == 1


def test_done_row_is_not_reported(tmp_path, capsys) -> None:
    claims = _write(
        tmp_path,
        "| Old work | `src/api/foo.py` | W1 | `claude/foo` | done — merged #1 (`abc`) |\n",
    )
    rc = cwc.main(["--claims-file", str(claims), "--files", "src/api/foo.py", "--strict"])
    assert rc == 0
    assert "No overlapping claim" in capsys.readouterr().out


def test_escaped_pipe_does_not_shift_the_status_cell(tmp_path) -> None:
    claims = _write(
        tmp_path,
        '| Year selector: "All Years \\| <season>" | `src/x.py` | D1 '
        "| `claude/x` | active — implemented |\n",
    )
    (row,) = cwc.parse_claims(claims)
    assert row["status"].startswith("active")
    assert row["branch"] == "`claude/x`"
    assert "All Years | <season>" in row["what"]
    assert cwc.is_open_status(row["status"])


def test_pipe_inside_code_span_stays_in_its_cell(tmp_path) -> None:
    claims = _write(
        tmp_path,
        "| Probe | `src/x.py` | D1 | `claude/x` | done — read the `Asset | Value` tables |\n"
        "| Odd tick ` here | `a.py` | D2 | `claude/y` | active — unbalanced row |\n",
    )
    first, second = cwc.parse_claims(claims)
    assert first["status"].startswith("done") and "asset | value" in first["status"]
    assert first["branch"] == "`claude/x`"
    assert second["status"].startswith("active")


def test_short_and_long_rows_do_not_crash(tmp_path) -> None:
    claims = _write(
        tmp_path,
        "| too | short |\n"
        "| Four cells | V1-80 | `claude/v1` | open — lane |\n"
        "| Six cells | `a.py` | `b.py` | D2 | `claude/six` | in progress |\n",
    )
    rows = cwc.parse_claims(claims)
    assert [r["what"] for r in rows] == ["Four cells", "Six cells"]
    four, six = rows
    assert four["defects"] == "V1-80" and four["status"].startswith("open")
    assert six["defects"] == "D2" and six["branch"] == "`claude/six`"
    assert {"a.py", "b.py"} <= cwc.claim_paths(six["paths"])


def test_defect_overlap_on_four_cell_row(tmp_path, capsys) -> None:
    claims = _write(tmp_path, "| Four cells | V1-80 | `claude/v1` | open — lane |\n")
    cwc.main(["--claims-file", str(claims), "--defect", "v1-80"])
    assert "OPEN CLAIM — Four cells" in capsys.readouterr().out


def test_list_open(tmp_path, capsys) -> None:
    claims = _write(
        tmp_path,
        "| A | `a.py` | — | `claude/a` | active |\n| B | `b.py` | — | `claude/b` | done — x |\n",
    )
    assert cwc.main(["--claims-file", str(claims), "--list-open"]) == 0
    out = capsys.readouterr().out
    assert "claude/a" in out and "claude/b" not in out
    assert "1 open of 2" in out


def test_live_claims_file_parses() -> None:
    rows = cwc.parse_claims()
    assert rows, "docs/WORK_CLAIMS.md produced no claim rows"
    for row in rows:
        assert set(row) == {"what", "paths", "defects", "branch", "status"}
