"""Every registered source has to be watched.

R13 / W05-F004.  ``validate_api_data_contract`` counted only the keys
that HAD a floor, and nine of the 21 registered blend sources had none —
``ktcSfTep`` (the retail anchor, 501 rows), ``fantasyProsSf``,
``fantasyCalc``, ``otcffbSf``, ``fantasyNavigatorSf``, ``pfkDynasty``,
``dlfRookieSf``, ``dlfRookieIdp``, ``flockFantasySfRookies``.  Stripping
each in turn from the live contract and re-running the validator
measured, before:

    ktcSfTep -> healthy []      dlfSf     -> invalid [source_missing:dlfSf]
    otcffbSf -> healthy []      yahooBoone-> invalid [source_missing:yahooBoone]

i.e. the retail anchor could be deleted from the whole board and
``contractHealth`` stayed "healthy" with zero errors.
"""

from __future__ import annotations

import copy

import pytest

from src.api.data_contract import (
    _RANKING_SOURCES,
    _load_source_row_floors,
    validate_api_data_contract,
)

REGISTRY_KEYS = [str(s["key"]) for s in _RANKING_SOURCES if s.get("key")]
# ``ktc`` is ingested and floored but is not a blend member, so a board
# fixture has to carry it too or the floor check reports it missing.
BOARD_KEYS = list(dict.fromkeys([*REGISTRY_KEYS, *_load_source_row_floors()]))

_SOURCE_MAPS = (
    "canonicalSiteValues",
    "sourceRanks",
    "sourceRankMeta",
    "sourceNativeValues",
    "sourceOriginalRanks",
    "effectiveSourceRanks",
    "rawSourceValues",
)


def _board(rows: int = 600) -> dict:
    """A structurally-valid board carrying every registered source.

    Built rather than loaded so the check is exercised without a live
    snapshot — but complete enough that the row-count-floor errors are
    not drowned out by required-key errors (the validator caps at 200).
    """
    players = []
    for i in range(rows):
        players.append(
            {
                "playerId": f"p{i}",
                "displayName": f"Player {i}",
                "canonicalName": f"player {i}",
                "position": "LB" if i % 4 == 0 else "WR",
                "team": "FA",
                "age": 25,
                "rookie": False,
                "assetClass": "offense",
                "values": {"overall": 5000, "rawComposite": 5000, "finalAdjusted": 5000},
                "sourceCount": len(BOARD_KEYS),
                "confidenceBucket": "high",
                "anomalyFlags": [],
                "canonicalSiteValues": {k: 5000 for k in BOARD_KEYS},
            }
        )
    return {
        "contractVersion": "test",
        "generatedAt": "2026-08-05T00:00:00+00:00",
        "maxValues": {},
        "players": {},
        "sites": [{"key": "ktc", "playerCount": rows}],
        "valueAuthority": {"coverage": {}},
        "playersArray": players,
    }


def test_every_registered_source_has_a_row_floor():
    """Registry-completeness gate: adding a source to ``_RANKING_SOURCES``
    without pinning a floor must fail the build, not pass silently."""
    floors = _load_source_row_floors()
    unfloored = sorted(k for k in REGISTRY_KEYS if k not in floors)
    assert unfloored == []


def test_the_completeness_gate_is_exported_for_the_validator():
    """The same list the validator warns from — one definition, so the
    test and the runtime check can't drift."""
    from src.api.data_contract import missing_row_floor_sources

    assert missing_row_floor_sources() == []
    assert missing_row_floor_sources({"ktc": 1}) == sorted(REGISTRY_KEYS)


def test_floors_are_only_for_sources_the_pipeline_ingests():
    from src.api.data_contract import _SOURCE_CSV_PATHS

    unknown = sorted(set(_load_source_row_floors()) - set(_SOURCE_CSV_PATHS))
    assert unknown == [], f"floor for a source the pipeline does not ingest: {unknown}"


@pytest.mark.parametrize("key", REGISTRY_KEYS)
def test_dropping_any_registered_source_is_an_error(key: str):
    board = _board()
    for row in board["playersArray"]:
        for field in _SOURCE_MAPS:
            m = row.get(field)
            if isinstance(m, dict):
                m.pop(key, None)
    report = validate_api_data_contract(board)
    assert f"source_missing:{key}" in report["errors"]
    assert report["ok"] is False


def test_a_source_below_its_floor_warns_without_erroring():
    floors = _load_source_row_floors()
    floor = floors["ktcSfTep"]
    board = _board()
    for row in board["playersArray"][floor - 1 :]:
        row["canonicalSiteValues"].pop("ktcSfTep", None)
    report = validate_api_data_contract(board)
    assert any(w.startswith("source_below_floor:ktcSfTep:") for w in report["warnings"])
    assert not any(e.startswith("source_missing:ktcSfTep") for e in report["errors"])


def test_an_unfloored_source_warns_at_runtime(monkeypatch):
    """If a future source lands without a floor the payload says so —
    the gap is reported, not merely untested."""
    trimmed = {k: v for k, v in _load_source_row_floors().items() if k != "ktcSfTep"}
    monkeypatch.setattr(
        "src.api.data_contract._load_source_row_floors", lambda: dict(trimmed)
    )
    report = validate_api_data_contract(_board())
    assert "source_floor_missing:ktcSfTep" in report["warnings"]
    # ...and its presence is still checked despite having no floor.
    board = _board()
    for row in board["playersArray"]:
        row["canonicalSiteValues"].pop("ktcSfTep", None)
    report = validate_api_data_contract(board)
    assert "source_missing:ktcSfTep" in report["errors"]


def test_full_board_is_clean():
    report = validate_api_data_contract(copy.deepcopy(_board()))
    assert not any(e.startswith("source_missing:") for e in report["errors"])
    assert not any(w.startswith("source_floor_missing:") for w in report["warnings"])
