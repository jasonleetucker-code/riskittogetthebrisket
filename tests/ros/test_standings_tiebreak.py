"""Both private ROS simulators order standings through the CANONICAL tiebreak.

THE DEFECT, reproduced before it was repaired.

``ros/playoff_sim.py`` and ``ros/championship.py`` each sorted their
simulated standings locally::

    ranked = sorted(owners, key=lambda o: (-sim_wins.get(o, 0.0),
                                           -sim_pf.get(o, 0.0)))

Two keys — and the third was *implicit*.  Python's sort is stable and
``owners`` is ``sorted(distributions.keys())``, so any pair the simulation
could not separate resolved in **alphabetical ownerId order**.

Measured on the fixture below (four owners the engine genuinely cannot
separate: identical deterministic distributions, so every game is an exact
tie and everyone finishes on equal wins AND equal points-for):

===================  =========================  ==========================
engine               before                     after
===================  =========================  ==========================
playoff odds (top 2) 1.00 / 1.00 / 0.00 / 0.00  ~0.50 each
championship         1.00 / 0.00 / 0.00 / 0.00  ~0.25 each
===================  =========================  ==========================

and renaming the owners so alphabetical order reversed flipped the result
exactly.  **Renaming an owner is not a football event.**

THE REPAIR IS NOT A NEW RULE.  ``public_league.playoff_odds`` already owned
this decision — W19-F008, 2026-08-18 — after the same defect was found in the
public engine: the third key is a per-simulation RNG draw, so two teams the
season could not separate split the outcome ~50/50 instead of 100/0 to
whoever sorts first.  This unit routes the two ROS engines through that owner
rather than adding a third opinion.  ``standings_from_sim`` was promoted from
``_standings_from_sim`` to a public name because it now genuinely has three
consumers; a private function borrowed across modules is not a shared owner.

WHAT IS DELIBERATELY *NOT* ASSERTED: exact equality of per-owner odds under a
fixed seed when the ids are permuted.  The jitter is drawn per owner in
iteration order, so permuting the ids permutes which draw each owner gets.
That is RNG stream position, not identifier semantics.  The property that
matters — and that the defect violated — is that no owner's result is decided
by where their id sorts.
"""

from __future__ import annotations

import random
import unittest.mock as mock
from types import SimpleNamespace

import pytest

from src.public_league import playoff_odds
from src.ros import championship, playoff_sim

# ── the discriminating fixture ────────────────────────────────────────

#: Four owners the simulator CANNOT separate.  ``sd=0.0`` makes every draw
#: identical, so every matchup is an exact tie: equal wins (0.5 each, every
#: week) and equal points-for.  Only the tiebreak can order them, which is
#: what makes this fixture discriminating rather than merely realistic.
_BASE_IDS = ["alice", "bob", "carol", "dave"]

#: A permutation chosen so alphabetical order REVERSES.  If identifiers decide
#: anything, this inverts the answer.
_RENAMED = {"alice": "zeta", "bob": "yank", "carol": "xray", "dave": "west"}


def _snapshot(playoff_teams: int):
    return SimpleNamespace(
        managers=SimpleNamespace(by_owner_id={}),
        current_season=SimpleNamespace(
            season="2026",
            league_id="L1",
            league={"settings": {"playoff_teams": playoff_teams, "playoff_week_start": 15}},
            rosters=[],
            matchups_by_week={},
            regular_season_weeks=[],
        ),
    )


def _level_league(names: list[str]):
    """Distributions + a full round robin. Every game is an exact tie."""
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=100.0, sd=0.0, pf_to_date=0.0) for o in names
    }
    schedule = [
        (1, names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))
    ]
    return dists, schedule


def _run(engine: str, names: list[str], *, playoff_teams: int = 2, sims: int = 2000):
    dists, schedule = _level_league(names)
    with (
        mock.patch.object(playoff_sim, "_current_record", lambda *a, **k: {o: {} for o in names}),
        mock.patch.object(playoff_sim, "_remaining_schedule", lambda *a, **k: schedule),
        mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda: {}),
        mock.patch.object(playoff_sim, "_league_best_ball", lambda: False),
        mock.patch.object(
            playoff_sim,
            "_build_team_distributions",
            lambda *a, **k: (dists, {o: 0.0 for o in names}),
        ),
    ):
        if engine == "playoff":
            out = playoff_sim.simulate_playoff_odds(
                _snapshot(playoff_teams), n_simulations=sims, rng=random.Random(11)
            )
            return {r["ownerId"]: r["playoffOdds"] for r in out["playoffOdds"]}
        out = championship.simulate_championship_odds(
            _snapshot(playoff_teams), n_simulations=sims, rng=random.Random(11)
        )
        return {r["ownerId"]: r["championshipOdds"] for r in out["championshipOdds"]}


# ── behavioural: the alphabet is not the answer ───────────────────────


