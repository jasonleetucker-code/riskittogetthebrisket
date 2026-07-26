"""LI-7 board-level adjustment + the LI-6 projection seam.

The load-bearing test here is the end-to-end no-op: with today's
evidence (no validated TE premium, no re-scored projections), running
the whole board must return values IDENTICAL to consensus.  That is the
guarantee that keeps an unvalidated number off the user's board, and it
is asserted with ``==`` rather than a tolerance.
"""

from __future__ import annotations

import pytest

from src.league_intel.adjustment import (
    AdjustmentAxis,
    EvidenceTier,
    ProjectionEvidence,
    build_board_adjustments,
    projection_corroboration_axis,
)


def row(name, position, value):
    return {"displayName": name, "position": position, "rankDerivedValue": value}


BOARD = [
    row("QB1", "QB", 9000),
    row("QB2", "QB", 7000),
    row("RB1", "RB", 8000),
    row("RB2", "RB", 6000),
    row("TE1", "TE", 7500),
    row("TE2", "TE", 5000),
    row("TE3", "TE", 3000),
    row("WR1", "WR", 8500),
]


class TestEndToEndNoOp:
    """Today's state: nothing moves."""

    def test_board_is_a_noop_with_no_evidence(self):
        board = build_board_adjustments(BOARD)
        assert board.is_noop is True
        assert board.adjusted_count == 0
        for e in board.explanations:
            # EXACT equality — a tolerance here would hide leakage.
            assert e.league_adjusted_value == e.consensus_value

    def test_noop_holds_even_with_a_te_measurement_absent(self):
        board = build_board_adjustments(BOARD, te_measurement=None)
        assert board.is_noop is True

    def test_noop_survives_projection_evidence_that_is_not_rescored(self):
        """A vendor's own point total must not unlock an adjustment."""
        proj = {
            "TE1": ProjectionEvidence(
                player_key="TE1",
                projected_points=180.0,
                source="somevendor",
                data_through="2026-07-26",
                categories_rescored=False,
            )
        }
        board = build_board_adjustments(BOARD, projections=proj)
        assert board.is_noop is True

    def test_every_row_reports_why_it_did_not_move(self):
        board = build_board_adjustments(BOARD)
        for e in board.explanations:
            assert e.evidence_tier is EvidenceTier.ABSENT
            assert e.confidence == 0.0
            assert any("rests on roster structure alone" in o for o in e.open_items)

    def test_te_rows_carry_the_open_te_question(self):
        board = build_board_adjustments(BOARD)
        te = [e for e in board.explanations if e.display_name.startswith("TE")]
        assert len(te) == 3
        for e in te:
            assert any("TE premium unresolved" in o for o in e.open_items)

    def test_monotonicity_clean_on_a_noop_board(self):
        board = build_board_adjustments(BOARD)
        assert board.monotonicity_violations == []

    def test_unpriced_rows_do_not_crash_the_board(self):
        board = build_board_adjustments(BOARD + [row("Ghost", "WR", 0)])
        assert board.is_noop is True
        ghost = next(e for e in board.explanations if e.display_name == "Ghost")
        assert ghost.league_adjusted_value is None


class TestScarcityActivatesTheAxis:
    """When LI-5 scarcity is supplied the structural axis engages —
    still behind the toggle, but no longer inert."""

    SCARCITY = {"QB": {"lineupScarcity": 0.9}, "WR": {"lineupScarcity": 0.1}}

    def test_scarce_position_moves_up_deep_position_moves_down(self):
        board = build_board_adjustments(BOARD, scarcity=self.SCARCITY)
        qb = next(e for e in board.explanations if e.display_name == "QB1")
        wr = next(e for e in board.explanations if e.display_name == "WR1")
        assert qb.league_adjusted_value > qb.consensus_value
        assert wr.league_adjusted_value < wr.consensus_value
        assert board.is_noop is False

    def test_positions_without_scarcity_stay_put(self):
        board = build_board_adjustments(BOARD, scarcity=self.SCARCITY)
        te = next(e for e in board.explanations if e.display_name == "TE1")
        assert te.league_adjusted_value == te.consensus_value

    def test_uniform_position_factor_preserves_order(self):
        board = build_board_adjustments(BOARD, scarcity=self.SCARCITY)
        assert board.monotonicity_violations == []

    def test_confidence_is_structural_only_not_neutral(self):
        board = build_board_adjustments(BOARD, scarcity=self.SCARCITY)
        qb = next(e for e in board.explanations if e.display_name == "QB1")
        assert qb.evidence_tier is EvidenceTier.STRUCTURAL_ONLY
        assert qb.projection_corroborated is False


