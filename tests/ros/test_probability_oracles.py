"""CW-49 -- independent oracles for the season probability engines.

Every expected number below is computed IN THIS FILE, by exhaustive
enumeration of game outcomes (or closed-form normal algebra), with the
playoff / draft-order rules written out from the documents
(``docs/picks/DRAFT_ORDER_RULE.md``: reverse regular-season record, ties
broken by LOWER points for; seeding: wins then HIGHER points for).  Nothing
here calls the production function that is being checked to obtain the
expectation, and no ``src`` ranking / tiebreak helper is imported.

Model design (so the oracle is exact, not approximate):

* A game between two teams of EQUAL mean and sd 1 is a fair coin flip
  (P = 0.5 by symmetry); a game between teams whose means differ by >> sd is
  decided for the higher mean (z >= 20).  So every game probability is one of
  {0, 0.5, 1} and the outcome space is enumerable.
* ``pf_to_date`` gaps are far larger than anything the remaining games can
  add, so the points-for tiebreak is decided by ``pf_to_date`` alone.

Monte Carlo comparison uses a fixed seed and a 4-sigma binomial tolerance.
"""

from __future__ import annotations

import itertools
import json
import math
import random
from types import SimpleNamespace
from unittest import mock

import pytest

from src.public_league import playoff_odds
from src.ros import playoff_sim

SIMS = 20000
OWNERS = ["aa", "bb", "cc", "dd"]


# --------------------------------------------------------------------------
# harness (builds inputs through the simulator's public entry point)
# --------------------------------------------------------------------------
def _snapshot(playoff_teams: int):
    season = SimpleNamespace(
        season="2026",
        league_id="L1",
        league={"settings": {"playoff_teams": playoff_teams, "playoff_week_start": 15}},
        rosters=[],
        matchups_by_week={},
        regular_season_weeks=[],
    )
    return SimpleNamespace(
        managers=SimpleNamespace(by_owner_id={}), current_season=season, seasons=[season]
    )


def _run(*, record, schedule, means, pf, playoff_teams=2, sims=SIMS, seed=11):
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=means[o], sd=1.0, pf_to_date=pf[o])
        for o in OWNERS
    }
    with (
        mock.patch.object(
            playoff_sim,
            "_current_standings",
            lambda *a, **k: (record, {"medianGame": False, "state": "not_applicable"}),
        ),
        mock.patch.object(playoff_sim, "_remaining_schedule", lambda *a, **k: schedule),
        mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: {}),
        mock.patch.object(playoff_sim, "_league_best_ball", lambda *a, **k: False),
        mock.patch.object(
            playoff_sim, "_build_team_distributions", lambda *a, **k: (dists, dict(pf))
        ),
        mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: {1, 2}),
        mock.patch(
            "src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: "dynasty_main"
        ),
    ):
        out = playoff_sim.simulate_playoff_odds(
            _snapshot(playoff_teams),
            n_simulations=sims,
            min_simulations=sims,
            max_simulations=sims,
            rng=random.Random(seed),
            reseed=True,
            playoff_seeds=playoff_teams,
            bye_seeds=0,
        )
    assert "unsimulable" not in out, out.get("unsimulable")
    out = json.loads(json.dumps(out))
    return out, {r["ownerId"]: r for r in out["playoffOdds"]}


# --------------------------------------------------------------------------
# independent oracle
# --------------------------------------------------------------------------
def _p_first_wins(means, a, b):
    """P(a beats b) under the {0, .5, 1} game design above."""
    if means[a] == means[b]:
        return 0.5
    return 1.0 if means[a] > means[b] else 0.0


def _enumerate(record, schedule, means):
    """Yield (probability, final_wins) for every joint outcome of the schedule."""
    games = [(a, b) for _w, a, b in schedule]
    for results in itertools.product((0, 1), repeat=len(games)):
        prob = 1.0
        wins = {o: float(record[o]["wins"]) for o in OWNERS}
        for (a, b), r in zip(games, results, strict=True):
            pa = _p_first_wins(means, a, b)
            prob *= pa if r == 1 else 1.0 - pa
            wins[a if r == 1 else b] += 1
        if prob > 0.0:
            yield prob, wins


def _seed_order(wins, pf):
    # Seeding: more wins first, then HIGHER points for.
    return sorted(OWNERS, key=lambda o: (-wins[o], -pf[o]))


