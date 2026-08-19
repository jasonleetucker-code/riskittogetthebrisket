"""LI-8 tests for ``src/ros/playoff_sim.py``.

Covers the four LI-8 deliverables:

  1. the sim uses the EXACT lineup optimizer (and therefore inherits the
     ``fantasy_positions`` fix), not the old slot-ordered greedy;
  2. the duplicated starter-slot flattener is gone — one implementation;
  3. trade impact runs on SHARED seeds and refuses to call a delta
     smaller than simulation error meaningful;
  4. simulation counts are convergence-driven, not fixed.

No network, no on-disk artifacts: distributions are injected.
"""

from __future__ import annotations

import random

import pytest

from src.ros import lineup, playoff_sim
from src.ros.playoff_sim import (
    _TeamDist,
    _bestball_weekly_score,
    _mean_is_converged,
    _paired_delta_ci,
    _proportion_se,
    _simulate_bracket,
    _wilson_interval,
    simulate_trade_impact,
)


# ── 2. One flattener ───────────────────────────────────────────────


class TestNoDuplication:
    def test_playoff_sim_reuses_the_canonical_flattener(self):
        assert playoff_sim._load_starter_slots is lineup.load_league_starter_slots

    def test_scrape_reuses_the_canonical_flattener(self):
        from src.ros import scrape

        assert scrape._flatten_starter_slots is lineup.flatten_starter_slots

    def test_playoff_sim_no_longer_defines_its_own_eligibility(self):
        # The private copy is gone; eligibility has exactly one home.
        assert "_eligible_for_slot" not in vars(playoff_sim)

    def test_flattener_normalizes_slot_aliases(self):
        # SFLEX was aliased in two private maps that could drift apart.
        assert lineup.flatten_starter_slots({"SFLEX": 1}) == ["SUPER_FLEX"]

    def test_a_wr_rb_flex_is_not_a_full_flex(self):
        """This assertion is INVERTED from what it said before C2-U1, and
        the old form was pinning a defect.

        ``WRRB_FLEX`` normalized to ``FLEX``, and ``FLEX`` accepts a tight
        end — so a slot whose whole point is excluding tight ends would
        have taken one.  It is now its own slot with its own eligibility.
        Neither live league runs one, so nothing on the board moves; this
        is the table being right rather than lucky.
        """
        assert lineup.flatten_starter_slots({"WRRB_FLEX": 2}) == ["WR_RB_FLEX"] * 2
        assert lineup.slot_eligible_positions("WRRB_FLEX") == frozenset({"RB", "WR"})
        assert "TE" not in lineup.slot_eligible_positions("WRRB_FLEX")
        assert "TE" in lineup.slot_eligible_positions("FLEX")

    def test_flattener_skips_junk_counts(self):
        assert lineup.flatten_starter_slots({"QB": 0, "RB": -1, "WR": "x", "TE": 2}) == [
            "TE",
            "TE",
        ]

    def test_flattener_handles_empty(self):
        assert lineup.flatten_starter_slots(None) == []
        assert lineup.flatten_starter_slots({}) == []


# ── 1. Exact lineup inside the sim ─────────────────────────────────


def _p(pid: str, pos: str, value: float, fpos: tuple[str, ...] = ()) -> dict:
    return {
        "playerId": pid,
        "position": pos,
        "rosValue": value,
        "fantasyPositions": fpos,
    }


class _FixedModel:
    """Deterministic points model: points == rosValue, no variance.

    Lets a lineup assertion be exact instead of statistical.
    """

    source = "test-fixed"
    generated_at = None

    def draw(self, ros_value, position, rng):  # noqa: ARG002
        return float(ros_value)


class TestExactLineupInSim:
    def test_weekly_score_is_the_optimal_assignment(self):
        # QB 10, RB 9, WR 8. Slots QB + FLEX(RB/WR/TE) + SUPER_FLEX.
        # Optimal: QB→QB(10), RB→SFLEX(9), WR→FLEX(8) = 27.
        roster = [_p("qb", "QB", 10.0), _p("rb", "RB", 9.0), _p("wr", "WR", 8.0)]
        total = _bestball_weekly_score(
            roster, ["QB", "FLEX", "SUPER_FLEX"], random.Random(1), _FixedModel()
        )
        assert total == pytest.approx(27.0)

    def test_hybrid_idp_can_fill_either_legal_slot(self):
        # A DL/LB hybrid plus a pure DL. With one DL and one LB slot the
        # optimal answer starts both — only possible if the sim honors
        # fantasy_positions. The pre-LI-8 sim matched on `position`
        # alone and would have left the LB slot empty.
        roster = [
            _p("hybrid", "DL", 12.0, fpos=("DL", "LB")),
            _p("puredl", "DL", 9.0),
        ]
        total = _bestball_weekly_score(roster, ["DL", "LB"], random.Random(1), _FixedModel())
        assert total == pytest.approx(21.0)

    def test_non_laminar_slots_beat_the_old_greedy(self):
        # Slots: FLEX(RB/WR/TE) and DL. Players: a WR(10) and a DL(1).
        # Any correct solver starts both for 11.
        roster = [_p("wr", "WR", 10.0), _p("dl", "DL", 1.0)]
        assert _bestball_weekly_score(
            roster, ["FLEX", "DL"], random.Random(1), _FixedModel()
        ) == pytest.approx(11.0)

    def test_empty_inputs_score_zero(self):
        assert _bestball_weekly_score([], ["QB"], random.Random(1)) == 0.0
        assert _bestball_weekly_score([_p("a", "QB", 5.0)], [], random.Random(1)) == 0.0

    def test_unpriced_players_are_skipped(self):
        roster = [_p("a", "QB", 0.0), _p("b", "QB", 10.0)]
        assert _bestball_weekly_score(
            roster, ["QB"], random.Random(1), _FixedModel()
        ) == pytest.approx(10.0)


