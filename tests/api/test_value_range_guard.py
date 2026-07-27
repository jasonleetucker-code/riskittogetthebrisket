"""D-1: one out-of-range source value must not rescale the whole board.

Operator decision 2026-07-27 — "B with a C escalation":

  B. A single out-of-range row is dropped from the value-direct path for
     that source only, falling through to the existing rank->Hill
     fallback.  Every other player is untouched.
  C. Above ``_VALUE_RANGE_ESCALATION_FRACTION`` out-of-range rows, the
     source's scale has changed rather than one row being corrupt, so
     the whole source is suppressed from the value-direct path.

The defect these pin: ``site_max`` was an unbounded ``max()`` and the
value-direct branch computes ``raw / site_max * 9999``.  One row at
``ktcSfTep=99990`` therefore deflated EVERY other player by ~45%, with
ordering preserved so the board still looked correctly sorted.
"""

from __future__ import annotations

import pytest

from src.api.data_contract import (
    _VALUE_RANGE_ESCALATION_FRACTION,
    _VALUE_SOURCE_DECLARED_MAX,
    _partition_value_source_ranges,
    _value_is_in_declared_range,
)


def _rows(source: str, values: list[float]) -> list[dict]:
    return [
        {"displayName": f"P{i}", "canonicalSiteValues": {source: v}} for i, v in enumerate(values)
    ]


class TestDeclaredRangeCheck:
    def test_in_range_values_accepted(self):
        assert _value_is_in_declared_range("ktcSfTep", 0.0)
        assert _value_is_in_declared_range("ktcSfTep", 5000.0)
        assert _value_is_in_declared_range("ktcSfTep", 9999.0)

    def test_out_of_range_values_rejected(self):
        assert not _value_is_in_declared_range("ktcSfTep", 10000.0)
        assert not _value_is_in_declared_range("ktcSfTep", 99990.0)
        assert not _value_is_in_declared_range("ktcSfTep", -1.0)

    def test_unlisted_source_is_not_range_checked(self):
        """Sources publish on their own scales — dynastyNerdsSfTep tops
        out at 10256 today.  A source with no declared ceiling must keep
        prior behaviour rather than being clamped to someone else's."""
        assert "dynastyNerdsSfTep" not in _VALUE_SOURCE_DECLARED_MAX
        assert _value_is_in_declared_range("dynastyNerdsSfTep", 10256.0)
        assert _value_is_in_declared_range("someFutureSource", 1e9)


class TestPolicyB_SingleBadRowDropped:
    def test_site_max_ignores_the_out_of_range_row(self):
        """The whole defect in one assertion: the divisor must come from
        the legitimate rows, not from the corrupt one."""
        # Realistic board size: one glitch in 101 rows is ~1%, below the
        # escalation threshold, so policy B applies.
        rows = _rows("ktcSfTep", [9999.0] + [5000.0] * 99 + [99990.0])
        value_source_max, suppressed, diags = _partition_value_source_ranges(rows)

        assert value_source_max["ktcSfTep"] == 9999.0, (
            "site_max must exclude the out-of-range row; "
            "pre-fix this was 99990 and deflated every player ~45%"
        )
        assert "ktcSfTep" not in suppressed
        assert diags["ktcSfTep"] == {"total": 101, "outOfRange": 1}

    def test_negative_value_is_also_out_of_range(self):
        rows = _rows("idpTradeCalc", [9999.0] + [5000.0] * 99 + [-50.0])
        _, _, diags = _partition_value_source_ranges(rows)
        assert diags["idpTradeCalc"]["outOfRange"] == 1

    def test_one_bad_row_does_not_suppress_the_source(self):
        """Policy B, not C: a lone glitch keeps the source in play."""
        rows = _rows("ktcSfTep", [9999.0] + [5000.0] * 199 + [99990.0])
        _, suppressed, diags = _partition_value_source_ranges(rows)
        assert diags["ktcSfTep"]["outOfRange"] == 1
        assert diags["ktcSfTep"]["total"] == 201
        assert "ktcSfTep" not in suppressed


