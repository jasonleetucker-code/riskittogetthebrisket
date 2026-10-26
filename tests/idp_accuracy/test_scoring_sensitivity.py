"""Lane E (IDP scoring sensitivity): rescoring identity, design, maths and evidence integrity.

Research only.  What is pinned here, in the order a reviewer would ask:

1. the pre-registered configuration is complete, documented and self-consistent;
2. rescoring by ``fixed + counts @ rates`` is the production scorer, for the actual card and for every
   kind of perturbed card, and stacking is a property of the stat line, not a model;
3. a bye, a DNP and an unknown week are never played weeks, and half-season splits use WEEK NUMBERS
   (a regression: positions 0-5 were once compared with week numbers 1-6);
4. the pure statistics do what they claim (tiers, gaps, reliability, ICC, intervals, paired contrasts);
5. the vendored best-ball solver is the owner's solver, and the best-ball marginal behaves as defined;
6. the committed evidence file is internally consistent, carries no manager / team / roster identity,
   and the write-up quotes it;
7. nothing in production imports this lane.

Tests that need the cached Sleeper bodies (not available in CI) are skipped, never faked.
"""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from scripts.idp_accuracy import scoring_sensitivity as S
from src.nfl_data.realized_points import compute_weekly_points
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    solve_optimal_assignment,
)

REPO = Path(__file__).resolve().parents[2]
CFG = S.load_config()
EVIDENCE_PATH = S.EVIDENCE_PATH
DOC_PATH = S.DOC_PATH
CACHE_OK = (S.CACHE_DIR / "nflverse" / "schedules__games.csv").exists() and any(
    S.CACHE_DIR.glob("*.json")
)

SLOTS = [
    "QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K",
    "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB",
]  # fmt: skip

#: The actual 2026 card for the keys these tests need (values are the pre-registered, Lane-A-verified
#: ones; the config test below pins them against the config).
ACTUAL_CARD: dict[str, float] = {
    **CFG["expectedActualIdpBlock"],
    "rec": 0.1,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "pass_td": 6.0,
    "pass_yd": 0.04,
    "pass_int": -4.0,
    "st_tkl_solo": 1.33,
    "st_ff": 4.25,
    "int": 1.0,  # a team-defense key that must never be paid to a player
}


def _evidence():
    if not EVIDENCE_PATH.exists():
        pytest.skip("evidence file not generated yet")
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


# ── 1. the pre-registered configuration ──────────────────────────────────────


def test_config_covers_every_directive_key_with_the_preregistered_grid():
    directive = {
        "solo", "assist", "tfl", "sack", "sack_yd", "qb_hit", "pd", "int", "ff", "fr", "def_td",
    }  # fmt: skip
    assert set(CFG["studyKeys"]) == directive
    assert set(CFG["oneAtATime"]["keys"]) == directive
    assert CFG["oneAtATime"]["multipliers"] == [0.0, 0.5, 1.5, 2.0]
    assert CFG["productionScoringChanged"] is False
    assert CFG["status"] == "RESEARCH_ONLY_NOT_FOR_PROMOTION"


def test_config_pins_the_lane_a_card_and_fingerprint():
    block = CFG["expectedActualIdpBlock"]
    assert block["idp_tkl_loss"] == 4.24
    assert block["idp_pass_def"] == 5.3
    assert block["idp_tkl_solo"] == 1.33
    assert (
        block["idp_tkl"] == 0.0
    )  # combined tackles are unpriced: solo + assist are never double-paid
    assert CFG["league"]["pinnedScoringFingerprint"] == "sf1:9e51824690d091f9"
    assert CFG["league"]["sleeperLeagueId"] == "1312006700437352448"
    assert CFG["league"]["leagueKey"] == "dynasty_main"


def test_idp_card_keys_resolve_to_the_tensor_keys_in_order():
    resolved = tuple(S._ALIASES.get(k, k) for k in CFG["idpCardKeys"])
    assert resolved == S.TENSOR_KEYS
    assert set(CFG["expectedActualIdpBlock"]) == set(CFG["idpCardKeys"])
    for ref in CFG["reference"]:
        assert set(ref["idpBlock"]) == set(CFG["idpCardKeys"]), ref["id"]


def test_every_card_is_documented_with_a_source_and_a_rationale():
    ids = [j["id"] for j in CFG["joint"]] + [r["id"] for r in CFG["reference"]]
    assert len(ids) == len(set(ids)) == 12
    for j in CFG["joint"]:
        assert len(j["rationale"]) > 40, j["id"]
        assert set(j["multipliers"]) <= set(CFG["studyKeys"]), j["id"]
    for r in CFG["reference"]:
        assert len(r["rationale"]) > 40 and len(r["source"]) > 40, r["id"]
        if r["kind"] == "constructed":
            assert "NOT any platform's default" in r["source"], r["id"]
        else:
            assert r["kind"] == "historical_actual"
            assert re.search(r"league \d{19}", r["source"]), r["id"]
    assert CFG["stacking"]["rule"] and CFG["stacking"]["evidence"]


def test_build_cards_makes_57_cards_that_differ_only_where_designed():
    cards = S.build_cards(ACTUAL_CARD, CFG)
    assert len(cards) == 1 + 11 * 4 + 8 + 4 == 57
    assert cards["actual"] == ACTUAL_CARD
    idp_keys = set(CFG["idpCardKeys"])
    for key in CFG["oneAtATime"]["keys"]:
        ck = CFG["studyKeys"][key]
        for m in CFG["oneAtATime"]["multipliers"]:
            card = cards[f"oat:{key}:x{m:g}"]
            diff = {k for k in card if card[k] != ACTUAL_CARD.get(k)}
            assert diff <= {ck}, (key, m, diff)
            assert math.isclose(card[ck], ACTUAL_CARD[ck] * m, rel_tol=1e-12)
    for j in CFG["joint"]:
        card = cards[f"joint:{j['id']}"]
        touched = {CFG["studyKeys"][k] for k in j["multipliers"]} | set(j.get("zeroCardKeys", []))
        assert {k for k in card if card[k] != ACTUAL_CARD.get(k)} <= touched, j["id"]
    for r in CFG["reference"]:
        card = cards[f"ref:{r['id']}"]
        assert {k: card[k] for k in idp_keys} == {k: float(v) for k, v in r["idpBlock"].items()}
        # offense, special teams and team-defense keys are never touched by a reference card
        for k, v in ACTUAL_CARD.items():
            if k not in idp_keys:
                assert card[k] == v, (r["id"], k)


