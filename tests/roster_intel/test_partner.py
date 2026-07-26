"""Tests for the WS-J trade partner fit + acceptance model.

The point of this suite is not coverage for its own sake. Four
properties in ``src/roster_intel/partner.py`` are load-bearing claims
made to the directive, and each one is pinned here so it cannot rot:

1. The manager-specific evidence gate is a **real branch with a real
   threshold**, and under the data we actually have it does not clear.
2. ``acceptanceConfidence`` is **capped** while no rejection data
   exists, regardless of how clean the other signals look.
3. Confidence **reduces the ranking quantity** — it is not decoration
   printed beside the score.
4. Mixed offense/IDP packages **suppress** the fairness term (audit
   F-1) rather than summing incompatible markets.

Plus the required limitations deliverable, asserted so the prose
cannot drift away from the code's behaviour.
"""

from __future__ import annotations

import math

import pytest

from src.roster_intel.partner import (
    BASE_ACCEPTANCE_PRIOR,
    MANAGER_EVIDENCE_MIN_DECISIONS,
    MANAGER_EVIDENCE_MIN_Z,
    MAX_CONFIDENCE_WITHOUT_DECISION_DATA,
    PARTNER_MODEL_VERSION,
    STRUCTURAL_COVERAGE_FLOOR,
    AcceptanceEvidence,
    PartnerInputs,
    RosterSignal,
    TradeShape,
    assess_partner,
    assess_partners,
    describe_limitations,
    manager_evidence,
)

# ── fixtures / builders ──────────────────────────────────────────────


def _our_roster(contend: float | None = 0.9) -> RosterSignal:
    return RosterSignal(
        owner_id="us",
        surplus={"RB": 2.0, "WR": 1.0},
        deficit={"TE": 1.0},
        contend_probability=contend,
    )


def _their_roster(contend: float | None = 0.1) -> RosterSignal:
    """Deficit is RB-heavy: RB 3.0, WR 1.0 (total 4.0, peak share 0.75)."""
    return RosterSignal(
        owner_id="them",
        surplus={"TE": 2.0},
        deficit={"RB": 3.0, "WR": 1.0},
        contend_probability=contend,
    )


def _shape(**kw) -> TradeShape:
    base = dict(
        send_positions={"RB": 1.0},
        receive_positions={"TE": 1.0},
        market_value_sent=5000.0,
        market_value_received=5000.0,
    )
    base.update(kw)
    return TradeShape(**base)


def _inputs(**kw) -> PartnerInputs:
    base = dict(
        owner_id="them",
        display_name="Partner",
        our_roster=_our_roster(),
        their_roster=_their_roster(),
        shape=_shape(),
    )
    base.update(kw)
    return PartnerInputs(**base)


# ── 1. the manager evidence gate ─────────────────────────────────────


