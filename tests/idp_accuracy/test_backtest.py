"""Lane G backtest (``scripts/idp_accuracy/backtest.py``): shadow, research only.

Everything here runs on SYNTHETIC data or committed artifacts.  No 2026 outcome is read:
the statistics are pure functions of arrays, and the blind-stage guard is tested by
trying (and failing) to read an outcome URL.
"""

from __future__ import annotations

import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from scripts.idp_accuracy import backtest as bt
from src.league_valuation.replacement_shadow import LineupPlayer

REPO = Path(__file__).resolve().parents[2]


# ── the exact solver behind the port ─────────────────────────────────────────


def _random_players(rng: random.Random, n: int) -> list[LineupPlayer]:
    shapes = [
        ("QB", ()),
        ("RB", ()),
        ("WR", ()),
        ("TE", ()),
        ("K", ()),
        ("DL", ("DL", "LB")),
        ("DL", ()),
        ("LB", ("LB", "DL")),
        ("LB", ()),
        ("DB", ()),
    ]
    out = []
    for i in range(n):
        pos, fps = rng.choice(shapes)
        out.append(LineupPlayer(f"p{i:03d}", pos, fps, rng.uniform(-3, 28)))
    return out


SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K",
         "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB"]  # fmt: skip


def test_cached_eligibility_gives_the_owners_own_assignment_byte_for_byte():
    port = bt.SolverPort()
    rng = random.Random(4)
    for _ in range(60):
        players = _random_players(rng, rng.randint(15, 58))
        assert port.solve(players, SLOTS) == port.solve_uncached(players, SLOTS)


def test_port_total_equals_the_owners_total_on_a_full_roster():
    port = bt.SolverPort()
    players = _random_players(random.Random(11), 58)
    assignment = port.solve(players, SLOTS)
    pts = {p.player_id: p.points for p in players}
    total = sum(pts[pid] for pid in assignment.values())
    assert total == pytest.approx(
        sum(pts[pid] for pid in port.solve_uncached(players, SLOTS).values())
    )
    assert len(assignment) == len(SLOTS)  # a 58-man roster fills every slot


# ── the blind-stage guard ─────────────────────────────────────────────────────

L = bt.LEAGUE_ID


def _seed(f: bt.Fetcher, url: str, body: object) -> None:
    f._path(url).write_text(json.dumps(body), encoding="utf-8")


def test_blind_fetcher_refuses_every_outcome_url_even_when_cached(tmp_path):
    f = bt.Fetcher(tmp_path, blind=True, offline=True)
    for url in (
        f"{bt.SLEEPER}/stats/nfl/regular/2026/1",
        f"{bt.SLEEPER}/stats/nfl/regular/2026/6",
        f"{bt.SLEEPER}/league/{L}/matchups/3",
    ):
        _seed(f, url, {"x": 1})
        with pytest.raises(bt.OutcomeGuardError):
            f.get(url)


def test_blind_fetcher_allows_history_and_league_reads(tmp_path):
    f = bt.Fetcher(tmp_path, blind=True, offline=True)
    for url in (f"{bt.SLEEPER}/stats/nfl/regular/2025/18", f"{bt.SLEEPER}/league/{L}"):
        _seed(f, url, {"ok": True})
        assert f.get(url) == {"ok": True}


def test_unblind_fetcher_reads_outcomes_and_offline_never_fetches(tmp_path):
    f = bt.Fetcher(tmp_path, blind=False, offline=True)
    url = f"{bt.SLEEPER}/stats/nfl/regular/2026/1"
    with pytest.raises(RuntimeError):
        f.get(url)  # not cached and offline: refuses to fetch
    _seed(f, url, {"1": {"gp": 1}})
    assert f.get(url) == {"1": {"gp": 1}}


def test_stage1_source_never_names_an_outcome_reader():
    prefix = (
        Path(bt.__file__).read_text(encoding="utf-8").split("# ── STAGE 2" + ": unblind, once")[0]
    )
    assert "load_outcomes(" not in prefix.replace("def load_outcomes", "")
    assert "blind=False" not in prefix
    assert bt.stage1_code_hash() == bt.stage1_code_hash()