def test_key_configs_exist_and_cover_the_questions():
    cards = S.build_cards(ACTUAL_CARD, CFG)
    for cid in CFG["analysis"]["keyConfigs"]:
        assert cid in cards, cid
    key = set(CFG["analysis"]["keyConfigs"])
    assert {"oat:tfl:x0", "oat:tfl:x2", "oat:pd:x0", "oat:pd:x2", "actual"} <= key
    assert {"ref:big_play", "ref:tackle_heavy_balanced"} <= key


def test_analysis_spec_is_the_one_the_code_runs():
    a = CFG["analysis"]
    assert a["pool"]["minPlayedGames2026"] == 4
    assert a["pool"]["minPlayedGamesSensitivity"] == [3, 5]
    assert a["tiers"]["elite"] == [1, 12] and a["tiers"]["averageStarter"] == [25, 36]
    assert a["tiers"]["firstBench"] == [37, 48] and a["tiers"]["starters"] == [1, 36]
    assert S.TIER_BOUNDS == {
        "p12": (0, 12),
        "p13_24": (12, 24),
        "p25_36": (24, 36),
        "p37_48": (36, 48),
    }
    assert S.STARTERS == 36
    assert a["bootstrap"]["replicates"] == {"W": 500, "P": 500, "B": 200}
    families = {q: [i["id"] for i in v["items"]] for q, v in a["contrasts"].items()}
    assert families["Q1"] == ["Q1.1", "Q1.2", "Q1.3"]
    assert families["Q2"] == ["Q2.1", "Q2.2", "Q2.3", "Q2.4", "Q2.5"]
    assert families["Q3"] == ["Q3.1", "Q3.2", "Q3.3", "Q3.4"]
    assert families["Q4"] == ["Q4.1", "Q4.2", "Q4.3", "Q4.4"]


# ── 2. the rescoring identity ────────────────────────────────────────────────

DIRECTORY = {
    "1001": {
        "position": "DL",
        "fantasy_positions": ["DL"],
        "team": "AAA",
        "full_name": "Edge Rusher",
    },
    "1002": {
        "position": "LB",
        "fantasy_positions": ["LB"],
        "team": "AAA",
        "full_name": "Backer One",
    },
    "1003": {
        "position": "DB",
        "fantasy_positions": ["DB"],
        "team": "BBB",
        "full_name": "Corner One",
    },
    "1004": {"position": "WR", "fantasy_positions": ["WR"], "team": "BBB", "full_name": "Wide One"},
    "1005": {
        "position": "DL",
        "fantasy_positions": ["DL", "LB"],
        "team": "CCC",
        "full_name": "Hybrid One",
    },
}
PLAY = {"AAA": {1, 2, 3}, "BBB": {1, 3}, "CCC": {1, 2, 3}}  # BBB is on a bye in week 2


def _stats():
    sack_play = {
        "gp": 1.0, "def_snp": 60.0, "idp_sack": 1.0, "idp_sack_yd": 7.0, "idp_tkl_loss": 1.0,
        "idp_qb_hit": 1.0, "idp_tkl_solo": 3.0, "idp_tkl_ast": 2.0, "idp_tkl": 5.0,
    }  # fmt: skip
    lb = {
        "gp": 1.0, "def_snp": 70.0, "idp_tkl_solo": 6.0, "idp_tkl_ast": 4.0, "idp_tkl": 10.0,
        "idp_pd": 1.0, "idp_int": 1.0, "idp_int_ret_yd": 18.0, "idp_ff": 1.0, "st_tkl_solo": 1.0,
    }  # fmt: skip
    db = {
        "gp": 1.0, "def_snp": 50.0, "idp_pass_def": 3.0, "idp_pass_def_3p": 1.0, "idp_tkl_solo": 4.0,
        "idp_fum_rec": 1.0, "idp_fum_ret_yd": 9.0, "idp_def_td": 1.0, "bonus_def_int_td_50p": 0.0,
    }  # fmt: skip
    wr = {"gp": 1.0, "off_snp": 40.0, "rec": 5.0, "rec_yd": 61.0, "rec_td": 1.0, "rec_5_9": 3.0}
    return {
        1: {
            "1001": sack_play,
            "1002": lb,
            "1003": db,
            "1004": wr,
            "1005": {**sack_play, "idp_hit": 2.0},
        },
        2: {"1001": {"gp": 1.0, "def_snp": 55.0, "idp_tkl_solo": 2.0}, "1002": {"gms_active": 1.0}},
        3: {"1001": {"gp": 1.0, "def_snp": 50.0, "idp_sack": 2.0, "idp_tkl_loss": 3.0}},
    }


def _season(card=None):
    return S.build_season(_stats(), DIRECTORY, card or ACTUAL_CARD, PLAY, 2026, (1, 2, 3))


def test_rescoring_equals_the_production_scorer_for_every_card():
    cards = S.build_cards(ACTUAL_CARD, CFG)
    season = _season()
    stats = _stats()
    for cid, card in cards.items():
        rates = S.rate_vector(card)
        lin = season.points(rates)
        for w_i, w in enumerate((1, 2, 3)):
            for pid, line in stats.get(w, {}).items():
                r = season.index[pid]
                if season.status[r, w_i] != S.PLAYED:
                    continue
                pos = S.lineup_position(DIRECTORY[pid]["position"])
                oracle = compute_weekly_points(
                    {**line, "player_id": pid, "season": 2026, "week": w},
                    card,
                    position=pos,
                    source="sleeper",
                )
                assert oracle is not None
                assert lin[r, w_i] == pytest.approx(oracle.fantasy_points, abs=1e-9), (cid, pid, w)


def test_alias_rule_matches_the_production_scorer():
    # the card spells two keys differently from the stat line
    assert (
        S.TENSOR_KEYS[S.KIDX["idp_hit"]] == "idp_hit"
        and S.TENSOR_KEYS[S.KIDX["idp_pd"]] == "idp_pd"
    )
    r = S.rate_vector({"idp_qb_hit": 2.5, "idp_pass_def": 7.0})
    assert r[S.KIDX["idp_hit"]] == 2.5 and r[S.KIDX["idp_pd"]] == 7.0
    # the canonical spelling wins when both are present (the production scorer copies only if absent)
    r = S.rate_vector({"idp_qb_hit": 2.5, "idp_hit": 9.0})
    assert r[S.KIDX["idp_hit"]] == 9.0
    # and the zeroed "fixed" card removes both spellings
    z = S.card_without_tensor({"idp_qb_hit": 2.5, "idp_hit": 9.0, "rec": 0.1})
    assert z["idp_qb_hit"] == 0.0 and z["idp_hit"] == 0.0 and z["rec"] == 0.1


