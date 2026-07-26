"""Tests for the Target Position and Target Player engines.

The two properties this suite exists to defend, both of which are
directive constraints rather than nice-to-haves:

1. **The weakest position is not automatically the recommendation.** A
   position nobody can upgrade is reported as a confirmed weakness and
   excluded from the ranked targets.
2. **No player is recommended on market edge alone.** Edge is derived
   from our own valuation and cannot corroborate itself.

Everything else here is supporting evidence that those two gates are
real branches rather than score terms that happen to be small.
"""

from __future__ import annotations

import pytest

from src.league_intel.replacement import (
    PositionReplacement,
    ReplacementLevel,
    ScarcityComponents,
)
from src.roster_intel.profiles import build_position_profiles
from src.roster_intel.targets import (
    MIN_CORROBORATING_SIGNALS,
    MIN_MATERIAL_POINTS,
    REALISTIC_CANDIDATE_DEPTH,
    TARGETS_MODEL_VERSION,
    PlayerTarget,
    TargetViability,
    ValueSignal,
    describe_limitations,
    rank_target_players,
    rank_target_positions,
    win_now_weight,
)
from src.roster_intel.window import COMPETITIVE_STATES, CompetitiveWindow, WindowInputs
from src.ros.lineup import RosterPlayer

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]


def _p(pid: str, pos: str, value: float, name: str | None = None) -> RosterPlayer:
    return RosterPlayer(
        player_id=pid,
        canonical_name=name or f"{pos} {pid}",
        position=pos,
        ros_value=value,
    )


def _roster() -> list[RosterPlayer]:
    """A roster that is strong at RB/WR and genuinely thin at TE."""
    return [
        _p("qb1", "QB", 100.0),
        _p("rb1", "RB", 90.0),
        _p("rb2", "RB", 80.0),
        _p("rb3", "RB", 70.0),
        _p("wr1", "WR", 95.0),
        _p("wr2", "WR", 85.0),
        _p("wr3", "WR", 60.0),
        _p("te1", "TE", 20.0),
    ]


def _window(**probs: float) -> CompetitiveWindow:
    full = {s: 0.0 for s in COMPETITIVE_STATES}
    full.update(probs)
    total = sum(full.values()) or 1.0
    full = {k: v / total for k, v in full.items()}
    return CompetitiveWindow(
        probabilities=full,
        inputs=WindowInputs(
            competitiveness=0.5,
            trajectory=0.5,
            competitiveness_source="test",
            trajectory_sample=8,
        ),
        most_likely=max(full, key=lambda k: full[k]),
    )


# ══ Gate 1: obtainability ════════════════════════════════════════════