# ── time: kickoff and cutoff ──────────────────────────────────────────────────


def test_kickoff_converts_eastern_to_utc_across_the_dst_boundary(tmp_path):
    csv_path = tmp_path / "games.csv"
    csv_path.write_text(
        "game_id,season,game_type,week,gameday,gametime,home_team,away_team\n"
        "g1,2026,REG,1,2026-09-09,20:20,SEA,NE\n"
        "g2,2026,REG,1,2026-09-10,20:35,LA,SF\n"
        "g3,2026,REG,12,2026-11-26,13:00,DET,CHI\n"
        "g4,2026,POST,1,2026-01-01,13:00,AAA,BBB\n",
        encoding="utf-8",
    )
    assert bt.kickoff_utc(2026, 1, csv_path)["kickoffUtc"] == "2026-09-10T00:20:00+00:00"
    # after the November change to standard time the offset is five hours
    assert bt.kickoff_utc(2026, 12, csv_path)["kickoffUtc"] == "2026-11-26T18:00:00+00:00"
    with pytest.raises(RuntimeError):
        bt.kickoff_utc(2026, 99, csv_path)


def test_archive_selection_is_strictly_before_the_kickoff():
    k = datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)
    sel = bt.select_archive(k)
    assert sel["name"] == "dynasty_export_20260909_211525.zip"
    assert sel["g"] < k
    assert all(bt.archive_generation(REPO / "exports/archive" / n)["g"] >= k for n in sel["later"])
    # a kickoff exactly at an archive's generation instant excludes that archive (strict)
    just_at = sel["g"]
    assert bt.select_archive(just_at)["g"] < just_at


# ── preregistration freeze ───────────────────────────────────────────────────


def _has_prereg_history() -> bool:
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{bt.PREREG_COMMIT}^{{commit}}"], cwd=REPO, capture_output=True
    )
    return r.returncode == 0


@pytest.mark.skipif(not _has_prereg_history(), reason="shallow checkout without the prereg commit")
def test_the_preregistration_blob_is_unchanged_since_its_first_commit():
    info = bt.check_preregistration()
    assert info["blob"] == bt.PREREG_BLOB and info["firstCommit"] == bt.PREREG_COMMIT


# ── statistics ────────────────────────────────────────────────────────────────


def test_spearman_uses_midranks_and_is_nan_for_a_constant():
    assert bt.spearman(np.array([1, 2, 3, 4.0]), np.array([10, 20, 30, 40.0])) == pytest.approx(1.0)
    assert bt.spearman(np.array([1, 2, 3, 4.0]), np.array([4, 3, 2, 1.0])) == pytest.approx(-1.0)
    tied = bt.spearman(np.array([1, 1, 2, 2.0]), np.array([1, 2, 3, 4.0]))
    assert tied == pytest.approx(0.8944271909999159)  # pearson on midranks 1.5,1.5,3.5,3.5
    assert np.isnan(bt.spearman(np.array([5, 5, 5.0]), np.array([1, 2, 3.0])))


def test_lexicographic_order_key_breaks_ties_in_the_first_component_only():
    dv = [10.0, 10.0, 5.0, 10.0]
    vg = [2.0, 1.0, 9.0, 2.0]
    key = bt.lex_rank_scores(dv, vg)
    assert key[2] < key[1] < key[0]  # (5,9) < (10,1) < (10,2)
    assert key[0] == key[3]  # identical pairs stay tied


def test_two_sided_p_matches_the_preregistered_formula_and_its_floor():
    assert bt.two_sided_p(np.full(2000, 1.0)) == pytest.approx(2 / 2001)  # smallest attainable
    assert bt.two_sided_p(np.full(2000, -1.0)) == pytest.approx(2 / 2001)
    half = np.concatenate([np.full(1000, 1.0), np.full(1000, -1.0)])
    assert bt.two_sided_p(half) == 1.0
    ties = np.zeros(2000)
    assert bt.two_sided_p(ties) == 1.0