class TestManagerEvidenceGate:
    def test_gate_does_not_clear_on_real_league_data(self):
        """The decisive property: our snapshot has completed trades only.

        ``trades_completed`` is the accepted arm with no denominator, so
        however many of them a manager racks up, the gate must stay
        shut and say why.
        """
        ev = manager_evidence(_inputs(trades_completed=99, league_mean_trades=4.0))
        assert ev.admissible is False
        assert "no decision data" in ev.reason
        # Names the missing input, not a vague "insufficient data".
        assert "rejections are unobserved" in ev.reason
        assert ev.decisions_observed == 0
        assert ev.z_score is None

    def test_completed_trades_are_never_counted_as_decisions(self):
        ev = manager_evidence(_inputs(trades_completed=50))
        assert ev.decisions_observed == 0
        assert ev.accepts_observed == 50
        assert ev.rejects_observed == 0

    def test_half_populated_decision_data_is_not_enough(self):
        """Accepts without rejects is exactly the unidentifiable case."""
        ev = manager_evidence(_inputs(decisions_accepted=40, decisions_rejected=None))
        assert ev.admissible is False
        assert "no decision data" in ev.reason

    def test_volume_gate_blocks_below_threshold(self):
        accepted, rejected = 5, 5
        assert accepted + rejected < MANAGER_EVIDENCE_MIN_DECISIONS
        ev = manager_evidence(_inputs(decisions_accepted=accepted, decisions_rejected=rejected))
        assert ev.admissible is False
        assert str(MANAGER_EVIDENCE_MIN_DECISIONS) in ev.reason
        assert ev.decisions_observed == 10

    def test_volume_alone_does_not_license_a_manager_term(self):
        """A manager who behaves like the league gets no term, even with
        plenty of decisions. This is the second gate condition."""
        # 40 decisions at rate 0.175, essentially the 0.18 baseline.
        ev = manager_evidence(_inputs(decisions_accepted=7, decisions_rejected=33))
        assert ev.decisions_observed >= MANAGER_EVIDENCE_MIN_DECISIONS
        assert ev.admissible is False
        assert abs(ev.z_score) < MANAGER_EVIDENCE_MIN_Z
        assert "behaves like" in ev.reason

    def test_gate_clears_only_when_both_conditions_hold(self):
        ev = manager_evidence(_inputs(decisions_accepted=16, decisions_rejected=24))
        assert ev.decisions_observed >= MANAGER_EVIDENCE_MIN_DECISIONS
        assert abs(ev.z_score) >= MANAGER_EVIDENCE_MIN_Z
        assert ev.admissible is True

    def test_threshold_matches_its_stated_rationale(self):
        """MANAGER_EVIDENCE_MIN_DECISIONS is documented as the n at which
        the standard error of a binary rate is ~7pp. If someone lowers it
        without revisiting the rationale, this fails."""
        se = math.sqrt(
            BASE_ACCEPTANCE_PRIOR * (1 - BASE_ACCEPTANCE_PRIOR) / MANAGER_EVIDENCE_MIN_DECISIONS
        )
        assert se == pytest.approx(0.0701, abs=0.01)

    def test_inadmissible_gate_contributes_exactly_zero(self):
        a = assess_partner(_inputs())
        assert a.manager_evidence.admissible is False
        assert a.contributions["managerSpecific"] == 0.0
        assert any("manager term inert" in n for n in a.notes)


# ── 2. confidence is capped, and tracks evidence not value ───────────