class TestObtainabilityGate:
    def test_weakest_position_is_not_a_target_when_nobody_can_fix_it(self):
        """The headline requirement.

        TE is by far the weakest spot on this roster, but every TE on
        the market is worse than the one already rostered. The engine
        must report a confirmed weakness and must NOT rank it.
        """
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={
                "TE": [_p("fa_te1", "TE", 12.0), _p("fa_te2", "TE", 8.0)],
            },
        )
        te = next(t for t in targets if t.position == "TE")
        assert te.viability is TargetViability.NO_OBTAINABLE_UPGRADE
        assert te.priority == 0.0
        assert "cannot currently be fixed" in te.reason

        viable = [t for t in targets if t.viability is TargetViability.VIABLE]
        assert "TE" not in {t.position for t in viable}

    def test_a_real_upgrade_does_pass_the_gate(self):
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={"TE": [_p("elite_te", "TE", 88.0), _p("good_te", "TE", 75.0)]},
        )
        te = next(t for t in targets if t.position == "TE")
        assert te.viability is TargetViability.VIABLE
        assert te.priority > 0
        assert te.realistic_gain >= MIN_MATERIAL_POINTS

    def test_gain_is_measured_by_resolving_the_lineup_not_by_value(self):
        """A 200-point QB is worth less to THIS roster than a 60-point
        TE, because the QB slot is already filled and the TE slot is a
        hole. Only an actual re-solve can express that."""
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={
                "QB": [_p("qb_stud", "QB", 200.0)],
                "TE": [_p("te_ok", "TE", 60.0)],
            },
        )
        by_pos = {t.position: t for t in targets}
        # QB upgrade replaces a 100 starter -> +100. TE replaces 20 -> +40.
        assert by_pos["QB"].best_case_gain == pytest.approx(100.0)
        assert by_pos["TE"].best_case_gain == pytest.approx(40.0)

    def test_trivial_gain_is_rejected_as_immaterial(self):
        """A strictly-positive test would let every position through and
        turn the gate back into the ranking it replaced."""
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={"TE": [_p("marginal_te", "TE", 21.0)]},
        )
        te = next(t for t in targets if t.position == "TE")
        assert te.viability is TargetViability.IMMATERIAL_GAIN
        assert te.best_case_gain == pytest.approx(1.0)
        assert te.priority == 0.0

    def test_missing_candidates_is_not_measured_not_nothing_available(self):
        """These are different claims and must never be collapsed."""
        pool = _roster()
        targets = rank_target_positions(pool, SLOTS, candidates={"TE": []}, profile=None)
        te = next(t for t in targets if t.position == "TE")
        assert te.viability is TargetViability.NO_CANDIDATES
        assert "not measured" in te.reason
        assert te.viability is not TargetViability.NO_OBTAINABLE_UPGRADE

    def test_realistic_gain_uses_median_not_best_case(self):
        """Gating on the best available player is best-case reasoning in
        a measurement's clothing — every position justifies itself with
        'if I land the best guy on the market'."""
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={
                "TE": [
                    _p("one_stud", "TE", 90.0),
                    _p("dud_a", "TE", 10.0),
                    _p("dud_b", "TE", 9.0),
                ]
            },
        )
        te = next(t for t in targets if t.position == "TE")
        assert te.best_case_gain == pytest.approx(70.0)
        # Median of [70, 0, 0] is 0 -> a lottery ticket, not a fixable hole.
        assert te.realistic_gain == pytest.approx(0.0)
        assert te.viability is TargetViability.IMMATERIAL_GAIN

    def test_consistent_depth_clears_where_one_stud_does_not(self):
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={
                "TE": [
                    _p("te_a", "TE", 80.0),
                    _p("te_b", "TE", 75.0),
                    _p("te_c", "TE", 70.0),
                ]
            },
        )
        te = next(t for t in targets if t.position == "TE")
        assert te.viability is TargetViability.VIABLE
        assert te.realistic_gain == pytest.approx(55.0)

    def test_non_viable_positions_are_still_returned_for_display(self):
        """A caller has to be able to show 'your worst spot is TE and
        nothing helps' — silently omitting it would be worse than not
        ranking it."""
        pool = _roster()
        targets = rank_target_positions(pool, SLOTS, candidates={"TE": [_p("bad_te", "TE", 5.0)]})
        assert any(t.position == "TE" for t in targets)

    def test_viable_sort_before_non_viable(self):
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={
                "TE": [_p("bad", "TE", 1.0)],
                "QB": [_p("qb_up", "QB", 150.0)],
            },
        )
        assert targets[0].position == "QB"
        assert targets[0].viability is TargetViability.VIABLE
        assert targets[-1].viability is not TargetViability.VIABLE


# ══ Window consumption ══════════════════════════════════════════════


