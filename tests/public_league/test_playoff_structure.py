"""V1-51 — one owner for the league's playoff bracket.

Two simulators answer "will this team make the playoffs", and they
disagreed about the question rather than the answer:

* ``public_league.playoff_odds`` read ``settings.playoff_teams`` and fell
  back to **6** when it was absent;
* ``ros.playoff_sim`` never read the setting — ``playoff_seeds: int = 6``
  and ``bye_seeds: int = 2`` were hardcoded, and **no caller overrode
  them**.

Measured 2026-08-19 against the live league
(``GET /v1/league/1312006700437352448``): ``playoff_teams: 7``. So the
private engine simulated a six-seed bracket for a league that takes
seven — on a 12-team league, the whole difference between sixth and
seventh place mattering, propagated into every team's odds and the
championship simulation downstream.

These tests pin the three things that fix requires: the bracket has one
owner, the bye count is derived rather than configured, and a league that
does not publish a bracket gets a refusal rather than a guess.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from src.public_league import playoff_odds
from src.public_league.playoff_structure import (
    REASON_IMPLAUSIBLE,
    REASON_NO_PLAYOFF_TEAMS,
    REASON_NO_SEASON,
    REASON_NO_SETTINGS,
    byes_for_teams,
    resolve_playoff_structure,
)
from src.ros import playoff_sim


def _season(**settings):
    return SimpleNamespace(league={"settings": dict(settings)}, rosters=[], season="2026")


# ── The bracket the league actually plays ────────────────────────────


def test_the_live_leagues_bracket_resolves_to_seven_and_one():
    """The measured case. `dynasty_main` publishes ``playoff_teams: 7``;
    the retired constants said 6 seeds and 2 byes."""
    got = resolve_playoff_structure(_season(playoff_teams=7, playoff_week_start=15))
    assert (got.teams, got.byes, got.week_start) == (7, 1, 15)
    assert got.known and got.source == "league_settings"


@pytest.mark.parametrize(
    "teams,byes",
    [(2, 0), (3, 1), (4, 0), (5, 3), (6, 2), (7, 1), (8, 0), (10, 6), (12, 4)],
)
def test_byes_are_derived_by_padding_to_the_next_power_of_two(teams, byes):
    """Derived, not configured — and the derivation reproduces the pair
    the code already hardcoded (6 teams → 2 byes), which is the evidence
    that it generalises the old behaviour rather than replacing it with a
    new invention. No constant could have produced 7 → 1."""
    assert byes_for_teams(teams) == byes


def test_a_bracket_below_two_is_refused_not_clamped():
    with pytest.raises(ValueError):
        byes_for_teams(1)


# ── Missing is never six ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "season,reason",
    [
        (None, REASON_NO_SEASON),
        (SimpleNamespace(league={}), REASON_NO_SETTINGS),
        (SimpleNamespace(league={"settings": {}}), REASON_NO_SETTINGS),
        (_season(playoff_week_start=15), REASON_NO_PLAYOFF_TEAMS),
        (_season(playoff_teams=0), REASON_IMPLAUSIBLE),
        (_season(playoff_teams=99), REASON_IMPLAUSIBLE),
        (_season(playoff_teams="seven"), REASON_NO_PLAYOFF_TEAMS),
    ],
)
def test_an_unpublished_or_implausible_bracket_is_unknown_with_a_reason(season, reason):
    """Refused, not clamped and not defaulted. A corrupt or absent setting
    turning into a confident simulation is the failure this removes, and
    the reason code says which way it failed."""
    got = resolve_playoff_structure(season)
    assert not got.known
    assert got.teams is None and got.byes is None
    assert got.reason == reason


def test_the_week_start_survives_an_unknown_bracket():
    """Two different facts. Not knowing how many teams qualify does not
    unlearn when the playoffs start."""
    got = resolve_playoff_structure(_season(playoff_week_start=15))
    assert got.week_start == 15 and not got.known


# ── Both engines consume it ──────────────────────────────────────────


def _snapshot(playoff_teams=None):
    settings = {"playoff_week_start": 15}
    if playoff_teams is not None:
        settings["playoff_teams"] = playoff_teams
    season = SimpleNamespace(
        season="2026",
        league_id="L1",
        league={"settings": settings},
        rosters=[{"roster_id": 1}, {"roster_id": 2}],
        matchups_by_week={},
        regular_season_weeks=[],
    )
    return SimpleNamespace(
        seasons=[season],
        current_season=season,
        managers=SimpleNamespace(by_owner_id={}, roster_to_owner={}, display_names={}),
    )


def test_the_private_engine_takes_the_leagues_bracket_not_a_constant(monkeypatch):
    """THE DEFECT. Before V1-51 this returned ``playoffSeeds: 6`` for a
    league that plays seven, because the parameter defaulted to 6 and
    ``ros/scrape.py`` — its only production caller — passes no value."""
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)
    monkeypatch.setattr(playoff_sim, "_build_team_distributions", lambda *a, **k: ({}, {}))
    out = playoff_sim.simulate_playoff_odds(_snapshot(playoff_teams=7), n_simulations=10)
    assert out["playoffSeeds"] == 7
    assert out["byeSeeds"] == 1
    assert out["playoffStructure"]["source"] == "league_settings"


def test_the_private_engine_refuses_an_unknown_bracket_rather_than_assuming_six(monkeypatch):
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)
    out = playoff_sim.simulate_playoff_odds(_snapshot(), n_simulations=10)

    assert out["playoffOdds"] == []
    assert out["playoffSeeds"] is None and out["byeSeeds"] is None
    assert out["unsimulable"]["reason"] == REASON_NO_PLAYOFF_TEAMS
    assert "not a six-team bracket" in out["unsimulable"]["detail"]


def test_an_explicit_bracket_still_wins_so_an_a_b_compares_one_league(monkeypatch):
    """``simulate_trade_impact`` pins both arms to the same bracket. If
    resolution overrode that, the two arms could be different leagues and
    the delta would measure the bracket, not the trade."""
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)
    monkeypatch.setattr(playoff_sim, "_build_team_distributions", lambda *a, **k: ({}, {}))
    out = playoff_sim.simulate_playoff_odds(
        _snapshot(playoff_teams=7), n_simulations=10, playoff_seeds=4, bye_seeds=0
    )
    assert (out["playoffSeeds"], out["byeSeeds"]) == (4, 0)


def test_the_public_engine_refuses_an_unknown_bracket_rather_than_defaulting():
    """It used to publish probabilities computed under
    ``DEFAULT_PLAYOFF_SPOTS``. Every owner is still listed — the rows are
    real — but the certainty is withheld."""
    out = playoff_odds.compute_playoff_odds(_snapshot(), num_sims=50, rng=random.Random(1))
    assert out["playoffSpots"] is None
    assert out["simulated"] is False
    assert out["scheduleCertainty"] == "unknown_bracket"
    assert out["unsimulable"]["reason"] == REASON_NO_PLAYOFF_TEAMS
    assert all(o["playoffProbability"] is None for o in out["owners"])


def test_the_public_engine_uses_the_leagues_bracket_when_it_has_one():
    out = playoff_odds.compute_playoff_odds(
        _snapshot(playoff_teams=7), num_sims=50, rng=random.Random(1)
    )
    assert out["playoffSpots"] == 7


def test_both_engines_agree_on_the_bracket_for_one_league(monkeypatch):
    """The consolidation, stated as a property. Two engines that disagree
    about how many teams qualify are not two views of one league."""
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)
    monkeypatch.setattr(playoff_sim, "_build_team_distributions", lambda *a, **k: ({}, {}))
    for teams in (4, 6, 7, 8):
        snap = _snapshot(playoff_teams=teams)
        public = playoff_odds.compute_playoff_odds(snap, num_sims=10, rng=random.Random(1))
        private = playoff_sim.simulate_playoff_odds(snap, n_simulations=10)
        assert public["playoffSpots"] == private["playoffSeeds"] == teams


def test_the_championship_engine_takes_the_leagues_bracket_too(monkeypatch):
    """The third hardcode. A championship simulation is MORE sensitive to
    the bracket than playoff odds are, because the bye count decides who
    skips a round — and ``ros/scrape.py``, its only production caller,
    passes neither seeds nor byes."""
    from src.ros import championship

    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)
    monkeypatch.setattr(playoff_sim, "_build_team_distributions", lambda *a, **k: ({}, {}))

    out = championship.simulate_championship_odds(_snapshot(playoff_teams=7), n_simulations=10)
    assert (out["playoffSeeds"], out["byeSeeds"]) == (7, 1)

    unknown = championship.simulate_championship_odds(_snapshot(), n_simulations=10)
    assert unknown["championshipOdds"] == []
    assert unknown["playoffSeeds"] is None
    assert unknown["unsimulable"]["reason"] == REASON_NO_PLAYOFF_TEAMS


def test_the_trade_impact_ab_resolves_one_bracket_for_both_arms(monkeypatch):
    """The fourth hardcode, and the one where getting it wrong is subtlest.

    Both arms share an RNG seed so the delta is the trade rather than two
    Monte Carlo runs. The league's rules deserve the same treatment: two
    arms on different brackets would measure the bracket.
    """
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)
    monkeypatch.setattr(playoff_sim, "_build_team_distributions", lambda *a, **k: ({}, {}))

    out = playoff_sim.simulate_trade_impact(
        _snapshot(), strength_delta={"a": 5.0}, n_simulations=10
    )
    assert out["playoff"] == [] and out["championship"] == []
    assert out["unsimulable"]["reason"] == REASON_NO_PLAYOFF_TEAMS
    assert "not a zero-impact trade" in out["unsimulable"]["detail"]


def test_no_production_module_still_hardcodes_a_six_team_bracket():
    """Structural guard. Four separate call sites defaulted to a six-seed
    bracket for a league that takes seven, and each was invisible on its
    own — the parameter looked configurable and nothing configured it."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    watched = {"playoff_seeds", "bye_seeds"}
    offenders = []
    for base in ("src", "scripts"):
        for path in (root / base).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                args = node.args
                pairs = list(zip(args.kwonlyargs, args.kw_defaults))
                positional = args.posonlyargs + args.args
                pairs += list(
                    zip(positional[len(positional) - len(args.defaults) :], args.defaults)
                )
                for arg, default in pairs:
                    if arg.arg not in watched or default is None:
                        continue
                    if isinstance(default, ast.Constant) and isinstance(default.value, int):
                        offenders.append(
                            f"{path.relative_to(root)}:{node.lineno}: "
                            f"{node.name}({arg.arg}={default.value})"
                        )
    assert not offenders, (
        "a default bracket is back — resolve it from the league instead:\n" + "\n".join(offenders)
    )