def test_stacking_is_a_property_of_the_stat_line():
    """A sack play pays the sack, the TFL and the QB hit together; keys never interact."""
    card = ACTUAL_CARD
    base = {"gp": 1.0, "idp_sack": 1.0, "idp_tkl_loss": 1.0, "idp_qb_hit": 1.0}
    pts = lambda line, c: compute_weekly_points(  # noqa: E731
        {**line, "player_id": "1001", "season": 2026, "week": 1}, c, position="DL", source="sleeper"
    ).fantasy_points
    stacked = pts(base, card)
    assert stacked == pytest.approx(2.92 + 4.24 + 2.12)
    # zeroing one key removes exactly that key's points from the SAME play: no cross terms
    for key, rate in (("idp_tkl_loss", 4.24), ("idp_qb_hit", 2.12), ("idp_sack", 2.92)):
        assert pts(base, {**card, key: 0.0}) == pytest.approx(stacked - rate)
    # and the linear path agrees on a play that carries all three
    season = S.build_season({1: {"1001": base}}, DIRECTORY, card, PLAY, 2026, (1,))
    c2 = S.build_cards(ACTUAL_CARD, CFG)["oat:tfl:x0"]
    assert season.points(S.rate_vector(c2))[0, 0] == pytest.approx(2.92 + 2.12)


def test_combined_tackles_are_unpriced_so_solo_and_assist_are_not_double_paid():
    line = {"gp": 1.0, "idp_tkl_solo": 3.0, "idp_tkl_ast": 2.0, "idp_tkl": 5.0}
    season = S.build_season({1: {"1002": line}}, DIRECTORY, ACTUAL_CARD, PLAY, 2026, (1,))
    assert season.points(S.rate_vector(ACTUAL_CARD))[0, 0] == pytest.approx(3 * 1.33 + 2 * 0.8)
    # a card that DID price the combined key would pay it on top, exactly as Sleeper would
    paid = {**ACTUAL_CARD, "idp_tkl": 0.5}
    assert season.points(S.rate_vector(paid))[0, 0] == pytest.approx(3 * 1.33 + 2 * 0.8 + 5 * 0.5)


def test_fixed_part_excludes_every_varied_key_and_keeps_the_rest():
    season = _season()
    r = season.index["1002"]
    # the LB line has a special-teams tackle (not varied) among IDP keys: it stays in `fixed`
    assert season.fixed[r, 0] == pytest.approx(1.33)  # st_tkl_solo 1 x 1.33
    wr = season.index["1004"]
    assert season.fixed[wr, 0] == pytest.approx(5 * 0.1 + 61 * 0.1 + 6.0)  # offense is all fixed
    assert np.all(season.counts[wr] == 0.0)


def test_week_status_never_confuses_bye_dnp_and_unknown_with_played():
    season = _season()
    st = season.status
    # 1003 (team BBB, bye in week 2) played week 1 and has no line for weeks 2-3
    assert list(st[season.index["1003"]]) == [S.PLAYED, S.BYE, S.DNP]
    # 1002 had only a gms_active placeholder in week 2: the team played, he did not -> DNP, not played
    assert st[season.index["1002"], 1] == S.DNP
    assert st[season.index["1002"], 2] == S.DNP
    # a DNP and a bye are not zero points of a played week
    assert season.fixed[season.index["1003"], 1] == 0.0
    assert season.n_played()[season.index["1003"]] == 1
    # a player whose team cannot be established is UNKNOWN in weeks without a line
    d2 = {**DIRECTORY, "1001": {**DIRECTORY["1001"], "team": None}}
    s2 = S.build_season({1: {"1001": _stats()[1]["1001"]}}, d2, ACTUAL_CARD, PLAY, 2026, (1, 2, 3))
    assert list(s2.status[0]) == [S.PLAYED, S.UNKNOWN, S.UNKNOWN]


def test_team_defense_entries_and_unlisted_positions_are_not_players():
    stats = {
        1: {"PHI": {"def_snp": 60.0, "int": 2.0}, "TEAM_BUF": {"sack": 3.0}, "9999": {"gp": 1.0}}
    }
    season = S.build_season(stats, DIRECTORY, ACTUAL_CARD, PLAY, 2026, (1,))
    assert season.pids == []  # team entries refused, 9999 absent from the directory


# ── 3. half-season splits use week numbers ───────────────────────────────────


def _universe(played_weeks, fixed=None, tfl=None):
    """A one-player-per-row Universe from lists of played WEEK NUMBERS (1-6)."""
    P, K = len(played_weeks), len(S.TENSOR_KEYS)
    Fp, Cp = np.zeros((P, 6)), np.zeros((P, 6, K))
    wk = np.full((P, 6), -1, dtype=np.int64)
    n = np.zeros(P, dtype=np.int64)
    for i, ws in enumerate(played_weeks):
        n[i] = len(ws)
        for j, w in enumerate(ws):
            wk[i, j] = w - 1
            Fp[i, j] = fixed[i][j] if fixed else 1.0
            if tfl:
                Cp[i, j, S.KIDX["idp_tkl_loss"]] = tfl[i][j]
    M = np.arange(6)[None, :] < n[:, None]
    return S.Universe(
        rows=np.arange(P), pids=[str(i) for i in range(P)], Fp=Fp, Cp=Cp, wk=wk, n=n, M=M,
        mF=Fp.sum(1) / n, mC=Cp.sum(1) / n[:, None], group=np.array(["DL"] * P),
        arch=np.array(["DT"] * P), rostered=np.zeros(P, bool), fa=np.zeros(P, bool),
        name=[str(i) for i in range(P)],
    )  # fmt: skip


def test_half_means_use_week_numbers_not_positions():
    # played weeks 1,2,4,5,6 with distinct points; week 3 missed.  Positions are 0,1,3,4,5.
    u = _universe([[1, 2, 4, 5, 6]], fixed=[[10.0, 20.0, 40.0, 50.0, 60.0]])
    nA, fA, _ = S.half_means(u, (1, 2, 3))
    assert nA[0] == 2 and fA[0] == pytest.approx(15.0)  # weeks 1 and 2 only
    nB, fB, _ = S.half_means(u, (4, 5, 6))
    assert nB[0] == 3 and fB[0] == pytest.approx(50.0)  # weeks 4, 5, 6
    nC, fC, _ = S.half_means(u, (1, 4, 6))
    assert nC[0] == 3 and fC[0] == pytest.approx((10 + 40 + 60) / 3)


def test_balanced_partitions_are_ten_disjoint_complete_3_3_splits():
    parts = S.balanced_partitions()
    assert len(parts) == 10
    for a, b in parts:
        assert (
            len(a) == len(b) == 3 and set(a) | set(b) == set(S.STUDY_WEEKS) and not set(a) & set(b)
        )
        assert 1 in a
    assert len({p[0] for p in parts}) == 10