def test_holm_step_down_and_adjusted_p():
    p = {"a": 0.001, "b": 0.01, "c": 0.04, "d": 0.5}
    out = bt.holm(p)
    assert out["a"]["reject"] and out["b"]["reject"]  # 0.001 <= .05/4; 0.01 <= .05/3
    assert not out["c"]["reject"]  # 0.04 > .05/2
    assert out["a"]["adjusted"] == pytest.approx(0.004)
    assert out["b"]["adjusted"] == pytest.approx(0.03)
    assert out["c"]["adjusted"] == pytest.approx(0.08)
    assert out["d"]["adjusted"] == pytest.approx(0.5)
    # once a hypothesis is not rejected, no later one is, whatever its p
    out2 = bt.holm({"x": 0.03, "y": 0.031, "z": 0.0001})
    assert out2["z"]["reject"] and not out2["x"]["reject"] and not out2["y"]["reject"]
    # a single hypothesis is tested at alpha
    assert bt.holm({"only": 0.049})["only"]["reject"]


def test_wilson_interval_is_sensible():
    lo, hi = bt.wilson(50, 100)
    assert lo < 0.5 < hi and 0.39 < lo < 0.41 and 0.59 < hi < 0.61
    assert np.isnan(bt.wilson(0, 0)[0])


def test_cross_pair_concordance_and_level_diagnostic_by_hand():
    # offense 10, 4; defenders 8, 6.  Realized offense 9, 3; defenders 7, 5.
    # Realized order: O1 > D1 > D2 > O2?  O1(9) > D1(7) > D2(5) > O2(3).
    st = bt.cross_pair_stats(
        np.array([10.0, 4.0]), np.array([8.0, 6.0]), np.array([9.0, 3.0]), np.array([7.0, 5.0])
    )
    # pairs (O1,D1) (O1,D2) (O2,D1) (O2,D2); candidate orders O1>D1, O1>D2, O2<D1, O2<D2.
    # realized: O1>D1, O1>D2, O2<D1, O2<D2 -> all four concordant
    assert st["cc"] == 1.0 and st["pairs"] == 4 and st["wrong"] == 0
    # now the candidate overrates defenders: every defender above every offense player
    st2 = bt.cross_pair_stats(
        np.array([1.0, 2.0]), np.array([8.0, 6.0]), np.array([9.0, 3.0]), np.array([7.0, 5.0])
    )
    # realized has O1 above both defenders: 2 pairs wrong (candidate says IDP > O1);
    # O2 below both defenders: 2 pairs right
    assert st2["cc"] == pytest.approx(0.5) and st2["wrong"] == 2
    assert st2["idpOverShare"] == 1.0
    # ties in the candidate score half a point; ties in the outcome are not pairs at all
    st3 = bt.cross_pair_stats(
        np.array([5.0]), np.array([5.0, 5.0]), np.array([1.0]), np.array([1.0, 2.0])
    )
    assert st3["pairs"] == 1 and st3["cc"] == 0.5


def test_realized_elite_set_includes_everyone_tied_at_the_boundary():
    y = np.array([5.0, 4.0, 4.0, 4.0, 1.0])
    assert sorted(bt.realized_top_k(y, 2).tolist()) == [0, 1, 2, 3]
    assert sorted(bt.realized_top_k(np.array([3.0, 2.0]), 5).tolist()) == [0, 1]


def test_predicted_elite_ties_break_by_champion_then_id():
    score = np.array([1.0, 1.0, 1.0, 0.0])
    tiebreak = np.array([10.0, 30.0, 20.0, 99.0])
    id_order = np.array([2, 1, 0, 3])
    assert bt.top_k_rows(score, tiebreak, id_order, 2).tolist() == [1, 2]
    tie2 = bt.top_k_rows(score, np.array([5.0, 5.0, 5.0, 5.0]), id_order, 2).tolist()
    assert tie2 == [2, 1]  # equal champion value: lower id first
    p = bt.precision_at_k(
        np.array([3.0, 2.0, 1.0]), np.array([9.0, 8.0, 0.0]), tiebreak[:3], id_order[:3], 2
    )
    assert p == 1.0