# ── 4. Convergence ─────────────────────────────────────────────────


class TestConvergence:
    def test_short_sample_is_never_converged(self):
        assert _mean_is_converged([1.0, 2.0], 0.01) is False

    def test_zero_variance_converges_immediately(self):
        assert _mean_is_converged([5.0] * 10, 0.01) is True

    def test_tight_sample_converges_before_a_noisy_one(self):
        rng = random.Random(11)
        tight = [rng.gauss(100, 1) for _ in range(200)]
        noisy = [rng.gauss(100, 60) for _ in range(200)]
        assert _mean_is_converged(tight, 0.01) is True
        assert _mean_is_converged(noisy, 0.01) is False

    def test_all_zero_sample_uses_the_absolute_criterion(self):
        # A relative test can never be satisfied at mean 0; without the
        # absolute fallback this would spin to the cap.
        assert _mean_is_converged([0.0] * 20, 0.01) is True

    def test_proportion_se_shrinks_with_n(self):
        assert _proportion_se(0.5, 100) > _proportion_se(0.5, 10000)
        assert _proportion_se(0.5, 0) == 0.0


class TestWilsonInterval:
    def test_interval_brackets_the_point_estimate(self):
        lo, hi = _wilson_interval(500, 1000)
        assert lo < 0.5 < hi

    def test_interval_stays_inside_zero_one_at_the_boundary(self):
        lo, hi = _wilson_interval(0, 1000)
        assert lo == 0.0
        # The honest part: zero successes does NOT mean zero probability.
        assert hi > 0.0
        lo2, hi2 = _wilson_interval(1000, 1000)
        assert hi2 == 1.0 and lo2 < 1.0

    def test_interval_narrows_as_n_grows(self):
        n_lo, n_hi = _wilson_interval(50, 100)
        w_lo, w_hi = _wilson_interval(5000, 10000)
        assert (w_hi - w_lo) < (n_hi - n_lo)

    def test_zero_n_is_maximally_uncertain(self):
        assert _wilson_interval(0, 0) == (0.0, 1.0)


# ── 3. Trade impact on shared seeds ────────────────────────────────


def _dists(means: dict[str, float], sd: float = 20.0) -> dict[str, _TeamDist]:
    return {o: _TeamDist(owner_id=o, mean=m, sd=sd, pf_to_date=0.0) for o, m in means.items()}


class TestPairedDeltaCi:
    def test_identical_arms_have_a_zero_delta(self):
        lo, hi = _paired_delta_ci(500, 500, 1000)
        assert lo <= 0.0 <= hi

    def test_interval_excludes_zero_for_a_large_shift(self):
        lo, hi = _paired_delta_ci(100, 900, 1000)
        assert lo > 0.0

    def test_interval_spans_zero_for_a_tiny_shift(self):
        # A 3-in-1000 move is inside the noise floor and must not be
        # sold as a result.
        lo, hi = _paired_delta_ci(500, 503, 1000)
        assert lo < 0.0 < hi

    def test_zero_n_is_a_zero_interval(self):
        assert _paired_delta_ci(0, 0, 0) == (0.0, 0.0)