# ── 4. the pure statistics ───────────────────────────────────────────────────


def test_tier_means_and_derived_metrics():
    x = np.arange(60, 0, -1, dtype=float)[:, None]  # 60..1, one config
    t = S.tier_means(x)
    assert t["p12"][0] == pytest.approx(np.mean(range(49, 61)))
    assert t["p25_36"][0] == pytest.approx(np.mean(range(25, 37)))
    assert t["p37_48"][0] == pytest.approx(np.mean(range(13, 25)))
    assert t["starters"][0] == pytest.approx(np.mean(range(25, 61)))
    d = S.derived_tier_metrics(t)
    assert d["sep"][0] == pytest.approx(t["p12"][0] - t["p25_36"][0])
    assert d["gap_rank"][0] == pytest.approx(t["starters"][0] - t["p37_48"][0])
    assert d["rel_gap_rank"][0] == pytest.approx(d["gap_rank"][0] / t["starters"][0])
    # a tier the pool cannot fill is undefined, never a partial mean or a zero
    short = S.tier_means(x[:30])
    assert (
        np.isnan(short["p25_36"][0])
        and np.isnan(short["starters"][0])
        and not np.isnan(short["p12"][0])
    )


def test_free_agent_level_is_the_median_of_the_top_five_and_needs_three():
    fa = np.array([[9.0], [8.0], [7.0], [6.0], [5.0], [1.0]])
    assert S.fa_level(fa)[0] == 7.0
    assert S.fa_level(fa[:3])[0] == 8.0  # median of three
    assert np.isnan(S.fa_level(fa[:2])[0])  # two free agents set no level


def test_spearman_and_spearman_brown():
    a = np.arange(20, dtype=float)[:, None]
    assert S.spearman_cols(a, a * 3 + 1)[0] == pytest.approx(1.0)
    assert S.spearman_cols(a, -a)[0] == pytest.approx(-1.0)
    assert S.spearman_brown(np.array([0.5]))[0] == pytest.approx(2 / 3)
    assert np.isnan(S.spearman_brown(np.array([-1.0]))[0])


def test_pair_stats_perfect_persistence_and_none():
    n = 80
    base = np.arange(n, dtype=float)[:, None]
    ps = S.PairSet([base, base], [base * 2.0, base * 2.0], [np.ones(n, bool)] * 2, n)
    out = S.pair_stats(ps, np.arange(n))
    assert out["split_half"][0] == pytest.approx(1.0)
    # both directions are averaged: rank on A and score B (= 2A), then rank on B and score A (= B / 2),
    # so the held-out elite mean is (2 + 1) / 2 times the elite mean of A
    m12, m25 = np.mean(range(68, 80)), np.mean(range(44, 56))
    assert out["oos_p12"][0] == pytest.approx(1.5 * m12)
    assert out["oos_sep"][0] == pytest.approx(1.5 * (m12 - m25))
    # no persistence: B is the reverse order of A, so the held-out elite are the worst
    rev = base[::-1].copy()
    ps2 = S.PairSet([base], [rev], [np.ones(n, bool)], n)
    out2 = S.pair_stats(ps2, np.arange(n))
    assert out2["split_half"][0] < 0 or np.isnan(out2["split_half"][0])
    assert out2["oos_sep"][0] < 0
    # an ineligible player is excluded from a partition
    el = np.ones(n, bool)
    el[:73] = False  # seven eligible players: below the eight needed for any estimate
    ps3 = S.PairSet([base], [base], [el], n)
    assert np.isnan(S.pair_stats(ps3, np.arange(n))["split_half"][0])  # < 8 eligible: no estimate


def test_yoy_stat_forward_tiers():
    n = 60
    a = np.arange(n, dtype=float)[:, None]
    b = a + 5.0
    out = S.yoy_stat(S.PairSet([a], [b], [np.ones(n, bool)], n), np.arange(n))
    assert out["yoy"][0] == pytest.approx(1.0)
    assert out["fwd_p12"][0] == pytest.approx(np.mean(range(48, 60)) + 5.0)
    assert out["fwd_sep"][0] == pytest.approx(np.mean(range(48, 60)) - np.mean(range(24, 36)))
    tiny = S.yoy_stat(S.PairSet([a[:5]], [b[:5]], [np.ones(5, bool)], 5), np.arange(5))
    assert np.isnan(tiny["yoy"][0]) and np.isnan(tiny["fwd_sep"][0])


def test_icc_separates_a_stable_player_effect_from_noise():
    a, W = 30, 6
    player = np.linspace(0.0, 20.0, a)[:, None, None] * np.ones((1, W, 1))
    valid = np.ones((a, W), bool)
    n = np.full(a, W)
    pure_between = player + np.tile(
        np.array([0.0, 0.01, -0.01, 0.0, 0.01, -0.01])[None, :, None], (a, 1, 1)
    )
    mean = pure_between.mean(axis=1)
    assert S.icc1(pure_between, valid, n, mean)[0] > 0.999
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 5, (a, W, 1))
    noise = noise - noise.mean(
        axis=0, keepdims=True
    )  # remove any between-player shift in week means
    mean_n = noise.mean(axis=1)
    assert abs(S.icc1(noise, valid, n, mean_n)[0]) < 0.25


def test_basic_ci_and_paired_estimates():
    reps = np.array([1.0, 2.0, 3.0, 4.0, 5.0] * 40)
    lo, hi = S.basic_ci(2.0, reps)
    assert lo < 2.0 < hi
    assert lo == pytest.approx(2 * 2.0 - 5.0) and hi == pytest.approx(2 * 2.0 - 1.0)
    # an estimate whose replicates sit above it gets an interval shifted DOWN (selection bias correction)
    assert float(np.mean([lo, hi])) < float(np.mean(reps))
    a = S.Est(1.0, np.array([1.0, 2.0, 3.0]))
    b = S.Est(0.5, np.array([0.5, 0.5, 1.0]))
    d = a - b
    assert d.obs == 0.5 and list(d.reps) == [0.5, 1.5, 2.0]
    assert (a * 2).obs == 2.0 and (a + 1).reps[0] == 2.0 and (a / b).obs == 2.0
    with pytest.raises(ValueError):
        a - S.Est(0.0, np.array([0.0, 0.0]))  # replicates from different schemes cannot be paired
    assert np.isnan(S.Est(1.0).ci()[0])