def test_bootstrap_draw_order_is_the_preregistered_one():
    n = {"QB": 5, "RB": 6, "WR": 7, "TE": 4, "DL": 5, "LB": 4, "DB": 6}
    sels = bt.draw_bootstrap_selections(n, b=3)
    rng = np.random.Generator(np.random.PCG64(20261026))
    for b in range(3):
        for p in bt.POSITIONS:
            expect = rng.integers(0, n[p], n[p])
            assert sels[b][p].tolist() == expect.tolist(), (b, p)
    assert bt.BOOT_B == 2000 and bt.BOOT_SEED == 20261026


# ── a planted effect: the machinery finds it, and finds nothing where there is none ──


def _synthetic(seed: int, *, n_per=40, good_noise=0.35, champ_noise=1.2, idp_shift=0.0):
    rng = np.random.default_rng(seed)
    ids, pos, y, champ, good, same = [], [], [], [], [], []
    k = 0
    for p in bt.POSITIONS:
        for _ in range(n_per):
            latent = rng.normal()
            level = idp_shift if p in bt.IDP else 0.0
            ids.append(f"{1000 + k}")
            k += 1
            pos.append(p)
            y.append(latent + 0.3 * rng.normal() + level)
            champ.append(latent + champ_noise * rng.normal() + level)
            good.append(latent + good_noise * rng.normal() + level)
            same.append(champ[-1])
    scores = {"champion": champ, "A": good, "C": same, "R0": good}
    return bt.Cohort(ids, pos, y, scores)


def test_a_better_candidate_is_detected_and_an_identical_one_is_exactly_zero():
    data = _synthetic(1)
    qual = data.qualifying()
    assert len(qual) == 7
    s = bt.point_summary(data, ["A", "C"], qual)
    assert s["deltas"]["delta1"]["A"] > 0.1
    assert s["deltas"]["delta1"]["C"] == 0.0  # C is the champion's own score
    assert s["deltas"]["delta2"]["C"] == 0.0
    boot = bt.bootstrap_deltas(data, ["A", "C"], qual, b=120)
    assert (boot["delta1"]["A"] > 0).mean() > 0.97
    assert np.all(boot["delta1"]["C"] == 0.0)


def test_a_candidate_with_a_cross_position_level_bias_loses_on_concordance_only():
    n = 40
    rng = np.random.default_rng(5)
    ids, pos, y, champ, biased = [], [], [], [], []
    k = 0
    for p in bt.POSITIONS:
        for _ in range(n):
            latent = rng.normal()
            ids.append(f"{2000 + k}")
            k += 1
            pos.append(p)
            y.append(latent)
            champ.append(latent + 0.2 * rng.normal())
            # same within-position order as the champion, but every defender priced 3 sd too high
            biased.append(champ[-1] + (3.0 if p in bt.IDP else 0.0))
    data = bt.Cohort(ids, pos, y, {"champion": champ, "A": biased})
    s = bt.point_summary(data, ["A"], data.qualifying())
    assert s["deltas"]["delta1"]["A"] == pytest.approx(0.0, abs=1e-12)  # within order untouched
    assert s["deltas"]["delta2"]["A"] < -0.2  # cross concordance collapses
    assert s["deltas"]["over"]["A"] > 0.95  # nearly every wrong pair overrates the defender


def test_empty_or_tiny_positions_are_not_pooled():
    data = _synthetic(2, n_per=10)
    assert data.qualifying() == []
    assert data.qualifying(5) == list(bt.POSITIONS)


# ── the verdict rules (section 8.2), one branch at a time ───────────────────────

QUAL = ["QB", "RB", "WR", "TE", "DL", "LB", "DB"]


def _point(delta1=0.08, delta2=0.0, rho=0.05, **per_position):
    return {
        "delta1": {"A": delta1},
        "delta2": {"A": delta2},
        "rho": {"A": {p: per_position.get(p, rho) for p in QUAL}},
    }


