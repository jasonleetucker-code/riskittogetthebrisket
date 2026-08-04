"""Insider Trading lead scoring.

Pins the product rules stated in the brief: a manager who both bought
the player elsewhere AND needs the position outranks one with only a
single signal; thin evidence is penalised; contradictory behaviour is
subtracted rather than netted away; and a lead score is never presented
as a probability of acceptance.
"""

from __future__ import annotations

import pytest

from src.intel import leads
from src.roster_intel import partner as partner_model

DAY_MS = leads.DAY_MS
NOW = 1_800_000_000_000


def obs(buys=0, sells=0, leagues=1, days_ago=5, user="them", asset="P1"):
    return leads.InterestObservation(
        user_id=user,
        asset_id=asset,
        buys=buys,
        sells=sells,
        unique_leagues=leagues,
        last_ts=NOW - int(days_ago * DAY_MS),
    )


def roster(owner="them", deficit=None, surplus=None, contend=0.5):
    return partner_model.RosterSignal(
        owner_id=owner,
        deficit=deficit or {},
        surplus=surplus or {},
        contend_probability=contend,
    )


def score(**kw):
    base = dict(
        owner_id="them",
        interest=None,
        partner=None,
        their_roster=None,
        position="WR",
        now_ms=NOW,
        direction="buy",
    )
    base.update(kw)
    return leads.score_lead(**base)


class TestDemonstratedInterest:
    def test_no_observation_scores_zero(self):
        assert leads.demonstrated_interest(None, NOW)[0] == 0.0

    def test_a_buy_creates_interest(self):
        strength, reasons, _ = leads.demonstrated_interest(obs(buys=1), NOW)
        assert strength > 0
        assert any("once" in r for r in reasons)

    def test_repeat_buys_outweigh_a_single_one(self):
        one, _, _ = leads.demonstrated_interest(obs(buys=1), NOW)
        two, reasons, _ = leads.demonstrated_interest(obs(buys=2), NOW)
        assert two > one
        assert any("2x" in r for r in reasons)

    def test_breadth_across_leagues_beats_repetition_in_one(self):
        narrow, _, _ = leads.demonstrated_interest(obs(buys=2, leagues=1), NOW)
        broad, _, _ = leads.demonstrated_interest(obs(buys=2, leagues=3), NOW)
        assert broad > narrow

    def test_recent_interest_beats_stale_interest(self):
        fresh, _, _ = leads.demonstrated_interest(obs(buys=2, days_ago=3), NOW)
        stale, _, _ = leads.demonstrated_interest(obs(buys=2, days_ago=400), NOW)
        assert fresh > stale

    def test_direction_flips_which_side_counts(self):
        """The same observations answer both modes from opposite sides."""
        seller = obs(buys=0, sells=2)
        assert leads.demonstrated_interest(seller, NOW, direction="buy")[0] == 0.0
        assert leads.demonstrated_interest(seller, NOW, direction="sell")[0] > 0

    def test_mixed_behaviour_is_flagged_as_a_caution(self):
        _, _, cautions = leads.demonstrated_interest(obs(buys=2, sells=1), NOW)
        assert cautions and "mixed signal" in cautions[0]


class TestCompositeRanking:
    def test_two_signals_beat_one(self):
        """The brief's rule: bought-elsewhere AND needs-the-position is
        a stronger lead than either alone."""
        both = score(
            interest=obs(buys=2, leagues=2),
            their_roster=roster(deficit={"WR": 10.0}),
        )
        interest_only = score(interest=obs(buys=2, leagues=2))
        need_only = score(their_roster=roster(deficit={"WR": 10.0}))
        assert both.score > interest_only.score
        assert both.score > need_only.score

    def test_no_signal_at_all_scores_zero(self):
        assert score().score == 0.0

    def test_contradictory_behaviour_is_subtracted(self):
        clean = score(interest=obs(buys=3, leagues=2))
        mixed = score(interest=obs(buys=3, sells=3, leagues=2))
        assert mixed.score < clean.score
        assert mixed.components["contradictionPenalty"] < 0

    def test_thin_evidence_is_penalised_and_flagged(self):
        thin = score(interest=obs(buys=1))
        assert thin.components["lowSamplePenalty"] < 0
        assert any("Thin evidence" in c for c in thin.cautions)

    def test_deep_evidence_carries_no_low_sample_penalty(self):
        deep = score(interest=obs(buys=4, leagues=3))
        assert deep.components["lowSamplePenalty"] == 0.0

    def test_every_component_is_exposed_for_audit(self):
        lead = score(interest=obs(buys=2))
        for key in (
            "demonstratedInterest",
            "partnerFit",
            "positionalNeed",
            "valueMatch",
            "activity",
            "contradictionPenalty",
            "lowSamplePenalty",
        ):
            assert key in lead.components

    def test_score_never_goes_negative(self):
        worst = score(interest=obs(buys=0, sells=5))
        assert worst.score >= 0.0