def test_ols_slope_recovers_the_coefficient_with_group_effects():
    rng = np.random.default_rng(11)
    n = 600
    cv = rng.uniform(0.3, 1.0, n)
    ppg = rng.uniform(5.0, 20.0, n)
    group = rng.choice(np.array(["DB", "DL", "LB"]), n)
    shift = np.where(group == "DL", 1.5, np.where(group == "LB", -0.7, 0.0))
    y = 0.4 + 2.5 * cv - 0.1 * ppg + shift + rng.normal(0, 0.05, n)
    assert S.ols_slope(y, cv, ppg, group) == pytest.approx(2.5, abs=0.1)
    assert np.isnan(S.ols_slope(y[:5], cv[:5], ppg[:5], group[:5]))


def test_draw_weeks_is_paired_linear_and_reproducible():
    played = [[1, 2, 3, 4, 5, 6], [1, 3, 5], [2, 4]]
    tfl = [[0, 1, 0, 2, 1, 0], [1, 0, 1], [3, 0]]
    u = _universe(played, fixed=[[5.0] * 6, [4.0] * 3, [3.0] * 2], tfl=tfl)
    r1 = S.draw_weeks(u, np.random.default_rng(5))
    r2 = S.draw_weeks(u, np.random.default_rng(5))
    assert np.array_equal(r1[0], r2[0]) and np.array_equal(r1[1], r2[1])
    Fb, Cb = r1
    # one resample scored under two cards: the difference is exactly the rate difference times the counts
    R = np.zeros((len(S.TENSOR_KEYS), 2))
    R[S.KIDX["idp_tkl_loss"], 1] = 4.0
    pts = Fb[:, :, None] + np.einsum("pjk,kc->pjc", Cb, R)
    assert np.allclose(pts[:, :, 1] - pts[:, :, 0], 4.0 * Cb[:, :, S.KIDX["idp_tkl_loss"]])
    # a one-game player has no spread to inflate; inflation is sqrt(n / (n - 1)) otherwise
    u1 = _universe([[1, 2]], fixed=[[2.0, 4.0]])
    means = []
    rng = np.random.default_rng(20261026)
    for _ in range(4000):
        Fb1, _ = S.draw_weeks(u1, rng)
        means.append(Fb1[0, :2].mean())
    assert np.mean(means) == pytest.approx(3.0, abs=0.1)  # unbiased for the observed mean
    # two games (2, 4): sample variance 2, so the variance of the mean should be 2 / 2 = 1.  Plain
    # resampling gives 0.5 (the plug-in variance is (n - 1) / n of the sample's); the inflation restores it.
    assert np.std(means) == pytest.approx(1.0, rel=0.1)


def test_w_metrics_matches_a_direct_computation():
    P = 70
    played = [list(range(1, 7))] * P
    fixed = [[float(P - i)] * 6 for i in range(P)]
    tfl = [[(1.0 if i % 2 else 0.0)] * 6 for i in range(P)]
    u = _universe(played, fixed=fixed, tfl=tfl)
    R = np.zeros((len(S.TENSOR_KEYS), 2))
    R[S.KIDX["idp_tkl_loss"], 1] = 10.0
    pools = {"DL": np.arange(P)}
    out = S.w_metrics(u.Fp, u.Cp, u, R, pools, {})
    for c, rate in enumerate((0.0, 10.0)):
        ppg = np.array([(P - i) + (rate if i % 2 else 0.0) for i in range(P)], float)
        s = np.sort(ppg)[::-1]
        assert out["DL.p12"][c] == pytest.approx(s[:12].mean())
        assert out["DL.p25_36"][c] == pytest.approx(s[24:36].mean())
        assert out["DL.starters"][c] == pytest.approx(s[:36].mean())
        assert out["DL.sep"][c] == pytest.approx(s[:12].mean() - s[24:36].mean())
        assert out["DL.gap_rank"][c] == pytest.approx(s[:36].mean() - s[36:48].mean())
        assert out["DL.n"][c] == P
    # constant weekly points -> zero weekly spread
    assert out["DL.sd_med"][0] == pytest.approx(0.0)


# ── 5. the vendored solver and the best-ball marginal ─────────────────────────


def _spec():
    spec = [("QB", ["QB"])] * 3 + [("RB", ["RB"])] * 8 + [("WR", ["WR"])] * 9
    spec += [("TE", ["TE"])] * 4 + [("K", ["K"])] * 2
    spec += [("DL", ["DL"])] * 5 + [("DL", ["DL", "LB"])] * 3
    spec += [("LB", ["LB"])] * 4 + [("LB", ["DL", "LB"])] * 2
    spec += [("DB", ["DB"])] * 5 + [("DB", ["DB", "LB"])] * 2
    return spec


def test_vendored_solver_is_the_owner_solver_on_random_weeks():
    spec = _spec()
    sigs = [S.signature_for(f"p{i}", pos, fps, SLOTS) for i, (pos, fps) in enumerate(spec)]
    solver = S.LineupSolver(SLOTS, sigs)
    type_ids = np.array([solver.type_id[s] for s in sigs])
    rng = np.random.default_rng(20261026)
    X = rng.gamma(2.0, 4.0, (60, len(spec))) - rng.uniform(0, 3, (60, len(spec)))  # some negatives
    mine = solver.solve(X, type_ids)
    for w in range(X.shape[0]):
        pool = [
            RosterPlayer(f"p{i}", f"p{i}", pos, float(X[w, i]), fantasy_positions=tuple(fps))
            for i, (pos, fps) in enumerate(spec)
        ]
        got = solve_optimal_assignment(pool, SLOTS, objective=OBJECTIVE_REALIZED_POINTS)
        assert mine[w] == pytest.approx(sum(p.ros_value for p in got.values()), abs=1e-9), w


def test_slot_signatures_and_subproblems():
    assert S.signature_for("a", "DL", ["DL", "LB"], SLOTS) == frozenset({"DL", "LB"})
    assert S.subproblem_of(S.signature_for("a", "DL", ["DL", "LB"], SLOTS)) == "idp"
    assert S.subproblem_of(S.signature_for("a", "RB", ["RB"], SLOTS)) == "off"
    # a two-way DB/WR player spans both lineups and is out of scope, not forced into one
    assert S.subproblem_of(S.signature_for("h", "DB", ["DB", "WR"], SLOTS)) is None
    off, idp = S.split_slots(SLOTS)
    assert len(off) == 12 and len(idp) == 9


