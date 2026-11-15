"""Offline fixture tests for ``scripts/scoring_parity_census.py`` (CW-08).

No network.  The census' pure core (``build_census`` / ``classify_key``) is
driven with a hand-built card, Sleeper directory, matchups, stat lines and
nflverse rows whose expected outcome is derived by hand.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scoring_parity_census.py"
_spec = importlib.util.spec_from_file_location("scoring_parity_census", _SCRIPT)
census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census)  # type: ignore[union-attr]

CARD = {"rec": 1.0, "rec_yd": 0.1, "idp_tkl_solo": 1.0, "idp_sack": 2.0, "pass_td": 6.0}


def _inputs():
    players = {
        "100": {
            "full_name": "Alpha Wide",
            "position": "WR",
            "gsis_id": " 00-0000001",
            "team": "AAA",
        },
        "300": {"full_name": "Charlie Lineback", "position": "LB", "team": "BBB"},
        "400": {"full_name": "Delta Tight", "position": "TE", "team": "CCC"},
        "500": {"full_name": "Echo Bye", "position": "RB", "team": "DDD"},
    }
    matchups = {
        1: [
            {
                "starters": ["100", "300"],
                "players_points": {"100": 5.0, "300": 3.0, "400": 7.5, "500": 0.0},
            }
        ]
    }
    stats = {
        1: {
            "100": {"rec": 2, "rec_yd": 30, "gp": 1},
            "300": {"idp_tkl_solo": 3, "gp": 1},
            "400": {"rec": 2, "rec_yd": 55, "gp": 1},
        }
    }
    base = {"season": 2026, "week": 1, "season_type": "REG"}
    rows = [
        # joined by GSIS (leading space in the directory is stripped); agrees
        {**base, "player_id": "00-0000001", "player_display_name": "Alpha Wide",
         "position": "WR", "team": "AAA", "receptions": 2, "receiving_yards": 30},
        # joined by the identity owner's exact-name rung; nflverse under-counts a solo
        {**base, "player_id": "00-9999999", "player_display_name": "Charlie Lineback",
         "position": "LB", "team": "BBB", "def_tackles_solo": 2},
        # nobody on the host side: counted as unjoined, never silently matched
        {**base, "player_id": "00-8888888", "player_display_name": "Nobody Known",
         "position": "WR", "team": "ZZZ", "receptions": 1},
    ]  # fmt: skip
    return players, matchups, stats, rows


@pytest.fixture(scope="module")
def result():
    players, matchups, stats, rows = _inputs()
    return census.build_census(
        card=CARD, players=players, matchups_by_week=matchups, stats_by_week=stats,
        nflverse_rows=rows, pbp_stats=None, scoring=census.load_scoring(), weeks=[1],
    )  # fmt: skip


def test_host_native_scorer_matches_awarded_points(result):
    b = result["hostNative"]
    assert b["rosteredPlayerWeeks"] == 4
    assert b["withStatLine"] == 3
    assert b["canonicalScoreStatLine"]["withinTol"] == 3
    assert b["productionHostNative"]["withinTol"] == 3
    # a rostered player with NO stat line is reported as such, not scored as a zero match
    assert b["noStatLine"] == 1 and b["noStatLineAwardedZero"] == 1


def test_identity_join_is_by_owner_and_counts_unjoined(result):
    j = result["nflverseJoin"]
    assert j["joinMethods"]["gsis_id"] == 1
    assert sum(v for k, v in j["joinMethods"].items() if k != "gsis_id") == 1  # exact-name rung
    assert j["nflverseRowsUnjoined"]["unresolved_by_identity_owner"] == 1
    assert j["hostRowsWithoutNflverseRow"]["no_nflverse_row_host_zero"] == 1
    # the tight end the host paid 7.5 has no nflverse row: surfaced, never 0
    assert [r["name"] for r in j["hostRowsWithoutNflverseRowButHostNonzero"]] == ["Delta Tight"]


def test_nflverse_path_agreement_and_decomposition(result):
    n = result["nflversePath"]
    assert n["scored"]["n"] == 2
    assert n["scored"]["withinTol"] == 1  # the WR agrees, the LB does not
    assert n["byGroup"]["WR"]["agreement"] == 1.0
    (mismatch,) = n["mismatches"]
    assert mismatch["name"] == "Charlie Lineback"
    assert mismatch["delta"] == pytest.approx(-1.0)
    assert set(mismatch["keys"]) == {"idp_tkl_solo"}
    assert mismatch["category"] == "missing_raw_stat_event_in_feed"
    assert mismatch["keys"]["idp_tkl_solo"]["subtype"] == "feed_undercounts_vs_host"
    assert n["mismatchedRowsExplainedBySingleKey"] == 1
    per_key = {k["key"]: k for k in n["perKey"]}
    assert per_key["idp_tkl_solo"]["rowsDiffer"] == 1
    assert per_key["rec"]["rowsDiffer"] == 0


@pytest.mark.parametrize(
    ("key", "host", "nfl", "row", "host_pos", "nfl_pos", "expect"),
    [
        # row carries the event, normalization emitted nothing -> mapping defect
        ("idp_tkl_solo", 1, 0, {"def_tackles_solo": 1}, "WR", "WR",
         ("category_mapping_defect", "event_present_in_row_not_emitted")),
        ("fgmiss_50_59", 1, 0, {"fg_blocked": 1}, "K", "K",
         ("category_mapping_defect", "event_present_in_row_not_emitted")),
        # emitted but a different count -> the providers disagree
        ("idp_tkl_solo", 3, 2, {"def_tackles_solo": 2}, "LB", "LB",
         ("missing_raw_stat_event_in_feed", "feed_undercounts_vs_host")),
        ("idp_tkl_solo", 2, 3, {"def_tackles_solo": 3}, "LB", "LB",
         ("missing_raw_stat_event_in_feed", "feed_overcounts_vs_host")),
        ("idp_tkl_solo", 2, 3, {"_pbp_st_idp_tkl_solo": 1.0}, "DB", "DB",
         ("missing_raw_stat_event_in_feed", "special_teams_play_in_defensive_column_exact")),
        # position vocabulary: host FB vs nflverse RB
        ("bonus_fd_rb", 0, 1, {}, "FB", "RB", ("category_mapping_defect", "position_vocabulary")),
    ],
)  # fmt: skip
def test_classify_key(key, host, nfl, row, host_pos, nfl_pos, expect):
    got = census.classify_key(key, host, nfl, row, host_pos=host_pos, nfl_pos=nfl_pos)
    assert got == expect