class TestWinNowWeight:
    def test_uses_the_full_distribution_not_the_argmax(self):
        """The roster engine reports probabilities precisely so
        consumers stop collapsing to a label. A near-tie and a decisive
        read must not produce the same weight."""
        decisive = _window(retool=0.85, rebuild=0.15)
        split = _window(retool=0.45, rebuild=0.40, playoff_contender=0.15)
        assert win_now_weight(decisive) != pytest.approx(win_now_weight(split))

    def test_contender_values_win_now_more_than_rebuilder(self):
        contender = _window(championship_contender=1.0)
        rebuilder = _window(rebuild=1.0)
        assert win_now_weight(contender) > win_now_weight(rebuilder)

    def test_rebuild_is_discounted_not_zeroed(self):
        """A rebuilder still prefers more points to fewer at equal cost;
        what changes is the price it should pay."""
        assert 0.0 < win_now_weight(_window(rebuild=1.0)) < 0.5

    def test_absent_window_is_neutral(self):
        assert win_now_weight(None) == pytest.approx(1.0)

    def test_window_scales_priority(self):
        pool = _roster()
        cands = {"TE": [_p("te_a", "TE", 80.0), _p("te_b", "TE", 78.0), _p("te_c", "TE", 76.0)]}
        contender = rank_target_positions(
            pool, SLOTS, candidates=cands, window=_window(championship_contender=1.0)
        )[0]
        rebuilder = rank_target_positions(
            pool, SLOTS, candidates=cands, window=_window(rebuild=1.0)
        )[0]
        assert contender.priority > rebuilder.priority
        # The measured gain is identical; only its worth to us changed.
        assert contender.realistic_gain == pytest.approx(rebuilder.realistic_gain)


# ══ Gate 2: corroboration ═══════════════════════════════════════════


class TestCorroborationGate:
    def test_market_edge_alone_is_rejected(self):
        """The headline requirement for the player engine.

        This candidate is cheap relative to our valuation and nothing
        else. That is the model agreeing with itself.
        """
        pool = _roster()
        cand = _p("edge_only", "QB", 30.0)
        out = rank_target_players(pool, SLOTS, [cand], market_values={"edge_only": 10.0})
        assert len(out) == 1
        t = out[0]
        assert t.recommended is False
        assert ValueSignal.MARKET_EDGE in t.signals
        assert t.corroborating == ()
        assert "agreeing with itself" in t.reason

    def test_edge_plus_one_corroborator_is_admitted(self):
        pool = _roster()
        cand = _p("real_te", "TE", 80.0)
        out = rank_target_players(pool, SLOTS, [cand], market_values={"real_te": 40.0})
        t = out[0]
        assert t.recommended is True
        assert ValueSignal.ROSTER_FIT in t.corroborating
        assert ValueSignal.MARKET_EDGE in t.signals

    def test_market_edge_is_not_a_corroborating_signal(self):
        """Structural guarantee, independent of any particular input."""
        from src.roster_intel.targets import CORROBORATING_SIGNALS

        assert ValueSignal.MARKET_EDGE not in CORROBORATING_SIGNALS
        assert len(CORROBORATING_SIGNALS) >= 1

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"role_scores": {"c": 0.9}}, ValueSignal.ROLE),
            ({"projection_scores": {"c": 0.9}}, ValueSignal.PROJECTION),
            ({"availability": {"c": 0.9}}, ValueSignal.AVAILABILITY),
        ],
    )
    def test_each_external_signal_can_carry_the_gate(self, kwargs, expected):
        """Each corroborator is independently sufficient, so a player
        with no lineup fit can still be a legitimate target on external
        evidence."""
        pool = _roster()
        cand = _p("c", "WR", 30.0)
        out = rank_target_players(pool, SLOTS, [cand], **kwargs)
        t = out[0]
        assert t.recommended is True
        assert expected in t.corroborating

    def test_scarcity_corroborates_only_when_genuinely_scarce(self):
        pool = _roster()
        cand = _p("c", "TE", 25.0)
        scarce = ScarcityComponents(
            position="TE",
            lineup_scarcity=None,
            roster_scarcity=None,
            waiver_scarcity=0.9,
            elite_separation=None,
            starter_separation=None,
            replacement_gap=None,
        )
        plentiful = ScarcityComponents(
            position="TE",
            lineup_scarcity=None,
            roster_scarcity=None,
            waiver_scarcity=0.1,
            elite_separation=None,
            starter_separation=None,
            replacement_gap=None,
        )
        assert rank_target_players(pool, SLOTS, [cand], scarcity={"TE": scarce})[0].recommended
        assert not rank_target_players(pool, SLOTS, [cand], scarcity={"TE": plentiful})[
            0
        ].recommended

    def test_no_signal_at_all_is_rejected_with_a_distinct_reason(self):
        """'Nothing to recommend' must read differently from 'edge
        only' — they are different failures."""
        pool = _roster()
        cand = _p("nobody", "WR", 5.0)
        t = rank_target_players(pool, SLOTS, [cand])[0]
        assert t.recommended is False
        assert "no admissible value signal" in t.reason

    def test_gate_threshold_is_honoured(self):
        pool = _roster()
        cand = _p("real_te", "TE", 80.0)
        strict = rank_target_players(
            pool, SLOTS, [cand], market_values={"real_te": 40.0}, min_corroborating=2
        )[0]
        assert strict.recommended is False
        assert len(strict.corroborating) < 2

    def test_rejected_candidates_are_returned_not_dropped(self):
        pool = _roster()
        out = rank_target_players(
            pool,
            SLOTS,
            [_p("good", "TE", 80.0), _p("edge_only", "QB", 30.0)],
            market_values={"edge_only": 10.0, "good": 50.0},
        )
        assert len(out) == 2
        assert out[0].recommended is True
        assert out[-1].recommended is False