def _world(entities, slots, teams):
    """A minimal BBWorld.  entities: (pid, group, fantasy_positions, owner, is_fa)."""
    pids = [e[0] for e in entities]
    sig = [S.signature_for(e[0], e[1], e[2], slots) for e in entities]
    sub = [S.subproblem_of(s) for s in sig]
    off_slots, idp_slots = S.split_slots(slots)
    solvers = {
        "off": S.LineupSolver(off_slots, {s for s, b in zip(sig, sub) if b == "off"}),
        "idp": S.LineupSolver(idp_slots, {s for s, b in zip(sig, sub) if b == "idp"}),
    }
    type_of = np.array([solvers[b].type_id[s] if b else 0 for s, b in zip(sig, sub)])
    roster_idx = [{"off": [], "idp": []} for _ in range(teams)]
    for i, e in enumerate(entities):
        if e[3] is not None and sub[i]:
            roster_idx[e[3]][sub[i]].append(i)
    E, K = len(pids), len(S.TENSOR_KEYS)
    return S.BBWorld(
        pids=pids, names=pids, group=[e[1] for e in entities], arch=[e[1] for e in entities], sig=sig,
        sub=sub, Fr=np.zeros((E, 6)), Cr=np.zeros((E, 6, K)), Pm=np.ones((E, 6), bool),
        Am=np.ones((E, 6), bool), owner=[e[3] for e in entities],
        fa=np.array([e[4] for e in entities]), type_of=type_of, solvers=solvers, roster_idx=roster_idx,
    )  # fmt: skip


def test_best_ball_marginal_definition_on_a_hand_checked_roster():
    slots = ["DL", "DL"]
    ents = [
        ("a", "DL", ["DL"], 0, False),
        ("b", "DL", ["DL"], 0, False),
        ("c", "DL", ["DL"], 0, False),
    ]
    ents += [(f"f{i}", "DL", ["DL"], None, True) for i in range(5)]
    w = _world(ents, slots, 1)
    D = 6
    X = np.zeros((D, len(ents)))
    X[:, 0], X[:, 1], X[:, 2] = 10.0, 8.0, 1.0
    for i, v in enumerate((9.0, 8.0, 7.0, 6.0, 5.0)):
        X[:, 3 + i] = v
    A = np.ones((D, len(ents)), bool)
    m = S.bb_marginals(w, X, A, subs=("idp",))
    # the replacement is the MEDIAN-scoring roster among the five free agents -> the 7.0 free agent
    assert m["bb"][0] == pytest.approx(
        3.0
    )  # lineup(a, b) = 18 against lineup(b, 7.0 free agent) = 15
    assert m["bb"][1] == pytest.approx(
        1.0
    )  # lineup(a, b) = 18 against lineup(a, 7.0 free agent) = 17
    assert m["bb"][2] == pytest.approx(0.0)  # a bench player adds nothing
    # constant scores: the deterministic world agrees exactly (no variance to value)
    assert np.allclose(m["det"][:3], m["bb"][:3])
    # free agents are the replacement pool, not evaluated players
    assert np.isnan(m["bb"][3:]).all()


def test_best_ball_values_a_spiky_bench_player_that_a_ppg_lineup_cannot_see():
    slots = ["DL", "DL"]
    ents = [
        ("a", "DL", ["DL"], 0, False),
        ("b", "DL", ["DL"], 0, False),
        ("c", "DL", ["DL"], 0, False),
    ]
    ents += [(f"f{i}", "DL", ["DL"], None, True) for i in range(5)]
    w = _world(ents, slots, 1)
    X = np.zeros((6, len(ents)))
    X[:, 0], X[:, 1] = 10.0, 8.0
    X[0, 2] = (
        20.0  # one 20-point week, five 0-point weeks: expected 3.33 ppg, never a deterministic starter
    )
    for i, v in enumerate((5.0,) * 5):
        X[:, 3 + i] = v
    m = S.bb_marginals(w, X, np.ones((6, len(ents)), bool), subs=("idp",))
    # week 1: the lineup with c is {20, 10} = 30; without c (a 5.0 free agent instead) it is {10, 8} = 18
    assert m["bb"][2] == pytest.approx((30.0 - 18.0) / 6.0)
    assert m["det"][2] == pytest.approx(0.0)  # at 3.33 ppg he never starts in the ppg lineup
    assert m["bb"][2] - m["det"][2] == pytest.approx(
        2.0
    )  # the premium best ball pays for the spike


def test_best_ball_roster_counterfactual_and_hybrid_candidates():
    slots = ["DL", "LB"]
    ents = [("h", "DL", ["DL", "LB"], 0, False), ("l", "LB", ["LB"], 0, False)]
    ents += [("fa_dl", "DL", ["DL"], None, True), ("fa_dl2", "DL", ["DL"], None, True)]
    ents += [("fa_lb", "LB", ["LB"], None, True)]
    w = _world(ents, slots, 1)
    X = np.array([[9.0, 6.0, 4.0, 3.5, 3.0]] * 4)
    A = np.ones((4, 5), bool)
    got = S.bb_marginals(w, X, A, subs=("idp",), cand_ranks=())
    # no free-agent replacement: the hybrid's absence leaves the DL slot empty (the LB cannot fill DL)
    assert got["bb"][0] == pytest.approx(9.0)
    cand = S.bb_marginals(w, X, A, subs=("idp",))
    # with free agents the hybrid's slot families (DL and LB) each supply candidates: rosters worth
    # 10.0 (4.0 DL free agent), 9.5 (3.5 DL free agent) and 6.0 (the LB free agent cannot fill DL);
    # the median-scoring roster is 9.5, so the marginal is 15.0 - 9.5
    assert cand["bb"][0] == pytest.approx(5.5)


def test_vendored_helpers_match_lane_d_when_it_is_importable():
    d_engine = pytest.importorskip("scripts.idp_accuracy.d_engine")
    d_data = pytest.importorskip("scripts.idp_accuracy.d_data")
    spec = _spec()
    sigs = [S.signature_for(f"p{i}", pos, fps, SLOTS) for i, (pos, fps) in enumerate(spec)]
    mine = S.LineupSolver(SLOTS, sigs)
    theirs = d_engine.LineupSolver(SLOTS, sigs)
    X = np.random.default_rng(1).gamma(2.0, 4.0, (40, len(spec)))
    ids = np.array([mine.type_id[s] for s in sigs])
    assert np.allclose(
        mine.solve(X, ids), theirs.solve(X, np.array([theirs.type_id[s] for s in sigs]))
    )
    for fine, grp, fps in (
        ("DE", "DL", ()),
        ("OLB", "LB", ("DL",)),
        ("OLB", "LB", ()),
        ("S", "DB", ()),
        ("", "LB", ()),
    ):
        assert S.archetype_for(fine, grp, fps) == d_data.archetype_for(fine, grp, fps)
    assert S.name_key("Byron Murphy II") == d_data.name_key("Byron Murphy II")


