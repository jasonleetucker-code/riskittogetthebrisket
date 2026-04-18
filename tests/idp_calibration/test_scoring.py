from __future__ import annotations

from src.idp_calibration.scoring import IDP_STAT_KEYS, parse_scoring, score_line


def test_parse_scoring_aliases_idp_keys():
    league = {
        "league_id": "abc",
        "season": 2024,
        "scoring_settings": {
            "idp_solo": 1.5,           # alias for idp_tkl_solo
            "idp_ast": 0.75,           # alias for idp_tkl_ast
            "idp_sack": 4.0,
            "idp_int": 3.0,
            "unknown_stat": 2.0,
        },
    }
    scoring = parse_scoring(league)
    assert scoring.league_id == "abc"
    assert scoring.season == 2024
    assert scoring.idp_weights["idp_tkl_solo"] == 1.5
    assert scoring.idp_weights["idp_tkl_ast"] == 0.75
    assert scoring.idp_weights["idp_sack"] == 4.0
    assert "unknown_stat" in scoring.unknown_keys
    # Inactive keys default to zero and stay accessible.
    for key in IDP_STAT_KEYS:
        assert key in scoring.idp_weights


def test_score_line_dots_weights_and_stats():
    weights = {"idp_tkl_solo": 1.0, "idp_sack": 4.0, "idp_int": 3.0}
    stats = {"idp_tkl_solo": 5, "idp_sack": 2, "idp_int": 1}
    assert score_line(stats, weights) == 5 * 1.0 + 2 * 4.0 + 1 * 3.0


def test_score_line_ignores_missing_stats():
    weights = {"idp_tkl_solo": 1.0, "idp_sack": 4.0}
    stats = {"idp_tkl_solo": 10}
    assert score_line(stats, weights) == 10.0
