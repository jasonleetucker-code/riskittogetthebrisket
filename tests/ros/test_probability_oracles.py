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

import copy
import itertools
import json
import math
import pathlib
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


def assert_pf_gaps_dominate_noise(owners, pf, means, schedule, *, ignore=()):
    """Guard the design assumption the seeding oracles rest on.

    The enumerations break points-for ties with the STATIC ``pf_to_date``.
    That is only exact while no simulated season can reorder the owners'
    final points-for.  A team's final PF is ``pf_to_date`` plus one N(mean,
    sd) draw per remaining game, so the expected final order must equal the
    static order with a margin of 8 standard deviations of the difference
    (sd of a sum of G games, for two teams: sd * sqrt(2 G)).  Owners in
    ``ignore`` are exempt (a deliberately strong team whose wins, not its PF,
    decide its seed).  Fails loudly with the offending pair.
    """
    games = dict.fromkeys(owners, 0)
    for _w, a, b in schedule:
        games[a] += 1
        games[b] += 1
    live = [o for o in owners if o not in ignore]
    expect = {o: pf[o] + games[o] * means[o] for o in live}
    ranked = sorted(live, key=lambda o: -pf[o])
    for hi, lo in itertools.pairwise(ranked):
        margin = 8.0 * 1.0 * math.sqrt(2.0 * max(games[hi], games[lo], 1))
        assert expect[hi] - expect[lo] > margin, (
            f"PF-gap assumption violated for {hi} vs {lo}: expected final PF "
            f"{expect[hi]:.1f} vs {expect[lo]:.1f}, margin {margin:.1f} -- the "
            "static pf_to_date tiebreak in the enumeration is no longer exact"
        )


def _run_n(
    *,
    owners,
    record,
    schedule,
    means,
    pf,
    seats,
    byes=0,
    reseed=True,
    sims=SIMS,
    seed=11,
    standings_rule=None,
    ignore_pf_guard=(),
):
    assert_pf_gaps_dominate_noise(owners, pf, means, schedule, ignore=ignore_pf_guard)
    rule = standings_rule or {"medianGame": False, "state": "not_applicable"}
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=means[o], sd=1.0, pf_to_date=pf[o])
        for o in owners
    }
    with (
        mock.patch.object(playoff_sim, "_current_standings", lambda *a, **k: (record, rule)),
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
            _snapshot(seats),
            n_simulations=sims,
            min_simulations=sims,
            max_simulations=sims,
            rng=random.Random(seed),
            reseed=reseed,
            playoff_seeds=seats,
            bye_seeds=byes,
        )
    assert "unsimulable" not in out, out.get("unsimulable")
    out = json.loads(json.dumps(out))
    return out, {r["ownerId"]: r for r in out["playoffOdds"]}


def _run(*, record, schedule, means, pf, playoff_teams=2, sims=SIMS, seed=11, ignore_pf_guard=()):
    return _run_n(
        owners=OWNERS,
        record=record,
        schedule=schedule,
        means=means,
        pf=pf,
        seats=playoff_teams,
        sims=sims,
        seed=seed,
        ignore_pf_guard=ignore_pf_guard,
    )


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
    _payload, rows = _run(
        record=RECORD_LEVEL, schedule=schedule, means=means, pf=PF, ignore_pf_guard=("dd",)
    )
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
    # The record basis the order ranks on is STATED, not merely implied: with
    # the median game off it is head-to-head results plus half-win ties.
    assert payload["draftOrderRecordBasis"] == "head_to_head_with_half_win_ties"
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
# 2b. PF-gap guard, byes / bracket depth, median-game counting
# --------------------------------------------------------------------------
def test_pf_gap_guard_fails_loudly_when_the_assumption_stops_holding():
    # Passes for the suites' own inputs ...
    assert_pf_gaps_dominate_noise(OWNERS, PF, EQUAL, _round_robin([1, 2]))
    # ... and fails on gaps the simulated scoring could overturn (3-point gap,
    # 6 games each at sd 1 -> margin ~27.7), naming the pair.
    tight = {"aa": 1000.0, "bb": 997.0, "cc": 600.0, "dd": 400.0}
    with pytest.raises(AssertionError, match="aa vs bb"):
        assert_pf_gaps_dominate_noise(OWNERS, tight, EQUAL, _round_robin([1, 2]))
    # A mean advantage that outruns the static gap is caught too (dd, mean 140,
    # six games: expected final PF 1240 > aa's 1000) unless the team is exempt.
    strong = {**EQUAL, "dd": 140.0}
    with pytest.raises(AssertionError, match="dd"):
        assert_pf_gaps_dominate_noise(OWNERS, PF, strong, _round_robin([1, 2]))
    assert_pf_gaps_dominate_noise(OWNERS, PF, strong, _round_robin([1, 2]), ignore=("dd",))