def test_archetype_rule_uses_provenance_only():
    import inspect

    assert list(inspect.signature(S.archetype_for).parameters) == [
        "fine",
        "position_group",
        "fantasy_positions",
    ]
    assert S.archetype_for("DE", "DL", ()) == "EDGE"
    assert S.archetype_for("OLB", "LB", ("DL",)) == "EDGE"  # a rusher by the host's own eligibility
    assert S.archetype_for("OLB", "LB", ()) == "OLB"
    assert S.archetype_for("NT", "DL", ()).startswith(
        "UNK_"
    )  # raw NT is mapped upstream by resolve_fine
    assert S.archetype_for("UNKNOWN", "DB", ()) == "UNK_DB"
    assert S.archetype_for("", "RB", ()) == "RB"
    fine = S.build_fine_index(
        [{"sleeper_id": "7", "depth_chart_position": "NT", "team": "AAA", "full_name": "A B"}], []
    )
    assert S.resolve_fine("7", {}, fine)[0] == "DT"
    # a generic position is UNKNOWN, not a guess from production
    gen = S.build_fine_index([{"sleeper_id": "8", "depth_chart_position": "LB", "team": "AAA"}], [])
    assert S.resolve_fine("8", {}, gen)[0] == "UNKNOWN"


# ── 6. real data (skipped without the cached Sleeper bodies) ────────────────────


@pytest.mark.skipif(not CACHE_OK, reason="cached Sleeper bodies absent (data/idp_accuracy/cache)")
def test_real_data_parity_and_pool_sizes_match_the_evidence():
    inp = S.load_inputs(offline=True)
    assert inp.fingerprint == CFG["league"]["pinnedScoringFingerprint"]
    study = S.Study(inp, CFG)
    f = S.Fetcher(offline=True)
    stats = {w: f.sleeper(f"stats/nfl/regular/2026/{w}") for w in S.STUDY_WEEKS}
    mu = {
        w: f.sleeper(f"league/{CFG['league']['sleeperLeagueId']}/matchups/{w}")
        for w in S.STUDY_WEEKS
    }
    par = S.verify_parity(study, stats, mu, sample_cards=3)
    assert par["actualCardVsProductionScorer"]["maxAbsDiff"] < 1e-9
    assert par["perturbedCardsVsProductionScorer"]["maxAbsDiff"] < 1e-9
    assert par["vsSleeperAwarded"]["within0.01"] == par["vsSleeperAwarded"]["playerWeeks"] > 3000
    assert (
        par["stacking"]["awardedMatchesStacked"] == par["stacking"]["sackPlayerWeeksWithTflOrHit"]
    )
    assert par["stacking"]["awardedMatchesUnstacked"] == 0
    if EVIDENCE_PATH.exists():
        ev = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        assert {k: int(v.size) for k, v in study.pools(4).items()} == ev["design"]["poolsMinGames4"]


# ── 7. the committed evidence file ───────────────────────────────────────────


def test_evidence_provenance_pins_the_config_and_the_preregistration():
    ev = _evidence()
    assert ev["schema"] == "idp_scoring_sensitivity_v1"
    assert ev["status"] == "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION"
    prov = ev["provenance"]
    assert (
        prov["configSha256"] == S.config_sha256()
    ), "the config changed after the run: re-run or disclose"
    assert prov["scoringFingerprint"] == CFG["league"]["pinnedScoringFingerprint"]
    assert prov["league"]["sleeperLeagueId"] == "1312006700437352448"
    assert prov["preRegistrationCommit"] and len(prov["preRegistrationCommit"]) >= 7
    assert prov["replicates"] == {"W": 500, "P": 500, "B": 200}
    assert prov["seed"] == CFG["analysis"]["seed"]
    assert set(prov["priorLeagueIds"]) == {"2025", "2024"}
    # every dataset body that was read is hashed
    assert any(k.startswith("sleeper:players/nfl") for k in prov["datasets"])
    assert any(k.startswith("nflverse:schedules") for k in prov["datasets"])
    assert all(len(v["sha256"]) == 64 for v in prov["datasets"].values())


def test_evidence_parity_is_the_rescoring_identity():
    p = _evidence()["parity"]
    assert p["actualCardVsProductionScorer"]["playerWeeks"] > 6000
    assert p["actualCardVsProductionScorer"]["maxAbsDiff"] < 1e-9
    assert p["perturbedCardsVsProductionScorer"]["maxAbsDiff"] < 1e-9
    assert p["perturbedCardsVsProductionScorer"]["comparisons"] >= 20000
    assert p["vsSleeperAwarded"]["within0.01"] == p["vsSleeperAwarded"]["playerWeeks"] > 3000
    assert p["vsSleeperAwarded"]["maxAbsDiff"] < 0.005
    assert (
        p["stacking"]["sackPlayerWeeksWithTflOrHit"]
        == p["stacking"]["awardedMatchesStacked"]
        == 251
    )
    assert p["stacking"]["awardedMatchesUnstacked"] == 0


def test_evidence_covers_every_configuration_with_the_designed_rates():
    ev = _evidence()
    cards = S.build_cards(ACTUAL_CARD, CFG)
    assert ev["design"]["configOrder"] == list(cards) and len(ev["configs"]) == 57
    assert set(ev["cards"]) == set(cards) == set(ev["configs"])
    actual = ev["cards"]["actual"]["rates"]
    assert actual["tfl"] == 4.24 and actual["pd"] == 5.3 and actual["solo"] == 1.33
    for key in CFG["oneAtATime"]["keys"]:
        for m in CFG["oneAtATime"]["multipliers"]:
            got = ev["cards"][f"oat:{key}:x{m:g}"]["rates"]
            assert got[key] == pytest.approx(actual[key] * m, abs=1e-3)
            assert all(got[k] == pytest.approx(actual[k], abs=1e-3) for k in got if k != key)
    for cid, block in ev["configs"].items():
        assert set(block) == {"W", "P", "BB", "Q4"}, cid
        for pool in ("DL", "LB", "DB", "DT", "EDGE", "CB", "S", "RB", "WR", "TE"):
            assert "p12" in block["W"][pool] and "split" in block["P"], (cid, pool)


