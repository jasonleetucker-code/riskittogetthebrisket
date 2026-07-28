"""A measurement must record whether its inputs were complete.

On 2026-07-28 the IDP positional scoring multipliers shipped with DB and
DL inverted. The code was correct; the *inputs* were not. They were
measured on a scoring card where one Sleeper key alias had been repaired
and a second had not, so a cornerback stat was scoring and an edge-rusher
stat was not. Nothing about the resulting number said so, and it was
caught only by reading an unrelated document days later.

**A digest alone would not have caught it.** "The inputs changed" is only
actionable once somebody re-derives and compares — which is the work the
digest was meant to save. The question that mattered was narrower: *were
the inputs known to be incomplete at the moment of measurement?* They
were, by seven rules.

So ``inputs_complete`` is the load-bearing field, and these tests pin two
properties that are easy to get wrong:

* it is False in exactly the historical failure state, and
* ``UNSCORABLE`` rules do NOT make it False — those cannot be fixed by
  any code change, so counting them would pin the flag permanently red,
  and a flag that is always red is a flag nobody reads.
"""

from __future__ import annotations

from src.nfl_data import realized_points as rp
from src.nfl_data.measurement_provenance import (
    Provenance,
    input_digest,
    scoring_provenance,
)


def test_the_digest_is_stable_across_key_order():
    """Dict ordering must not look like an input change."""
    a = input_digest({"pass_yd": 0.04, "rush_yd": 0.1})
    b = input_digest({"rush_yd": 0.1, "pass_yd": 0.04})
    assert a == b


def test_the_digest_moves_when_a_rate_changes():
    assert input_digest({"pass_yd": 0.04}) != input_digest({"pass_yd": 0.05})


def test_the_digest_survives_an_unexpected_type():
    """A diagnostic must never be the thing that raises."""
    assert input_digest({"weird": object()})


def test_a_complete_card_reports_complete():
    prov = scoring_provenance({"pass_yd": 0.04, "idp_sack": 2.92})
    assert prov.inputs_complete
    assert prov.input_gaps == ()


def test_an_unreadable_rule_makes_the_inputs_incomplete():
    prov = scoring_provenance({"pass_yd": 0.04, "some_unknown_rule": 3.0})
    assert not prov.inputs_complete
    assert "some_unknown_rule" in prov.input_gaps


def test_unscorable_rules_do_not_count_as_incompleteness():
    """The distinction that keeps the flag meaningful.

    Distance-banded receptions cannot be reconstructed from weekly
    stats — no code change fixes that. If they counted, the live card
    would report incomplete forever and the signal would be worthless.
    """
    prov = scoring_provenance({"rec_40p": 1.92, "pass_yd": 0.04})
    assert prov.inputs_complete, "an unscorable rule must not read as a defect"
    assert "rec_40p" in prov.input_unscorable


def test_gaps_are_unioned_across_every_card():
    """A comparison is compromised by an unread rule in EITHER league,
    and for a relative quantity an asymmetric gap is the worst case —
    it moves one side only."""
    prov = scoring_provenance({"pass_yd": 0.04}, {"another_unknown_rule": 1.0})
    assert not prov.inputs_complete
    assert "another_unknown_rule" in prov.input_gaps


def test_the_historical_failure_state_is_flagged():
    """THE REGRESSION, reconstructed.

    Recreates the alias map as it stood when PR #606's measurement was
    taken — ``idp_pass_def`` aliased, ``idp_qb_hit`` not — against the
    real rates from the live card. Verified against the actual cards:
    complete map reports no gaps, half-fixed map reports
    ``['idp_qb_hit']``.
    """
    card = {"idp_pass_def": 5.32, "idp_qb_hit": 2.13, "idp_sack": 2.92}
    full = dict(rp._SCORING_KEY_ALIASES)
    try:
        assert scoring_provenance(card).inputs_complete

        rp._SCORING_KEY_ALIASES = {k: v for k, v in full.items() if k != "idp_qb_hit"}
        prov = scoring_provenance(card)
        assert not prov.inputs_complete, (
            "the state that shipped an inverted DB-vs-DL tilt reports as "
            "complete — this guard would not have caught it"
        )
        assert prov.input_gaps == ("idp_qb_hit",)
    finally:
        rp._SCORING_KEY_ALIASES = full


def test_provenance_serialises_for_the_api():
    prov = scoring_provenance({"pass_yd": 0.04}, rows_scored=19421, notes="hello")
    payload = prov.to_dict()
    assert payload["rowsScored"] == 19421
    assert payload["inputsComplete"] is True
    assert payload["notes"] == "hello"
    assert isinstance(payload["inputGaps"], list)


def test_an_empty_provenance_is_inert():
    """The default on a measurement that refused itself. It must not
    claim incompleteness it did not measure."""
    prov = Provenance()
    assert prov.inputs_complete
    assert prov.input_digest == ""
    assert prov.rows_scored == 0


def test_the_scoring_fit_measurement_carries_provenance():
    """End-to-end: the field reaches the measurement object and its dict."""
    from src.league_intel.scoring_fit import measure_positional_scoring_fit

    m = measure_positional_scoring_fit([], {"idp_sack": 1.0}, {"idp_sack": 2.0})
    assert hasattr(m, "provenance")
    assert "provenance" in m.to_dict()
