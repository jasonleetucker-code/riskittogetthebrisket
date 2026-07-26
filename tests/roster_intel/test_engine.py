"""Tests for ``src/roster_intel/engine.py``.

The headline test is ``TestFragilityIsNotDeficiency``: a consuming agent
derived deficit as ``fragility x marginal`` and got QB reported as the
biggest need on a QB-STRONG roster.  That inversion is pinned here so
the engine's own ``deficit`` can never reproduce it, and so the
semantics stay stated where they are exported.
"""

from __future__ import annotations

import pytest

from src.league_intel.replacement import PositionReplacement, ReplacementLevel
from src.roster_intel.engine import analyze_roster, position_needs
from src.roster_intel.marginal import to_roster_players
from src.roster_intel.profiles import build_position_profiles


def _p(pid, pos, value, **kw):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "fantasyPositions": (),
        **kw,
    }


def _rep(pos, elite, starter, roster, starters_per_team=2.0):
    def lvl(tier, v):
        return ReplacementLevel(
            position=pos,
            tier=tier,
            value=v,
            threshold_rank=None,
            band_low=None,
            band_high=None,
            sample_size=50,
        )

    return PositionReplacement(
        position=pos,
        starters_per_team=starters_per_team,
        rostered_count=50,
        priced_count=50,
        levels={
            "bestBallStarter": lvl("bestBallStarter", elite),
            "starter": lvl("starter", starter),
            "roster": lvl("roster", roster),
        },
    )


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]

REPLACEMENT = {
    "QB": _rep("QB", 80.0, 55.0, 25.0),
    "RB": _rep("RB", 70.0, 45.0, 20.0),
    "WR": _rep("WR", 70.0, 45.0, 20.0),
    "TE": _rep("TE", 50.0, 30.0, 12.0),
}


def _odds(rows):
    return [
        {
            "ownerId": o,
            "playoffOdds": p,
            "championshipOdds": c,
            "playoffOddsCi": [max(0.0, p - 0.05), min(1.0, p + 0.05)],
            "championshipOddsCi": [max(0.0, c - 0.03), min(1.0, c + 0.03)],
        }
        for o, p, c in rows
    ]


# ── The inversion, pinned ──────────────────────────────────────────


class TestFragilityIsNotDeficiency:
    """A QB-strong roster in superflex is BOTH high-marginal and
    high-fragility: two excellent starters, nobody close behind. Any
    'deficit' derived from fragility x marginal therefore reports the
    roster's greatest strength as its greatest need."""

    def _qb_strong(self):
        return to_roster_players(
            [
                _p("qb1", "QB", 95),
                _p("qb2", "QB", 92),  # elite pair
                _p("rb1", "RB", 30),
                _p("rb2", "RB", 28),  # below replacement
                _p("wr1", "WR", 32),
                _p("wr2", "WR", 30),
                _p("te1", "TE", 15),
            ]
        )

    def test_the_naive_derivation_does_invert(self):
        """Documents the defect this guard exists for. If this ever
        stops inverting, the guard below is no longer meaningful and
        someone should re-derive it rather than delete it."""
        prof = build_position_profiles(self._qb_strong(), SLOTS, replacement=REPLACEMENT)
        naive = {pos: p.fragility * p.marginal_points for pos, p in prof.positions.items()}
        # The naive rule crowns QB — the roster's strongest position.
        assert max(naive, key=lambda k: naive[k]) == "QB"

    def test_engine_deficit_does_not_crown_the_strong_position(self):
        """MECHANISM TEST. The engine's own deficit must name a WEAK
        position, not the strong one."""
        prof = build_position_profiles(self._qb_strong(), SLOTS, replacement=REPLACEMENT)
        needs = position_needs(prof, REPLACEMENT)
        assert needs["QB"].deficit == 0.0
        worst = max(needs, key=lambda k: needs[k].deficit)
        assert worst != "QB"
        assert needs[worst].deficit > 0

    def test_concentration_and_deficit_are_reported_separately(self):
        prof = build_position_profiles(self._qb_strong(), SLOTS, replacement=REPLACEMENT)
        needs = position_needs(prof, REPLACEMENT)
        qb = needs["QB"]
        # Strong AND concentrated: high risk, zero deficit. Both true.
        assert qb.concentration_risk > 0.0
        assert qb.deficit == 0.0

    def test_exported_payload_states_the_semantics(self):
        """The semantics must travel WITH the data — a consumer reading
        only the payload has to be able to tell these apart."""
        prof = build_position_profiles(self._qb_strong(), SLOTS, replacement=REPLACEMENT)
        blob = position_needs(prof, REPLACEMENT)["QB"].to_dict()
        sem = blob["_semantics"]
        assert "acquire a starter" in sem["deficit"]
        assert "acquire insurance" in sem["concentrationRisk"]
        assert "do NOT multiply" in sem["warning"]


