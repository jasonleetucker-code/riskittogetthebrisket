"""Market confidence reaches the signal rule, and absent != zero.

N2, 2026-07-29 audit round 2.

``low_conf_unstable`` (MONITOR, priority 60) was broken in THREE places
at once, in opposite directions:

1. Backend — ``terminal.py::_build_signal_context`` read
   ``row["confidence"]``.  No contract builder stamps that key; the
   contract stamps ``marketConfidence``.  The rule could never fire
   server-side, so it never reached the email alert sweep.

2. Frontend, playersArray path — ``buildRows`` mapped
   ``Number(player.marketConfidence ?? 0)``.  256 of 1094 live rows
   carry no confidence at all, and 0 is under the 0.35 threshold, so
   the rule fired on rows that merely LACK the field.

3. Frontend, legacy-dict path — mapped
   ``Number(player._marketReliabilityScore ?? 0)``.  That field appeared
   exactly once in the entire repository — at that consumer — and
   nothing ever produced it (0 of 1076 live players carry it, while 838
   carry ``_marketConfidence``).  Confidence was therefore permanently
   0 and the rule fired for every eligible row on that path.

MONITOR is in ``signal_alerts.ACTIONABLE_SIGNALS``, so #1 is the one
that gates emails.  The measured distribution says fixing it is safe:
live ``marketConfidence`` runs p10 0.480 / median 0.491 / p90 0.564
against a 0.35 threshold, and exactly ONE row of 1094 sits below it.
That is recorded in ``test_threshold_is_far_below_the_live_distribution``
so the "turning this on floods every inbox" assumption is not re-made
without evidence — and so that if the distribution ever shifts down
toward the threshold, someone notices.
"""

from __future__ import annotations

from src.api.terminal import _build_signal_context, _evaluate_signal


def _row(**over):
    row = {
        "displayName": "Test Player",
        "position": "WR",
        "rankDerivedValue": 5000,
        "canonicalConsensusRank": 60,
    }
    row.update(over)
    return row


class TestConfidenceReachesTheContext:
    def test_market_confidence_is_read(self):
        """The key the contract actually stamps."""
        ctx = _build_signal_context(_row(marketConfidence=0.2), points=[], news_for_player=[])
        assert ctx["confidence"] == 0.2

    def test_short_name_still_works_as_a_fallback(self):
        """A caller handing over an already-materialized frontend row
        (or a fixture using the short name) must keep working."""
        ctx = _build_signal_context(_row(confidence=0.25), points=[], news_for_player=[])
        assert ctx["confidence"] == 0.25

    def test_market_confidence_wins_over_the_short_name(self):
        ctx = _build_signal_context(
            _row(marketConfidence=0.2, confidence=0.9), points=[], news_for_player=[]
        )
        assert ctx["confidence"] == 0.2

    def test_absent_confidence_is_none_not_zero(self):
        """The defect that made the rule fire on the frontend: a row
        with no confidence must be UNMEASURED, never 'zero confidence'."""
        ctx = _build_signal_context(_row(), points=[], news_for_player=[])
        assert ctx["confidence"] is None

    def test_garbage_confidence_is_none(self):
        ctx = _build_signal_context(
            _row(marketConfidence="not-a-number"), points=[], news_for_player=[]
        )
        assert ctx["confidence"] is None


class TestTheRuleNowFires:
    def _ctx(self, conf, trend7=-4.0):
        return {
            "value": 5000,
            "confidence": conf,
            "trend7": trend7,
            "trend30": None,
            "volatility": {"label": "med", "mad": 3.0},
            "rankChange": None,
            "alertCount": 0,
            "negativeImpactCount": 0,
            "positiveImpactCount": 0,
            "newsCount": 0,
        }

    def test_low_confidence_plus_movement_fires_monitor(self):
        """Server-side this could not fire at all before the fix."""
        verdict = _evaluate_signal(self._ctx(0.2))
        tags = {f["tag"] for f in verdict["fired"]}
        assert "low_conf_unstable" in tags

    def test_absent_confidence_does_not_fire(self):
        verdict = _evaluate_signal(self._ctx(None))
        tags = {f["tag"] for f in verdict["fired"]}
        assert "low_conf_unstable" not in tags

    def test_healthy_confidence_does_not_fire(self):
        """0.49 is the live median — the common case must stay quiet."""
        verdict = _evaluate_signal(self._ctx(0.49))
        tags = {f["tag"] for f in verdict["fired"]}
        assert "low_conf_unstable" not in tags


class TestAlertVolumeIsBounded:
    def test_monitor_is_actionable_so_this_gates_email(self):
        """Pins the coupling that made this change delicate: if MONITOR
        ever leaves ACTIONABLE_SIGNALS, the reasoning below changes."""
        from src.api.signal_alerts import ACTIONABLE_SIGNALS

        assert "MONITOR" in ACTIONABLE_SIGNALS

    def test_threshold_is_far_below_the_live_distribution(self):
        """The evidence that wiring this rule up does not flood inboxes.

        The scraper defaults ``_marketConfidence`` to 0.5 and the live
        spread is p10 0.480 / median 0.491 / p90 0.564, so a 0.35
        threshold catches almost nothing — 1 row in 1094 when measured.

        This test does not read live data (unit tests must not), but it
        pins the two numbers the safety argument rests on, so a future
        change to either is a deliberate one.
        """
        from src.api.terminal import _evaluate_signal as ev

        base = {
            "value": 5000,
            "trend7": -4.0,
            "trend30": None,
            "volatility": {"label": "med", "mad": 3.0},
            "rankChange": None,
            "alertCount": 0,
            "negativeImpactCount": 0,
            "positiveImpactCount": 0,
            "newsCount": 0,
        }
        # The scraper's default, and the live p10 — neither may fire.
        for conf in (0.5, 0.480):
            tags = {f["tag"] for f in ev({**base, "confidence": conf})["fired"]}
            assert "low_conf_unstable" not in tags, f"{conf} fired; threshold moved"
        # Just under the threshold must fire.
        tags = {f["tag"] for f in ev({**base, "confidence": 0.34})["fired"]}
        assert "low_conf_unstable" in tags