def _seed_order_n(owners, wins, pf):
    return sorted(owners, key=lambda o: (-wins[o], -pf[o]))


def _bracket(order, means, byes, reseed):
    """Exact title / final-appearance probabilities for a seeded bracket.

    Rules, from ``docs/playoffs/V1_51_CANONICAL_PLAYOFF_BRACKET.md`` and the
    bracket convention it records: the top ``byes`` seeds sit out round one;
    the rest play first-vs-last.  After round one a RESEED league pairs the
    best surviving seed with the worst every round; a FIXED league keeps the
    slot order (byes, then round-one winners in game order) and pairs slot s
    with slot m+1-s, the winner keeping the smaller slot.
    """
    champ: dict[str, float] = {}
    final: dict[str, float] = {}
    rank = {o: i for i, o in enumerate(order)}

    def games(teams, prob, then):
        n = len(teams)
        pairs = [(teams[i], teams[n - 1 - i]) for i in range(n // 2)]
        mid = [teams[n // 2]] if n % 2 else []
        for bits in itertools.product((0, 1), repeat=len(pairs)):
            p, winners = prob, []
            for (a, b), r in zip(pairs, bits, strict=True):
                pa = _p_first_wins(means, a, b)
                p *= pa if r else 1.0 - pa
                winners.append(a if r else b)
            if p > 0.0:
                then(winners + mid, p)

    def rounds(survivors, prob):
        if reseed:
            survivors = sorted(survivors, key=rank.__getitem__)
        if len(survivors) == 1:
            champ[survivors[0]] = champ.get(survivors[0], 0.0) + prob
            return
        if len(survivors) == 2:
            for o in survivors:
                final[o] = final.get(o, 0.0) + prob
        games(survivors, prob, rounds)

    bye_teams, contenders = list(order[:byes]), list(order[byes:])
    if len(contenders) < 2:
        rounds(bye_teams + contenders, 1.0)
    else:
        games(contenders, 1.0, lambda winners, p: rounds(bye_teams + winners, p))
    return champ, final


def _bracket_expected(owners, record, schedule, means, pf, seats, byes, reseed):
    """Enumerate the regular season, then the bracket for every seed order."""
    n = len(owners)
    playoff = dict.fromkeys(owners, 0.0)
    bye = dict.fromkeys(owners, 0.0)
    top = dict.fromkeys(owners, 0.0)
    champ = dict.fromkeys(owners, 0.0)
    final = dict.fromkeys(owners, 0.0)
    seed_dist = {o: [0.0] * n for o in owners}
    games = [(a, b) for _w, a, b in schedule]
    for results in itertools.product((0, 1), repeat=len(games)):
        prob = 1.0
        wins = {o: float(record[o]["wins"]) for o in owners}
        for (a, b), r in zip(games, results, strict=True):
            pa = _p_first_wins(means, a, b)
            prob *= pa if r else 1.0 - pa
            wins[a if r else b] += 1
        if prob == 0.0:
            continue
        order = _seed_order_n(owners, wins, pf)
        for i, o in enumerate(order):
            seed_dist[o][i] += prob
            if i < seats:
                playoff[o] += prob
            if i < byes:
                bye[o] += prob
        top[order[0]] += prob
        c, f = _bracket(order[:seats], means, byes, reseed)
        for o, p in c.items():
            champ[o] += prob * p
        for o, p in f.items():
            final[o] += prob * p
    return {
        "playoff": playoff,
        "bye": bye,
        "top": top,
        "champ": champ,
        "final": final,
        "seeds": seed_dist,
    }


def _assert_matches(rows, exp, owners):
    for o in owners:
        for field, key in (
            ("playoffOdds", "playoff"),
            ("byeOdds", "bye"),
            ("topSeedOdds", "top"),
            ("championshipOdds", "champ"),
            ("finalsOdds", "final"),
        ):
            assert rows[o][field] == pytest.approx(exp[key][o], abs=_tol(exp[key][o])), (o, field)
        for i, p in enumerate(exp["seeds"][o]):
            assert rows[o]["seedDistribution"][i] == pytest.approx(p, abs=_tol(p)), (o, i)


OWNERS8 = [f"o{i}" for i in range(1, 9)]
PF8 = {o: 1000.0 - 100.0 * i for i, o in enumerate(OWNERS8)}  # o1 highest


@pytest.mark.parametrize("reseed", [True, False])
def test_six_seats_two_byes_with_random_seeding_matches_enumeration(reseed):
    # 8 teams, 6 seats, 2 byes (next power of two 8 - 6 teams = 2 byes, the
    # league's documented derivation).  Two weeks of coin-flip games make the
    # seeding random; everything downstream is enumerated.
    record = {o: {"wins": 1, "losses": 1, "ties": 0} for o in OWNERS8}
    wk1 = [(1, OWNERS8[i], OWNERS8[i + 1]) for i in range(0, 8, 2)]
    wk2 = [(2, OWNERS8[i], OWNERS8[i + 4]) for i in range(4)]
    schedule = wk1 + wk2
    means = dict.fromkeys(OWNERS8, 100.0)
    exp = _bracket_expected(OWNERS8, record, schedule, means, PF8, 6, 2, reseed)
    payload, rows = _run_n(
        owners=OWNERS8,
        record=record,
        schedule=schedule,
        means=means,
        pf=PF8,
        seats=6,
        byes=2,
        reseed=reseed,
    )
    assert payload["byeSeeds"] == 2 and payload["playoffSeeds"] == 6
    _assert_matches(rows, exp, OWNERS8)
    assert sum(r["byeOdds"] for r in rows.values()) == pytest.approx(2.0, abs=1e-3)
    assert sum(r["playoffOdds"] for r in rows.values()) == pytest.approx(6.0, abs=1e-3)
    assert sum(r["championshipOdds"] for r in rows.values()) == pytest.approx(1.0, abs=1e-3)
    assert sum(r["finalsOdds"] for r in rows.values()) == pytest.approx(2.0, abs=1e-3)
    # structural spot checks written by hand: a bye seed is 2 wins from a
    # title (1/4 on equal strength), a round-one seed needs 3 (1/8).
    c, _f = _bracket(OWNERS8[:6], means, 2, reseed)
    assert c["o1"] == pytest.approx(0.25) and c["o3"] == pytest.approx(0.125)


def test_fixed_and_reseeded_brackets_differ_and_both_match_enumeration():
    # Seeds are certain (finished table, o1..o8 descending).  Strengths make
    # round one go 6 over 3 (o6 200 vs o3 40) and o4/o5 a coin flip, then
    # o1 160 / o2 130 (every gap >= 30 sd, so those games are certain): a FIXED bracket plays 1 v w(4/5), 2 v 6; a RESEEDED one
    # plays 1 v 6, 2 v w(4/5) -- so the finalists differ.
    record = {o: {"wins": 7 - i, "losses": i, "ties": 0} for i, o in enumerate(OWNERS8)}
    means = {
        "o1": 160.0,
        "o2": 130.0,
        "o3": 40.0,
        "o4": 100.0,
        "o5": 100.0,
        "o6": 200.0,
        "o7": 100.0,
        "o8": 100.0,
    }
    expected = {}
    for reseed in (True, False):
        exp = _bracket_expected(OWNERS8, record, [], means, PF8, 6, 2, reseed)
        expected[reseed] = exp
        _payload, rows = _run_n(
            owners=OWNERS8,
            record=record,
            schedule=[],
            means=means,
            pf=PF8,
            seats=6,
            byes=2,
            reseed=reseed,
        )
        _assert_matches(rows, exp, OWNERS8)
        # a finished table is certain: seeds 1-2 byes, 1-6 in, 7-8 out
        assert [rows[o]["byeOdds"] for o in OWNERS8] == [1, 1, 0, 0, 0, 0, 0, 0]
        assert [rows[o]["playoffOdds"] for o in OWNERS8] == [1, 1, 1, 1, 1, 1, 0, 0]
    # the case discriminates: the two formats have different finalists
    assert expected[True]["final"]["o2"] > 0.4 and expected[False]["final"]["o2"] == 0.0
    assert expected[False]["final"]["o1"] > 0.9 and expected[True]["final"]["o1"] == 0.0


def _median_expected(record, schedule, pf, seats):
    """Enumerate every ordering of the league's scores each week (equal means
    -> every permutation equally likely).  Each week is two games per team:
    head-to-head, and a game against the median (top half beats it)."""
    n = len(OWNERS)
    weeks = sorted({w for w, _a, _b in schedule})
    perms = list(itertools.permutations(OWNERS))
    seed_dist = {o: [0.0] * n for o in OWNERS}
    draft_dist = {o: [0.0] * n for o in OWNERS}
    draft_dist_incl_median = {o: [0.0] * n for o in OWNERS}
    playoff = dict.fromkeys(OWNERS, 0.0)
    champ = dict.fromkeys(OWNERS, 0.0)
    for combo in itertools.product(perms, repeat=len(weeks)):
        w_total = {o: float(record[o]["wins"]) for o in OWNERS}
        w_h2h = {o: float(record[o]["wins"] - record[o]["medianWins"]) for o in OWNERS}
        for week, perm in zip(weeks, combo, strict=True):
            place = {o: i for i, o in enumerate(perm)}  # 0 = highest score
            for _w, a, b in (g for g in schedule if g[0] == week):
                winner = a if place[a] < place[b] else b
                w_total[winner] += 1
                w_h2h[winner] += 1
            for o in OWNERS:
                if place[o] < n // 2:  # strictly above the median
                    w_total[o] += 1
        prob = 1.0 / len(perms) ** len(weeks)
        order = _seed_order_n(OWNERS, w_total, pf)
        for i, o in enumerate(order):
            seed_dist[o][i] += prob
            if i < seats:
                playoff[o] += prob
        for i, o in enumerate(sorted(OWNERS, key=lambda o: (w_h2h[o], pf[o]))):
            draft_dist[o][i] += prob
        for i, o in enumerate(sorted(OWNERS, key=lambda o: (w_total[o], pf[o]))):
            draft_dist_incl_median[o][i] += prob
        c, _f = _bracket(order[:seats], EQUAL, 0, True)
        for o, p in c.items():
            champ[o] += prob * p
    return playoff, champ, seed_dist, draft_dist, draft_dist_incl_median


def test_median_game_counts_for_seeding_but_draft_order_stays_head_to_head():
    # Host record to date counts the median: wins = H2H + median.  aa 2 (1 med),
    # bb 1 (0 med), cc 1 (1 med), dd 0.  Two remaining weeks, two H2H pairs each.
    record = {
        "aa": {"wins": 2, "losses": 0, "ties": 0, "medianWins": 1, "medianTies": 0},
        "bb": {"wins": 1, "losses": 1, "ties": 0, "medianWins": 0, "medianTies": 0},
        "cc": {"wins": 1, "losses": 1, "ties": 0, "medianWins": 1, "medianTies": 0},
        "dd": {"wins": 0, "losses": 2, "ties": 0, "medianWins": 0, "medianTies": 0},
    }
    schedule = [
        (1, "aa", "bb"),
        (1, "cc", "dd"),
        (2, "aa", "cc"),
        (2, "bb", "dd"),
    ]
    playoff, champ, seeds, draft, draft_incl = _median_expected(record, schedule, PF, 2)
    rule = {"medianGame": True, "state": playoff_odds.MEDIAN_COUNTED}
    payload, rows = _run_n(
        owners=OWNERS,
        record=record,
        schedule=schedule,
        means=EQUAL,
        pf=PF,
        seats=2,
        sims=SIMS,
        standings_rule=rule,
    )
    # the standings rule and the draft record basis are STATED
    assert payload["standingsRule"]["state"] == "counted"
    assert payload["draftOrderRecordBasis"] == "head_to_head_with_half_win_ties"
    for o in OWNERS:
        assert rows[o]["playoffOdds"] == pytest.approx(playoff[o], abs=_tol(playoff[o])), o
        assert rows[o]["championshipOdds"] == pytest.approx(champ[o], abs=_tol(champ[o])), o
        for i in range(4):
            assert rows[o]["seedDistribution"][i] == pytest.approx(
                seeds[o][i], abs=_tol(seeds[o][i])
            ), (o, i, "seed")
            assert rows[o]["draftSlotDistribution"][i] == pytest.approx(
                draft[o][i], abs=_tol(draft[o][i])
            ), (o, i, "draft")
    # the case discriminates: counting the median in the draft order would
    # have given a materially different distribution.
    assert max(abs(draft[o][i] - draft_incl[o][i]) for o in OWNERS for i in range(4)) > 0.05


# --------------------------------------------------------------------------
# 2c. Unmocked smoke: the public entry point on a REAL archived snapshot
# --------------------------------------------------------------------------
# ``tests/fixtures/public_league/median_record_parity_2026w4.json`` is the
# host's own league state (Sleeper settings, rosters, four scored weeks of
# matchups).  Nothing below is patched except the ROS data directory (so no
# box-local file can leak in) and ``best_ball=False`` is passed as the public
# argument: every other helper the oracle tests above replace runs for real.
_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "public_league"
    / "median_record_parity_2026w4.json"
)


def _archived_snapshot(key, *, scored, weeks):
    """The captured league truncated to ``scored`` finished weeks; weeks up to
    ``weeks`` are posted with 0.0 stubs, reusing the real pairings in rotation
    (exactly how Sleeper serves an unplayed week)."""
    league = json.loads(_FIXTURE.read_text(encoding="utf-8"))["leagues"][key]
    matchups = {}
    for wk in range(1, weeks + 1):
        rows = copy.deepcopy(league["matchups"][str((wk - 1) % 4 + 1)])
        if wk > scored:
            for r in rows:
                r["points"] = 0.0
        matchups[wk] = rows
    settings = {**league["settings"], "last_scored_leg": scored}
    season = SimpleNamespace(
        season=league["season"],
        league_id=league["leagueId"],
        league={"settings": settings},
        num_teams=league["total_rosters"],
        rosters=league["rosters"],
        matchups_by_week=matchups,
        regular_season_weeks=list(range(1, weeks + 1)),
        winners_bracket=[],
        losers_bracket=[],
    )
    roster_to_owner = {
        (league["leagueId"], r["roster_id"]): f"o{r['roster_id']:02d}" for r in league["rosters"]
    }
    managers = SimpleNamespace(
        roster_to_owner=roster_to_owner,
        by_owner_id={o: SimpleNamespace(display_name=o) for o in roster_to_owner.values()},
    )
    snap = SimpleNamespace(
        seasons=[season],
        current_season=season,
        managers=managers,
        root_league_id=league["leagueId"],
        generated_at="2026-10-08T00:00:00+00:00",
    )
    return snap, league


def _assert_probability_invariants(out, *, has_draft_rule):
    rows = out["playoffOdds"]
    n = len(rows)
    seats, byes = out["playoffSeeds"], out["byeSeeds"]
    assert n >= 2 and seats <= n
    for r in rows:
        for field in ("playoffOdds", "byeOdds", "topSeedOdds", "missPlayoffsOdds"):
            assert 0.0 <= r[field] <= 1.0, (r["ownerId"], field)
        lo, hi = r["playoffOddsCi"]
        assert 0.0 <= lo <= r["playoffOdds"] + 1e-4 and r["playoffOdds"] - 1e-4 <= hi <= 1.0
        assert r["playoffOdds"] + r["missPlayoffsOdds"] == pytest.approx(1.0, abs=2e-4)
        assert sum(r["seedDistribution"]) == pytest.approx(1.0, abs=2e-3)
    tol = 1e-3  # four-decimal rounding of up to 12 published values
    assert sum(r["playoffOdds"] for r in rows) == pytest.approx(seats, abs=tol)
    assert sum(r["byeOdds"] for r in rows) == pytest.approx(byes, abs=tol)
    assert sum(r["topSeedOdds"] for r in rows) == pytest.approx(1.0, abs=tol)
    assert sum(r["championshipOdds"] for r in rows) == pytest.approx(1.0, abs=tol)
    assert sum(r["finalsOdds"] for r in rows) == pytest.approx(2.0, abs=tol)
    for i in range(n):  # seed matrix: every seed is held by exactly one owner
        assert sum(r["seedDistribution"][i] for r in rows) == pytest.approx(1.0, abs=tol)
    if has_draft_rule:
        assert out["draftOrderRule"] is not None
        assert out["draftOrderRecordBasis"] == "head_to_head_with_half_win_ties"
        for r in rows:
            assert sum(r["draftSlotDistribution"]) == pytest.approx(1.0, abs=2e-3)
        for i in range(n):
            col = sum(r["draftSlotDistribution"][i] for r in rows)
            assert col == pytest.approx(1.0, abs=tol)
    else:
        assert out["draftOrderRule"] is None and out["draftOrderRecordBasis"] is None
        assert all("draftSlotDistribution" not in r for r in rows)


@pytest.fixture
def _hermetic_ros(monkeypatch, tmp_path):
    """Point the ROS data directory at an empty temp dir and persist a
    team-strength snapshot through the module's own writer, so the real
    ``_load_ros_strength_map`` -> ``load_or_compute_team_strength`` path runs
    (the engine refuses to publish odds with no team evidence, by design)."""
    from src.api import league_registry
    from src.ros import team_strength

    # The suite's conftest points the league registry at a missing file; the
    # real engine resolves the league KEY (draft-order rule, strength file)
    # from the registry, so aim it at the repo's own.
    monkeypatch.setenv(
        "LEAGUE_REGISTRY_PATH",
        str(pathlib.Path(__file__).resolve().parents[2] / "config" / "leagues" / "registry.json"),
    )
    league_registry.reload_registry()
    monkeypatch.setattr(playoff_sim, "ROS_DATA_DIR", tmp_path)
    monkeypatch.setattr(team_strength, "ROS_DATA_DIR", tmp_path)
    for key in ("dynasty_main", "dynasty_new"):
        size = 12 if key == "dynasty_main" else 10
        rows = [
            {
                "ownerId": f"o{i:02d}",
                "teamRosStrength": 40.0 + 7.0 * ((i * 5) % size),
                "startingLineupScore": 100.0 + 3.0 * ((i * 5) % size),
            }
            for i in range(1, size + 1)
        ]
        team_strength.write_team_strength_snapshot(rows, league_key=key)
    yield
    monkeypatch.undo()
    league_registry.reload_registry()


@pytest.mark.parametrize(
    ("key", "seats", "byes", "median", "draft_rule"),
    [("dynasty_main", 7, 1, True, True), ("dynasty_new", 6, 2, False, False)],
)
def test_unmocked_public_entry_point_on_an_archived_league_holds_every_invariant(
    _hermetic_ros, key, seats, byes, median, draft_rule
):
    snap, _league = _archived_snapshot(key, scored=2, weeks=14)
    out = playoff_sim.simulate_playoff_odds(
        snap,
        n_simulations=1500,
        min_simulations=1500,
        max_simulations=1500,
        rng=random.Random(20261008),
        best_ball=False,
    )
    assert "unsimulable" not in out, out.get("unsimulable")
    assert out["n_simulations"] == 1500
    # the bracket is the league's OWN (settings.playoff_teams; byes derived)
    assert (out["playoffSeeds"], out["byeSeeds"]) == (seats, byes)
    assert out["standingsRule"]["state"] == ("counted" if median else "not_applicable")
    _assert_probability_invariants(out, has_draft_rule=draft_rule)
    # two scored weeks of twelve: nobody is mathematically settled yet
    assert any(0.0 < r["playoffOdds"] < 1.0 for r in out["playoffOdds"])


@pytest.mark.parametrize(("key", "seats"), [("dynasty_main", 7), ("dynasty_new", 6)])
def test_unmocked_finished_archived_season_is_certain_and_matches_the_host_table(
    _hermetic_ros, key, seats
):
    # Only the four scored weeks exist: the season is OVER, so clinched teams
    # are exactly 1 and eliminated teams exactly 0.  The expected set is
    # computed here from the host's own roster records (wins + half-ties, then
    # higher points for) -- not from the simulator.
    snap, league = _archived_snapshot(key, scored=4, weeks=4)
    out = playoff_sim.simulate_playoff_odds(
        snap,
        n_simulations=400,
        min_simulations=400,
        max_simulations=400,
        rng=random.Random(3),
        best_ball=False,
    )
    assert "unsimulable" not in out, out.get("unsimulable")
    pf = {}
    for rows in league["matchups"].values():
        for r in rows:
            pf[r["roster_id"]] = pf.get(r["roster_id"], 0.0) + r["points"]
    host = {
        r["roster_id"]: float(r["settings"]["wins"] or 0) + 0.5 * float(r["settings"]["ties"] or 0)
        for r in league["rosters"]
    }
    table = sorted(host, key=lambda rid: (-host[rid], -pf[rid]))
    qualifiers = {f"o{rid:02d}" for rid in table[:seats]}
    got = {r["ownerId"]: r["playoffOdds"] for r in out["playoffOdds"]}
    assert {o for o, p in got.items() if p == 1.0} == qualifiers
    assert {o for o, p in got.items() if p == 0.0} == set(got) - qualifiers
    top = {r["ownerId"]: r["topSeedOdds"] for r in out["playoffOdds"]}
    assert top[f"o{table[0]:02d}"] == 1.0
    _assert_probability_invariants(out, has_draft_rule=(key == "dynasty_main"))


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