# ── Deficit behaviour ──────────────────────────────────────────────


class TestDeficit:
    def test_below_replacement_position_shows_a_deficit(self):
        pool = to_roster_players(
            [
                _p("qb1", "QB", 90),
                _p("rb1", "RB", 8),
                _p("rb2", "RB", 6),
                _p("wr1", "WR", 60),
                _p("wr2", "WR", 55),
                _p("te1", "TE", 35),
            ]
        )
        needs = position_needs(
            build_position_profiles(pool, SLOTS, replacement=REPLACEMENT), REPLACEMENT
        )
        assert needs["RB"].deficit > 0
        assert needs["RB"].urgent is True
        assert any("replacement-level" in r for r in needs["RB"].reasons)

    def test_no_replacement_levels_means_no_fabricated_deficit(self):
        """Without levels there is no baseline; inventing one would be
        the 'constant masquerading as a score' failure again."""
        pool = to_roster_players([_p("qb1", "QB", 90), _p("rb1", "RB", 5)])
        needs = position_needs(build_position_profiles(pool, SLOTS))
        assert all(n.deficit == 0.0 for n in needs.values())
        assert all(n.replacement_baseline is None for n in needs.values())

    def test_deficit_scales_with_required_slots(self):
        """Two dedicated RB slots need twice the replacement-level
        contribution of one."""
        pool = to_roster_players([_p("rb1", "RB", 5)])
        one = position_needs(
            build_position_profiles(pool, ["RB"], replacement=REPLACEMENT), REPLACEMENT
        )["RB"]
        two = position_needs(
            build_position_profiles(pool, ["RB", "RB"], replacement=REPLACEMENT),
            REPLACEMENT,
        )["RB"]
        assert two.deficit > one.deficit


# ── playoff_sim wiring ─────────────────────────────────────────────


class TestPlayoffSimWiring:
    def _pool(self):
        return to_roster_players(
            [
                _p("qb1", "QB", 90),
                _p("rb1", "RB", 60),
                _p("rb2", "RB", 55),
                _p("wr1", "WR", 58),
                _p("wr2", "WR", 52),
                _p("te1", "TE", 40),
            ]
        )

    def test_odds_and_intervals_are_read_from_simulator_output(self):
        odds = _odds([("me", 0.72, 0.18), ("other", 0.30, 0.05)])
        intel = analyze_roster("me", self._pool(), SLOTS, playoff_odds=odds)
        assert intel.playoff_odds == pytest.approx(0.72)
        assert intel.championship_odds == pytest.approx(0.18)
        assert intel.playoff_odds_ci == (pytest.approx(0.67), pytest.approx(0.77))
        assert intel.odds_source == "playoff_sim"

    def test_simulator_output_upgrades_the_window_axis(self):
        """MECHANISM TEST. Supplying odds must change the window's
        source from the structural proxy to simulated odds."""
        pool = self._pool()
        proxy = analyze_roster("me", pool, SLOTS, lineup_scores={"me": 500.0, "x": 400.0})
        simmed = analyze_roster(
            "me",
            pool,
            SLOTS,
            playoff_odds=_odds([("me", 0.9, 0.4), ("x", 0.1, 0.01)]),
            lineup_scores={"me": 500.0, "x": 400.0},
        )
        assert proxy.window.inputs.competitiveness_source == "lineupScoreRank"
        assert simmed.window.inputs.competitiveness_source == "championshipOdds"

    def test_missing_simulation_is_stated_not_defaulted_to_zero(self):
        """Zero odds would read as 'certain to miss'; None reads as
        'not simulated'. The difference matters."""
        intel = analyze_roster("me", self._pool(), SLOTS)
        assert intel.playoff_odds is None
        assert intel.championship_odds is None
        assert intel.odds_source == "unavailable"
        assert any("no playoff_sim output" in n for n in intel.notes)

    def test_owner_absent_from_simulation_is_distinguished(self):
        intel = analyze_roster("ghost", self._pool(), SLOTS, playoff_odds=_odds([("me", 0.5, 0.1)]))
        assert intel.odds_source == "owner_not_in_simulation"
        assert intel.playoff_odds is None

    def test_absent_intervals_stay_none_not_zero_width(self):
        """A point estimate with no interval must not read as certain."""
        intel = analyze_roster(
            "me",
            self._pool(),
            SLOTS,
            playoff_odds=[{"ownerId": "me", "playoffOdds": 0.5, "championshipOdds": 0.1}],
        )
        assert intel.playoff_odds == pytest.approx(0.5)
        assert intel.playoff_odds_ci is None