# ── The bracket the championship engine actually PLAYS ───────────────
#
# V1-51 unified where the bracket comes FROM. It did not check that the
# championship simulator uses it, and the two tests above could not: one
# asserts the *stamped* pair ``(7, 1)``, the other walks kwarg defaults,
# and the defect was an integer literal in a function body.
#
# ``_simulate_bracket`` capped the field at six while ``bye_seeds`` came
# through as the league's real 1, which leaves five wildcard teams. The
# pairing loop runs ``while len(wildcard) >= 2``, so one is stranded,
# three reach the semis, one survives, and ``if len(semis_advance) >= 2``
# is False — **the final is never played**. The champion then falls out
# of the defensive placement block in seed order.
#
# Measured on 12 identical teams before the repair: seed 1 took 49.86% of
# championships and seeds 5, 6 and 7 took 0.00% — not a low probability,
# a structurally impossible one, published beside a payload stamping
# ``playoffSeeds: 7``.


def _identical_field(n_owners: int):
    """N owners the simulator cannot tell apart. Any asymmetry in the
    result is therefore the bracket's, not the teams'."""
    owners = [f"o{i:02d}" for i in range(1, n_owners + 1)]
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=100.0, sd=15.0, pf_to_date=0.0) for o in owners
    }
    return owners, dists