def _draft_order(wins, pf):
    # docs/picks/DRAFT_ORDER_RULE.md: reverse record; tied records -> LOWER PF first.
    return sorted(OWNERS, key=lambda o: (wins[o], pf[o]))


def _tol(p, n=SIMS):
    # 4 sigma binomial standard error + rounding of the published 4dp value.
    return 4.0 * math.sqrt(max(p * (1 - p), 1e-12) / n) + 1e-4


def _round_robin(weeks):
    return [(w, OWNERS[i], OWNERS[j]) for w in weeks for i in range(4) for j in range(i + 1, 4)]


EQUAL = dict.fromkeys(OWNERS, 100.0)
PF = {"aa": 1000.0, "bb": 800.0, "cc": 600.0, "dd": 400.0}  # gaps >> remaining scoring
RECORD_LEVEL = {o: {"wins": 1, "losses": 1, "ties": 0} for o in OWNERS}


def _expected(record, schedule, means, pf, seats):
    playoff = dict.fromkeys(OWNERS, 0.0)
    champ = dict.fromkeys(OWNERS, 0.0)
    seed_dist = {o: [0.0] * 4 for o in OWNERS}
    draft_dist = {o: [0.0] * 4 for o in OWNERS}
    for prob, wins in _enumerate(record, schedule, means):
        order = _seed_order(wins, pf)
        for i, o in enumerate(order):
            seed_dist[o][i] += prob
            if i < seats:
                playoff[o] += prob
        for i, o in enumerate(_draft_order(wins, pf)):
            draft_dist[o][i] += prob
        if seats == 2:  # the final: seed 1 v seed 2
            s1, s2 = order[0], order[1]
            p1 = _p_first_wins(means, s1, s2)
            champ[s1] += prob * p1
            champ[s2] += prob * (1 - p1)
    return playoff, champ, seed_dist, draft_dist


# --------------------------------------------------------------------------
# 1. playoff / championship probabilities
# --------------------------------------------------------------------------
@pytest.mark.parametrize("weeks", [[1], [1, 2]])
def test_playoff_and_title_odds_match_exhaustive_enumeration(weeks):
    schedule = _round_robin(weeks)
    playoff, champ, seed_dist, _ = _expected(RECORD_LEVEL, schedule, EQUAL, PF, 2)
    _payload, rows = _run(record=RECORD_LEVEL, schedule=schedule, means=EQUAL, pf=PF)
    for o in OWNERS:
        assert rows[o]["playoffOdds"] == pytest.approx(playoff[o], abs=_tol(playoff[o])), o
        assert rows[o]["championshipOdds"] == pytest.approx(champ[o], abs=_tol(champ[o])), o
        for i in range(4):
            assert rows[o]["seedDistribution"][i] == pytest.approx(
                seed_dist[o][i], abs=_tol(seed_dist[o][i])
            ), (o, i)


def test_one_stronger_team_with_deterministic_games():
    # dd is far stronger: it wins every game it plays.  The others are coin flips.
    means = {"aa": 100.0, "bb": 100.0, "cc": 100.0, "dd": 140.0}
    schedule = _round_robin([1, 2])
    playoff, champ, _, _ = _expected(RECORD_LEVEL, schedule, means, PF, 2)
    _payload, rows = _run(record=RECORD_LEVEL, schedule=schedule, means=means, pf=PF)
    assert rows["dd"]["playoffOdds"] == pytest.approx(1.0, abs=1e-9)
    for o in OWNERS:
        assert rows[o]["playoffOdds"] == pytest.approx(playoff[o], abs=_tol(playoff[o])), o
        assert rows[o]["championshipOdds"] == pytest.approx(champ[o], abs=_tol(champ[o])), o


def test_probabilities_sum_to_the_number_of_seats_and_one_champion():
    schedule = _round_robin([1, 2])
    payload, rows = _run(record=RECORD_LEVEL, schedule=schedule, means=EQUAL, pf=PF)
    assert sum(r["playoffOdds"] for r in rows.values()) == pytest.approx(2.0, abs=1e-3)
    assert sum(r["championshipOdds"] for r in rows.values()) == pytest.approx(1.0, abs=1e-3)
    assert sum(r["missPlayoffsOdds"] for r in rows.values()) == pytest.approx(2.0, abs=1e-3)
    for r in rows.values():
        assert sum(r["seedDistribution"]) == pytest.approx(1.0, abs=1e-9)
    for i in range(4):
        assert sum(r["seedDistribution"][i] for r in rows.values()) == pytest.approx(1.0, abs=1e-9)
    assert payload["playoffSeeds"] == 2