class TestPolicyC_ScaleChangeSuppresses:
    def test_many_out_of_range_rows_suppress_the_source(self):
        """A vendor rescaling their board is not a glitch. Silently
        dropping most of a source would be worse than failing."""
        rows = _rows("ktcSfTep", [50000.0] * 30 + [5000.0] * 70)
        _, suppressed, diags = _partition_value_source_ranges(rows)
        assert diags["ktcSfTep"]["outOfRange"] == 30
        assert "ktcSfTep" in suppressed

    def test_threshold_boundary_does_not_suppress(self):
        """At exactly the threshold we stay in policy B — suppression
        requires strictly exceeding it."""
        total = 100
        bad = int(_VALUE_RANGE_ESCALATION_FRACTION * total)  # 2
        rows = _rows("ktcSfTep", [50000.0] * bad + [5000.0] * (total - bad))
        _, suppressed, _ = _partition_value_source_ranges(rows)
        assert "ktcSfTep" not in suppressed

    def test_just_over_threshold_suppresses(self):
        total = 100
        bad = int(_VALUE_RANGE_ESCALATION_FRACTION * total) + 1  # 3
        rows = _rows("ktcSfTep", [50000.0] * bad + [5000.0] * (total - bad))
        _, suppressed, _ = _partition_value_source_ranges(rows)
        assert "ktcSfTep" in suppressed


class TestCleanBoardUnaffected:
    def test_healthy_board_produces_no_drops_and_no_suppression(self):
        """The guard must be a no-op on good data. Measured against the
        live board 2026-07-27: both value sources max at exactly 9999
        with zero out-of-range rows, so this reflects production."""
        rows = _rows("ktcSfTep", [9999.0, 7000.0, 4000.0, 1.0, 0.0])
        value_source_max, suppressed, diags = _partition_value_source_ranges(rows)
        assert value_source_max["ktcSfTep"] == 9999.0
        assert suppressed == set()
        assert diags["ktcSfTep"]["outOfRange"] == 0

    def test_non_numeric_and_missing_values_are_skipped_not_counted(self):
        rows = [
            {"canonicalSiteValues": {"ktcSfTep": 9999.0}},
            {"canonicalSiteValues": {"ktcSfTep": None}},
            {"canonicalSiteValues": {"ktcSfTep": "not-a-number"}},
            {"canonicalSiteValues": None},
            {},
        ]
        value_source_max, suppressed, diags = _partition_value_source_ranges(rows)
        assert value_source_max["ktcSfTep"] == 9999.0
        assert diags["ktcSfTep"]["total"] == 1
        assert suppressed == set()


class TestEndToEndDeflation:
    """The measured failure, driven through the partition step.

    Pre-fix, ``site_max`` would be 99990 and a legitimate 9999 player
    would normalise to ``9999/99990*9999 = 1000`` — a 90% haircut on the
    top asset, and proportionally on everyone else.
    """

    @pytest.mark.parametrize("bad_value", [99990.0, 950000.0])
    def test_top_asset_keeps_full_value_despite_a_corrupt_row(self, bad_value):
        rows = _rows("ktcSfTep", [9999.0] + [5000.0] * 99 + [bad_value])
        value_source_max, suppressed, _ = _partition_value_source_ranges(rows)
        site_max = value_source_max["ktcSfTep"]

        normalized_top = 9999.0 / site_max * 9999.0
        assert normalized_top == pytest.approx(9999.0), (
            f"top asset must stay at 9999; with the unbounded max it "
            f"would be {9999.0 / bad_value * 9999.0:.0f}"
        )
        assert "ktcSfTep" not in suppressed


class TestEscalationNeedsAdequateSample:
    """Escalation C claims the SOURCE's scale changed. That claim cannot
    be made from a handful of rows — on a 4-row fixture one glitch is
    25%, which would suppress a healthy source outright. Below
    ``_VALUE_RANGE_ESCALATION_MIN_ROWS`` we always take policy B.

    This was found by a test, not by review: the first version of the
    guard suppressed ktcSfTep on a 4-row fixture holding a single bad
    value.
    """

    def test_tiny_sample_never_escalates_even_at_high_fraction(self):
        from src.api.data_contract import _VALUE_RANGE_ESCALATION_MIN_ROWS

        rows = _rows("ktcSfTep", [9999.0, 8000.0, 5000.0, 99990.0])
        assert len(rows) < _VALUE_RANGE_ESCALATION_MIN_ROWS
        value_source_max, suppressed, diags = _partition_value_source_ranges(rows)

        assert diags["ktcSfTep"]["outOfRange"] == 1
        assert diags["ktcSfTep"]["total"] == 4  # 25%, far above the 2% fraction
        assert "ktcSfTep" not in suppressed, "one bad row in four is not evidence of a scale change"
        assert value_source_max["ktcSfTep"] == 9999.0

    def test_adequate_sample_still_escalates(self):
        from src.api.data_contract import _VALUE_RANGE_ESCALATION_MIN_ROWS

        n = _VALUE_RANGE_ESCALATION_MIN_ROWS
        bad = int(n * 0.5)
        rows = _rows("ktcSfTep", [50000.0] * bad + [5000.0] * (n - bad))
        _, suppressed, _ = _partition_value_source_ranges(rows)
        assert "ktcSfTep" in suppressed
