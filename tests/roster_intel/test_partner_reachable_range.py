"""``tradePartnerFitScore`` occupies the bottom third of its own scale.

Collaborative audit, finding J.  The field is nominally 0-100.  Its
reachable range is ~7.2 to ~43.1, because ``DECISION_CALIBRATED``
confidence (0.85) needs rejection data Sleeper does not expose, so the
best attainable confidence is 0.40.

The existing guard (``test_fit_score_stays_in_range``) asserts only
``0 <= x <= 100`` — true, and far too loose to notice that the top 57%
of the scale is unreachable.  A renderer trusting the nominal range
would draw the best possible partner as a failing grade.
"""

from __future__ import annotations

import itertools

import pytest

from src.roster_intel import partner as P
from src.roster_intel.partner import (
    FIT_SCORE_REACHABLE_MAX,
    FIT_SCORE_REACHABLE_MIN,
    MAX_CONFIDENCE_WITHOUT_DECISION_DATA,
)


def _sweep_fit_scores() -> list[float]:
    """Exhaustive-ish sweep of the assembly arithmetic.

    Deliberately recomputes ``fit_score`` from the module's own constants
    rather than calling ``assess_partner``: the point is to bound what
    the FORMULA can emit, independent of whether any particular input
    fixture can reach the corners.
    """
    scores: list[float] = []
    base = P._logit(P.BASE_ACCEPTANCE_PRIOR)
    confidences = [
        min(c, MAX_CONFIDENCE_WITHOUT_DECISION_DATA)
        for tier, c in P._EVIDENCE_CONFIDENCE.items()
        if tier is not P.AcceptanceEvidence.DECISION_CALIBRATED
    ]
    for need, window, fair, hist, conf in itertools.product(
        (0.0, 0.5, 1.0),
        (0.0, 0.5, 1.0),
        (-P.MAX_FAIRNESS_LOGIT, 0.0, P.MAX_FAIRNESS_LOGIT),
        (-P.MAX_HISTORY_LOGIT, 0.0, P.MAX_HISTORY_LOGIT),
        confidences,
    ):
        need_logit = P.MAX_NEED_LOGIT * (2.0 * need - 1.0)
        window_logit = P.MAX_WINDOW_LOGIT * (2.0 * window - 1.0)
        estimate = P._sigmoid(base + fair + need_logit + window_logit + hist)
        anchored = P.BASE_ACCEPTANCE_PRIOR + conf * (estimate - P.BASE_ACCEPTANCE_PRIOR)
        structural = 0.5 * (need + window)
        scores.append(100.0 * P._clamp(0.65 * anchored + 0.35 * structural * conf, 0.0, 1.0))
    return scores


class TestTheAdvertisedRangeMatchesTheReachableOne:
    def test_published_bounds_match_an_independent_sweep(self):
        """The bounds are DERIVED from the caps; this checks that
        derivation against brute force over the same arithmetic. If a cap
        moves, both sides move together and this still passes — which is
        the point."""
        scores = _sweep_fit_scores()
        assert min(scores) == pytest.approx(FIT_SCORE_REACHABLE_MIN, abs=0.05)
        assert max(scores) == pytest.approx(FIT_SCORE_REACHABLE_MAX, abs=0.05)

    def test_the_top_half_of_the_nominal_scale_is_unreachable(self):
        """The finding, as an assertion. If this ever fails because the
        ceiling rose, rejection data arrived — check that before relaxing
        it."""
        assert FIT_SCORE_REACHABLE_MAX < 50.0

    def test_the_bounds_ship_with_the_score(self):
        """A consumer must not have to read this test file to learn the
        scale."""
        rng = _assessment().to_dict()["tradePartnerFitScoreRange"]
        assert rng["min"] == FIT_SCORE_REACHABLE_MIN
        assert rng["max"] == FIT_SCORE_REACHABLE_MAX
        assert rng["nominal"] == [0.0, 100.0]
        assert "rejection data" in rng["why"]

    def test_a_real_assessment_lands_inside_the_published_bounds(self):
        score = _assessment().trade_partner_fit_score
        assert FIT_SCORE_REACHABLE_MIN <= score <= FIT_SCORE_REACHABLE_MAX

    def test_the_documented_cap_does_not_actually_bind(self):
        """``MAX_CONFIDENCE_WITHOUT_DECISION_DATA`` is 0.45 but the best
        reachable tier is 0.40, so the cap never fires. Recorded because
        a reader would otherwise assume 0.45 is the operative ceiling."""
        assert P._MAX_REACHABLE_CONFIDENCE < MAX_CONFIDENCE_WITHOUT_DECISION_DATA