def test_eliminated_is_exactly_zero_and_clinched_exactly_one():
    # One week left (aa-bb, cc-dd).  aa/bb are 6-0, cc/dd 0-6: cc and dd
    # cannot reach the top two by any outcome; aa and bb cannot miss it.
    record = {
        "aa": {"wins": 6, "losses": 0, "ties": 0},
        "bb": {"wins": 6, "losses": 0, "ties": 0},
        "cc": {"wins": 0, "losses": 6, "ties": 0},
        "dd": {"wins": 0, "losses": 6, "ties": 0},
    }
    schedule = [(7, "aa", "bb"), (7, "cc", "dd")]
    _payload, rows = _run(record=record, schedule=schedule, means=EQUAL, pf=PF)
    assert rows["cc"]["playoffOdds"] == 0.0 and rows["dd"]["playoffOdds"] == 0.0
    assert rows["aa"]["playoffOdds"] == 1.0 and rows["bb"]["playoffOdds"] == 1.0
    assert rows["cc"]["championshipOdds"] == 0.0 and rows["dd"]["championshipOdds"] == 0.0
    # The final is aa v bb, equal strength: 0.5 each.
    assert rows["aa"]["championshipOdds"] == pytest.approx(0.5, abs=_tol(0.5))


def test_finished_season_is_certainty_of_the_observed_table():
    record = {
        "aa": {"wins": 5, "losses": 2, "ties": 0},
        "bb": {"wins": 4, "losses": 3, "ties": 0},
        "cc": {"wins": 3, "losses": 4, "ties": 0},
        "dd": {"wins": 2, "losses": 5, "ties": 0},
    }
    _payload, rows = _run(record=record, schedule=[], means=EQUAL, pf=PF, sims=2000)
    assert [rows[o]["playoffOdds"] for o in OWNERS] == [1.0, 1.0, 0.0, 0.0]


def test_points_for_breaks_a_tie_on_wins_for_seeding():
    # bb and cc finish level on wins; higher PF (bb) takes the last seat.
    record = {
        "aa": {"wins": 9, "losses": 0, "ties": 0},
        "bb": {"wins": 4, "losses": 0, "ties": 0},
        "cc": {"wins": 4, "losses": 0, "ties": 0},
        "dd": {"wins": 0, "losses": 4, "ties": 0},
    }
    _payload, rows = _run(record=record, schedule=[], means=EQUAL, pf=PF, sims=2000)
    assert rows["bb"]["playoffOdds"] == 1.0
    assert rows["cc"]["playoffOdds"] == 0.0


# --------------------------------------------------------------------------
# 2. draft-slot distribution
# --------------------------------------------------------------------------
@pytest.mark.parametrize("weeks", [[1], [1, 2]])
def test_draft_slot_distribution_matches_enumeration(weeks):
    schedule = _round_robin(weeks)
    _, _, _, draft = _expected(RECORD_LEVEL, schedule, EQUAL, PF, 2)
    payload, rows = _run(record=RECORD_LEVEL, schedule=schedule, means=EQUAL, pf=PF)
    assert payload["draftOrderRule"] is not None
    for o in OWNERS:
        dist = rows[o]["draftSlotDistribution"]
        assert sum(dist) == pytest.approx(1.0, abs=1e-9)
        for i in range(4):
            assert dist[i] == pytest.approx(draft[o][i], abs=_tol(draft[o][i])), (o, i)
    for i in range(4):
        col = sum(rows[o]["draftSlotDistribution"][i] for o in OWNERS)
        assert col == pytest.approx(1.0, abs=1e-9), i


def test_draft_order_lower_points_for_picks_first_on_equal_records():
    # Season over, all 2-2: slot 0 goes to the LOWEST points-for.
    record = {o: {"wins": 2, "losses": 2, "ties": 0} for o in OWNERS}
    _payload, rows = _run(record=record, schedule=[], means=EQUAL, pf=PF, sims=2000)
    for slot, owner in enumerate(["dd", "cc", "bb", "aa"]):  # PF ascending
        assert rows[owner]["draftSlotDistribution"][slot] == 1.0