# ── Value rollups ──────────────────────────────────────────────────


class TestValueRollups:
    def test_starter_and_bench_split_follows_the_optimizer(self):
        """MECHANISM TEST. The split must come from the lineup solve,
        not from a top-N slice of the roster."""
        pool = to_roster_players(
            [
                _p("qb1", "QB", 90),
                _p("qb2", "QB", 88),
                _p("qb3", "QB", 86),  # cannot start: only 2 QB-capable slots
                _p("rb1", "RB", 60),
                _p("rb2", "RB", 55),
                _p("wr1", "WR", 58),
                _p("wr2", "WR", 52),
                _p("te1", "TE", 40),
            ]
        )
        v = analyze_roster("me", pool, SLOTS).values
        assert v.bench_ros == pytest.approx(86.0)
        assert v.starters_ros == pytest.approx(v.ros - 86.0)

    def test_parallel_scales_stay_separate(self):
        pool = to_roster_players([_p("a", "QB", 50), _p("b", "RB", 40)])
        pv = {
            "a": {"marketValue": 5000, "consensusValue": 4800, "leagueAdjustedDynastyValue": 5200},
            "b": {"marketValue": 3000, "consensusValue": 3100},
        }
        v = analyze_roster("me", pool, ["QB", "RB"], player_values=pv).values
        assert v.market == pytest.approx(8000)
        assert v.consensus == pytest.approx(7900)
        # b has no adjusted value -> falls back to its consensus.
        assert v.league_adjusted == pytest.approx(5200 + 3100)

    def test_unpriced_players_are_counted_not_hidden(self):
        pool = to_roster_players([_p("a", "QB", 50), _p("b", "RB", 0)])
        v = analyze_roster("me", pool, ["QB", "RB"]).values
        assert v.priced_players == 1
        assert v.unpriced_players == 1


# ── Shape / degradation ────────────────────────────────────────────


class TestShape:
    def test_payload_is_json_shaped_and_complete(self):
        intel = analyze_roster(
            "me",
            to_roster_players([_p("qb1", "QB", 90), _p("rb1", "RB", 50)]),
            SLOTS,
            replacement=REPLACEMENT,
            playoff_odds=_odds([("me", 0.6, 0.12)]),
        )
        blob = intel.to_dict()
        assert set(blob) >= {
            "ownerId",
            "values",
            "lineupScore",
            "positions",
            "needs",
            "competitiveWindow",
            "playoffOdds",
            "championshipOdds",
            "oddsSource",
        }
        assert blob["competitiveWindow"]["probabilities"]
        assert sum(blob["competitiveWindow"]["probabilities"].values()) == pytest.approx(1.0)

    def test_missing_replacement_levels_are_declared(self):
        intel = analyze_roster("me", to_roster_players([_p("qb1", "QB", 90)]), SLOTS)
        assert any("no replacement levels" in n for n in intel.notes)

    def test_analysis_varies_across_distinct_rosters(self):
        seen = set()
        for i in range(12):
            intel = analyze_roster(
                f"t{i}",
                to_roster_players(
                    [
                        _p("qb1", "QB", 60 + i * 3),
                        _p("rb1", "RB", 55 - i),
                        _p("rb2", "RB", 40 + i * 2),
                        _p("wr1", "WR", 58 - i * 2),
                        _p("te1", "TE", 25 + i * 4),
                    ]
                ),
                SLOTS,
                replacement=REPLACEMENT,
                lineup_scores={f"t{j}": 300.0 + j * 40 for j in range(12)},
            )
            seen.add((round(intel.lineup_score, 3), round(intel.needs["RB"].deficit, 3)))
        assert len(seen) == 12


