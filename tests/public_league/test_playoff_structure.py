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