class TestAcceptanceConfidence:
    def test_capped_without_decision_data_even_with_perfect_signals(self):
        a = assess_partner(
            _inputs(
                shape=_shape(market_value_sent=9000.0, market_value_received=1000.0),
                their_roster=_their_roster(contend=0.0),
                our_roster=_our_roster(contend=1.0),
                trades_completed=20,
                league_mean_trades=4.0,
            )
        )
        assert a.acceptance_confidence <= MAX_CONFIDENCE_WITHOUT_DECISION_DATA
        assert a.evidence is not AcceptanceEvidence.DECISION_CALIBRATED
        assert any("not a calibrated acceptance probability" in n for n in a.notes)

    def test_every_reachable_tier_is_below_the_cap(self):
        """Not just the tier we happen to hit — the cap must bind for all
        of them, since none are decision-calibrated."""
        cases = [
            _inputs(our_roster=None, their_roster=None, shape=None),
            _inputs(),
            _inputs(trades_completed=20, league_mean_trades=4.0),
        ]
        tiers = set()
        for inp in cases:
            a = assess_partner(inp)
            tiers.add(a.evidence)
            assert a.acceptance_confidence <= MAX_CONFIDENCE_WITHOUT_DECISION_DATA
        # Confirms the cases really do exercise distinct tiers.
        assert len(tiers) >= 2
        assert AcceptanceEvidence.DECISION_CALIBRATED not in tiers

    def test_bare_inputs_yield_absent_tier_at_the_prior(self):
        a = assess_partner(
            PartnerInputs(owner_id="them", our_roster=None, their_roster=None, shape=None)
        )
        assert a.evidence is AcceptanceEvidence.ABSENT
        # No admissible signal anywhere: the estimate is the bare prior.
        assert a.trade_acceptance_estimate == pytest.approx(BASE_ACCEPTANCE_PRIOR, abs=1e-6)

    def test_abstaining_terms_cost_confidence(self):
        """A defaulted term is an abstention, not a measurement. Partners
        assessed on fewer real signals must carry less confidence even
        when they land in the same evidence tier."""
        full = assess_partner(_inputs())
        no_window = assess_partner(
            _inputs(our_roster=_our_roster(None), their_roster=_their_roster(None))
        )
        blind = assess_partner(_inputs(our_roster=None, their_roster=None))

        assert full.evidence is no_window.evidence is blind.evidence
        assert full.acceptance_confidence > no_window.acceptance_confidence
        assert no_window.acceptance_confidence > blind.acceptance_confidence

    def test_coverage_shortfall_is_reported(self):
        blind = assess_partner(_inputs(our_roster=None, their_roster=None))
        assert any("structural coverage 1/3" in n for n in blind.notes)

    def test_full_coverage_is_not_penalised(self):
        full = assess_partner(_inputs())
        assert not any("structural coverage" in n for n in full.notes)
        assert full.acceptance_confidence == pytest.approx(0.30)

    def test_a_zero_contribution_is_still_a_measurement(self):
        """Regression. Tier must key on whether a term could be measured,
        not on the magnitude of its contribution.

        A perfectly balanced 5000-for-5000 offer produces a fairness
        delta of exactly 0.0, and a manager trading at exactly the league
        mean produces a history delta of exactly 0.0. Both are genuine
        measurements that say 'no adjustment'. Scoring them as absent
        evidence would give the cleanest, best-understood cases the
        lowest confidence — precisely backwards.
        """
        balanced = assess_partner(
            _inputs(
                our_roster=None,
                their_roster=None,
                shape=_shape(market_value_sent=5000.0, market_value_received=5000.0),
            )
        )
        assert balanced.contributions["marketFairness"] == 0.0
        assert balanced.evidence is AcceptanceEvidence.SHAPE_ONLY

        average = assess_partner(_inputs(trades_completed=4, league_mean_trades=4.0))
        assert average.contributions["leagueHistory"] == pytest.approx(0.0, abs=1e-9)
        assert average.evidence is AcceptanceEvidence.HISTORY_INFORMED

    def test_confidence_rises_with_evidence_not_with_the_estimate(self):
        """Two partners, same evidence tier, wildly different estimates:
        confidence must be identical. Confidence is about support, not
        about how attractive the number is."""
        generous = assess_partner(
            _inputs(shape=_shape(market_value_sent=9000.0, market_value_received=1000.0))
        )
        insulting = assess_partner(
            _inputs(shape=_shape(market_value_sent=1000.0, market_value_received=9000.0))
        )
        assert generous.trade_acceptance_estimate > insulting.trade_acceptance_estimate
        assert generous.evidence is insulting.evidence
        assert generous.acceptance_confidence == insulting.acceptance_confidence


# ── 3. confidence reduces the ranking quantity ───────────────────────


def _fit_at_full_confidence(a) -> float:
    """Recompute the fit score as if confidence were 1.0.

    Mirrors ``assess_partner``'s final expression deliberately: the test
    is asserting that the confidence factor is *present and binding*, so
    it needs the counterfactual to compare against.
    """
    anchored = a.trade_acceptance_estimate
    structural = 0.5 * (a.partner_need_alignment + a.partner_window_alignment)
    return 100.0 * min(max(0.65 * anchored + 0.35 * structural, 0.0), 1.0)