# ══ Ranking behaviour ═══════════════════════════════════════════════


class TestRanking:
    def test_confidence_reduces_priority(self):
        """Same measured gain, less supplied evidence, lower rank —
        matching the partner model's treatment of confidence."""
        pool = _roster()
        cands = {"TE": [_p("a", "TE", 80.0), _p("b", "TE", 78.0), _p("c", "TE", 76.0)]}
        bare = rank_target_positions(pool, SLOTS, candidates=cands)[0]
        rich = rank_target_positions(
            pool,
            SLOTS,
            candidates=cands,
            window=_window(championship_contender=1.0),
            scarcity={
                "TE": ScarcityComponents(
                    position="TE",
                    lineup_scarcity=None,
                    roster_scarcity=None,
                    waiver_scarcity=0.5,
                    elite_separation=None,
                    starter_separation=None,
                    replacement_gap=None,
                )
            },
        )[0]
        assert rich.confidence > bare.confidence

    def test_thin_candidate_sample_is_flagged_and_discounted(self):
        pool = _roster()
        thin = rank_target_positions(pool, SLOTS, candidates={"TE": [_p("a", "TE", 80.0)]})[0]
        assert any("thin sample" in n for n in thin.notes)
        assert thin.candidates_tested < REALISTIC_CANDIDATE_DEPTH

    def test_positions_ranked_by_priority_descending(self):
        pool = _roster()
        targets = rank_target_positions(
            pool,
            SLOTS,
            candidates={
                "TE": [_p("t1", "TE", 80.0), _p("t2", "TE", 79.0), _p("t3", "TE", 78.0)],
                "WR": [_p("w1", "WR", 97.0), _p("w2", "WR", 96.0), _p("w3", "WR", 96.0)],
            },
        )
        viable = [t for t in targets if t.viability is TargetViability.VIABLE]
        assert [t.priority for t in viable] == sorted([t.priority for t in viable], reverse=True)
        # TE is the bigger hole and should win on measured gain.
        assert viable[0].position == "TE"

    def test_ranking_is_deterministic(self):
        pool = _roster()
        cands = {"TE": [_p("a", "TE", 80.0), _p("b", "TE", 80.0), _p("c", "TE", 80.0)]}
        first = [t.to_dict() for t in rank_target_positions(pool, SLOTS, candidates=cands)]
        second = [t.to_dict() for t in rank_target_positions(pool, SLOTS, candidates=cands)]
        assert first == second

    def test_player_priority_anchors_on_measured_points(self):
        """Edge adjusts, it does not drive. A player with a huge edge
        but no lineup impact must not outrank a real upgrade."""
        pool = _roster()
        out = rank_target_players(
            pool,
            SLOTS,
            [
                _p("big_upgrade", "TE", 85.0),
                _p("cheap_bench", "WR", 30.0),
            ],
            market_values={"big_upgrade": 84.0, "cheap_bench": 3.0},
            role_scores={"cheap_bench": 0.9},
        )
        rec = [t for t in out if t.recommended]
        assert rec[0].player_id == "big_upgrade"


# ══ Integration with the roster engine ══════════════════════════════


