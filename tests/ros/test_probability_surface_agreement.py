"""V1-51 / #943 — the three probability surfaces must describe ONE state.

THE DEFECT, measured on the deployed build ``e37d2786e`` (2026-08-20, preseason,
``weeksPlayed: 0``), one request each to the same league:

===============================================  ==========================================
endpoint                                         what it said about that state
===============================================  ==========================================
``/api/public/league/playoffOdds``               ``numSims: 0``, ``simulated: false``,
                                                 ``unsimulable`` present
``/api/public/league/rosPlayoffOdds``            ``n_simulations: 0``
``/api/public/league/rosChampionship``           ``championshipOdds: []`` but
                                                 **``n_simulations: 10000``**
===============================================  ==========================================

The third payload claims ten thousand simulations were run and returns nothing.
Every other signal on it agrees that the inputs were fine — ``rosStrengthAvailable:
true``, ``playoffStructure`` fully resolved to a 7-team bracket — so a consumer
cannot tell it from *"we simulated, and nobody has a path to a championship."*
That is MISSING IS NEVER ZERO inverted: an absence of evidence published as a
completed measurement.

``src/ros/championship.py``'s own sibling branch twenty lines above already had
the right shape, and ``src/public_league/playoff_odds.py`` says the invariant out
loud:

    Same posture, and deliberately the same vocabulary, as
    ``src/ros/playoff_sim.py``'s ``unsimulable`` block — two engines must not
    invent different words for the same state.

WHAT THIS FILE PINS.  Not the shape of one branch — the AGREEMENT.  The engines
publish different field NAMES for the same quantity (``numSims`` vs
``n_simulations``), so the adapter below normalises them and the assertions are
about meaning.  A future engine that gets its own branch right while drifting
from the others still fails here.

KNOWN RESIDUAL, reported rather than silently fixed or silently ignored:
``playoff_sim.simulate_playoff_odds``'s own no-distributions branch is TRUTHFUL
(``n_simulations: 0``) but SILENT — it carries no ``unsimulable`` block, unlike
both its bracket-unknown sibling and the public engine.  That is a different and
much smaller defect than publishing a false count, it is in a different file, and
#943 scopes this unit to ``championship.py``.  It is asserted here only to the
extent the truthfulness invariant covers it; the explanation gap is left visible
for whoever picks it up.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.public_league import playoff_odds as public_odds
from src.ros import championship, playoff_sim

# ── the shared preseason state ────────────────────────────────────────

_OWNERS = ["alice", "bob", "carol", "dave"]

#: The requested simulation count.  Deliberately the production value: the
#: defect is that this number reaches the payload, so a small one would make a
#: passing test that says nothing about what shipped.
_REQUESTED_SIMS = 10000


def _snapshot():
    """A league with a fully resolved bracket and not one scored week.

    Every input the engines report on is HEALTHY — the bracket resolves from
    league settings, ROS strength is available.  Only the thing that actually
    blocks simulation is missing.  That is what makes the false ``10000``
    indefensible rather than merely unlucky: nothing else on the payload hints
    that anything is wrong.
    """
    return SimpleNamespace(
        seasons=[],
        managers=SimpleNamespace(by_owner_id={}),
        current_season=SimpleNamespace(
            season="2026",
            league_id="L1",
            league={"settings": {"playoff_teams": 7, "playoff_week_start": 15}},
            rosters=[],
            matchups_by_week={},
            regular_season_weeks=[],
        ),
    )


def _run_ros(fn):
    """Drive a ROS engine with NO team distributions — the preseason branch."""
    with (
        patch.object(playoff_sim, "_build_team_distributions", return_value=({}, {})),
        patch.object(playoff_sim, "_load_ros_strength_map", return_value={"alice": 50.0}),
        patch.object(playoff_sim, "_league_best_ball", return_value=False),
    ):
        return fn(_snapshot(), n_simulations=_REQUESTED_SIMS)


def _run_public():
    with patch.object(public_odds, "_season_weekly_scores", return_value=({}, [])):
        return public_odds.compute_playoff_odds(_snapshot(), num_sims=_REQUESTED_SIMS)


class Surface:
    """One probability surface, normalised across the engines' field names."""

    def __init__(self, name, payload, odds_key, sims_key):
        self.name = name
        self.payload = payload
        self.odds = payload.get(odds_key)
        self.sims = payload.get(sims_key)
        self.unsimulable = payload.get("unsimulable")

    @property
    def simulated(self):
        """Did this surface actually simulate? Derived, never assumed.

        The engines answer this differently and BOTH are legitimate: the public
        engine publishes an explicit ``simulated`` boolean, while the two ROS
        engines express it as ``n_simulations``.  Deriving it is what makes the
        agreement assertion meaningful across all three — and it is why no
        ``simulated`` flag was bolted onto ``championship.py``'s refusal alone,
        which would have produced a field that exists only when there is no
        result and is absent from its own success path and from its sibling
        ``playoff_sim`` entirely.
        """
        if "simulated" in self.payload:
            return bool(self.payload["simulated"])
        return bool(self.sims)


def _surfaces():
    return [
        Surface("playoffOdds", _run_public(), "owners", "numSims"),
        Surface(
            "rosPlayoffOdds",
            _run_ros(playoff_sim.simulate_playoff_odds),
            "playoffOdds",
            "n_simulations",
        ),
        Surface(
            "rosChampionship",
            _run_ros(championship.simulate_championship_odds),
            "championshipOdds",
            "n_simulations",
        ),
    ]


