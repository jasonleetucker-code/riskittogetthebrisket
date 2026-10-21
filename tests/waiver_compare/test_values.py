"""The waiver-compare value is a plain 50/50 average of two published values."""

from __future__ import annotations

import pytest

from src.waiver_compare.values import build_value_index, combine, source_values


def _row(pid, name, *, ktc=None, idptc=None, pos="WR", asset="offense", **extra):
    sites = {}
    if ktc is not None:
        sites["ktcCrowdTradesSfTep"] = ktc
    if idptc is not None:
        sites["idpTradeCalc"] = idptc
    return {
        "playerId": pid,
        "displayName": name,
        "position": pos,
        "assetClass": asset,
        "team": "DET",
        "age": 25,
        "canonicalSiteValues": sites,
        "rankDerivedValue": 1234,  # the canonical value — must never be read
        **extra,
    }


def test_both_sources_average_exactly():
    assert combine(1861.0, 2350.0) == 2105.5
    assert combine(4000.0, 4000.0) == 4000.0


@pytest.mark.parametrize("ktc,idptc,expected", [(5000.0, None, 5000.0), (None, 3100.0, 3100.0)])
def test_single_source_keeps_its_value(ktc, idptc, expected):
    # Missing is never zero: a lone value is NOT halved.
    assert combine(ktc, idptc) == expected


def test_neither_source_is_none_not_zero():
    assert combine(None, None) is None


def test_index_reads_only_the_two_requested_sources():
    row = _row("1", "A", ktc=6000, idptc=5000)
    row["canonicalSiteValues"].update({"ktcCrowdSfTep": 9999, "ktc": 9999, "dlfSf": 999000})
    idx = build_value_index([row])
    pv = idx.by_player_id["1"]
    assert (pv.ktc, pv.idptc, pv.combined) == (6000.0, 5000.0, 5500.0)


def test_canonical_value_is_never_a_fallback():
    idx = build_value_index([_row("1", "No sources")])
    assert "1" not in idx.by_player_id


@pytest.mark.parametrize("bad", [0, -5, 10000, float("nan"), "abc", True])
def test_invalid_published_values_are_missing(bad):
    row = _row("1", "A", ktc=bad, idptc=bad)
    assert source_values(row) == (None, None)


def test_picks_are_excluded():
    idx = build_value_index([_row("p", "2027 Early 1st", ktc=6000, idptc=7000, asset="pick")])
    assert idx.by_player_id == {}


def test_same_name_different_players_stay_separate():
    # Two players named Josh Allen: identity is the Sleeper id, never the name.
    qb = _row("4984", "Josh Allen", ktc=9997, idptc=9997, pos="QB")
    dl = _row("3155", "Josh Allen", idptc=3000, pos="DL", asset="idp")
    idx = build_value_index([qb, dl])
    assert idx.by_player_id["4984"].combined == 9997.0
    assert idx.by_player_id["3155"].combined == 3000.0
    assert idx.by_player_id["3155"].ktc is None


def test_unidentified_rows_are_counted_not_guessed():
    idx = build_value_index([_row("", "Mystery", ktc=4000)])
    assert idx.by_player_id == {}
    assert idx.unidentified_rows == 1


def test_conflicting_rows_for_one_id_are_withheld():
    a = _row("7", "X", ktc=4000)
    b = _row("7", "X", ktc=5000)
    idx = build_value_index([a, b])
    assert "7" not in idx.by_player_id
    assert idx.conflicting_ids == ["7"]