def _championship_counts(
    *, playoff_seeds: int, bye_seeds: int, n_owners: int = 12, runs: int = 600
):
    from src.ros import championship

    owners, dists = _identical_field(n_owners)
    rng = random.Random(7)
    champions: dict[str, int] = {o: 0 for o in owners}
    runners_up = 0
    for _ in range(runs):
        finishes = championship._simulate_bracket(
            list(owners),
            dists,
            bye_seeds=bye_seeds,
            playoff_seeds=playoff_seeds,
            rng=rng,
        )
        won = [o for o, place in finishes.items() if place == 1]
        assert len(won) == 1, f"a bracket produced {len(won)} champions: {finishes}"
        champions[won[0]] += 1
        runners_up += sum(1 for place in finishes.values() if place == 2)
    return owners, champions, runners_up, runs


def test_every_qualifier_can_win_the_live_seven_team_bracket():
    """The defect, stated as the property it broke. Seven teams qualify,
    so all seven must be able to win it — and only those seven."""
    owners, champions, _, _ = _championship_counts(playoff_seeds=7, bye_seeds=1)

    qualifiers = owners[:7]
    impossible = [o for o in qualifiers if champions[o] == 0]
    assert not impossible, (
        "seeds with a structurally impossible championship: "
        f"{impossible} — counts {[champions[o] for o in qualifiers]}"
    )

    eliminated = [o for o in owners[7:] if champions[o]]
    assert not eliminated, f"a non-qualifier won the bracket: {eliminated}"


