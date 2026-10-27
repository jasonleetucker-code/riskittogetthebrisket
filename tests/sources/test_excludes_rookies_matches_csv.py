"""G2-D3 — ``excludes_rookies`` is a claim about a source's DATA; check it there.

``excludes_rookies=True`` tells the pipeline a source structurally cannot
rank rookies: ``_expected_sources_for_position`` stops expecting it for
rookies, ``sparse_evidence`` refuses it (``board_excludes_rookies``), the
source census reports ``population.rookies = False``, and the vote loop
drops its rookie ranks in the bottom 20 % of its pool.

Until PR #1998's G2 audit both ``fantasyProsIdp`` and ``dlfIdp`` carried
the flag on the stated premise that neither board lists first-year
prospects.  Their own tracked CSVs said otherwise: FantasyPros ranked
Sonny Styles 37, Arvell Reese 59, CJ Allen 62, David Bailey 66 and Caleb
Downs 74; DLF IDP ranked Jacob Rodriguez 9, Reese 16.5 and Downs 41.
Nothing checked the flag against the data, so a hand-written comment
decided what counted as missing evidence.

The invariant pinned here: **a source flagged ``excludes_rookies`` must not
publish any name from the current rookie class.**  The rookie class is what
the registry's own rookie-only boards (``needs_rookie_translation``) list —
no hand-kept roster.  With no source flagged the invariant holds trivially;
it exists so the next flag is checked against the CSV it describes.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.api.data_contract import _RANKING_SOURCES, _SOURCE_CSV_PATHS
from src.utils.name_clean import resolve_canonical_name

REPO = Path(__file__).resolve().parents[2]
_NAME_COLUMNS = ("name", "Name", "player", "Player", "player_name", "PlayerName")


def _csv_path(source_key: str) -> Path | None:
    cfg = _SOURCE_CSV_PATHS.get(source_key)
    rel = cfg.get("path") if isinstance(cfg, dict) else cfg
    return REPO / rel if rel else None


def _names(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        col = next((c for c in _NAME_COLUMNS if c in (reader.fieldnames or [])), None)
        if col is None:
            return set()
        return {resolve_canonical_name(r.get(col) or "") for r in reader} - {""}


def rookie_class_contradictions(
    sources: list[dict], csv_for: dict[str, Path | None]
) -> dict[str, list[str]]:
    """``{flagged source key: rookie-class names its own CSV publishes}``.

    The rookie class is the union of the rookie-only boards' names.  Only
    sources flagged ``excludes_rookies`` with a readable CSV are checked.
    """
    rookies: set[str] = set()
    for src in sources:
        path = csv_for.get(src["key"])
        if src.get("needs_rookie_translation") and path is not None and path.is_file():
            rookies |= _names(path)
    out: dict[str, list[str]] = {}
    for src in sources:
        path = csv_for.get(src["key"])
        if not src.get("excludes_rookies") or path is None or not path.is_file():
            continue
        hits = sorted(_names(path) & rookies)
        if hits:
            out[src["key"]] = hits
    return out


def test_no_flagged_source_publishes_a_rookie():
    csv_for = {s["key"]: _csv_path(s["key"]) for s in _RANKING_SOURCES}
    rookie_boards = [
        s["key"]
        for s in _RANKING_SOURCES
        if s.get("needs_rookie_translation") and (csv_for[s["key"]] or Path()).is_file()
    ]
    if not rookie_boards:
        pytest.skip("no rookie-only board CSV present — the rookie class is unknown")
    contradictions = rookie_class_contradictions(_RANKING_SOURCES, csv_for)
    assert not contradictions, (
        "excludes_rookies=True contradicts the source's own CSV, which ranks "
        f"rookie-class players: {contradictions}"
    )


def test_fantasypros_and_dlf_idp_are_not_flagged():
    flags = {s["key"]: s.get("excludes_rookies") for s in _RANKING_SOURCES}
    assert flags["fantasyProsIdp"] is False
    assert flags["dlfIdp"] is False


def test_the_check_fires_on_a_contradicted_flag(tmp_path: Path):
    rookie_csv = tmp_path / "rookies.csv"
    rookie_csv.write_text("name,rank\nSonny Styles,1\nCaleb Downs,2\n", encoding="utf-8")
    vet_csv = tmp_path / "vets.csv"
    vet_csv.write_text("name,rank\nAidan Hutchinson,1\nSonny Styles,37\n", encoding="utf-8")
    clean_csv = tmp_path / "clean.csv"
    clean_csv.write_text("name,rank\nAidan Hutchinson,1\n", encoding="utf-8")
    sources = [
        {"key": "rk", "needs_rookie_translation": True},
        {"key": "flagged", "excludes_rookies": True},
        {"key": "honest", "excludes_rookies": True},
        {"key": "unflagged", "excludes_rookies": False},
    ]
    csv_for = {"rk": rookie_csv, "flagged": vet_csv, "honest": clean_csv, "unflagged": vet_csv}
    assert rookie_class_contradictions(sources, csv_for) == {"flagged": ["sonny styles"]}


def test_frontend_mirror_agrees():
    js = (REPO / "frontend" / "lib" / "dynasty-data.js").read_text(encoding="utf-8")
    for key in ("fantasyProsIdp", "dlfIdp"):
        start = js.index(f'key: "{key}"')
        block = js[start : js.index("}", start)]
        assert "excludesRookies: false" in block, key
