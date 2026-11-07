"""CW-49 independent oracles — playoff, bye, seed, title and draft-slot odds.

Owner directive 2026-11-07 (sitewide feature verification), workstream CW-49.
Every expected value here is computed by THIS file from the documented rules —
never by calling a production helper (``standings_from_sim``, ``draft_order``,
``_simulate_bracket``, ``_bracket_order`` ...).  The production Monte Carlo
(``src.ros.playoff_sim.simulate_playoff_odds``) is then compared against it.

How the oracle stays exact
--------------------------
The engine draws each team's weekly score from ``max(0, N(mean, sd))``.  With
every ``mean / sd >= 6`` the truncation has probability < 1e-9, so one game
``a`` vs ``b`` is won by ``a`` with probability
``P(N(mean_a - mean_b, sqrt(sd_a^2 + sd_b^2)) > 0)`` (``statistics.NormalDist``),
and games are independent (each team plays once per week; every playoff game
is a fresh draw).  Points-For-to-date gaps are made wider than any team's
possible remaining scoring, so the PF tiebreak is DETERMINISTIC; the outcome
space is then the 2^G win/loss vectors, enumerated exactly.  The one scenario
where the PF tiebreak is decided by the simulation itself has a closed form
(``test_pf_tiebreak_decided_by_the_simulated_week_matches_the_closed_form``).
The median-game scenario uses identical score distributions, so every ordering
of a week's scores is equally likely (exchangeability) — exact again.

Rules the oracle encodes (sources)
----------------------------------
* seeding: record (a tie is half a win) descending, then Points For descending
  — ``src/public_league/playoff_odds.py::standings_from_sim`` docstring;
* playoff field / byes: ``settings.playoff_teams``; byes = next power of two
  minus the field (``playoff_structure`` docstring);
* bracket: byes sit out round one, the rest play highest vs lowest; then
  ``playoff_seed_type`` 1 = re-seed (best survivor meets worst) or 0 = fixed
  bracket (round-one winner takes the higher seed's slot; slot ``s`` meets
  slot ``m + 1 - s``, winner keeps the smaller slot) —
  ``playoff_structure`` / ``_simulate_bracket`` docstrings;
* placements: champion 1, finalist 2, both semifinal losers 3, earlier-round
  losers ``survivors + 1 + k`` in game order; a team outside the bracket
  finishes at its regular-season seed — ``_record_round`` docstring;
* draft order: reverse final regular-season record, ties on record by LOWER
  Points For, recursively (owner decision 2026-10-04,
  ``docs/picks/DRAFT_ORDER_RULE.md``); ranked on the head-to-head record with
  half-win ties, never the median game (``DRAFT_ORDER_RECORD_BASIS``);
* median game (D3): each simulated week every team also wins (above) / loses
  (below) / ties (exactly on) the average of the middle two scores.

Tolerance: the engine runs at a FIXED seed, so each assertion is
deterministic; the bound is ``4.5 * sqrt(p(1-p)/n)`` plus rounding slack, which
a correct engine exceeds with probability ~7e-6 per comparison at any seed.
For an exact 0 or 1 the bound collapses to the rounding slack: a decided event
must be published decided, and an impossible one must never appear.
"""

from __future__ import annotations

import itertools
import math
import random
from statistics import NormalDist
from types import SimpleNamespace
from unittest import mock

import pytest

from src.public_league import playoff_odds
from src.ros import playoff_sim

_Z = 4.5
_ODDS_SLACK = 1e-4  # odds are published to 4 dp
_MEAN_SLACK = 0.006  # expectedWins / expectedFinish / summaries to 2 dp


# ── the independent oracle ─────────────────────────────────────────────


def _p_beats(dist: dict[str, tuple[float, float]], a: str, b: str) -> float:
    """P(score_a > score_b) for independent normal weekly scores."""
    (ma, sa), (mb, sb) = dist[a], dist[b]
    return 1.0 - NormalDist(ma - mb, math.hypot(sa, sb)).cdf(0.0)


def _assert_truncation_negligible(dist: dict[str, tuple[float, float]]) -> None:
    for owner, (m, s) in dist.items():
        assert m / s >= 6.0, f"{owner}: mean/sd {m / s:.2f} — the zero floor would matter"


def _assert_pf_order_is_deterministic(
    pf: dict[str, float], dist: dict[str, tuple[float, float]], games_per_team: int
) -> None:
    """No team can make up a PF-to-date gap in the games it has left."""
    swing = games_per_team * max(m + 10.0 * s for m, s in dist.values())
    values = sorted(pf.values())
    assert min(b - a for a, b in zip(values, values[1:])) > swing


def _season_outcomes(games, dist):
    """Every win/loss vector of the remaining games, with its probability."""
    for bits in itertools.product((True, False), repeat=len(games)):
        prob = 1.0
        winners = []
        for (a, b), a_wins in zip(games, bits):
            q = _p_beats(dist, a, b)
            prob *= q if a_wins else 1.0 - q
            winners.append(a if a_wins else b)
        yield prob, winners