@pytest.mark.parametrize(
    "engine,expected",
    [("playoff", 0.50), ("champ", 0.25)],
)
def test_a_level_league_is_not_resolved_by_the_alphabet(engine, expected):
    """Four owners nothing can separate must SHARE the outcome.

    Under the defect this returned 1.00/1.00/0.00/0.00 (playoff) and
    1.00/0.00/0.00/0.00 (championship) — certainty and impossibility
    manufactured out of the id order.
    """
    odds = _run(engine, _BASE_IDS)

    assert set(odds) == set(_BASE_IDS)
    for owner, value in odds.items():
        assert 0.0 < value < 1.0, (
            f"{owner} got a structurally certain/impossible {value} on a league "
            f"where every team is identical: {odds}"
        )
        assert abs(value - expected) < 0.08, f"{owner}={value}, expected ≈{expected}: {odds}"


@pytest.mark.parametrize("engine", ["playoff", "champ"])
def test_renaming_the_owners_does_not_move_the_odds(engine):
    """The invariance that names the defect.

    Same teams, same seed, same schedule — only the identifiers change, and
    they change so that alphabetical order REVERSES.  Under the defect this
    inverted the result completely.
    """
    before = _run(engine, _BASE_IDS)
    after = _run(engine, [_RENAMED[o] for o in _BASE_IDS])

    for owner in _BASE_IDS:
        a, b = before[owner], after[_RENAMED[owner]]
        assert abs(a - b) < 0.10, (
            f"renaming {owner} -> {_RENAMED[owner]} moved its odds {a} -> {b}. "
            "A rename is not a football event."
        )


# ── the canonical owner is actually consumed ──────────────────────────


@pytest.mark.parametrize("engine", ["playoff", "champ"])
def test_both_engines_consume_the_canonical_tiebreak(engine):
    """Consumption proof, not a shape assertion.

    Spies on the canonical function itself, so a future edit that
    reintroduces a local sort fails here even if the numbers happen to
    look plausible.
    """
    calls: list[dict] = []
    real = playoff_odds.standings_from_sim

    def _spy(wins, points, owners, **kwargs):
        calls.append({"owners": list(owners), "kwargs": set(kwargs)})
        return real(wins, points, owners, **kwargs)

    with mock.patch.object(playoff_odds, "standings_from_sim", _spy):
        _run(engine, _BASE_IDS, sims=25)

    assert calls, "the engine ordered its standings without the canonical owner"
    for call in calls:
        assert "rng" in call["kwargs"], (
            "the canonical tiebreak was called WITHOUT an rng, which falls back "
            "to the ownerId — the exact defect this unit removes"
        )


def test_the_canonical_owner_has_one_name():
    """``standings_from_sim`` is public because it has three consumers now.

    A private ``_``-prefixed function imported across module boundaries is a
    borrowed implementation, not a shared owner — and an alias for the old
    name would be a second name for one concept.
    """
    assert hasattr(playoff_odds, "standings_from_sim")
    assert not hasattr(
        playoff_odds, "_standings_from_sim"
    ), "the old private name survives as an alias — one owner, one name"


# ── structural guard ──────────────────────────────────────────────────

_ROS_ENGINES = ("src/ros/playoff_sim.py", "src/ros/championship.py")


def _bracket_modules():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    return [(rel, (root / rel).read_text(encoding="utf-8")) for rel in _ROS_ENGINES]


def test_no_ros_engine_sorts_its_own_standings():
    """Structural guard, in the repo's idiom (cf. the lineup no-greedy test).

    The behavioural tests above can be satisfied by a local sort that happens
    to include a jitter key — which would be a SECOND owner of the tiebreak,
    free to drift from the public engine's. This asserts the absence of the
    local sort itself.

    Scoped to sorting the OWNER list: these modules legitimately sort seasons
    and other collections.
    """
    import ast

    offenders = []
    for rel, src in _bracket_modules():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "sorted"):
                continue
            if not node.args:
                continue
            first = node.args[0]
            names = {n.id for n in ast.walk(first) if isinstance(n, ast.Name)}
            if names & {"owners", "seeded_owners", "ranked", "seeded"}:
                offenders.append(f"{rel}:{node.lineno}: local sort of the owner list")
    assert not offenders, (
        "a ROS engine is ordering owners itself again. Standings order has one "
        "owner — playoff_odds.standings_from_sim:\n" + "\n".join(offenders)
    )


def test_ros_engines_state_their_tiebreak_choice():
    """Every call site must pass ``rng=`` EXPLICITLY.

    The canonical function keeps an ownerId fallback for callers that pass no
    rng (a completed season needs no coin flip). A simulation that silently
    dropped the argument would reinstate the defect with the behavioural tests
    still green if they ever weakened, so the argument is pinned structurally
    — the same posture the public engine's own guard takes.
    """
    import ast

    total = 0
    for rel, src in _bracket_modules():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name != "standings_from_sim":
                continue
            total += 1
            assert "rng" in {k.arg for k in node.keywords}, (
                f"{rel}:{node.lineno}: standings_from_sim called without an "
                "explicit rng= — that path falls back to the ownerId"
            )
    assert total == len(_ROS_ENGINES), (
        f"expected one canonical standings call per ROS engine, found {total}. "
        "If an engine stopped ordering standings, say so here; if it was "
        "renamed, this guard is now blind."
    )