def _ids(surfaces):
    return [s.name for s in surfaces]


# ── the invariant the production contradiction violated ───────────────


@pytest.mark.parametrize("surface", _surfaces(), ids=_ids(_surfaces()))
def test_no_surface_claims_simulations_it_did_not_run(surface):
    """A simulation count is a claim about WORK DONE, not about what was asked for.

    This is the whole of #943 stated as a property. ``rosChampionship`` reported
    the REQUESTED count from a branch that never entered the simulation loop, so
    the number described the caller's argument rather than the engine's output.
    """
    produced_nothing = not surface.odds
    if produced_nothing:
        assert surface.sims == 0, (
            f"{surface.name} published {surface.sims} simulations alongside an "
            f"empty result set. A count is a claim that work happened."
        )


def test_the_three_surfaces_agree_on_this_state():
    """Cross-surface, not per-branch. The actual V1-51 capability.

    One league, one moment, three endpoints: they must not disagree about
    whether anything was simulated.
    """
    surfaces = _surfaces()
    verdicts = {s.name: (bool(s.odds), s.sims) for s in surfaces}
    assert all(sims == 0 for _, sims in verdicts.values()), (
        "the surfaces disagree about how much was simulated in one shared " f"state: {verdicts}"
    )
    assert not any(
        produced for produced, _ in verdicts.values()
    ), f"a surface produced odds from no distributions: {verdicts}"


def test_the_surfaces_agree_on_whether_anything_was_simulated():
    """The "simulated state" agreement, asserted semantically.

    A consumer reading all three endpoints must get one answer to *"did this
    league get simulated?"*.  Before the repair it got two: false, false, and
    an implied true from a count of ten thousand.
    """
    verdicts = {s.name: s.simulated for s in _surfaces()}
    assert set(verdicts.values()) == {
        False
    }, f"the surfaces disagree about whether anything was simulated: {verdicts}"


# ── missing is never zero ─────────────────────────────────────────────


@pytest.mark.parametrize("surface", _surfaces(), ids=_ids(_surfaces()))
def test_no_owner_is_given_a_fabricated_probability(surface):
    """Refusing must not degrade into publishing 0.0 for everyone.

    An empty list and a list of zeros read identically on a chart and mean
    opposite things: "we cannot say" versus "we say nobody can win".
    """
    for row in surface.odds or []:
        for key, value in row.items():
            if "odds" in key.lower() or "probability" in key.lower():
                assert value is None or value != 0.0, (
                    f"{surface.name} published a fabricated {key}={value} for "
                    f"{row.get('ownerId')} with nothing simulated"
                )


# ── the refusal explains itself, in the shared vocabulary ─────────────


def test_championship_says_why_it_could_not_simulate():
    """An empty list with no reason is its own ambiguity.

    ``championshipOdds: []`` alone reads as "no teams". The sibling branch at
    ``:193`` and the public engine both attach an ``unsimulable`` block; this is
    the third engine joining them rather than inventing new words.
    """
    out = _run_ros(championship.simulate_championship_odds)
    assert out.get("unsimulable"), "the refusal carries no machine-readable reason"
    assert out["unsimulable"]["reason"], "the reason is empty"
    assert out["unsimulable"]["detail"], "the reason has no human-readable detail"


def test_the_two_refusal_reasons_are_distinguishable():
    """*No bracket* and *no distributions* are different problems.

    They need different operator responses — one is a league-settings question,
    the other resolves itself once games are played — so collapsing them into
    one reason string would throw away the only actionable part.
    """
    no_distributions = _run_ros(championship.simulate_championship_odds)

    with (
        patch.object(playoff_sim, "_load_ros_strength_map", return_value={}),
        patch.object(playoff_sim, "_league_best_ball", return_value=False),
    ):
        no_bracket = championship.simulate_championship_odds(
            SimpleNamespace(
                seasons=[],
                managers=SimpleNamespace(by_owner_id={}),
                current_season=SimpleNamespace(
                    season="2026",
                    league_id="L1",
                    league={"settings": {}},
                    rosters=[],
                    matchups_by_week={},
                    regular_season_weeks=[],
                ),
            ),
            n_simulations=_REQUESTED_SIMS,
        )

    assert no_bracket.get("unsimulable"), "the bracket-unknown sibling lost its block"
    assert (
        no_distributions["unsimulable"]["reason"] != no_bracket["unsimulable"]["reason"]
    ), "both refusals report the same reason, so the payload cannot say which happened"


def test_the_no_distributions_reason_is_the_one_the_siblings_already_use():
    """One state, one word — the invariant the public engine states out loud.

    ``playoff_odds.py`` refuses this exact state (nothing scored anywhere, so no
    distribution to draw from) under ``no_scored_weeks_in_league``. A second
    engine coining its own synonym is how the two drift.
    """
    out = _run_ros(championship.simulate_championship_odds)
    assert out["unsimulable"]["reason"] == "no_scored_weeks_in_league"


def test_the_bracket_is_reported_as_resolved_because_it_was():
    """The refusal must not blame the wrong input.

    This fixture's bracket resolves fine (7 teams from league settings). A repair
    that reported the bracket as unknown to explain the refusal would be a second
    falsehood replacing the first.
    """
    out = _run_ros(championship.simulate_championship_odds)
    assert out.get("playoffSeeds") == 7
    assert (out.get("playoffStructure") or {}).get("playoffTeams") == 7
    assert out.get("rosStrengthAvailable") is True