class TestSimulateTradeImpact:
    @pytest.fixture(autouse=True)
    def _stub_league(self, monkeypatch):
        """Inject distributions + a trivial schedule; no snapshot I/O."""
        owners = {f"o{i}": 100.0 for i in range(1, 9)}
        base = _dists(owners)
        monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda: {})
        monkeypatch.setattr(
            playoff_sim,
            "_build_team_distributions",
            lambda *a, **k: (base, {o: 0.0 for o in owners}),
        )
        monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda: False)
        monkeypatch.setattr(playoff_sim, "_current_record", lambda s: {})
        # Round-robin-ish schedule so wins actually differentiate.
        names = sorted(owners)
        sched = [
            (w, names[i], names[i + 1]) for w in range(1, 6) for i in range(0, len(names) - 1, 2)
        ]
        monkeypatch.setattr(playoff_sim, "_remaining_schedule", lambda s: sched)
        monkeypatch.setattr(playoff_sim.metrics, "display_name_for", lambda s, o: f"Team {o}")
        self.owners = names

    def test_zero_delta_trade_produces_no_significant_movement(self):
        out = simulate_trade_impact(
            snapshot=None,
            strength_delta={},
            n_simulations=1500,
            playoff_seeds=4,
            bye_seeds=2,
        )
        # Shared seeds mean an empty trade is EXACTLY zero everywhere —
        # this is the property an unpaired run would not have.
        assert all(r["delta"] == 0.0 for r in out["playoff"])
        assert all(r["significant"] is False for r in out["playoff"])
        assert out["meaningfulDeltas"] == 0

    def test_shared_seed_is_reported_and_reproducible(self):
        a = simulate_trade_impact(
            snapshot=None, strength_delta={"o1": 25.0}, n_simulations=1200, seed=99
        )
        b = simulate_trade_impact(
            snapshot=None, strength_delta={"o1": 25.0}, n_simulations=1200, seed=99
        )
        assert a["sharedSeed"] == 99
        assert [r["delta"] for r in a["playoff"]] == [r["delta"] for r in b["playoff"]]

    def test_large_upgrade_moves_that_team_up_significantly(self):
        out = simulate_trade_impact(
            snapshot=None,
            strength_delta={"o1": 60.0},
            n_simulations=3000,
            playoff_seeds=4,
            bye_seeds=2,
        )
        row = next(r for r in out["playoff"] if r["ownerId"] == "o1")
        assert row["delta"] > 0
        assert row["significant"] is True
        # The interval must not span zero when we call it significant.
        assert row["deltaCi"][0] > 0

    def test_every_row_carries_an_interval(self):
        out = simulate_trade_impact(snapshot=None, strength_delta={"o1": 10.0}, n_simulations=1200)
        for r in out["playoff"] + out["championship"]:
            assert len(r["deltaCi"]) == 2
            assert r["deltaCi"][0] <= r["delta"] <= r["deltaCi"][1] or r["delta"] == 0.0

    def test_championship_deltas_are_reported(self):
        out = simulate_trade_impact(
            snapshot=None,
            strength_delta={"o1": 60.0},
            n_simulations=2000,
            playoff_seeds=4,
            bye_seeds=2,
        )
        assert out["championship"], "championship deltas must be present"
        champ_total = sum(r["after"] for r in out["championship"])
        # Exactly one champion per sim ⇒ the odds are a distribution.
        assert champ_total == pytest.approx(1.0, abs=0.02)

    def test_methodology_states_the_significance_rule(self):
        out = simulate_trade_impact(
            snapshot=None, strength_delta={}, n_simulations=800, playoff_seeds=4, bye_seeds=0
        )
        assert "shared RNG seed" in out["methodology"]
        assert "significant=false" in out["methodology"]

    def test_no_distributions_returns_an_explicit_empty(self, monkeypatch):
        monkeypatch.setattr(playoff_sim, "_build_team_distributions", lambda *a, **k: ({}, {}))
        # The bracket is pinned so this exercises the NO-DISTRIBUTIONS
        # refusal it is named for. Since V1-51 a ``snapshot=None`` has no
        # resolvable bracket either, and that refusal fires first — the
        # test would pass for the wrong reason without this.
        out = simulate_trade_impact(
            snapshot=None, strength_delta={"o1": 5.0}, playoff_seeds=4, bye_seeds=0
        )
        assert out["playoff"] == []
        assert out["meaningfulDeltas"] == 0
        assert out["note"] == "no team distributions available"

    def test_an_unknown_bracket_refuses_with_the_full_envelope(self):
        """V1-51. A refusal that drops keys the normal return carries makes
        every consumer branch on shape before it can read anything — and
        ``methodology`` is the field a caller reads to explain why there is
        no result."""
        out = simulate_trade_impact(snapshot=None, strength_delta={"o1": 5.0})
        assert out["playoff"] == [] and out["championship"] == []
        assert out["unsimulable"]["reason"] == "no_current_season"
        assert "shared RNG seed" in out["methodology"]
        assert out["note"] == "playoff bracket unknown"


# ── Bracket ────────────────────────────────────────────────────────


class TestBracket:
    def test_champion_comes_from_the_seeded_field(self):
        d = _dists({f"o{i}": 100.0 for i in range(1, 7)})
        champ = _simulate_bracket(list(d), d, 2, random.Random(4))
        assert champ in d

    def test_dominant_seed_wins_most_of_the_time(self):
        d = _dists({"strong": 200.0, "a": 80.0, "b": 80.0, "c": 80.0}, sd=5.0)
        rng = random.Random(5)
        wins = sum(
            1
            for _ in range(300)
            if _simulate_bracket(["strong", "a", "b", "c"], d, 1, rng) == "strong"
        )
        assert wins > 250

    def test_empty_field_returns_none(self):
        assert _simulate_bracket([], {}, 2, random.Random(1)) is None

    def test_single_team_field_wins_by_default(self):
        d = _dists({"solo": 100.0})
        assert _simulate_bracket(["solo"], d, 2, random.Random(1)) == "solo"
