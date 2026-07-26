"""Pins the Dynasty Nerds TE-premium pair findings (LI-6, DATA_SOURCES §8).

DN ships SFLEX and SFLEXTEP in one inline payload our fetcher already
downloads, so the pair costs zero extra HTTP. These tests pin what
measuring it actually showed, so nobody later assumes a usable second
calibration where there isn't one — and so the zero-sum property is
documented in executable form for whoever builds the ordinal path.

Fixture: every TE (41) plus the top 30 controls per position, trimmed
from the live pair. Offline.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

import pytest

from src.league_intel.calibration import (
    CARDINAL_MIN_DYNAMIC_RANGE,
    measure_paired_te_premium,
)

FIXTURE = Path(__file__).parent / "fixtures" / "dynasty_nerds_te_pair.json"


@pytest.fixture(scope="module")
def pair():
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def rows(pair):
    return pair["rows"]


def _ratios_by_pos(rows):
    out = defaultdict(list)
    for r in rows:
        sv = r["canonicalSiteValues"]
        a, b = sv.get("base"), sv.get("premium")
        if a and b and a > 0 and b > 0:
            out[r["position"]].append(b / a)
    return out


class TestPairShape:
    def test_pair_covers_all_three_controls_plus_te(self, rows):
        pos = {r["position"] for r in rows}
        assert {"QB", "RB", "WR", "TE"} <= pos

    def test_te_sample_is_thinner_than_ktc(self, rows):
        """Power caveat is real: 41 TEs vs KTC's 74."""
        assert sum(1 for r in rows if r["position"] == "TE") == 41


class TestCardinalGate:
    def test_dn_values_are_cardinal_not_rank_encoded(self, rows):
        """DN passes the gate FantasyPros fails — this is a real value scale."""
        vals = [
            r["canonicalSiteValues"]["base"] for r in rows if r["canonicalSiteValues"].get("base")
        ]
        assert max(vals) / min(vals) > CARDINAL_MIN_DYNAMIC_RANGE * 10


class TestConfoundedVerdict:
    def test_pair_is_rejected_as_confounded(self, rows):
        """Cardinal but confounded — the third case, neither KTC nor FantasyPros."""
        result = measure_paired_te_premium(rows, "base", "premium")
        assert result.usable is False
        assert "confounded" in result.reason
        assert result.te_premium is None, "an unusable pair must not emit a number"

    def test_controls_are_not_a_uniform_rescale(self, rows):
        """The diagnosis: control players move in BOTH directions.

        A renormalization moves every control by the same factor. These
        don't — which is why the pair is two boards, not one board with
        a TE knob.
        """
        ratios = _ratios_by_pos(rows)
        controls = [r for p in ("QB", "RB", "WR") for r in ratios[p]]
        assert min(controls) < 0.95, "some controls fall"
        assert max(controls) > 1.02, "others RISE — not a uniform rescale"

    def test_few_control_rows_are_identical(self, rows):
        """KTC was 388/388 byte-identical. DN is nothing like that."""
        controls = [
            r
            for r in rows
            if r["position"] in ("QB", "RB", "WR")
            and r["canonicalSiteValues"].get("base")
            and r["canonicalSiteValues"].get("premium")
        ]
        identical = sum(
            1
            for r in controls
            if r["canonicalSiteValues"]["base"] == r["canonicalSiteValues"]["premium"]
        )
        assert identical / len(controls) < 0.25


class TestRankDisplacementIsZeroSum:
    """The finding for whoever builds the ordinal path.

    A controls-at-zero-displacement gate can never pass on a combined
    ranking list: when TEs climb, the non-TEs they pass must fall by the
    same total. Control drift is the mechanical consequence of the TE
    premium, not evidence of confounding.
    """

    def test_te_gain_is_offset_by_control_loss(self, rows):
        te = sum(r["premiumRank"] - r["baseRank"] for r in rows if r["position"] == "TE")
        ctl = sum(
            r["premiumRank"] - r["baseRank"] for r in rows if r["position"] in ("QB", "RB", "WR")
        )
        assert te < 0, "TEs gain rank under the premium"
        assert ctl > 0, "controls necessarily lose rank"
        # Fixture is trimmed to the top controls, so the cancellation is
        # partial by construction; the sign relationship is the invariant.
        assert abs(te) > 0 and abs(ctl) > 0

    def test_controls_cannot_sit_at_zero_displacement(self, rows):
        ctl = [
            r["premiumRank"] - r["baseRank"] for r in rows if r["position"] in ("QB", "RB", "WR")
        ]
        assert statistics.median(ctl) != 0


class TestDepthGradientShape:
    """DN corroborates the SHAPE of the KTC curve, not its level."""

    def test_premium_grows_with_te_depth(self, rows):
        te = sorted(
            (r for r in rows if r["position"] == "TE"),
            key=lambda r: r["premiumRank"],
        )
        bands = [("TE1-12", 0, 12), ("TE13-24", 12, 24), ("TE25-40", 24, 40)]
        gains = []
        for _label, lo, hi in bands:
            chunk = te[lo:hi]
            assert chunk, "band must be populated"
            gains.append(statistics.median(r["premiumRank"] - r["baseRank"] for r in chunk))
        # More negative = bigger rank gain. Deeper TEs gain MORE, the
        # same direction as KTC's 1.287 -> 1.512 value gradient.
        assert gains[2] < gains[0], "deep TEs gain more rank than elite TEs"

    def test_every_te_gains_rank(self, rows):
        te = [r for r in rows if r["position"] == "TE"]
        assert all(r["premiumRank"] < r["baseRank"] for r in te)