class TestNeedAndWindowEnterTwice:
    def test_need_influences_the_score_through_two_paths(self):
        """Once via the capped logit, once via the uncapped ``structural``
        term. Documented at the assembly site; pinned here so it stays a
        decision rather than an accident."""
        import inspect

        src = inspect.getsource(P.assess_partner)
        assert "need_logit = MAX_NEED_LOGIT" in src
        assert "structural = 0.5 * (need + window)" in src

    def test_need_outweighs_fairness_on_the_ranking_score(self):
        """The behavioural consequence of the double entry, and the
        reason it matters.

        The module's stated hierarchy puts fairness strongest (budget
        1.40 vs need's 0.90). That is true of the ESTIMATE. On
        ``fit_score`` — the quantity that actually ranks partners — need
        enters twice and overtakes it. Asserted by moving each through
        its full range with the other held neutral.
        """
        base = P._logit(P.BASE_ACCEPTANCE_PRIOR)
        conf = P._MAX_REACHABLE_CONFIDENCE

        def fit(need: float, fairness: float) -> float:
            need_logit = P.MAX_NEED_LOGIT * (2.0 * need - 1.0)
            estimate = P._sigmoid(base + fairness + need_logit)
            anchored = P.BASE_ACCEPTANCE_PRIOR + conf * (estimate - P.BASE_ACCEPTANCE_PRIOR)
            structural = 0.5 * (need + 0.5)  # window held neutral
            return 100.0 * P._clamp(0.65 * anchored + 0.35 * structural * conf, 0.0, 1.0)

        need_swing = fit(1.0, 0.0) - fit(0.0, 0.0)
        fairness_swing = fit(0.5, P.MAX_FAIRNESS_LOGIT) - fit(0.5, -P.MAX_FAIRNESS_LOGIT)

        assert need_swing > fairness_swing, (
            f"need swing {need_swing:.2f} no longer exceeds fairness swing "
            f"{fairness_swing:.2f} — the double entry may have been removed; "
            "if so, update the module docstring, which now describes a "
            "hierarchy that holds for both the estimate and fit_score"
        )

    def test_the_double_entry_is_documented_at_the_site(self):
        import inspect

        src = inspect.getsource(P.assess_partner)
        assert "enter this score TWICE" in src, (
            "the need/window double entry is undocumented again — the module's "
            "stated budget hierarchy describes the estimate, not fit_score"
        )


def _assessment():
    """A minimal but realistic assessment."""
    return P.assess_partner(
        P.PartnerInputs(
            owner_id="owner-1",
            display_name="Someone",
            shape=P.TradeShape(
                send_positions={"WR": 1},
                receive_positions={"RB": 1},
                market_value_sent=5000,
                market_value_received=5200,
                markets_mixed=False,
            ),
        )
    )


class TestWindowAffinitiesAreNotCalledProbabilities:
    """Audit finding H. The five states are softmaxed distances to
    hand-placed anchors; nothing was fitted to outcomes."""

    def _window(self):
        from tests.roster_intel.test_window import ROSTER, SLOTS
        from src.roster_intel.window import compute_window

        return compute_window(
            "me", ROSTER, SLOTS, lineup_scores={"me": 0.9, "other": 0.4}
        ).to_dict()

    def test_affinities_is_published(self):
        assert "affinities" in self._window()

    def test_probabilities_survives_as_an_alias(self):
        w = self._window()
        assert w["probabilities"] == w["affinities"]

    def test_affinities_still_sum_to_one(self):
        """Renaming must not change the arithmetic — only the claim."""
        assert sum(self._window()["affinities"].values()) == pytest.approx(1.0, abs=1e-6)

    def test_the_gameplan_projection_keeps_the_notes(self):
        """``gameplan.py`` used to drop ``notes``, hiding 'no state
        cleared 30%' and the proxy-source stamp from every API consumer."""
        import inspect

        from src.api import gameplan

        src = inspect.getsource(gameplan)
        block = src[src.index('"competitiveWindow": {') :][:1400]
        assert '"notes"' in block, (
            "the competitiveWindow projection drops notes again — those notes "
            "carry the honesty signals the window model relies on"
        )