def _fam(reject1=True, reject2=False, f2_reject=()):
    h = lambda r: {"p": 0.001, "adjusted": 0.002, "reject": r, "m": 2, "rank": 1}  # noqa: E731
    return {
        "F1": {"delta1|A": h(reject1), "delta2|A": h(reject2)},
        "F2": {f"rho|A|{p}": h(p in f2_reject) for p in QUAL},
    }


def test_verdict_advance_retrospective_needs_all_five_conditions():
    v = bt.axis_verdict(
        "within", "A", _point(), _fam(), QUAL, {"S1": True, "S2": True}, tested=True
    )
    assert v["verdict"] == "advance_retrospective"


@pytest.mark.parametrize(
    "point,fam,signs,expected",
    [
        (_point(0.08), _fam(reject1=False), {}, "no_detectable_difference"),
        (_point(-0.08), _fam(), {}, "champion_better"),
        (_point(0.03), _fam(), {}, "below_meaningful_effect"),
        (_point(0.08, delta2=-0.02), _fam(), {}, "advance_blocked_regression"),  # cross guard -0.01
        (_point(0.08, DB=-0.05), _fam(f2_reject=("DB",)), {}, "advance_blocked_regression"),
        # a significant POSITIVE position is never a regression
        (_point(0.08, DB=0.2), _fam(f2_reject=("DB",)), {}, "advance_retrospective"),
        (_point(0.08), _fam(), {"S3": False}, "advance_unstable"),
    ],
)
def test_verdict_branches(point, fam, signs, expected):
    assert (
        bt.axis_verdict("within", "A", point, fam, QUAL, signs, tested=True)["verdict"] == expected
    )


def test_a_large_loss_at_one_position_blocks_an_advance_even_when_not_significant():
    point = _point(0.08)
    point["rho"]["A"]["DB"] = -0.11  # below the -0.10 point floor
    v = bt.axis_verdict("within", "A", point, _fam(), QUAL, {}, tested=True)
    assert v["verdict"] == "advance_blocked_regression" and v["positionsBelowPointFloor"] == ["DB"]
    point["rho"]["A"]["DB"] = -0.09  # inside the floor: not a block
    assert (
        bt.axis_verdict("within", "A", point, _fam(), QUAL, {}, tested=True)["verdict"]
        == "advance_retrospective"
    )


def test_cross_axis_uses_its_own_threshold_and_the_within_guard():
    point = _point(delta1=-0.03, delta2=0.03)
    fam = _fam(reject1=False, reject2=True)
    v = bt.axis_verdict("cross", "A", point, fam, QUAL, {}, tested=True)
    assert v["verdict"] == "advance_blocked_regression"  # within delta -0.03 < the -0.02 guard
    point = _point(delta1=-0.01, delta2=0.03)
    assert (
        bt.axis_verdict("cross", "A", point, fam, QUAL, {}, tested=True)["verdict"]
        == "advance_retrospective"
    )
    below = _point(delta1=0.0, delta2=0.015)
    assert (
        bt.axis_verdict("cross", "A", below, fam, QUAL, {}, tested=True)["verdict"]
        == "below_meaningful_effect"
    )


def test_an_untested_axis_is_insufficient_sample_never_a_verdict():
    v = bt.axis_verdict("within", "A", _point(), _fam(), QUAL, {}, tested=False)
    assert v["verdict"] == "insufficient_sample:cohort_size"


def test_stability_signs_require_the_same_strict_sign_under_applicable_variants():
    point = {"delta1": {"A": 0.07, "C": 0.04}}
    variants = {
        "S1": {"delta1": {"A": 0.05, "C": -0.01}},
        "S2": {"delta1": {"A": 0.0}},
        "S3": {"state": "not_evaluable"},
    }
    applies = {"S1": ["A", "C"], "S2": ["A"], "S3": ["A"]}
    out = bt.stability_signs(["A", "C"], point, variants, applies, "delta1")
    assert out["A"] == {"S1": True, "S2": False}  # a zero is not the same sign
    assert out["C"] == {"S1": False}


# ── family sizes and cohort sufficiency (section 5, 7.5) ────────────────────────


