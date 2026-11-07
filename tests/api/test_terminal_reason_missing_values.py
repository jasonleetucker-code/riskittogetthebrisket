"""Terminal reason copy never prints an unmeasured value as zero (missing is never zero).

The coercion gate flagged five ``x or 0`` reads in ``src/api/terminal.py`` reason strings:
an absent MAD rendered as ``MAD 0.0`` and an absent rank change as ``Dropped 0 ranks``.
"""

from __future__ import annotations

from src.api import terminal


def test_unmeasured_mad_reads_na_not_zero():
    assert terminal._fmt_mad(None) == "n/a"
    assert terminal._fmt_mad("not-a-number") == "n/a"


def test_measured_mad_keeps_one_decimal():
    assert terminal._fmt_mad(12.345) == "12.3"
    assert terminal._fmt_mad(0) == "0.0"  # a measured zero is still a real zero