def test_draft_order_is_reverse_record_before_points_for():
    record = {
        "aa": {"wins": 0, "losses": 4, "ties": 0},  # worst record, HIGHEST pf
        "bb": {"wins": 1, "losses": 3, "ties": 0},
        "cc": {"wins": 2, "losses": 2, "ties": 0},
        "dd": {"wins": 3, "losses": 1, "ties": 0},  # best record, LOWEST pf
    }
    _payload, rows = _run(record=record, schedule=[], means=EQUAL, pf=PF, sims=2000)
    for slot, owner in enumerate(["aa", "bb", "cc", "dd"]):
        assert rows[owner]["draftSlotDistribution"][slot] == 1.0


# --------------------------------------------------------------------------
# 3. Game Day win odds  (src/ros/game_day_sim.py)
# --------------------------------------------------------------------------
from src.league_intel.sim_calibration import PointsModel  # noqa: E402
from src.ros.game_day_sim import (  # noqa: E402
    LeagueWeekRules,
    PlayerWeek,
    TeamWeek,
    simulate_league_week,
)

DRAWS = 20000


class _TwoPointModel:
    """Each player scores 2*mean or 0 with probability 1/2 (mean preserved).

    Duck-typed stand-in for ``PointsModel`` (the simulator only calls
    ``draw_from_mean`` and reads ``source``): it makes every team score
    discrete, so the exact answer is a finite enumeration.
    """

    source = "oracle-two-point"
    generated_at = None

    def draw_from_mean(self, mean, position, rng):
        return 2.0 * mean if rng.random() < 0.5 else 0.0


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pct_tol(p, n=DRAWS):
    # tolerance in PERCENT units: 4 sigma + 2dp rounding
    return 100.0 * 4.0 * math.sqrt(max(p * (1 - p), 1e-12) / n) + 0.01


def _gd_rules(slots, *, best_ball, median):
    return LeagueWeekRules(
        league_key="oracle",
        starter_slots=slots,
        best_ball=best_ball,
        median_enabled=median,
        team_count=None,
    )


def _qb(pid, mean, state="not_started", **kw):
    return PlayerWeek(player_id=pid, position="QB", state=state, projected_remaining=mean, **kw)


def test_game_day_discrete_matchup_and_median_match_enumeration():
    # T1..T4 each start one QB scoring {0, 2m} w.p. 1/2.  Matchups T1-T2, T3-T4.
    means = {"T1": 1.0, "T2": 2.0, "T3": 2.0, "T4": 3.0}
    teams = [
        TeamWeek(team_id=t, players=(_qb(f"{t}q", m),), declared_starters=(f"{t}q",))
        for t, m in means.items()
    ]
    opp = {"T1": "T2", "T2": "T1", "T3": "T4", "T4": "T3"}
    sim = simulate_league_week(
        rules=_gd_rules(("QB",), best_ball=False, median=True),
        teams=teams,
        opponents=opp,
        season=2026,
        week=1,
        draws=DRAWS,
        seed=5,
        points_model=_TwoPointModel(),
    )
    got = {o.team_id: o for o in sim.teams}

    ids = list(means)
    keys = ("win", "tie", "med", "medtie", "w20", "w11h", "w11m", "w02")
    exp = {t: dict.fromkeys(keys, 0.0) for t in ids}
    bucket = {(1, 1): "w20", (1, -1): "w11h", (-1, 1): "w11m", (-1, -1): "w02"}
    for bits in itertools.product((0, 1), repeat=4):
        score = {t: (2.0 * means[t] if b else 0.0) for t, b in zip(ids, bits, strict=True)}
        s = sorted(score.values())
        median = (s[1] + s[2]) / 2.0  # even league: mean of the middle two
        w = 1 / 16
        for t in ids:
            e = exp[t]
            o = opp[t]
            h2h = (score[t] > score[o]) - (score[t] < score[o])
            if h2h > 0:
                e["win"] += w
            elif h2h == 0:
                e["tie"] += w
            med = (score[t] > median) - (score[t] < median)
            if med > 0:
                e["med"] += w
            elif med == 0:
                e["medtie"] += w
            if h2h != 0 and med != 0:  # a tied leg falls out of the four buckets
                e[bucket[(h2h, med)]] += w
    for t in ids:
        o, e = got[t], exp[t]
        assert o.win_matchup_pct == pytest.approx(100 * e["win"], abs=_pct_tol(e["win"])), t
        assert o.tie_matchup_pct == pytest.approx(100 * e["tie"], abs=_pct_tol(e["tie"])), t
        assert o.beat_median_pct == pytest.approx(100 * e["med"], abs=_pct_tol(e["med"])), t
        assert o.median_tie_pct == pytest.approx(100 * e["medtie"], abs=_pct_tol(e["medtie"])), t
        for field, key in (
            ("joint_2_0_pct", "w20"),
            ("joint_1_1_h2h_pct", "w11h"),
            ("joint_1_1_median_pct", "w11m"),
            ("joint_0_2_pct", "w02"),
        ):
            assert getattr(o, field) == pytest.approx(100 * e[key], abs=_pct_tol(e[key])), (
                t,
                field,
            )
    # Within a matchup: win% + opponent win% + tie% == 100.
    for a, b in (("T1", "T2"), ("T3", "T4")):
        total = got[a].win_matchup_pct + got[b].win_matchup_pct + got[a].tie_matchup_pct
        assert total == pytest.approx(100.0, abs=0.05)


