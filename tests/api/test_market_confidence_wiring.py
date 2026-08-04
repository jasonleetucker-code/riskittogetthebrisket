"""Market confidence reaches the signal context — and no rule reads it.

History, because both halves matter:

**2026-07-29 (audit N2).**  ``low_conf_unstable`` (MONITOR, priority 60)
was broken in THREE places at once, in opposite directions:

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
   nothing ever produced it, so confidence was permanently 0 and the
   rule fired for every eligible row on that path.

All three plumbing defects were fixed then, and the fixes are what this
file still pins.

**2026-07-30 — the rule itself is RETIRED.**  With the plumbing correct,
the metric turned out to be the problem.  ``_marketConfidence`` is
computed by ``Dynasty Scraper.py::_market_confidence`` with a
``site_count / 8.0`` term inherited from an era when ~10 scraper
``SITES`` were enabled.  Two are enabled today (KTC + IDPTradeCalc),
which yields at most three numeric dash keys per player, so
``site_score`` is confined to {0.20, 0.25, 0.375} and confidence is
structurally capped at ``0.375*0.65 + 1.00*0.35 = 0.59375``.  Live
distribution: p10 0.480 / median 0.491 / p90 0.564, one row of 1094
below 0.35.  Every candidate divisor moves confidence UP
(``scripts/simulate_market_confidence_divisor.py``: zero players below
0.35 at divisors 3, 4 and 5), so no re-threshold rescues it.

So: the context field stays (it is a real, inspectable number and the
plumbing must not silently rot), and the rule is gone.  This file tests
both facts — including, explicitly, that the rule does NOT come back
without someone editing this test.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.api.terminal import _build_signal_context, _evaluate_signal

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "signal_parity_cases.json"


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
    """The 2026-07-29 plumbing fixes.  Still load-bearing: the number is
    surfaced in ``/api/terminal`` payloads and is the substrate any future
    confidence rule would be built on."""

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
        """A row with no confidence must be UNMEASURED, never 'zero
        confidence' — the distinction that made defect #2 above fire."""
        ctx = _build_signal_context(_row(), points=[], news_for_player=[])
        assert ctx["confidence"] is None

    def test_garbage_confidence_is_none(self):
        ctx = _build_signal_context(
            _row(marketConfidence="not-a-number"), points=[], news_for_player=[]
        )
        assert ctx["confidence"] is None


class TestTheRuleIsRetired:
    """The 2026-07-30 retirement, pinned from three directions so it
    cannot be undone by accident in either engine."""

    def _ctx(self, conf, trend7=-4.0, vol="med"):
        return {
            "value": 5000,
            "confidence": conf,
            "trend7": trend7,
            "trend30": None,
            "volatility": {"label": vol, "mad": 3.0},
            "rankChange": None,
            "alertCount": 0,
            "negativeImpactCount": 0,
            "positiveImpactCount": 0,
            "newsCount": 0,
        }

    def test_low_confidence_no_longer_fires_anything(self):
        """The exact input that used to produce the MONITOR verdict."""
        verdict = _evaluate_signal(self._ctx(0.2))
        tags = {f["tag"] for f in verdict["fired"]}
        assert "low_conf_unstable" not in tags
        assert tags == set(), f"unexpected rules fired: {sorted(tags)}"
        assert verdict["signal"] == "HOLD"

    def test_zero_confidence_does_not_fire_either(self):
        """0.0 is a measurement, not an absence — and neither one has a
        rule to reach any more."""
        tags = {f["tag"] for f in _evaluate_signal(self._ctx(0.0))["fired"]}
        assert tags == set()

    def test_no_surviving_rule_reads_confidence(self):
        """Sweep the whole rule set: confidence must not change any
        verdict.  Catches a reinstatement under a different tag."""
        for conf in (None, 0.0, 0.1, 0.34, 0.35, 0.5, 0.9, 1.0):
            for trend7 in (-4.0, 0.0, 4.0):
                for vol in ("low", "med", "high"):
                    with_conf = _evaluate_signal(self._ctx(conf, trend7=trend7, vol=vol))
                    without = _evaluate_signal(self._ctx(None, trend7=trend7, vol=vol))
                    assert [f["tag"] for f in with_conf["fired"]] == [
                        f["tag"] for f in without["fired"]
                    ], f"confidence {conf} changed the verdict (trend7={trend7}, vol={vol})"

    def test_parity_fixture_no_longer_registers_the_rule(self):
        """The shared fixture is the contract between the Python and JS
        engines.  If the tag is back in its rule registry, one of the two
        engines has been changed without the other."""
        data = json.loads(_FIXTURE.read_text())
        tags = {r["tag"] for r in data["rules"]}
        assert "low_conf_unstable" not in tags


class TestMonitorStillGatesEmail:
    def test_monitor_is_actionable(self):
        """Pins the coupling that made the retired rule delicate in the
        first place: MONITOR verdicts send mail, so the surviving MONITOR
        rules (``alert_present``, ``high_vol``) are email-gating too."""
        from src.api.signal_alerts import ACTIONABLE_SIGNALS

        assert "MONITOR" in ACTIONABLE_SIGNALS