class TestConfidencePenalisesRanking:
    def test_thin_evidence_scores_below_its_face_value(self):
        a = assess_partner(
            _inputs(shape=_shape(market_value_sent=8000.0, market_value_received=2000.0))
        )
        assert a.acceptance_confidence < 1.0
        assert a.trade_acceptance_estimate > BASE_ACCEPTANCE_PRIOR
        # The confidence factor must actually cost the partner ranking
        # points, not merely appear in the payload.
        assert a.trade_partner_fit_score < _fit_at_full_confidence(a)

    def test_higher_estimate_on_thinner_evidence_still_ranks_lower(self):
        """The sharpest form of the requirement.

        ``speculative`` is assessed blind — no roster engine output, so
        need and window abstain — but carries a *more attractive* raw
        estimate thanks to a lopsided offer. ``supported`` is a fair
        offer measured on all three structural terms.

        If confidence were decoration, speculative would win on the
        estimate. It must not.
        """
        speculative = _inputs(
            owner_id="speculative",
            our_roster=None,
            their_roster=None,
            shape=_shape(market_value_sent=9000.0, market_value_received=1000.0),
        )
        supported = _inputs(
            owner_id="supported",
            shape=_shape(market_value_sent=5000.0, market_value_received=5000.0),
        )
        spec, sup = assess_partner(speculative), assess_partner(supported)

        # Precondition: the raw estimate really does favour the blind one.
        assert spec.trade_acceptance_estimate > sup.trade_acceptance_estimate
        assert spec.acceptance_confidence < sup.acceptance_confidence
        # ...and the ranking inverts it anyway.
        assert spec.trade_partner_fit_score < sup.trade_partner_fit_score
        assert [a.owner_id for a in assess_partners([speculative, supported])] == [
            "supported",
            "speculative",
        ]

    def test_ranking_is_by_fit_score_descending_and_deterministic(self):
        made = [
            _inputs(owner_id="b", shape=_shape(market_value_sent=6000.0)),
            _inputs(owner_id="a", shape=_shape(market_value_sent=6000.0)),
            _inputs(owner_id="c", shape=_shape(market_value_sent=1000.0)),
        ]
        ranked = assess_partners(made)
        scores = [a.trade_partner_fit_score for a in ranked]
        assert scores == sorted(scores, reverse=True)
        # Ties break on owner id, so the order is stable across runs.
        assert [a.owner_id for a in ranked] == ["a", "b", "c"]

    def test_fit_score_stays_in_range(self):
        extremes = [
            _inputs(shape=_shape(market_value_sent=9999.0, market_value_received=1.0)),
            _inputs(shape=_shape(market_value_sent=1.0, market_value_received=9999.0)),
            _inputs(our_roster=None, their_roster=None, shape=None),
        ]
        for inp in extremes:
            a = assess_partner(inp)
            assert 0.0 <= a.trade_partner_fit_score <= 100.0
            assert 0.0 <= a.trade_acceptance_estimate <= 1.0
            assert 0.0 <= a.acceptance_confidence <= 1.0


# ── 4. audit F-1: mixed markets suppress fairness ────────────────────


class TestMixedMarketSuppression:
    def test_mixed_markets_suppress_the_fairness_term(self):
        mixed = assess_partner(
            _inputs(
                shape=_shape(
                    market_value_sent=9000.0,
                    market_value_received=1000.0,
                    markets_mixed=True,
                )
            )
        )
        assert mixed.contributions["marketFairness"] == 0.0
        assert any("audit F-1" in n for n in mixed.notes)

    def test_suppression_is_not_silent(self):
        """A suppressed fairness term must be visible in the notes, or a
        consumer will read the resulting mediocre score as a measurement
        rather than an abstention."""
        mixed = assess_partner(_inputs(shape=_shape(markets_mixed=True)))
        note = next(n for n in mixed.notes if "audit F-1" in n)
        assert "suppressed" in note

    def test_same_market_package_does_use_fairness(self):
        clean = assess_partner(
            _inputs(shape=_shape(market_value_sent=9000.0, market_value_received=1000.0))
        )
        assert clean.contributions["marketFairness"] > 0.0

    def test_fairness_sign_follows_the_partners_side_of_the_deal(self):
        """Positive when THEY come out ahead. Getting this backwards
        would invert every recommendation, so it is pinned explicitly."""
        favours_them = assess_partner(
            _inputs(shape=_shape(market_value_sent=8000.0, market_value_received=2000.0))
        )
        favours_us = assess_partner(
            _inputs(shape=_shape(market_value_sent=2000.0, market_value_received=8000.0))
        )
        assert favours_them.contributions["marketFairness"] > 0
        assert favours_us.contributions["marketFairness"] < 0

    def test_fairness_saturates_rather_than_running_to_certainty(self):
        lopsided = assess_partner(
            _inputs(shape=_shape(market_value_sent=9999.0, market_value_received=1.0))
        )
        assert lopsided.trade_acceptance_estimate < 1.0
        # A gift is more plausible than a fair deal, but not a certainty.
        assert lopsided.trade_acceptance_estimate < 0.75


# ── term behaviour: need + window alignment ──────────────────────────