# ── Disclosure of dead inputs ──────────────────────────────────────


class TestInputDisclosure:
    """Two inputs can be silently absent and leave a plausible payload
    behind.  Both must announce themselves.

    Measured on the real league: no committed artifact carries player
    ages, so every roster's trajectory axis sat at exactly 0.500 with
    sample size 0, and ``productive_struggle`` — the state that needs a
    young roster with a bad record — was unreachable for all 12 teams.
    Nothing in the payload said so.
    """

    _POOL = [
        _p("qb1", "QB", 90),
        _p("qb2", "QB", 70),
        _p("rb1", "RB", 60),
        _p("rb2", "RB", 45),
        _p("wr1", "WR", 65),
        _p("wr2", "WR", 40),
        _p("te1", "TE", 35),
    ]

    def _run(self, meta=None):
        return analyze_roster(
            "me",
            to_roster_players(self._POOL),
            SLOTS,
            replacement=REPLACEMENT,
            player_meta=meta,
            lineup_scores={"me": 300.0, "other": 200.0},
        )

    def test_absent_ages_are_disclosed(self):
        intel = self._run()
        assert intel.window.inputs.trajectory_sample == 0
        assert intel.window.inputs.trajectory == pytest.approx(0.5)
        assert any("ages" in n for n in intel.notes)

    def test_supplied_ages_move_the_axis_and_drop_the_note(self):
        """MECHANISM TEST. Fails if ``player_meta`` stops reaching the
        window — the note would keep firing, and the trajectory would
        stay pinned, on data that HAS ages."""
        young = self._run({p["playerId"]: {"age": 22} for p in self._POOL})
        old = self._run({p["playerId"]: {"age": 33} for p in self._POOL})

        for intel in (young, old):
            assert intel.window.inputs.trajectory_sample > 0
            assert not any("ages" in n for n in intel.notes)

        assert young.window.inputs.trajectory > 0.5
        assert old.window.inputs.trajectory < 0.5
        # ...and the axis must actually change the distribution, not
        # just the diagnostic block.
        assert young.window.probabilities != old.window.probabilities

    def test_ages_unlock_states_a_one_dimensional_read_cannot_reach(self):
        """The concrete cost of the dead axis: a weak-but-young roster
        and a weak-but-old roster must not receive the same label."""
        weak = {"me": 100.0, "a": 300.0, "b": 320.0, "c": 340.0}
        young = analyze_roster(
            "me",
            to_roster_players(self._POOL),
            SLOTS,
            replacement=REPLACEMENT,
            player_meta={p["playerId"]: {"age": 22} for p in self._POOL},
            lineup_scores=weak,
        )
        old = analyze_roster(
            "me",
            to_roster_players(self._POOL),
            SLOTS,
            replacement=REPLACEMENT,
            player_meta={p["playerId"]: {"age": 33} for p in self._POOL},
            lineup_scores=weak,
        )
        assert young.window.most_likely != old.window.most_likely

    def test_override_does_not_trigger_the_age_note(self):
        """A pinned window is a stated intent; the trajectory axis is
        not being used, so warning about it is noise."""
        intel = analyze_roster(
            "me",
            to_roster_players(self._POOL),
            SLOTS,
            replacement=REPLACEMENT,
            override_state="rebuild",
            override_reason="manager said so",
        )
        assert intel.window.overridden
        assert not any("ages" in n for n in intel.notes)

    def test_zero_unpriced_is_not_sold_as_join_coverage(self):
        """``build_roster_pool`` DROPS names it cannot value, so on the
        live path ``unpricedPlayers`` is structurally 0 while real
        players went missing.  Zero must not read as full coverage."""
        clean = self._run()
        assert clean.values.unpriced_players == 0
        assert any("join-coverage" in n for n in clean.notes)

        with_unpriced = analyze_roster(
            "me",
            to_roster_players([*self._POOL, _p("ghost", "WR", 0)]),
            SLOTS,
            replacement=REPLACEMENT,
        )
        assert with_unpriced.values.unpriced_players == 1
        assert not any("join-coverage" in n for n in with_unpriced.notes)