def test_family_sizes_are_fixed_from_cohort_sizes_alone():
    n = {"QB": 40, "RB": 100, "WR": 150, "TE": 50, "DL": 80, "LB": 70, "DB": 90}
    fam, qual, within_ok, cross_ok = bt.family_sizes(n, 3)
    assert qual == list(bt.POSITIONS) and within_ok and cross_ok
    assert fam["F1"]["m"] == 6 and fam["F2"]["m"] == 21 and fam["F3"]["m"] == 6
    thin = {**n, "DL": 45, "LB": 10, "DB": 10}  # one IDP position qualifies; 65 IDP players
    fam2, qual2, within2, cross2 = bt.family_sizes(thin, 3)
    assert not within2 and cross2 and qual2 == ["QB", "RB", "WR", "TE", "DL"]
    assert fam2["F1"]["withinAxis"] == "insufficient_sample:cohort_size"
    assert fam2["F1"]["m"] == 3  # only the cross hypotheses are tested
    none = {p: 5 for p in bt.POSITIONS}
    fam3, _q, w3, c3 = bt.family_sizes(none, 3)
    assert not w3 and not c3 and fam3["F1"]["m"] == 0


# ── availability and the history-derived inputs ───────────────────────────────


def test_availability_inputs_use_only_admissible_games_and_report_unknown_schedules():
    info = {
        "1": {"position": "WR", "team": "KC"},
        "2": {"position": "WR", "team": "LAR"},  # Sleeper abbreviation for LA
        "3": {"position": "WR", "team": None},
    }
    universe = {"info": info}
    hist = {"1": {(2025, w): 10.0 for w in range(1, 18)}, "2": {(2025, 1): 5.0}}
    if not bt.GAMES_CSV.exists():
        pytest.skip("nflverse schedule cache not present")
    av = bt.availability_inputs(
        universe, hist, ["1", "2"], window=[(2025, w) for w in bt.HISTORY_WEEKS]
    )
    assert av["g"]["1"] == 17 and av["G"]["1"] == 17  # 17 games, one bye in 18 weeks
    assert av["G"]["2"] == 17  # LAR -> LA
    assert av["G"]["3"] is None  # no team: availability unknown, never a guess
    assert bt.availability_for(av, "3", 4.0) is None
    assert 0.0 <= bt.availability_for(av, "2", 4.0) <= 1.0


def test_c_scores_take_the_best_eligible_position_and_skip_undefined_levels():
    universe = {
        "info": {
            "a": {"fantasyPositions": ("DL", "LB")},
            "b": {"fantasyPositions": ("QB",)},
            "c": {"fantasyPositions": ("K",)},
        }
    }
    levels = {"DL": 12.0, "LB": 9.0, "QB": None}
    out, pi = bt.c_scores({"a": 15.0, "b": 20.0, "c": 8.0}, universe, levels)
    assert out == {"a": 6.0} and pi == {"a": "LB"}  # b: QB level undefined; c: no level at all


# ── D runs identically in one process and many ─────────────────────────────────


def test_parallel_d_equals_serial_d_exactly():
    from tests.league_valuation.test_cross_position import MU, POS, SLOTS as TOY_SLOTS, TEAMS

    rng = random.Random(8)
    own = {k: tuple(rng.uniform(-3, 3) for _ in range(7)) for k in MU}
    spec = {
        "mu": dict(MU),
        "availability": {k: 0.9 for k in MU},
        "own": {k: list(v) for k, v in own.items()},
        "pooled": {"QB": [0.0], "RB": [0.0], "WR": [0.0]},
        "stratum": dict(POS),
        "position": dict(POS),
        "fantasy_positions": {k: [] for k in MU},
        "teams": {k: list(v) for k, v in TEAMS.items()},
        "slots": list(TOY_SLOTS),
        "evaluate": sorted(MU),
        "sigma": True,
        "own_team_only": False,
        "seed": bt.SIM_SEED,
    }
    serial = bt.run_d(spec, weeks=24, workers=1)
    parallel = bt.run_d(spec, weeks=24, workers=2)
    assert dict(serial.value) == dict(parallel.value)
    assert dict(serial.mc_se) == dict(parallel.mc_se)