class TestNeedAlignment:
    def test_sending_their_biggest_deficit_scores_maximally(self):
        a = assess_partner(_inputs(shape=_shape(send_positions={"RB": 1.0})))
        assert a.partner_need_alignment == pytest.approx(1.0)

    def test_sending_a_position_they_do_not_need_scores_zero(self):
        a = assess_partner(_inputs(shape=_shape(send_positions={"QB": 1.0})))
        assert a.partner_need_alignment == pytest.approx(0.0)

    def test_secondary_need_scores_between(self):
        a = assess_partner(_inputs(shape=_shape(send_positions={"WR": 1.0})))
        assert 0.0 < a.partner_need_alignment < 1.0

    def test_poor_fit_pushes_the_estimate_down_not_merely_to_neutral(self):
        """The need term is signed: a genuinely bad positional fit has to
        cost the estimate, otherwise 'no fit' and 'perfect fit' would
        differ only in the upside."""
        bad = assess_partner(_inputs(shape=_shape(send_positions={"QB": 1.0})))
        assert bad.contributions["rosterFit"] < 0

    def test_missing_roster_engine_output_degrades_to_neutral(self):
        """The roster engine is another workstream. Landing before it is
        a supported state, not a crash."""
        a = assess_partner(_inputs(our_roster=None, their_roster=None))
        assert a.partner_need_alignment == pytest.approx(0.5)
        assert a.contributions["rosterFit"] == pytest.approx(0.0)
        assert any("roster engine output unavailable" in n for n in a.notes)

    def test_standing_complementarity_used_when_no_package_exists(self):
        """Partner ranking has to work before any specific offer is
        constructed — fall back to surplus-vs-deficit."""
        a = assess_partner(_inputs(shape=None))
        assert a.partner_need_alignment > 0.5


class TestWindowAlignment:
    def test_contender_and_rebuilder_are_complementary(self):
        a = assess_partner(_inputs(our_roster=_our_roster(1.0), their_roster=_their_roster(0.0)))
        assert a.partner_window_alignment == pytest.approx(1.0)

    def test_identical_windows_are_not_complementary(self):
        a = assess_partner(_inputs(our_roster=_our_roster(0.8), their_roster=_their_roster(0.8)))
        assert a.partner_window_alignment == pytest.approx(0.0)
        assert a.contributions["windowFit"] < 0

    def test_missing_window_degrades_to_neutral(self):
        a = assess_partner(_inputs(our_roster=_our_roster(None), their_roster=_their_roster(None)))
        assert a.partner_window_alignment == pytest.approx(0.5)
        assert any("window" in n for n in a.notes)

    def test_window_budget_is_smaller_than_need_budget(self):
        """Hierarchy check: window fit must not outweigh roster fit,
        which must not outweigh market fairness."""
        strong = assess_partner(
            _inputs(
                shape=_shape(
                    send_positions={"RB": 1.0},
                    market_value_sent=8000.0,
                    market_value_received=2000.0,
                ),
                our_roster=_our_roster(1.0),
                their_roster=_their_roster(0.0),
            )
        )
        c = strong.contributions
        assert c["marketFairness"] > c["rosterFit"] > c["windowFit"] > 0


# ── league history is activity, hard-shrunk ──────────────────────────


class TestHistoryTerm:
    def test_inert_without_a_league_baseline(self):
        a = assess_partner(_inputs(trades_completed=12, league_mean_trades=None))
        assert a.contributions["leagueHistory"] == 0.0
        assert any("no league trade baseline" in n for n in a.notes)

    def test_league_average_manager_gets_no_nudge(self):
        a = assess_partner(_inputs(trades_completed=4, league_mean_trades=4.0))
        assert a.contributions["leagueHistory"] == pytest.approx(0.0, abs=1e-9)

    def test_shrinkage_keeps_a_low_volume_outlier_near_the_mean(self):
        """One extra trade in a 12-team league is noise. The history term
        must barely move, or it becomes a manager term through the back
        door — which is precisely what the gate exists to prevent."""
        avg = assess_partner(_inputs(trades_completed=4, league_mean_trades=4.0))
        active = assess_partner(_inputs(trades_completed=8, league_mean_trades=4.0))
        delta = active.contributions["leagueHistory"] - avg.contributions["leagueHistory"]
        assert 0 < delta < 0.20

    def test_history_never_exceeds_the_fairness_budget(self):
        extreme = assess_partner(_inputs(trades_completed=500, league_mean_trades=1.0))
        assert abs(extreme.contributions["leagueHistory"]) < abs(
            assess_partner(
                _inputs(shape=_shape(market_value_sent=8000.0, market_value_received=2000.0))
            ).contributions["marketFairness"]
        )


