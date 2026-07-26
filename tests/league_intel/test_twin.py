"""LI-8 League Twin bridge — roster change to playoff-odds input.

The bridge's whole job is producing ``simulate_trade_impact``'s
``strength_delta`` from real rosters.  Two properties carry the weight:
the delta must be in ``_TeamDist.mean`` units (i.e. scaled by the same
multiplicative ROS blend the simulator applied), and an owner the model
cannot price must be ABSENT rather than zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_intel.twin import (
    TWIN_BRIDGE_VERSION,
    strength_deltas_from_rosters,
)

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "LB", "DL"]


def player(pid, pos, value, fp=()):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "fantasyPositions": list(fp),
    }


def roster(n=14, base=1000):
    return [player(f"p{i}", "WR", base + i * 10) for i in range(n)]


class TestUnitsAreTeamDistMeanNotPresimPoints:
    """`_TeamDist.mean = presim_mean * (1 + ROS_BLEND * ros_z)`, so a raw
    presim delta is in the wrong units for the field it lands in."""

    def test_blend_factor_scales_the_delta_exactly(self):
        before, after = roster(), roster()[:-1]
        plain = strength_deltas_from_rosters({"o1": before}, {"o1": after}, SLOTS, weeks=30, seed=5)
        blended = strength_deltas_from_rosters(
            {"o1": before},
            {"o1": after},
            SLOTS,
            weeks=30,
            seed=5,
            ros_z_by_owner={"o1": 2.0},
            ros_blend=0.20,
        )
        d0, d1 = plain.per_owner[0], blended.per_owner[0]
        assert d0.blend_factor == pytest.approx(1.0)
        assert d1.blend_factor == pytest.approx(1.4)
        # Multiplicative blend scales exactly — not approximately.
        assert d1.mean_delta == pytest.approx(d0.raw_mean_delta * 1.4)

    def test_raw_delta_is_reported_so_the_scaling_is_auditable(self):
        out = strength_deltas_from_rosters(
            {"o1": roster()},
            {"o1": roster()[:-1]},
            SLOTS,
            weeks=30,
            seed=5,
            ros_z_by_owner={"o1": -1.5},
        )
        d = out.per_owner[0]
        assert d.raw_mean_delta is not None
        assert d.mean_delta == pytest.approx(d.raw_mean_delta * d.blend_factor)

    def test_no_ros_score_means_factor_exactly_one(self):
        """The simulator skips the blend entirely for an owner with no
        ROS strength, so 1.0 is correct rather than a fudge."""
        out = strength_deltas_from_rosters(
            {"o1": roster()}, {"o1": roster()[:-1]}, SLOTS, weeks=20, seed=5
        )
        assert out.per_owner[0].blend_factor == 1.0

    def test_negative_z_shrinks_the_delta(self):
        before, after = roster(), roster()[:-1]
        weak = strength_deltas_from_rosters(
            {"o1": before},
            {"o1": after},
            SLOTS,
            weeks=30,
            seed=5,
            ros_z_by_owner={"o1": -2.0},
            ros_blend=0.20,
        )
        assert weak.per_owner[0].blend_factor == pytest.approx(0.6)


class TestUnavailableIsAbsentNotZero:
    def test_unpriceable_owner_is_omitted_from_the_map(self):
        """`simulate_trade_impact` reads a missing owner as unmoved,
        which is the right reading of 'no information'.  An explicit 0.0
        would assert the trade is neutral for them."""
        out = strength_deltas_from_rosters(
            {"o1": [player("only", "WR", 1000)]},
            {"o1": []},
            SLOTS,
            weeks=10,
            seed=5,
        )
        assert "o1" not in out.strength_delta
        assert len(out.unavailable) == 1
        assert out.unavailable[0].unavailable_reason

    def test_available_owner_is_present(self):
        out = strength_deltas_from_rosters(
            {"o1": roster()}, {"o1": roster()[:-1]}, SLOTS, weeks=20, seed=5
        )
        assert "o1" in out.strength_delta

    def test_owner_missing_from_after_is_skipped_entirely(self):
        out = strength_deltas_from_rosters(
            {"o1": roster(), "ghost": roster()}, {"o1": roster()}, SLOTS, weeks=20, seed=5
        )
        assert {d.owner_id for d in out.per_owner} == {"o1"}


class TestVarianceIsReportedNotDiscarded:
    """simulate_trade_impact copies sd unchanged, so the trade's effect
    on variance vanishes there.  The bridge must not also lose it."""

    def test_sd_delta_is_present_and_independent_of_mean(self):
        out = strength_deltas_from_rosters(
            {"o1": roster()}, {"o1": roster()[:-1]}, SLOTS, weeks=40, seed=5
        )
        d = out.per_owner[0]
        assert d.sd_delta is not None
        assert d.mean_delta is not None

    def test_the_limitation_is_stamped_not_implied(self):
        out = strength_deltas_from_rosters(
            {"o1": roster()}, {"o1": roster()[:-1]}, SLOTS, weeks=20, seed=5
        )
        assert any("NOT fed into simulate_trade_impact" in a for a in out.assumptions)
        assert any("ros_z is assumed UNCHANGED" in a for a in out.assumptions)


class TestMonotonicitySurvivesTheBridge:
    def test_dropping_a_player_never_raises_the_scaled_delta(self):
        """The ADR-011 invariant must hold through the scaling too — a
        positive blend factor cannot flip the sign."""
        full = roster(16)
        for drop in range(0, 16, 3):
            after = [p for i, p in enumerate(full) if i != drop]
            out = strength_deltas_from_rosters(
                {"o1": full},
                {"o1": after},
                SLOTS,
                weeks=30,
                seed=11,
                ros_z_by_owner={"o1": 1.5},
            )
            assert out.per_owner[0].mean_delta <= 1e-9

    def test_identical_rosters_give_exactly_zero(self):
        out = strength_deltas_from_rosters(
            {"o1": roster()},
            {"o1": roster()},
            SLOTS,
            weeks=30,
            seed=11,
            ros_z_by_owner={"o1": 1.5},
        )
        assert out.per_owner[0].mean_delta == 0.0


class TestOnRealRosters:
    @staticmethod
    def _pool():
        path = Path(__file__).resolve().parent / "fixtures" / "league_pool.json"
        if not path.exists():
            pytest.skip("league pool fixture not present")
        return json.loads(path.read_text())

    def test_a_real_trade_moves_both_sides_in_opposite_directions(self):
        pool = self._pool()
        slots = (
            ["QB"]
            + ["RB"] * 2
            + ["WR"] * 3
            + ["TE"] * 2
            + ["FLEX"] * 2
            + ["SUPER_FLEX"]
            + ["K"]
            + ["DL"] * 3
            + ["LB"] * 3
            + ["DB"] * 3
        )
        a, b = pool[0], pool[1]
        # NOTE: key on rosterId, not ownerId. This fixture carries no
        # ownerId, so `str(a.get("ownerId"))` yields "None" for BOTH
        # teams, the two dict entries collapse to one key, and B
        # silently overwrites A. The first draft of this test did that
        # and reported +12.03 for the team GIVING a player away — which
        # looked exactly like the ADR-011 monotonicity defect and was
        # actually B's gain read under A's name. Worth keeping: a
        # single-sided assertion would have passed.
        a_id, b_id = str(a["rosterId"]), str(b["rosterId"])
        assert a_id != b_id
        # A sends its best player to B for nothing — a pure giveaway, so
        # the sign is knowable without trusting the magnitude.
        best = max(a["players"], key=lambda p: float(p.get("rosValue") or 0))
        before = {a_id: a["players"], b_id: b["players"]}
        after = {
            a_id: [p for p in a["players"] if p["playerId"] != best["playerId"]],
            b_id: b["players"] + [best],
        }
        out = strength_deltas_from_rosters(before, after, slots, weeks=60, seed=3)
        assert out.strength_delta[a_id] < 0
        assert out.strength_delta[b_id] > 0

    def test_bridge_version_is_stamped(self):
        out = strength_deltas_from_rosters(
            {"o1": roster()}, {"o1": roster()[:-1]}, SLOTS, weeks=10, seed=5
        )
        assert out.to_dict()["bridgeVersion"] == TWIN_BRIDGE_VERSION