def _bracket_outcomes(seeds: list[str], byes: int, reseed: bool, win_prob):
    """Every path through the bracket: ``(prob, champion, place, field)``.

    ``place[o]`` follows the documented convention; ``field[o]`` is the size of
    the smallest round ``o`` entered (the whole bracket for round one).
    """
    n = len(seeds)
    seed_rank = {o: i for i, o in enumerate(seeds)}
    out: list[tuple[float, str, dict[str, int], dict[str, int]]] = []

    def play(games, prob):
        """Every outcome of one round's games: ``(prob, winners, losers)``."""
        for bits in itertools.product((True, False), repeat=len(games)):
            p = prob
            winners, losers = [], []
            for (a, b), a_wins in zip(games, bits):
                q = win_prob(a, b)
                p *= q if a_wins else 1.0 - q
                winners.append(a if a_wins else b)
                losers.append(b if a_wins else a)
            yield p, winners, losers

    def placed(place, losers, survivors_after):
        new = dict(place)
        for k, loser in enumerate(losers):
            if survivors_after == 1:
                new[loser] = 2
            elif survivors_after == 2:
                new[loser] = 3
            else:
                new[loser] = survivors_after + 1 + k
        return new

    def later_rounds(prob, alive, place, field):
        """``alive``: re-seed -> list of owners; fixed -> {slot: owner}."""
        size = len(alive)
        if size == 1:
            (champ,) = alive.values() if isinstance(alive, dict) else alive
            out.append((prob, champ, {**place, champ: 1}, {**field, champ: 1}))
            return
        if reseed:
            ordered = sorted(alive, key=lambda o: seed_rank[o])
            games = [(ordered[i], ordered[size - 1 - i]) for i in range(size // 2)]
            entrants = list(alive)
        else:
            # Fixed bracket: slot s meets slot m + 1 - s; the winner keeps
            # the smaller slot.
            slots = sorted(alive)
            games = [(alive[slots[i]], alive[slots[size - 1 - i]]) for i in range(size // 2)]
            entrants = list(alive.values())
        new_field = {**field, **{o: min(field.get(o, size), size) for o in entrants}}
        for p, winners, losers in play(games, prob):
            nxt = winners if reseed else {sorted(alive)[i]: w for i, w in enumerate(winners)}
            later_rounds(p, nxt, placed(place, losers, size // 2), new_field)

    # Round one: byes advance; the rest play highest vs lowest.  The non-bye
    # count (2 * field - next power of two) is always even.
    bye_teams = seeds[:byes]
    rest = seeds[byes:]
    assert len(rest) % 2 == 0
    games = [(rest[i], rest[len(rest) - 1 - i]) for i in range(len(rest) // 2)]
    field0 = dict.fromkeys(seeds, n)
    for p, winners, losers in play(games, 1.0):
        survivors = bye_teams + winners
        place = placed({}, losers, len(survivors))
        if reseed:
            alive = survivors
        else:
            # A bye keeps its seed's slot; round-one game k's winner takes the
            # slot of the higher seed in it (seed byes + 1 + k).
            alive = {i + 1: o for i, o in enumerate(bye_teams)}
            alive.update({byes + 1 + k: w for k, w in enumerate(winners)})
        later_rounds(p, alive, place, field0)
    return out


def _oracle(
    *,
    dist,
    pf,
    record_wins,
    draft_base,
    games_by_week,
    playoff_teams,
    reseed,
    median=False,
    week_orderings=None,
):
    """Exact expected outputs for every published field the scenario fixes.

    ``record_wins`` is the seeding record to date (half-win ties included);
    ``draft_base`` the head-to-head draft record to date.  With ``median`` the
    weeks are enumerated through ``week_orderings`` (all score orderings,
    equally likely) instead of independent games.
    """
    owners = sorted(dist)
    n = len(owners)
    byes = 1
    while byes < playoff_teams:
        byes *= 2
    byes -= playoff_teams
    acc = {
        o: {
            "playoff": 0.0,
            "bye": 0.0,
            "top": 0.0,
            "seed": [0.0] * n,
            "wins": 0.0,
            "wins2": 0.0,
            "champ": 0.0,
            "finals": 0.0,
            "semis": 0.0,
            "finish": 0.0,
            "finish2": 0.0,
            "slot": [0.0] * n,
            "draft_wins": 0.0,
            "draft_wins2": 0.0,
        }
        for o in owners
    }

    def season_paths():
        if not median:
            games = [g for wk in games_by_week for g in wk]
            for prob, winners in _season_outcomes(games, dist):
                h2h = dict.fromkeys(owners, 0.0)
                for w in winners:
                    h2h[w] += 1.0
                yield prob, h2h, dict.fromkeys(owners, 0.0)
            return
        weeks = len(games_by_week)
        prob = 1.0 / (len(week_orderings) ** weeks)
        for combo in itertools.product(week_orderings, repeat=weeks):
            h2h = dict.fromkeys(owners, 0.0)
            med = dict.fromkeys(owners, 0.0)
            for pairs, order in zip(games_by_week, combo):
                rank = {o: i for i, o in enumerate(order)}  # 0 = highest score
                for a, b in pairs:
                    h2h[a if rank[a] < rank[b] else b] += 1.0
                for o in order[: len(order) // 2]:
                    med[o] += 1.0  # strictly above the middle-two average
            yield prob, h2h, med

    total = 0.0
    for prob, h2h, med in season_paths():
        total += prob
        wins = {o: record_wins[o] + h2h[o] + med[o] for o in owners}
        keys = {(wins[o], pf[o]) for o in owners}
        assert len(keys) == n, "oracle scenario must not leave an exact record+PF tie"
        seeding = sorted(owners, key=lambda o: (-wins[o], -pf[o]))
        dwins = {o: draft_base[o] + h2h[o] for o in owners}
        draft = sorted(owners, key=lambda o: (dwins[o], pf[o]))
        for i, o in enumerate(seeding):
            a = acc[o]
            a["seed"][i] += prob
            a["wins"] += prob * wins[o]
            a["wins2"] += prob * wins[o] ** 2
            if i < playoff_teams:
                a["playoff"] += prob
            if i < byes:
                a["bye"] += prob
            if i == 0:
                a["top"] += prob
        for i, o in enumerate(draft):
            acc[o]["slot"][i] += prob
            acc[o]["draft_wins"] += prob * dwins[o]
            acc[o]["draft_wins2"] += prob * dwins[o] ** 2
        bracket = seeding[:playoff_teams]
        for bprob, champ, place, field in _bracket_outcomes(
            bracket, byes, reseed, lambda a, b: _p_beats(dist, a, b)
        ):
            p = prob * bprob
            acc[champ]["champ"] += p
            for i, o in enumerate(seeding):
                fin = place.get(o, i + 1)
                acc[o]["finish"] += p * fin
                acc[o]["finish2"] += p * fin * fin
                if field.get(o, 99) <= 2:
                    acc[o]["finals"] += p
                if field.get(o, 99) <= 4:
                    acc[o]["semis"] += p
    assert total == pytest.approx(1.0, abs=1e-12)
    return acc, byes


# ── the engine harness (production code, inputs injected) ──────────────


def _snapshot(playoff_teams: int, seed_type: int, num_teams: int):
    season = SimpleNamespace(
        season="2026",
        league_id="L1",
        league={
            "settings": {
                "playoff_teams": playoff_teams,
                "playoff_seed_type": seed_type,
                "playoff_week_start": 15,
            }
        },
        rosters=[],
        matchups_by_week={},
        regular_season_weeks=[],
        num_teams=num_teams,
    )
    return SimpleNamespace(
        managers=SimpleNamespace(by_owner_id={}), current_season=season, seasons=[season]
    )


def _engine(
    *,
    dist,
    pf,
    record,
    schedule,
    playoff_teams,
    seed_type,
    sims,
    seed,
    rule=None,
    league_key="dynasty_main",
):
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=m, sd=s, pf_to_date=pf[o], basis="empirical")
        for o, (m, s) in dist.items()
    }
    rule = rule or {"medianGame": False, "state": "not_applicable"}
    with (
        mock.patch.object(playoff_sim, "_current_standings", lambda *a, **k: (record, rule)),
        mock.patch.object(playoff_sim, "_remaining_schedule", lambda *a, **k: list(schedule)),
        mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: {}),
        mock.patch.object(playoff_sim, "_league_best_ball", lambda *a, **k: False),
        mock.patch.object(
            playoff_sim, "_build_team_distributions", lambda *a, **k: (dists, dict(pf))
        ),
        mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: set(range(1, 12))),
        mock.patch("src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: league_key),
    ):
        out = playoff_sim.simulate_playoff_odds(
            _snapshot(playoff_teams, seed_type, len(dist)),
            n_simulations=sims,
            rng=random.Random(seed),
        )
    assert out["n_simulations"] == sims, out.get("unsimulable")
    return out, {r["ownerId"]: r for r in out["playoffOdds"]}


def _close(engine_value, exact, n, what, *, var=None, slack=_ODDS_SLACK):
    var = max(exact * (1.0 - exact) if var is None else var, 0.0)  # float noise
    tol = _Z * math.sqrt(var / n) + slack
    assert (
        abs(engine_value - exact) <= tol
    ), f"{what}: engine {engine_value} vs exact {exact:.6f} (tolerance {tol:.6f})"


def _compare_all(rows, acc, n, *, bracket=True, draft=True):
    for o, a in acc.items():
        r = rows[o]
        _close(r["playoffOdds"], a["playoff"], n, f"{o} playoffOdds")
        _close(r["missPlayoffsOdds"], 1.0 - a["playoff"], n, f"{o} missPlayoffsOdds")
        _close(r["byeOdds"], a["bye"], n, f"{o} byeOdds")
        _close(r["topSeedOdds"], a["top"], n, f"{o} topSeedOdds")
        for i, p in enumerate(a["seed"]):
            _close(r["seedDistribution"][i], p, n, f"{o} seed {i + 1}", slack=1e-12)
        _close(
            r["expectedWins"],
            a["wins"],
            n,
            f"{o} expectedWins",
            var=a["wins2"] - a["wins"] ** 2,
            slack=_MEAN_SLACK,
        )
        if bracket:
            _close(r["championshipOdds"], a["champ"], n, f"{o} championshipOdds")
            _close(r["finalsOdds"], a["finals"], n, f"{o} finalsOdds")
            _close(r["semifinalOdds"], a["semis"], n, f"{o} semifinalOdds")
            _close(
                r["expectedFinish"],
                a["finish"],
                n,
                f"{o} expectedFinish",
                var=a["finish2"] - a["finish"] ** 2,
                slack=_MEAN_SLACK,
            )
        if draft:
            for i, p in enumerate(a["slot"]):
                _close(r["draftSlotDistribution"][i], p, n, f"{o} draft slot {i + 1}", slack=1e-12)
            _close(
                r["finalWins"]["mean"],
                a["draft_wins"],
                n,
                f"{o} finalWins.mean",
                var=a["draft_wins2"] - a["draft_wins"] ** 2,
                slack=_MEAN_SLACK,
            )


def _record(h2h_w, h2h_l, h2h_t=0, med_w=0, med_l=0, med_t=0, median=False):
    row = {"wins": h2h_w + med_w, "losses": h2h_l + med_l, "ties": h2h_t + med_t}
    if median:
        row.update(medianWins=med_w, medianLosses=med_l, medianTies=med_t)
    return row


def _schedule(games_by_week, first_week=12):
    return [(first_week + w, a, b) for w, wk in enumerate(games_by_week) for a, b in wk]


# ── scenario 1: six teams, two weeks left, re-seeded 3-team bracket ─────

_S1_DIST = {
    "a": (90.0, 15.0),
    "b": (100.0, 15.0),
    "c": (110.0, 15.0),
    "d": (120.0, 15.0),
    "e": (130.0, 15.0),
    "f": (140.0, 15.0),
}
# PF-to-date ranks deliberately disagree with strength, so a tiebreak that
# read the wrong direction (or the wrong key) would move every number.
_S1_PF = {"a": 6000.0, "b": 2000.0, "c": 5000.0, "d": 1000.0, "e": 4000.0, "f": 3000.0}
_S1_RECORD = {
    "a": _record(7, 4),
    "b": _record(6, 5),
    "c": _record(6, 5),
    "d": _record(6, 5),
    "e": _record(5, 6),
    "f": _record(5, 6),
}
_S1_WEEKS = [
    [("a", "f"), ("b", "e"), ("c", "d")],
    [("a", "e"), ("b", "d"), ("c", "f")],
]


def _wins_of(record):
    return {o: r["wins"] + 0.5 * r["ties"] for o, r in record.items()}


def _draft_base_of(record):
    return {
        o: r["wins"] - r.get("medianWins", 0) + 0.5 * r["ties"] - 0.5 * r.get("medianTies", 0)
        for o, r in record.items()
    }


def test_six_team_reseeded_three_team_bracket_matches_exact_enumeration():
    _assert_truncation_negligible(_S1_DIST)
    _assert_pf_order_is_deterministic(_S1_PF, _S1_DIST, games_per_team=2)
    acc, byes = _oracle(
        dist=_S1_DIST,
        pf=_S1_PF,
        record_wins=_wins_of(_S1_RECORD),
        draft_base=_draft_base_of(_S1_RECORD),
        games_by_week=_S1_WEEKS,
        playoff_teams=3,
        reseed=True,
    )
    assert byes == 1
    n = 20000
    out, rows = _engine(
        dist=_S1_DIST,
        pf=_S1_PF,
        record=_S1_RECORD,
        schedule=_schedule(_S1_WEEKS),
        playoff_teams=3,
        seed_type=1,
        sims=n,
        seed=101,
    )
    assert out["playoffSeeds"] == 3 and out["byeSeeds"] == 1
    _compare_all(rows, acc, n)


# ── scenario 2/3: eight teams — fixed 6-team and re-seeded 7-team bracket ──

_S2_DIST = {
    "a": (85.0, 14.0),
    "b": (95.0, 14.0),
    "c": (105.0, 14.0),
    "d": (115.0, 14.0),
    "e": (125.0, 14.0),
    "f": (135.0, 14.0),
    "g": (145.0, 14.0),
    "h": (155.0, 14.0),
}
_S2_PF = {
    "a": 7000.0,
    "b": 3000.0,
    "c": 8000.0,
    "d": 1000.0,
    "e": 6000.0,
    "f": 2000.0,
    "g": 5000.0,
    "h": 4000.0,
}
_S2_RECORD = {
    "a": _record(7, 4),
    "b": _record(7, 4),
    "c": _record(6, 5),
    "d": _record(6, 5),
    "e": _record(6, 4, 1),
    "f": _record(5, 6),
    "g": _record(5, 6),
    "h": _record(4, 7),
}


@pytest.mark.parametrize(
    "playoff_teams, seed_type, weeks",
    [
        # dynasty_new's shape: six seeds, two byes, a FIXED bracket.
        (6, 0, [[("a", "h"), ("b", "g"), ("c", "f"), ("d", "e")]]),
        # dynasty_main's shape: seven seeds, one bye, RE-SEEDED every round.
        (
            7,
            1,
            [
                [("a", "h"), ("b", "g"), ("c", "f"), ("d", "e")],
                [("a", "b"), ("c", "d"), ("e", "f"), ("g", "h")],
            ],
        ),
        # Five seeds, three byes, fixed: 1 v winner(4/5), 2 v 3.
        (5, 0, [[("a", "e"), ("b", "f"), ("c", "g"), ("d", "h")]]),
    ],
    ids=["fixed-6-2byes", "reseed-7-1bye", "fixed-5-3byes"],
)
def test_eight_team_brackets_match_exact_enumeration(playoff_teams, seed_type, weeks):
    _assert_truncation_negligible(_S2_DIST)
    _assert_pf_order_is_deterministic(_S2_PF, _S2_DIST, games_per_team=len(weeks))
    acc, byes = _oracle(
        dist=_S2_DIST,
        pf=_S2_PF,
        record_wins=_wins_of(_S2_RECORD),
        draft_base=_draft_base_of(_S2_RECORD),
        games_by_week=weeks,
        playoff_teams=playoff_teams,
        reseed=seed_type == 1,
    )
    n = 20000
    out, rows = _engine(
        dist=_S2_DIST,
        pf=_S2_PF,
        record=_S2_RECORD,
        schedule=_schedule(weeks),
        playoff_teams=playoff_teams,
        seed_type=seed_type,
        sims=n,
        seed=202 + playoff_teams,
    )
    assert out["byeSeeds"] == byes
    _compare_all(rows, acc, n)


# ── bracket only: the season is over, seeding is fixed ─────────────────


@pytest.mark.parametrize("field", [2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("seed_type", [0, 1], ids=["fixed", "reseed"])
def test_bracket_title_finals_semis_and_finish_match_exact_enumeration(field, seed_type):
    """No games left and games played: the standings are the final ones, so the
    seeding is a fact and every title / finals / semifinal / finish number is
    the bracket alone — enumerated here path by path."""
    owners = list("abcdefgh")
    # Close enough that upsets are common, so a fixed bracket and a re-seeded
    # one genuinely differ (they coincide whenever the higher seeds win).
    dist = {o: (130.0 - 4.0 * i, 12.0 + 0.5 * i) for i, o in enumerate(owners)}
    _assert_truncation_negligible(dist)
    pf = {o: 1000.0 * (i + 1) for i, o in enumerate(owners)}
    record = {o: _record(10 - i, 3 + i) for i, o in enumerate(owners)}
    acc, _ = _oracle(
        dist=dist,
        pf=pf,
        record_wins=_wins_of(record),
        draft_base=_draft_base_of(record),
        games_by_week=[],
        playoff_teams=field,
        reseed=seed_type == 1,
    )
    n = 12000
    _out, rows = _engine(
        dist=dist,
        pf=pf,
        record=record,
        schedule=[],
        playoff_teams=field,
        seed_type=seed_type,
        sims=n,
        seed=300 + field,
    )
    _compare_all(rows, acc, n)
    # The seeding is decided, so it is published decided — not near-certain.
    for i, o in enumerate(owners):
        assert rows[o]["seedDistribution"][i] == 1.0
        assert rows[o]["playoffOdds"] == (1.0 if i < field else 0.0)
        assert rows[o]["draftSlotDistribution"][len(owners) - 1 - i] == 1.0


# ── median game counted (D3): exchangeable scores, exact orderings ──────


def test_median_game_seeding_and_head_to_head_draft_order_match_exact_orderings():
    """Four i.i.d. teams: each week's 24 score orderings are equally likely.

    Seeding must count the median result (top two of four beat the
    middle-two average); the DRAFT order must not — it ranks on head-to-head
    results with half-win ties only (``draftOrderRecordBasis``).  A median tie
    already on the books must leave the draft record exactly once.
    """
    dist = {o: (100.0, 10.0) for o in "wxyz"}
    pf = {"w": 4000.0, "x": 3000.0, "y": 2000.0, "z": 1000.0}
    record = {
        "w": _record(5, 5, 1, med_w=5, med_l=6, median=True),
        "x": _record(5, 6, 0, med_w=6, med_l=5, median=True),
        "y": _record(6, 5, 0, med_w=5, med_l=5, med_t=1, median=True),
        "z": _record(5, 6, 0, med_w=5, med_l=6, median=True),
    }
    weeks = [[("w", "x"), ("y", "z")], [("w", "y"), ("x", "z")]]
    _assert_truncation_negligible(dist)
    _assert_pf_order_is_deterministic(pf, dist, games_per_team=2)
    acc, byes = _oracle(
        dist=dist,
        pf=pf,
        record_wins=_wins_of(record),
        draft_base=_draft_base_of(record),
        games_by_week=weeks,
        playoff_teams=3,
        reseed=True,
        median=True,
        week_orderings=list(itertools.permutations("wxyz")),
    )
    assert byes == 1
    n = 20000
    rule = {
        "medianGame": True,
        "state": playoff_odds.MEDIAN_COUNTED,
        "threshold": "median",
        "tieRule": "exact_median_is_tie",
    }
    out, rows = _engine(
        dist=dist,
        pf=pf,
        record=record,
        schedule=_schedule(weeks),
        playoff_teams=3,
        seed_type=1,
        sims=n,
        seed=404,
        rule=rule,
    )
    assert out["draftOrderRecordBasis"] == playoff_sim.DRAFT_ORDER_RECORD_BASIS
    _compare_all(rows, acc, n)


# ── the PF tiebreak decided BY the simulated week: closed form ─────────


def test_pf_tiebreak_decided_by_the_simulated_week_matches_the_closed_form():
    """A and B are level on record AND Points For, and both certainly win their
    last game; C and D likewise certainly lose.  The seeding between A and B is
    then exactly ``P(score_A > score_B)`` (higher PF seeds first) and the draft
    order between them the complement (LOWER PF picks first) — and the same
    holds for C and D at the top of the draft."""
    dist = {"A": (120.0, 15.0), "B": (110.0, 10.0), "C": (20.0, 3.0), "D": (25.0, 3.0)}
    _assert_truncation_negligible(dist)
    assert _p_beats(dist, "C", "A") < 1e-9 and _p_beats(dist, "D", "B") < 1e-9
    pf = {"A": 1500.0, "B": 1500.0, "C": 900.0, "D": 900.0}
    record = {"A": _record(7, 4), "B": _record(7, 4), "C": _record(3, 8), "D": _record(3, 8)}
    n = 30000
    _out, rows = _engine(
        dist=dist,
        pf=pf,
        record=record,
        schedule=[(12, "A", "C"), (12, "B", "D")],
        playoff_teams=2,
        seed_type=1,
        sims=n,
        seed=505,
    )
    p_a_over_b = _p_beats(dist, "A", "B")  # Φ(10 / √325) ≈ 0.7105
    p_c_under_d = 1.0 - _p_beats(dist, "C", "D")  # Φ(5 / √18) ≈ 0.8807
    _close(rows["A"]["topSeedOdds"], p_a_over_b, n, "A top seed")
    _close(rows["B"]["topSeedOdds"], 1.0 - p_a_over_b, n, "B top seed")
    assert rows["A"]["playoffOdds"] == rows["B"]["playoffOdds"] == 1.0
    assert rows["C"]["playoffOdds"] == rows["D"]["playoffOdds"] == 0.0
    # A two-team bracket: the final is one game, whoever is seeded first.
    _close(rows["A"]["championshipOdds"], p_a_over_b, n, "A title")
    slot = {o: rows[o]["draftSlotDistribution"] for o in rows}
    _close(slot["C"][0], p_c_under_d, n, "C picks 1st", slack=1e-12)
    _close(slot["D"][0], 1.0 - p_c_under_d, n, "D picks 1st", slack=1e-12)
    _close(slot["A"][2], 1.0 - p_a_over_b, n, "A picks 3rd", slack=1e-12)
    _close(slot["B"][2], p_a_over_b, n, "B picks 3rd", slack=1e-12)
    assert slot["A"][0] == slot["A"][1] == 0.0 and slot["C"][2] == slot["C"][3] == 0.0
    _close(rows["A"]["finalPointsFor"]["mean"], 1620.0, n, "A final PF", var=15.0**2, slack=0.006)
    assert rows["A"]["finalWins"]["mean"] == 8.0


# ── metamorphic properties ─────────────────────────────────────────────


def test_renaming_the_owners_permutes_the_odds_and_nothing_else():
    """Renaming is not a football event: the relabelled league must give each
    team the same odds (within two-sample noise) even though the new ids sort
    in the opposite order, which reshuffles every RNG assignment."""
    weeks = [[("a", "h"), ("b", "g"), ("c", "f"), ("d", "e")]]
    rename = {o: f"z{8 - i}" for i, o in enumerate(sorted(_S2_DIST))}  # a->z8 ... h->z1
    n = 20000
    _o1, base = _engine(
        dist=_S2_DIST,
        pf=_S2_PF,
        record=_S2_RECORD,
        schedule=_schedule(weeks),
        playoff_teams=6,
        seed_type=0,
        sims=n,
        seed=606,
    )
    _o2, renamed = _engine(
        dist={rename[o]: v for o, v in _S2_DIST.items()},
        pf={rename[o]: v for o, v in _S2_PF.items()},
        record={rename[o]: v for o, v in _S2_RECORD.items()},
        schedule=[(w, rename[a], rename[b]) for w, a, b in _schedule(weeks)],
        playoff_teams=6,
        seed_type=0,
        sims=n,
        seed=606,
    )
    for o, new in rename.items():
        for field in ("playoffOdds", "byeOdds", "topSeedOdds", "championshipOdds"):
            p = base[o][field]
            tol = _Z * math.sqrt(2.0 * max(p * (1.0 - p), 1.0 / n) / n) + 2 * _ODDS_SLACK
            assert abs(renamed[new][field] - p) <= tol, (o, field, p, renamed[new][field])


def test_an_extra_win_never_lowers_a_teams_odds_exact_and_engine():
    """Credit team ``c`` a remaining game outright (``c`` beats ``d``).  In the
    exact oracle ``c``'s playoff, bye and top-seed odds cannot fall; the engine
    must agree with the oracle in both states, so it inherits the property."""
    base_weeks = _S1_WEEKS
    won_weeks = [[g for g in wk if g != ("c", "d")] for wk in base_weeks]
    won_record = dict(_S1_RECORD)
    won_record["c"] = _record(7, 5)
    won_record["d"] = _record(6, 6)
    results = {}
    n = 20000
    for label, weeks, record in (
        ("before", base_weeks, _S1_RECORD),
        ("after", won_weeks, won_record),
    ):
        acc, _ = _oracle(
            dist=_S1_DIST,
            pf=_S1_PF,
            record_wins=_wins_of(record),
            draft_base=_draft_base_of(record),
            games_by_week=weeks,
            playoff_teams=3,
            reseed=True,
        )
        _out, rows = _engine(
            dist=_S1_DIST,
            pf=_S1_PF,
            record=record,
            schedule=_schedule(weeks),
            playoff_teams=3,
            seed_type=1,
            sims=n,
            seed=707,
        )
        _compare_all(rows, acc, n)
        results[label] = acc
    for key in ("playoff", "bye", "top"):
        assert results["after"]["c"][key] >= results["before"]["c"][key] - 1e-12, key
        assert results["after"]["d"][key] <= results["before"]["d"][key] + 1e-12, key
    # And it genuinely moved (not a vacuous comparison).
    assert results["after"]["c"]["playoff"] > results["before"]["c"]["playoff"] + 0.05


def test_clinched_and_eliminated_are_exact_and_undecided_is_strictly_between():
    """Two seeds, one week left: A and B (9 wins) cannot be caught by C or D
    (6 wins, one game left), so their playoff odds are exactly 1 and C/D's
    exactly 0 — while the top seed between A and B is NOT decided."""
    dist = {"A": (110.0, 12.0), "B": (105.0, 12.0), "C": (100.0, 12.0), "D": (95.0, 12.0)}
    pf = {"A": 4000.0, "B": 3000.0, "C": 2000.0, "D": 1000.0}
    record = {"A": _record(9, 2), "B": _record(9, 2), "C": _record(6, 5), "D": _record(6, 5)}
    weeks = [[("A", "C"), ("B", "D")]]
    _assert_truncation_negligible(dist)
    _assert_pf_order_is_deterministic(pf, dist, games_per_team=1)
    acc, _ = _oracle(
        dist=dist,
        pf=pf,
        record_wins=_wins_of(record),
        draft_base=_draft_base_of(record),
        games_by_week=weeks,
        playoff_teams=2,
        reseed=True,
    )
    for o, decided in (("A", 1.0), ("B", 1.0), ("C", 0.0), ("D", 0.0)):
        assert acc[o]["playoff"] == pytest.approx(decided, abs=1e-12)
    assert 0.01 < acc["A"]["top"] < 0.99
    n = 20000
    _out, rows = _engine(
        dist=dist,
        pf=pf,
        record=record,
        schedule=_schedule(weeks),
        playoff_teams=2,
        seed_type=1,
        sims=n,
        seed=808,
    )
    assert rows["A"]["playoffOdds"] == rows["B"]["playoffOdds"] == 1.0
    assert rows["C"]["playoffOdds"] == rows["D"]["playoffOdds"] == 0.0
    assert 0.0 < rows["A"]["topSeedOdds"] < 1.0 and 0.0 < rows["B"]["topSeedOdds"] < 1.0
    # A Wilson interval stays honest at the boundary: certain is [~1, 1].
    lo, hi = rows["A"]["playoffOddsCi"]
    assert hi == 1.0 and lo > 0.999
    _compare_all(rows, acc, n)


def test_every_probability_family_sums_to_its_slot_count():
    weeks = [
        [("a", "h"), ("b", "g"), ("c", "f"), ("d", "e")],
        [("a", "b"), ("c", "d"), ("e", "f"), ("g", "h")],
    ]
    n = 8000
    out, rows = _engine(
        dist=_S2_DIST,
        pf=_S2_PF,
        record=_S2_RECORD,
        schedule=_schedule(weeks),
        playoff_teams=7,
        seed_type=1,
        sims=n,
        seed=909,
    )
    teams = list(rows.values())
    k = len(teams)
    eps = k * 5e-5 + 1e-9
    assert sum(r["playoffOdds"] for r in teams) == pytest.approx(7.0, abs=eps)
    assert sum(r["byeOdds"] for r in teams) == pytest.approx(1.0, abs=eps)
    assert sum(r["topSeedOdds"] for r in teams) == pytest.approx(1.0, abs=eps)
    assert sum(r["championshipOdds"] for r in teams) == pytest.approx(1.0, abs=eps)
    assert sum(r["finalsOdds"] for r in teams) == pytest.approx(2.0, abs=eps)
    assert sum(r["semifinalOdds"] for r in teams) == pytest.approx(4.0, abs=eps)
    for r in teams:
        assert sum(r["seedDistribution"]) == pytest.approx(1.0, abs=1e-9)
        assert sum(r["draftSlotDistribution"]) == pytest.approx(1.0, abs=1e-9)
        assert r["playoffOdds"] + r["missPlayoffsOdds"] == pytest.approx(1.0, abs=2e-4)
        assert r["championshipOdds"] <= r["finalsOdds"] <= r["semifinalOdds"] <= r["playoffOdds"]
    for i in range(k):
        assert sum(r["seedDistribution"][i] for r in teams) == pytest.approx(1.0, abs=1e-9)
        assert sum(r["draftSlotDistribution"][i] for r in teams) == pytest.approx(1.0, abs=1e-9)


# ── the draft-order rule itself, against a literal recursive reading ───


def _recursive_rule(wins: dict[str, float], pf: dict[str, float]) -> list[list[str]]:
    """The owner's text, applied literally: group by record (worst first);
    inside a record group, group by Points For (lowest first); what is left
    tied on both keys is an unresolved group.  Returns the groups in order."""
    groups: list[list[str]] = []
    for w in sorted(set(wins.values())):
        same_record = [o for o in wins if wins[o] == w]
        for p in sorted({pf[o] for o in same_record}):
            groups.append(sorted(o for o in same_record if pf[o] == p))
    return groups


def test_draft_order_matches_the_recursive_reading_of_the_owner_rule():
    from src.public_league.draft_order import draft_order, draft_order_from_standings

    rng = random.Random(1007)
    for trial in range(400):
        n = rng.randint(2, 12)
        owners = [f"o{i:02d}" for i in range(n)]
        rng.shuffle(owners)
        wins = {o: rng.randint(0, 8) + 0.5 * rng.randint(0, 1) for o in owners}
        pf = {o: float(rng.choice([1200, 1250, 1300, 1310.5])) for o in owners}
        groups = _recursive_rule(wins, pf)
        result = draft_order(wins, pf, owners)
        # Every owner appears once, in group order; ties are exactly the
        # multi-owner groups and nothing else.
        flat = [o for g in groups for o in g]
        assert sorted(result.order) == sorted(owners), trial
        pos = {o: i for i, o in enumerate(result.order)}
        for g1, g2 in zip(groups, groups[1:]):
            assert max(pos[o] for o in g1) < min(pos[o] for o in g2), trial
        assert sorted(sorted(t) for t in result.unresolved_ties) == sorted(
            g for g in groups if len(g) > 1
        ), trial
        assert len(flat) == n
        # Real standings rows: a tie is half a win, the same order.
        rows = []
        for o in owners:
            w = int(wins[o])
            rows.append(
                {"ownerId": o, "wins": w, "ties": int(round(2 * (wins[o] - w))), "pointsFor": pf[o]}
            )
        assert draft_order_from_standings(rows).order == result.order, trial


@pytest.mark.parametrize(
    "bad",
    [
        {"ownerId": "x", "wins": None, "ties": 0, "pointsFor": 100.0},
        {"ownerId": "x", "wins": 3, "ties": 0},
        {"ownerId": "x", "wins": 3, "ties": True, "pointsFor": 100.0},
        {"wins": 3, "ties": 0, "pointsFor": 100.0},
    ],
)
def test_real_standings_with_a_missing_input_have_no_order_never_a_zero(bad):
    from src.public_league.draft_order import draft_order_from_standings

    good = {"ownerId": "y", "wins": 5, "ties": 0, "pointsFor": 900.0}
    with pytest.raises(ValueError):
        draft_order_from_standings([good, bad])