def test_game_day_best_ball_lineup_is_the_exact_max_of_draws():
    # Best ball, one QB slot.  A holds QBs worth {0,2} and {0,4}: score = max.
    # B holds one QB worth {0,4}.  Enumerate all 8 outcomes.
    teams = [
        TeamWeek(team_id="A", players=(_qb("a1", 1.0), _qb("a2", 2.0))),
        TeamWeek(team_id="B", players=(_qb("b1", 2.0),)),
    ]
    sim = simulate_league_week(
        rules=_gd_rules(("QB",), best_ball=True, median=False),
        teams=teams,
        opponents={"A": "B", "B": "A"},
        season=2026,
        week=1,
        draws=DRAWS,
        seed=9,
        points_model=_TwoPointModel(),
    )
    got = {o.team_id: o for o in sim.teams}
    win = tie = 0.0
    for x1, x2, y in itertools.product((0.0, 2.0), (0.0, 4.0), (0.0, 4.0)):
        score_a = max(x1, x2)
        win += (score_a > y) / 8
        tie += (score_a == y) / 8
    assert got["A"].win_matchup_pct == pytest.approx(100 * win, abs=_pct_tol(win))
    assert got["A"].tie_matchup_pct == pytest.approx(100 * tie, abs=_pct_tol(tie))
    # a1 (worth up to 2) must start whenever it strictly beats a2's draw and
    # must not whenever a2 strictly beats it; on an exact tie (both 0) which
    # one is seated is an arbitrary tie-break, so only the bounds are oracle.
    lo = sum(1 / 4 for x1, x2 in itertools.product((0.0, 2.0), (0.0, 4.0)) if x1 > x2)
    hi = sum(1 / 4 for x1, x2 in itertools.product((0.0, 2.0), (0.0, 4.0)) if x1 >= x2)
    pct_a1 = got["A"].player_lineup_pct["a1"]
    assert 100 * lo - _pct_tol(lo) <= pct_a1 <= 100 * hi + _pct_tol(hi)
    # exactly one QB slot: the two lineup shares partition every draw
    assert pct_a1 + got["A"].player_lineup_pct["a2"] == pytest.approx(100.0, abs=0.02)
    # median is off: not applicable, never a fabricated percentage
    assert got["A"].beat_median_pct is None
    assert got["A"].beat_median_state == "NOT_APPLICABLE"