class TestProjectionSeam:
    """LI-6's interface: corroboration raises confidence, never value."""

    EV = ProjectionEvidence(
        player_key="TE1",
        projected_points=180.0,
        source="li6",
        data_through="2026-08-01",
        categories_rescored=True,
    )

    def test_absent_when_no_evidence(self):
        a = projection_corroboration_axis(None, structural_factor=1.1)
        assert a.tier is EvidenceTier.ABSENT
        assert a.effective_factor == 1.0

    def test_absent_when_not_rescored_through_our_rules(self):
        ev = ProjectionEvidence("x", 180.0, "vendor", "2026-08-01", categories_rescored=False)
        a = projection_corroboration_axis(ev, structural_factor=1.1)
        assert a.tier is EvidenceTier.ABSENT
        assert "not re-scored" in a.rationale

    def test_rescored_evidence_reaches_the_top_tier(self):
        a = projection_corroboration_axis(self.EV, structural_factor=1.1)
        assert a.tier is EvidenceTier.PROJECTION_CORROBORATED

    def test_corroboration_never_moves_the_value(self):
        """It upgrades the tier; scaling here would double-count the
        structural effect it is corroborating."""
        for ev in (None, self.EV):
            a = projection_corroboration_axis(ev, structural_factor=1.4)
            assert a.factor == 1.0
            assert a.effective_factor == 1.0

    def test_corroboration_upgrades_board_confidence_without_moving_values(self):
        scarcity = {"TE": {"lineupScarcity": 0.9}}
        plain = build_board_adjustments(BOARD, scarcity=scarcity)
        with_proj = build_board_adjustments(BOARD, scarcity=scarcity, projections={"TE1": self.EV})
        a = next(e for e in plain.explanations if e.display_name == "TE1")
        b = next(e for e in with_proj.explanations if e.display_name == "TE1")
        assert a.league_adjusted_value == b.league_adjusted_value  # value unchanged
        assert a.projection_corroborated is False
        assert b.projection_corroborated is True
        assert b.confidence > a.confidence

    def test_evidence_serializes(self):
        d = self.EV.to_dict()
        assert set(d) == {
            "playerKey",
            "projectedPoints",
            "source",
            "dataThrough",
            "categoriesRescored",
        }


class TestBoardReporting:
    def test_board_serializes_with_provenance(self):
        board = build_board_adjustments(BOARD, config_version=1, data_through="2026-07-26")
        d = board.to_dict()
        assert d["isNoop"] is True
        assert d["configVersion"] == 1
        assert d["dataThrough"] == "2026-07-26"
        assert d["playerCount"] == len(BOARD)
        assert d["adjustedCount"] == 0

    def test_magnitude_cap_applies_board_wide(self):
        board = build_board_adjustments(
            BOARD, scarcity={"QB": {"lineupScarcity": 1.0}}, max_total_adjustment=0.01
        )
        qb = next(e for e in board.explanations if e.display_name == "QB1")
        assert qb.league_adjusted_value <= qb.consensus_value * 1.01 + 1e-9


class TestNonDuplicationAcrossAxes:
    def test_structural_and_corroboration_do_not_compound(self):
        """Fixture-pinned: the corroboration axis contributes exactly
        1.0, so adding it cannot change the arithmetic."""
        scarcity = {"QB": {"lineupScarcity": 0.9}}
        without = build_board_adjustments(BOARD, scarcity=scarcity)
        with_ev = build_board_adjustments(
            BOARD,
            scarcity=scarcity,
            projections={"QB1": ProjectionEvidence("QB1", 300.0, "li6", "2026-08-01", True)},
        )
        a = next(e for e in without.explanations if e.display_name == "QB1")
        b = next(e for e in with_ev.explanations if e.display_name == "QB1")
        assert a.league_adjusted_value == pytest.approx(b.league_adjusted_value, abs=1e-9)

    def test_axis_product_reproduces_the_value(self):
        board = build_board_adjustments(BOARD, scarcity={"RB": {"lineupScarcity": 0.7}})
        rb = next(e for e in board.explanations if e.display_name == "RB1")
        rebuilt = rb.consensus_value
        for axis in rb.axes:
            rebuilt *= axis.effective_factor
        assert rb.league_adjusted_value == pytest.approx(rebuilt, abs=1e-9)


class TestRealBoardNoOp:
    """The guarantee that matters: on the ACTUAL contract, today's
    model changes nothing."""

    @staticmethod
    def _rows():
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "audit" / "baseline" / "api_data.json"
        if not path.exists():
            pytest.skip("baseline contract snapshot not present")
        return json.loads(path.read_text())["playersArray"]

    def test_real_board_is_exactly_a_noop(self):
        rows = self._rows()
        board = build_board_adjustments(rows, config_version=1)
        assert board.is_noop is True
        assert board.adjusted_count == 0
        assert board.monotonicity_violations == []

    def test_real_board_reports_open_items_on_every_priced_row(self):
        board = build_board_adjustments(self._rows())
        priced = [e for e in board.explanations if e.consensus_value]
        assert len(priced) > 500
        assert all(e.open_items for e in priced)


class TestGuardAgainstSmuggling:
    def test_absent_axis_with_a_large_factor_still_cannot_move_a_board(self):
        """Defence in depth: even if a future axis is mis-tiered, ABSENT
        is inert at the arithmetic level."""
        from src.league_intel.adjustment import build_adjustment

        exp = build_adjustment(
            display_name="X",
            position="TE",
            consensus_value=5000.0,
            axes=[AdjustmentAxis("rogue", 2.0, EvidenceTier.ABSENT, "no evidence")],
        )
        assert exp.league_adjusted_value == 5000.0