class TestRosterEngineIntegration:
    def test_consumes_a_real_roster_profile(self):
        """Uses the roster engine's own builder rather than a hand-made
        stand-in, so a shape change upstream fails here."""
        pool = _roster()
        replacement = {
            "TE": PositionReplacement(
                position="TE",
                starters_per_team=1.0,
                rostered_count=12,
                levels={
                    "starter": ReplacementLevel(
                        position="TE",
                        tier="starter",
                        value=50.0,
                        threshold_rank=12,
                        band_low=45.0,
                        band_high=55.0,
                        sample_size=24,
                    )
                },
            )
        }
        profile = build_position_profiles(pool, SLOTS, replacement=replacement)
        targets = rank_target_positions(
            pool,
            SLOTS,
            profile=profile,
            candidates={"TE": [_p("up", "TE", 80.0), _p("up2", "TE", 78.0), _p("up3", "TE", 76.0)]},
            replacement=replacement,
            market_prices={"TE": 60.0},
        )
        te = next(t for t in targets if t.position == "TE")
        assert te.viability is TargetViability.VIABLE
        assert te.market_efficiency is not None
        assert te.severity >= 0.0

    def test_flex_is_never_reported_as_a_target_position(self):
        """The roster engine deliberately does not attribute FLEX /
        SUPER_FLEX to any position because who fills them is
        endogenous. Inventing a FLEX target would reintroduce exactly
        the even-split assumption that was measured wrong."""
        pool = _roster()
        profile = build_position_profiles(pool, SLOTS)
        targets = rank_target_positions(pool, SLOTS, profile=profile)
        positions = {t.position for t in targets}
        assert not positions & {"FLEX", "SUPER_FLEX", "IDP_FLEX", "BN"}

    def test_partner_signal_bridges_from_engine_output(self):
        from src.roster_intel.partner import RosterSignal

        pool = _roster()
        profile = build_position_profiles(pool, SLOTS)
        window = _window(championship_contender=0.6, playoff_contender=0.2, rebuild=0.2)
        sig = RosterSignal.from_engine("owner1", profile=profile, window=window)
        assert sig.owner_id == "owner1"
        assert sig.contend_probability == pytest.approx(0.8)
        assert not set(sig.surplus) & {"FLEX", "SUPER_FLEX", "BN"}

    def test_partner_signal_degrades_without_engine_output(self):
        from src.roster_intel.partner import RosterSignal

        sig = RosterSignal.from_engine("owner1")
        assert sig.surplus == {}
        assert sig.deficit == {}
        assert sig.contend_probability is None
        assert sig.has_window is False

    def test_deficit_identifies_the_weak_position_not_the_concentrated_one(self):
        """Regression, and the important one.

        This roster is strong at QB (100 vs a 90 starter level) and
        genuinely thin at TE (20 vs 50). A lone elite QB has fragility
        1.0 because losing him erases the whole group, so any deficit
        built from ``fragility x marginal_points`` reports QB as the
        biggest hole — which would tell the partner model to send a
        quarterback to a team that already has a good one.

        Deficit must track shortfall below a startable baseline.
        """
        from src.roster_intel.partner import RosterSignal

        pool = _roster()
        profile = build_position_profiles(pool, SLOTS)
        sig = RosterSignal.from_engine(
            "owner1",
            profile=profile,
            starter_levels={"QB": 90.0, "RB": 55.0, "WR": 55.0, "TE": 50.0},
        )
        assert "TE" in sig.deficit
        assert "QB" not in sig.deficit
        assert sig.deficit["TE"] == pytest.approx(30.0)

    def test_deficit_is_empty_without_a_startable_baseline(self):
        """Nothing in a single roster's profile says whether 20 points at
        TE is bad. Reporting a magnitude anyway would be fabricating
        calibration, so the honest output is nothing."""
        from src.roster_intel.partner import RosterSignal

        pool = _roster()
        profile = build_position_profiles(pool, SLOTS)
        sig = RosterSignal.from_engine("owner1", profile=profile)
        assert sig.deficit == {}
        # Surplus needs no league baseline and is still reported.
        assert sig.surplus

    def test_uncalibrated_deficit_degrades_need_alignment_to_neutral(self):
        """The downstream consequence of the honest degradation."""
        from src.roster_intel.partner import PartnerInputs, RosterSignal, assess_partner

        pool = _roster()
        profile = build_position_profiles(pool, SLOTS)
        theirs = RosterSignal.from_engine("them", profile=profile)
        a = assess_partner(PartnerInputs(owner_id="them", their_roster=theirs))
        assert a.partner_need_alignment == pytest.approx(0.5)