@pytest.mark.parametrize("seeds,byes", [(4, 0), (6, 2), (7, 1), (8, 0)])
def test_the_bracket_plays_every_game_it_owes(monkeypatch, seeds, byes):
    """The mechanism, pinned separately from its consequence — and pinned
    on the games PLAYED, not on the finishes emitted.

    My first version of this test asserted that exactly one owner is
    stamped runner-up, and it passed under the defect: when the final is
    never played, the defensive placement block at the end of
    ``_simulate_bracket`` still hands out finishes 1 and 2 in seed order,
    so the payload looks identical. Counting games is what actually
    distinguishes them.

    A single-elimination bracket of N qualifiers plays exactly N-1
    games, whatever the bye count. Under the defect the live 7/1 bracket
    played 3 of its 6: an odd wildcard round strands a team, three reach
    the semis, one survives, and ``len(semis_advance) >= 2`` is False."""
    from src.ros import championship

    played = []
    real = championship._simulate_matchup
    monkeypatch.setattr(
        championship,
        "_simulate_matchup",
        lambda a, b, d, r: played.append((a, b)) or real(a, b, d, r),
    )

    owners, dists = _identical_field(12)
    championship._simulate_bracket(
        list(owners), dists, bye_seeds=byes, playoff_seeds=seeds, rng=random.Random(7)
    )
    assert (
        len(played) == seeds - 1
    ), f"a {seeds}-team bracket played {len(played)} games, not {seeds - 1}: {played}"


def test_the_top_seed_does_not_absorb_the_stranded_teams_odds():
    """One bye among seven teams is worth roughly a doubled share, not a
    quadrupled one. Under the defect the top seed took 49.86% because it
    inherited every bracket that failed to reach a final."""
    owners, champions, _, runs = _championship_counts(playoff_seeds=7, bye_seeds=1)
    top_seed_share = champions[owners[0]] / runs
    assert 0.18 <= top_seed_share <= 0.34, f"top seed took {top_seed_share:.2%} of championships"


def test_the_six_seed_bracket_is_unchanged():
    """Non-vacuity in the other direction: this repair generalises the
    bracket the code already played rather than changing it. Six seeds
    and two byes must still produce two bye-sized shares and four equal
    ones, exactly as before."""
    owners, champions, _, runs = _championship_counts(playoff_seeds=6, bye_seeds=2)

    assert all(champions[o] == 0 for o in owners[6:])
    byes = sorted(champions[o] / runs for o in owners[:2])
    rest = sorted(champions[o] / runs for o in owners[2:6])
    assert all(0.18 <= s <= 0.34 for s in byes), byes
    assert all(0.06 <= s <= 0.20 for s in rest), rest
    assert min(byes) > max(rest), f"a bye stopped being worth more: {byes} vs {rest}"


def test_the_championship_engine_receives_the_leagues_field_size(monkeypatch):
    """The wiring, not the arithmetic. ``playoff_seeds`` was in scope at
    the call site — used two lines later — and simply was not passed."""
    from src.ros import championship

    seen: dict[str, int] = {}
    real = championship._simulate_bracket

    def _spy(seeded_owners, distributions, **kwargs):
        seen.update(playoff_seeds=kwargs["playoff_seeds"], bye_seeds=kwargs["bye_seeds"])
        return real(seeded_owners, distributions, **kwargs)

    monkeypatch.setattr(championship, "_simulate_bracket", _spy)
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)

    owners, dists = _identical_field(12)
    monkeypatch.setattr(playoff_sim, "_build_team_distributions", lambda *a, **k: (dists, {}))
    monkeypatch.setattr(playoff_sim, "_current_record", lambda *a, **k: {})
    monkeypatch.setattr(playoff_sim, "_remaining_schedule", lambda *a, **k: [])

    out = championship.simulate_championship_odds(_snapshot(playoff_teams=7), n_simulations=5)
    assert seen == {"playoff_seeds": 7, "bye_seeds": 1}
    assert (out["playoffSeeds"], out["byeSeeds"]) == (7, 1)


def test_no_bracket_function_sizes_its_field_from_a_literal():
    """The guard above walks kwarg DEFAULTS, so it could not see an
    integer literal inside a function BODY — which is where this defect
    lived.

    Scoped to assignments that name a field size rather than to every
    integer in the function. The first version of this test flagged
    ``for _ in range(8)`` in ``playoff_sim._simulate_bracket``, which is
    the tie re-draw cap and has nothing to do with the bracket — a guard
    that cries wolf gets its assertion loosened, which is how the
    original one ended up unable to see anything."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    watched_files = ("src/ros/championship.py", "src/ros/playoff_sim.py")
    sizing = ("field_size", "playoff_seeds", "bye_seeds", "field", "seeds")
    offenders = []
    for rel in watched_files:
        path = root / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(any(k in n for k in sizing) for n in names):
                continue
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, int):
                    offenders.append(
                        f"{rel}:{node.lineno}: {'/'.join(names)} sized from literal {sub.value}"
                    )
    assert not offenders, (
        "a bracket field size is hardcoded again — take it from the "
        "resolved structure instead:\n" + "\n".join(offenders)
    )