# ── serialization + the limitations deliverable ──────────────────────


class TestSerialization:
    def test_to_dict_carries_confidence_and_evidence_alongside_the_estimate(self):
        """Anything that renders the estimate must be able to render its
        caveats from the same payload — no separate lookup."""
        d = assess_partner(_inputs()).to_dict()
        for key in (
            "tradePartnerFitScore",
            "tradeAcceptanceEstimate",
            "partnerNeedAlignment",
            "partnerWindowAlignment",
            "acceptanceConfidence",
            "evidence",
            "managerEvidence",
            "modelVersion",
        ):
            assert key in d
        assert d["modelVersion"] == PARTNER_MODEL_VERSION
        assert d["managerEvidence"]["admissible"] is False
        assert d["managerEvidence"]["reason"]

    def test_contributions_expose_every_term_for_audit(self):
        d = assess_partner(_inputs()).to_dict()
        assert set(d["contributions"]) == {
            "prior",
            "marketFairness",
            "rosterFit",
            "windowFit",
            "leagueHistory",
            "managerSpecific",
        }


class TestLimitationsDeliverable:
    def test_states_the_unidentifiability_of_an_acceptance_rate(self):
        lim = describe_limitations()
        blob = " ".join(lim["cannotSupport"]).lower()
        assert "will accept" in blob
        assert "unidentifiable" in blob

    def test_declares_the_prior_as_an_assumption(self):
        lim = describe_limitations()
        assert lim["keyAssumptions"]["baseAcceptancePriorIsMeasured"] is False
        assert lim["keyAssumptions"]["baseAcceptancePrior"] == BASE_ACCEPTANCE_PRIOR

    def test_confidence_ceiling_matches_the_code_that_enforces_it(self):
        """If someone raises the cap without revisiting the doc, or vice
        versa, the deliverable stops describing the model."""
        lim = describe_limitations()
        assert lim["confidenceCeiling"] == MAX_CONFIDENCE_WITHOUT_DECISION_DATA
        a = assess_partner(_inputs(trades_completed=20, league_mean_trades=4.0))
        assert a.acceptance_confidence <= lim["confidenceCeiling"]

    def test_structural_coverage_floor_is_documented(self):
        lim = describe_limitations()
        assert lim["structuralCoverageFloor"] == STRUCTURAL_COVERAGE_FLOOR
        assert "abstain" in lim["structuralCoverageNote"]

    def test_names_what_would_unlock_more(self):
        lim = describe_limitations()
        assert any("declined" in s.lower() for s in lim["whatWouldUnlockMore"])

    def test_gate_threshold_is_quoted_accurately(self):
        lim = describe_limitations()
        assert any(str(MANAGER_EVIDENCE_MIN_DECISIONS) in s for s in lim["cannotSupport"])


# ── purity ───────────────────────────────────────────────────────────


class TestPurity:
    def test_repeated_assessment_is_identical(self):
        inp = _inputs(trades_completed=6, league_mean_trades=4.0)
        first = assess_partner(inp).to_dict()
        second = assess_partner(inp).to_dict()
        assert first == second

    def test_assessment_does_not_mutate_its_inputs(self):
        shape = _shape()
        theirs = _their_roster()
        inp = _inputs(shape=shape, their_roster=theirs)
        assess_partner(inp)
        assert dict(shape.send_positions) == {"RB": 1.0}
        assert dict(theirs.deficit) == {"RB": 3.0, "WR": 1.0}

    def test_module_performs_no_io(self):
        """Pure computation is a directive constraint, so it is checked
        structurally rather than trusted."""
        import inspect

        from src.roster_intel import partner

        src = inspect.getsource(partner)
        for forbidden in ("import requests", "open(", "Path(", "datetime.now", "os.getenv"):
            assert forbidden not in src, f"{forbidden} found — module must stay pure"
