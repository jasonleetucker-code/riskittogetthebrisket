"""A source that stops parsing must say so.

R13 / W05-F003.  Two failure modes a real fetcher produces were both
silent:

  * a **vendor header rename** — the schema probe covered 4 of the 22
    registered sources (dlfSf, dlfIdp, fantasyProsIdp, fantasyProsSf),
    so renaming a column on any of the other 18 (including the retail
    anchor ``ktcSfTep`` and the IDP backbone ``idpTradeCalc``) fell
    through the alias lookup and dropped the source from the board with
    ``sourceParseErrors == []``;
  * a **header-only CSV** — the fetcher ran and scraped nothing — hit
    ``if not csv_lookup: continue`` with no error at all.

Measured before, with the finding's own reproduction:
``dlfSf -> [schema_mismatch]`` but ``otcffbSf / ktcSfTep / fantasyCalc
-> []``.  After: every source reports.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.api.data_contract import (
    _SOURCE_CSV_PATHS,
    _enrich_from_source_csvs,
    validate_api_data_contract,
)

REPO = Path(__file__).resolve().parents[2]

# One value-signal and one rank-signal source that the old 4-source
# probe did NOT cover, plus one it did (so the replacement can't be a
# regression for the sources that were already protected).
UNCOVERED = ["ktcSfTep", "idpTradeCalc", "otcffbSf", "fantasyCalc", "draftSharks"]
PREVIOUSLY_COVERED = ["dlfSf", "fantasyProsIdp"]


def _rel(key: str) -> str:
    cfg = _SOURCE_CSV_PATHS[key]
    return cfg if isinstance(cfg, str) else str(cfg["path"])


@pytest.fixture()
def csv_tree(tmp_path: Path) -> Path:
    src = REPO / "CSVs" / "site_raw"
    if not src.exists():  # pragma: no cover - checkout without CSVs
        pytest.skip("no source CSVs in this checkout")
    (tmp_path / "CSVs").mkdir()
    shutil.copytree(src, tmp_path / "CSVs" / "site_raw")
    return tmp_path


def _run(root: Path) -> tuple[dict[str, int], list[dict]]:
    rows = [
        {"canonicalName": "Ja'Marr Chase", "displayName": "Ja'Marr Chase", "position": "WR"},
    ]
    errors: list[dict] = []
    index = _enrich_from_source_csvs(rows, parse_errors=errors, csv_root=root)
    return {k: len(v) for k, v in index.items()}, errors


@pytest.mark.parametrize("key", UNCOVERED + PREVIOUSLY_COVERED)
def test_header_rename_reports_schema_mismatch(csv_tree: Path, key: str):
    path = csv_tree / _rel(key)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    lines[0] = "colA,colB"
    path.write_text("\n".join(lines))
    _, errors = _run(csv_tree)
    mine = [e for e in errors if e.get("source") == key]
    assert mine, f"{key} vanished from the board with no parse error"
    assert mine[0]["error"] == "schema_mismatch"


@pytest.mark.parametrize("key", ["otcffbSf", "ktcSfTep"])
def test_header_only_csv_reports_source_empty(csv_tree: Path, key: str):
    path = csv_tree / _rel(key)
    header = path.read_text(encoding="utf-8-sig").splitlines()[0]
    path.write_text(header + "\n")
    _, errors = _run(csv_tree)
    mine = [e for e in errors if e.get("source") == key]
    assert mine, f"{key} parsed to zero rows with no parse error"
    assert mine[0]["error"] == "source_empty"


def test_untouched_tree_reports_no_parse_errors(csv_tree: Path):
    """The probe must not false-positive on the real CSVs — every
    registered source's live header has to satisfy it."""
    counts, errors = _run(csv_tree)
    assert errors == []
    assert len(counts) == len(_SOURCE_CSV_PATHS)


def test_parse_errors_degrade_contract_health():
    """The signal has to reach the health surface, not just the log."""
    payload = {
        "playersArray": [],
        "sourceParseErrors": [{"source": "ktcSfTep", "error": "schema_mismatch"}],
    }
    health = validate_api_data_contract(payload)
    assert any("schema_mismatch" in w for w in health["warnings"])
    assert health["status"] in ("degraded", "invalid")