class TestPositionalNeed:
    def test_biggest_gap_scores_highest(self):
        strong, reasons = leads.positional_need_fit(roster(deficit={"WR": 10.0, "RB": 2.0}), "WR")
        weak, _ = leads.positional_need_fit(roster(deficit={"WR": 10.0, "RB": 2.0}), "RB")
        assert strong > weak
        assert any("biggest" in r for r in reasons)

    def test_need_is_normalised_against_their_own_gaps(self):
        """A roster with mild needs everywhere must not read as
        desperate for one of them."""
        even, _ = leads.positional_need_fit(roster(deficit={"WR": 5.0, "RB": 5.0, "TE": 5.0}), "WR")
        assert even == pytest.approx(1.0)

    def test_sell_direction_reads_surplus_not_deficit(self):
        r = roster(deficit={"WR": 9.0}, surplus={"RB": 9.0})
        assert leads.positional_need_fit(r, "RB", direction="sell")[0] > 0
        assert leads.positional_need_fit(r, "WR", direction="sell")[0] == 0.0

    def test_missing_roster_is_zero_not_an_error(self):
        assert leads.positional_need_fit(None, "WR")[0] == 0.0


class TestValueMatch:
    def test_close_value_is_a_full_match(self):
        assert leads.value_match(1000.0, [1050.0])[0] == 1.0

    def test_far_value_is_no_match(self):
        assert leads.value_match(1000.0, [50.0])[0] == 0.0

    def test_degrades_smoothly_rather_than_cliff_edging(self):
        near = leads.value_match(1000.0, [1250.0])[0]
        far = leads.value_match(1000.0, [1450.0])[0]
        assert 0.0 < far < near < 1.0

    def test_best_of_several_assets_is_used(self):
        assert leads.value_match(1000.0, [50.0, 990.0, 5000.0])[0] == 1.0

    def test_no_assets_is_zero(self):
        assert leads.value_match(1000.0, [])[0] == 0.0


class TestActivity:
    def test_inactive_manager_scores_zero(self):
        assert leads.activity_fit(0, 5.0)[0] == 0.0

    def test_churn_cannot_dominate(self):
        busy = leads.activity_fit(500, 3.0)[0]
        normal = leads.activity_fit(9, 3.0)[0]
        assert busy <= 1.0
        assert busy - normal < 0.05, "activity saturates rather than scaling"


class TestPartnerFitNormalisation:
    def test_normalised_against_the_reachable_max_not_nominal_100(self):
        """partner.py's fit score cannot reach 100 by construction —
        normalising against 100 would silently halve this term."""
        reachable = partner_model.FIT_SCORE_REACHABLE_MAX
        assert reachable < 50.0

        class _Fit:
            trade_partner_fit_score = reachable
            acceptance_confidence = 0.3

        lead = score(partner=_Fit())
        assert lead.components["partnerFit"] == pytest.approx(leads.W_PARTNER_FIT)

    def test_absent_partner_assessment_contributes_nothing(self):
        assert score(partner=None).components["partnerFit"] == 0.0


class TestRanking:
    def test_ranks_by_score_then_volume(self):
        a = score(owner_id="a", interest=obs(buys=3, leagues=3))
        b = score(owner_id="b", interest=obs(buys=1))
        ranked = leads.rank_leads([b, a])
        assert [x.owner_id for x in ranked] == ["a", "b"]

    def test_limit_is_applied(self):
        made = [score(owner_id=f"u{i}", interest=obs(buys=i + 1)) for i in range(5)]
        assert len(leads.rank_leads(made, limit=2)) == 2


class TestEpistemics:
    def test_limitations_declare_it_is_not_a_probability(self):
        lim = leads.describe_limitations()
        assert lim["isNotAProbability"] is True
        assert "not a prediction" in lim["statement"]

    def test_limitations_name_the_coverage_caveat(self):
        lim = leads.describe_limitations()
        assert "Absence of observed interest is not" in lim["coverageCaveat"]

    def test_demonstrated_interest_is_called_out_as_observable(self):
        """It is the one signal here that ISN'T inference — unlike
        acceptance, it was committed in public with real assets."""
        assert "observable" in leads.describe_limitations()["demonstratedInterestIsObservable"]

    def test_payload_never_exposes_an_acceptance_probability(self):
        lead = score(interest=obs(buys=2)).to_dict()
        assert "acceptanceProbability" not in lead
        assert "probability" not in json_keys(lead)


def json_keys(d, prefix=""):
    out = []
    for k, v in d.items():
        out.append(f"{prefix}{k}".lower())
        if isinstance(v, dict):
            out.extend(json_keys(v, prefix=f"{k}."))
    return out
