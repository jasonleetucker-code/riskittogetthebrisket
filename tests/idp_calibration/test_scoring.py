from __future__ import annotations

from src.idp_calibration.scoring import IDP_STAT_KEYS, parse_scoring, score_line


def test_expanded_sleeper_idp_keys_are_recognised():
    # Snapshot of the IDP scoring in a real Sleeper "Standard" league.
    # Each key below corresponds to a labelled line item in Sleeper's
    # mobile Scoring Settings → IDP tab; the test asserts every one
    # round-trips through the alias map onto a canonical weight.
    # (This league does not score 10+ Tackle Bonus; that alias is
    # still supported for leagues that do — see test_unknown… below.)
    league = {
        "league_id": "abc",
        "season": 2025,
        "scoring_settings": {
            "idp_td": 6.15,           # IDP TD → idp_def_td
            "idp_sack": 4.65,         # Sack
            "idp_sack_yd": 0.13,      # Sack Yards (per yard)
            "idp_qb_hit": 1.04,       # Hit on QB
            "idp_tkl_loss": 2.03,     # Tackle For Loss
            "idp_blk_kick": 3.4,      # Blocked Punt, PAT or FG
            "idp_int": 6.1,           # Interception
            "idp_int_ret_yd": 0.10,   # INT Return Yards
            "idp_fum_rec": 3.85,      # Fumble Recovery
            "idp_fum_ret_yd": 0.10,   # Fumble Return Yards
            "idp_ff": 3.85,           # Forced Fumble
            "idp_safe": 4.88,         # Safety
            "idp_tkl_ast": 0.75,      # Assisted Tackle
            "idp_tkl_solo": 1.47,     # Solo Tackle
            "idp_pd": 1.81,           # Pass Defended
        },
    }
    scoring = parse_scoring(league)
    active = scoring.summary()["active_idp_stats"]
    expected = {
        "idp_def_td": 6.15,
        "idp_sack": 4.65,
        "idp_sack_yd": 0.13,
        "idp_qb_hit": 1.04,
        "idp_tkl_loss": 2.03,
        "idp_blk_kick": 3.4,
        "idp_int": 6.1,
        "idp_int_ret_yd": 0.10,
        "idp_fum_rec": 3.85,
        "idp_fum_ret_yd": 0.10,
        "idp_ff": 3.85,
        "idp_safe": 4.88,
        "idp_tkl_ast": 0.75,
        "idp_tkl_solo": 1.47,
        "idp_pd": 1.81,
    }
    for key, val in expected.items():
        assert key in active, f"missing canonical key {key}"
        assert abs(active[key] - val) < 1e-6
    # Sanity: summary reports zero unmapped IDP keys for this payload.
    assert scoring.summary()["unknown_idp_keys"] == {}


def test_legacy_idp_hit_still_maps_to_qb_hit():
    # Backward-compat — the older alias continues to land on the new
    # canonical idp_qb_hit (so rescoring a saved league snapshot from
    # before the rename still works).
    league = {"scoring_settings": {"idp_hit": 1.0}}
    scoring = parse_scoring(league)
    assert scoring.summary()["active_idp_stats"].get("idp_qb_hit") == 1.0


def test_unknown_idp_keys_surface_in_summary():
    # Exotic / future Sleeper IDP keys should round-trip through
    # summary()["unknown_idp_keys"] so the UI can tell the operator
    # exactly what to alias next time.
    league = {
        "scoring_settings": {
            "idp_sack": 4.0,              # known
            "idp_made_up_stat": 2.5,      # unknown IDP key
            "pass_yd": 0.04,              # offense — should NOT surface
        },
    }
    summary = parse_scoring(league).summary()
    assert summary["unknown_idp_keys"] == {"idp_made_up_stat": 2.5}


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