# ══ Serialization + limitations ═════════════════════════════════════


class TestSerialization:
    def test_position_target_round_trips(self):
        pool = _roster()
        d = rank_target_positions(pool, SLOTS, candidates={"TE": [_p("a", "TE", 80.0)]})[
            0
        ].to_dict()
        for key in ("position", "viability", "reason", "realisticGain", "priority", "modelVersion"):
            assert key in d
        assert d["modelVersion"] == TARGETS_MODEL_VERSION

    def test_player_target_exposes_its_signals(self):
        pool = _roster()
        d = rank_target_players(pool, SLOTS, [_p("a", "TE", 80.0)])[0].to_dict()
        assert d["recommended"] is True
        assert "rosterFit" in d["corroborating"]
        assert "marketEdge" not in d["corroborating"]

    def test_rejection_reason_is_always_populated(self):
        pool = _roster()
        for t in rank_target_players(pool, SLOTS, [_p("x", "WR", 1.0)]):
            assert t.reason


class TestLimitationsDeliverable:
    def test_declares_the_current_season_scope(self):
        lim = describe_limitations()
        blob = " ".join(lim["cannotSupport"]).lower()
        assert "rebuild" in blob
        assert "rest-of-season" in blob

    def test_declares_it_does_not_price_cost(self):
        lim = describe_limitations()
        assert any("cost" in s.lower() for s in lim["cannotSupport"])

    def test_declares_the_materiality_floor_as_an_assumption(self):
        lim = describe_limitations()
        assert lim["keyAssumptions"]["materialityFloorIsMeasured"] is False
        assert lim["keyAssumptions"]["materialityFloorPoints"] == MIN_MATERIAL_POINTS

    def test_declares_median_not_max(self):
        lim = describe_limitations()
        assert lim["keyAssumptions"]["realisticGainIsMedianNotMax"] is True

    def test_gate_constant_matches_the_code(self):
        lim = describe_limitations()
        assert lim["keyAssumptions"]["minCorroboratingSignals"] == MIN_CORROBORATING_SIGNALS

    def test_not_measured_distinction_is_documented(self):
        lim = describe_limitations()
        assert any("nothing available" in s for s in lim["cannotSupport"])


class TestPurity:
    def test_no_io_in_the_module(self):
        import inspect

        from src.roster_intel import targets

        src = inspect.getsource(targets)
        for forbidden in ("import requests", "open(", "datetime.now", "os.getenv"):
            assert forbidden not in src, f"{forbidden} found — module must stay pure"

    def test_does_not_depend_on_the_pre_fix_trade_engines(self):
        """src/trade/finder.py was returning offense-only results until
        recently (the KTC top-150 filter excluded every IDP defender).
        This engine measures lineup impact directly and must not inherit
        that bug by consuming those outputs."""
        import inspect

        from src.roster_intel import targets

        assert "src.trade" not in inspect.getsource(targets)

    def test_inputs_are_not_mutated(self):
        pool = _roster()
        before = [(p.player_id, p.ros_value) for p in pool]
        rank_target_positions(pool, SLOTS, candidates={"TE": [_p("a", "TE", 80.0)]})
        rank_target_players(pool, SLOTS, [_p("a", "TE", 80.0)])
        assert [(p.player_id, p.ros_value) for p in pool] == before
        assert len(pool) == 8


def test_player_target_is_frozen():
    t = PlayerTarget(player_id="x", name="X", position="WR", recommended=False, reason="r")
    with pytest.raises(Exception):
        t.recommended = True  # type: ignore[misc]