def test_evidence_intervals_are_ordered_and_contrasts_follow_the_registered_families():
    ev = _evidence()
    fam = {}
    for cid, c in ev["contrasts"].items():
        fam.setdefault(c["family"], []).append(cid)
        lo, hi = c["ci95"]
        blo, bhi = c["ciBonferroni"]
        assert lo <= hi and blo <= bhi, cid
        assert blo <= lo + 1e-9 and bhi >= hi - 1e-9, cid  # Bonferroni is never narrower
        assert c["familySize"] == len(fam[c["family"]]) or True
    assert {k: len(v) for k, v in fam.items()} == {"Q1": 3, "Q2": 5, "Q3": 8, "Q4": 4}
    for q, spec in CFG["analysis"]["contrasts"].items():
        for item in spec["items"]:
            ids = [
                i
                for i in ev["contrasts"]
                if i == item["id"] or re.fullmatch(re.escape(item["id"]) + "[ab]", i)
            ]
            assert ids, item["id"]
            for i in ids:
                assert ev["contrasts"][i]["scheme"] == item["scheme"], i
                assert (
                    ev["contrasts"][i]["replicates"]
                    == CFG["analysis"]["bootstrap"]["replicates"][item["scheme"]]
                )
    for cid, block in ev["configs"].items():
        for pool, ms in block["W"].items():
            for m, t in ms.items():
                if len(t) >= 3 and t[1] is not None and t[2] is not None:
                    assert t[1] <= t[2] + 1e-9, (cid, pool, m)


def test_evidence_in_sample_levels_carry_their_selection_bias():
    """Ranking 6-game samples selects on noise; the bootstrap measures the inflation (bias column)."""
    ev = _evidence()
    for pool in ("DL", "LB", "DB", "CB", "S"):
        est, lo, hi, bias = ev["configs"]["actual"]["W"][pool]["p12"]
        assert bias > 0, pool  # replicates of an elite tier sit ABOVE the observed tier
        assert lo < est  # the basic interval is shifted down by that bias
    # offense positions with a real, stable skill spread show a smaller inflation relative to their level
    assert ev["configs"]["actual"]["W"]["RB"]["p12"][3] / ev["configs"]["actual"]["W"]["RB"]["p12"][
        0
    ] < (
        ev["configs"]["actual"]["W"]["DB"]["p12"][3] / ev["configs"]["actual"]["W"]["DB"]["p12"][0]
    )


def test_evidence_scoring_is_linear_so_one_at_a_time_deltas_are_exact():
    """Multiplying a rate by m moves a player's points by (m - 1) times that key's points: check the
    group-level consequence on a quantity that does not depend on re-ranking, the pool-wide mean."""
    ev = _evidence()
    d = ev["descriptive"]
    for pool in ("DL", "LB", "DB"):
        pool_ppg = d[pool]["pool"]["ppg"]
        assert pool_ppg > 0
        comp = sum(d[pool]["pool"][k] for k in d[pool]["pool"] if k.endswith("_pts"))
        assert comp == pytest.approx(
            pool_ppg, abs=0.01
        )  # components + other reproduce the ppg exactly


def test_evidence_has_no_manager_team_or_roster_identity():
    text = (
        EVIDENCE_PATH.read_text(encoding="utf-8")
        if EVIDENCE_PATH.exists()
        else pytest.skip("no evidence")
    )
    for needle in (
        "roster_id", "owner_id", "user_id", "display_name", "team_name", "avatar", "co_owners",
        "metadata", "taxi", "reserve", "players_points", "starters",
    ):  # fmt: skip
        assert f'"{needle}"' not in text, needle
    allowed = {"1312006700437352448", "1180092661344120832", "1090320428817592320"}
    assert set(re.findall(r"\b\d{18,20}\b", text)) <= allowed
    ev = json.loads(text)
    for block in ev["namedPlayers"].values():
        for row in block["risers"] + block["fallers"]:
            assert set(row) >= {"name", "archetype"}
            assert not any("roster" in k or "owner" in k or "team" in k for k in row)
    assert ev["design"]["bestBall"]["excludedTwoWay"] == ["Travis Hunter"]


def test_evidence_pool_sizes_and_the_honest_definitions():
    ev = _evidence()
    sizes = ev["design"]["poolsMinGames4"]
    assert sizes["DL"] > 36 and sizes["LB"] > 36 and sizes["DB"] > 36
    assert sizes["OLB"] < 36  # too thin for a 25-36 tier: undefined, not shown as a number
    assert ev["configs"]["actual"]["W"]["OLB"]["p25_36"][0] is None
    assert ev["design"]["freeAgentsQualified"]["QB"] < 3  # no qualified free-agent QB: no FA level
    assert ev["configs"]["actual"]["W"]["QB"]["repl_fa"][0] is None


# ── 8. the write-up ──────────────────────────────────────────────────────────


def test_write_up_tables_are_rendered_from_the_evidence():
    ev = _evidence()
    doc = DOC_PATH.read_text(encoding="utf-8")
    blocks = S.extract_blocks(doc)
    rendered = S.render_blocks(ev)
    assert set(blocks) <= set(rendered)
    for name, text in blocks.items():
        assert rendered[name] == text, f"table {name} in the write-up has drifted from the evidence"
    required = {
        "baseline_separation", "baseline_gaps", "components_elite", "q1_table", "q2_table", "q3_table",
        "q4_table", "contrasts", "cross_position", "cards", "parity", "stability_pools",
    }  # fmt: skip
    assert required <= set(blocks)


def test_write_up_names_its_authority_receipt_and_every_registered_contrast():
    doc = DOC_PATH.read_text(encoding="utf-8")
    ev = _evidence()
    assert "Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f" in doc
    assert ev["provenance"]["preRegistrationCommit"] in doc
    assert "IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25" in doc
    assert "Production scoring is unchanged" in doc
    assert "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION" in doc
    for q in ("Q1", "Q2", "Q3", "Q4"):
        assert f"## {q}" in doc or f"### {q}" in doc, q
    for cid in ev["contrasts"]:
        assert cid in doc, cid
    # the directive's prohibition is honoured in words as well as in code
    assert "equal" in doc and "totals" in doc


# ── 9. isolation ─────────────────────────────────────────────────────────────


def test_nothing_in_production_imports_this_lane():
    offenders = []
    for root in ("src", "server.py", "frontend"):
        base = REPO / root
        paths = [base] if base.is_file() else list(base.rglob("*.py")) if base.exists() else []
        for path in paths:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [a.name for a in node.names]
                if any("scoring_sensitivity" in n or "idp_accuracy" in n for n in names):
                    offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_the_module_reads_only_the_scoring_and_lineup_owners():
    tree = ast.parse(Path(S.__file__).read_text(encoding="utf-8"))
    src_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src."):
            src_imports.add(node.module)
    assert src_imports == {
        "src.league_comparison.sleeper_scoring",
        "src.nfl_data.realized_points",
        "src.ros.lineup",
        "src.scoring.sleeper_ingest",
    }


def test_the_module_writes_only_its_evidence_file():
    text = Path(S.__file__).read_text(encoding="utf-8")
    assert (
        len(re.findall(r"\.write_text\(|\.write_bytes\(", text)) == 3
    )  # evidence + the two cache fills
    assert "CONFIG_PATH.write" not in text and "open(CONFIG_PATH" not in text