# ── the committed blind-stage artifacts, when present ──────────────────────────


def test_committed_stage1_artifacts_are_internally_consistent():
    if not bt.MANIFEST_PATH.exists():
        pytest.skip("stage 1 has not run in this checkout")
    manifest, scores = bt.load_stage1()  # raises if any hash disagrees
    assert manifest["promotes"] is False and scores["promotes"] is False
    assert manifest["outcomesLoaded"] is False and manifest["blind"] is True
    assert manifest["label"] == "retrospective_point_in_time"
    assert set(manifest["pins"]["seeds"]) >= {"bootstrap", "simulationD", "B"}
    assert manifest["pins"]["seeds"]["bootstrap"] == 20261026
    assert manifest["pins"]["preregistration"]["blob"] == bt.PREREG_BLOB
    bt.rs.assert_public_artifact(manifest, forbidden_values=[bt.LEAGUE_ID])
    bt.rs.assert_public_artifact(scores, forbidden_values=[bt.LEAGUE_ID])
    cohort = set(scores["cohort"])
    for name in ("champion", "A_dv", "C", "D"):
        assert cohort <= set(scores["vectors"][name]), name  # the cohort is the common support
    assert len(cohort) == manifest["cohort"]["size"]


def test_committed_f_evidence_shows_the_scope_value_multisets_do_not_move():
    path = bt.F_EVIDENCE_PATH
    if not path.exists():
        pytest.skip("stage 1 has not run in this checkout")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["promotes"] is False
    boards = [doc["w0Board"]]
    if doc["laneAPinnedBoard"].get("orders"):
        boards.append(doc["laneAPinnedBoard"])
    assert len(boards) >= 1
    for board in boards:
        assert board["orders"], "no utility order was tried"
        for name, per_cfg in board["orders"].items():
            for cfg in ("k1_full_quality", "bareQuantileMatchK1"):
                moved = per_cfg[cfg]["scopeValueMultisetUnchanged"]
                assert moved == {"OFFENSE": True, "IDP": True}, (name, cfg)
                after = per_cfg[cfg]["after"]
                assert after["idpTop12Mean"] == board["before"]["idpTop12Mean"], (name, cfg)
                assert after["offenseTop12Mean"] == board["before"]["offenseTop12Mean"], (name, cfg)
                assert after["idpInTop36"] == board["before"]["idpInTop36"], (name, cfg)
    for tag, hyp in doc["w0Board"]["hypotheticalLevelErrors"].items():
        # a level error built into the board is still there, unchanged, after the model
        assert hyp["afterBareQuantileMatchK1"] == hyp["before"], tag


def test_committed_stage1_names_no_team_manager_or_roster():
    if not bt.SCORES_PATH.exists():
        pytest.skip("stage 1 has not run in this checkout")
    text = bt.SCORES_PATH.read_text(encoding="utf-8") + bt.MANIFEST_PATH.read_text(encoding="utf-8")
    for needle in ("ownerId", "roster_id", "sleeperTeamName", "display_name", bt.LEAGUE_ID):
        assert needle not in text, needle
    rows = json.loads(bt.SCORES_PATH.read_text(encoding="utf-8"))["players"]
    assert all("team" not in r and "roster" not in {k.lower() for k in r} for r in rows)


def test_committed_result_is_labelled_and_never_promotes_when_present():
    if not bt.RESULT_PATH.exists():
        pytest.skip("stage 2 has not run in this checkout")
    res = json.loads(bt.RESULT_PATH.read_text(encoding="utf-8"))
    assert res["promotes"] is False
    if res.get("status") == "completed":
        assert res["label"] == "retrospective_point_in_time"
        bt.rs.assert_public_artifact(res, forbidden_values=[bt.LEAGUE_ID])
        for c, v in res["verdicts"].items():
            for axis in ("within", "cross"):
                assert v[axis]["verdict"] in {
                    "advance_retrospective", "advance_unstable", "advance_blocked_regression",
                    "below_meaningful_effect", "no_detectable_difference", "champion_better",
                    "insufficient_sample:cohort_size",
                }  # fmt: skip