def test_game_day_normal_sums_match_the_phi_closed_form():
    # Managed lineup; sd = mean * cv with cv = 0.1 (means >> 5 so neither the
    # 0.5 sd floor nor the zero clip binds).
    model = PointsModel(cv_by_position={"QB": 0.1, "RB": 0.1, "WR": 0.1}, default_cv=0.1)
    a = TeamWeek(
        team_id="A",
        players=(
            PlayerWeek(player_id="a_qb", position="QB", state="completed", points_scored=100.0),
            # in progress: 60 banked (certain) + remainder ~ N(40, 4)
            PlayerWeek(
                player_id="a_rb",
                position="RB",
                state="in_progress",
                points_scored=60.0,
                projected_remaining=40.0,
            ),
            PlayerWeek(
                player_id="a_wr", position="WR", state="not_started", projected_remaining=100.0
            ),  # N(100, 10)
        ),
        declared_starters=("a_qb", "a_rb", "a_wr"),
    )
    b = TeamWeek(
        team_id="B",
        players=(
            PlayerWeek(
                player_id="b_qb", position="QB", state="not_started", projected_remaining=100.0
            ),  # N(100, 10)
            PlayerWeek(
                player_id="b_rb", position="RB", state="not_started", projected_remaining=80.0
            ),  # N(80, 8)
            PlayerWeek(
                player_id="b_wr", position="WR", state="not_started", projected_remaining=70.0
            ),  # N(70, 7)
        ),
        declared_starters=("b_qb", "b_rb", "b_wr"),
    )
    sim = simulate_league_week(
        rules=_gd_rules(("QB", "RB", "WR"), best_ball=False, median=False),
        teams=[a, b],
        opponents={"A": "B", "B": "A"},
        season=2026,
        week=1,
        draws=DRAWS,
        seed=21,
        points_model=model,
    )
    got = {o.team_id: o for o in sim.teams}
    mu_a, var_a = 300.0, 4.0**2 + 10.0**2
    mu_b, var_b = 250.0, 10.0**2 + 8.0**2 + 7.0**2
    p_a = _phi((mu_a - mu_b) / math.sqrt(var_a + var_b))
    assert got["A"].win_matchup_pct == pytest.approx(100 * p_a, abs=_pct_tol(p_a))
    assert got["B"].win_matchup_pct == pytest.approx(100 * (1 - p_a), abs=_pct_tol(p_a))
    # Banked points are a fact (100 + 60); the in-progress remainder is not.
    assert got["A"].points_banked == 160.0
    sd_a = math.sqrt(var_a)
    se_mean = sd_a / math.sqrt(DRAWS)
    assert got["A"].projected_mean == pytest.approx(mu_a, abs=4 * se_mean + 0.01)
    assert got["A"].projected_p50 == pytest.approx(mu_a, abs=5 * se_mean + 0.01)
    # p10 / p90 of a normal: mu -/+ 1.2816 sigma
    assert got["A"].projected_p90 == pytest.approx(mu_a + 1.2816 * sd_a, abs=0.5)
    assert got["A"].projected_p10 == pytest.approx(mu_a - 1.2816 * sd_a, abs=0.5)


def test_game_day_finished_matchup_is_exactly_decided():
    # Everyone completed: no randomness, so the answer is exactly 100 / 0 and
    # an exact tie is a tie, not a win for either side.
    def comp(pid, pts):
        return PlayerWeek(player_id=pid, position="QB", state="completed", points_scored=pts)

    teams = [
        TeamWeek(team_id="A", players=(comp("a", 101.5),), declared_starters=("a",)),
        TeamWeek(team_id="B", players=(comp("b", 99.0),), declared_starters=("b",)),
        TeamWeek(team_id="C", players=(comp("c", 50.0),), declared_starters=("c",)),
        TeamWeek(team_id="D", players=(comp("d", 50.0),), declared_starters=("d",)),
    ]
    sim = simulate_league_week(
        rules=_gd_rules(("QB",), best_ball=False, median=False),
        teams=teams,
        opponents={"A": "B", "B": "A", "C": "D", "D": "C"},
        season=2026,
        week=1,
        draws=50,
        seed=1,
        points_model=_TwoPointModel(),
    )
    got = {o.team_id: o for o in sim.teams}
    assert (got["A"].win_matchup_pct, got["B"].win_matchup_pct) == (100.0, 0.0)
    assert (got["C"].win_matchup_pct, got["C"].tie_matchup_pct) == (0.0, 100.0)


def test_game_day_unknown_player_and_missing_opponent_are_not_zero():
    teams = [
        TeamWeek(
            team_id="A",
            players=(_qb("a", 10.0), PlayerWeek(player_id="ghost", position="QB", state="unknown")),
            declared_starters=("a", "ghost"),
        ),
    ]
    sim = simulate_league_week(
        rules=_gd_rules(("QB",), best_ball=False, median=False),
        teams=teams,
        opponents={"A": None},
        season=2026,
        week=1,
        draws=100,
        seed=1,
        points_model=_TwoPointModel(),
    )
    o = sim.teams[0]
    assert o.win_matchup_pct is None and o.tie_matchup_pct is None  # not 50%, not 0%
    assert o.unsimulable_player_ids == ("ghost",)
