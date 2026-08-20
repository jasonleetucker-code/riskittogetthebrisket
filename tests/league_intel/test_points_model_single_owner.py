"""The rosValue -> weekly-points conversion has ONE owner.

WHAT WAS DUPLICATED
-------------------
``src/league_intel/sim_calibration.py`` owns the conversion: a
``PointsModel`` with ``ros_value_per_point``, a per-position CV table and
a ``source`` stamp, loadable from a calibrated artifact and degrading to
documented fallback constants.

Two copies of its numbers had grown beside it:

* ``ros/playoff_sim._PLAYER_CV_BY_POSITION`` / ``_DEFAULT_PLAYER_CV`` —
  byte-identical to ``sim_calibration.FALLBACK_CV_BY_POSITION`` /
  ``FALLBACK_DEFAULT_CV``, and read by nothing in that module;
* ``league_intel/sim._LegacyPointsModel`` — a second implementation of
  ``draw()`` with ``2.7`` hardcoded, importing the CV table from
  ``playoff_sim`` rather than from the owner.

So the same three numbers existed in three places and the same Gaussian
draw in two.

NOT A LIVE DEFECT, AND SAYING SO MATTERS
----------------------------------------
``league_intel/sim.py`` and ``league_intel/twin.py`` are reachable only
from tests — no production caller — so the hardcoded ``2.7`` was never
serving a user, and the live path (``playoff_sim`` -> ``PointsModel``)
reads the owner correctly. This is dormant duplication being removed
before it diverges, not a repair of something that was wrong on the
site. Recording that distinction rather than claiming a bigger fix.

The value of removing it is specific: a calibrated
``sim_points_model.json`` changes the live path and would leave the
dormant copy silently on the fallback constants, at which point two
answers to "how many points is this rosValue" exist and only one of them
tracks the calibration.
"""

from __future__ import annotations

import random

from src.league_intel import sim as _sim
from src.league_intel import sim_calibration as _sc


def test_the_cv_table_has_one_definition():
    """``playoff_sim`` must not keep its own copy of the owner's table."""
    from src.ros import playoff_sim

    assert not hasattr(playoff_sim, "_PLAYER_CV_BY_POSITION"), (
        "playoff_sim re-declares the owner's CV table; a second copy of "
        "constants is a second owner waiting to diverge"
    )
    assert not hasattr(playoff_sim, "_DEFAULT_PLAYER_CV")


def test_the_legacy_model_draws_identically_to_the_owner():
    """Behavioural parity, not a reading of the two implementations.

    Same seed, same inputs, same draws — which is what makes replacing
    one with the other an exact identity rather than a judgement call.
    """
    owner = _sc.PointsModel()
    legacy = _sim._LEGACY_POINTS_MODEL

    for position in ("QB", "RB", "WR", "TE", "LB", "DB", "K", ""):
        for ros in (0.0, 0.4, 5.0, 9.15, 25.0, 59.41, 100.0):
            a = owner.draw(ros, position, random.Random(4242))
            b = legacy.draw(ros, position, random.Random(4242))
            assert a == b, f"diverged at position={position!r} rosValue={ros}: {a} vs {b}"


def test_the_legacy_model_still_declares_its_own_source():
    """Parity of NUMBERS is not parity of PROVENANCE. The dormant path
    must keep saying it is on legacy constants, so a sim run reporting
    ``pointsModelSource`` cannot claim calibration it did not get."""
    assert _sim._LEGACY_POINTS_MODEL.source == "legacy-constants"
    assert _sc.PointsModel().source == "fallback-constants"


def test_the_conversion_constant_is_not_restated_in_code():
    """``2.7`` must not appear as a divisor in the consumer's CODE.

    Asserted over the AST rather than the source text, because the first
    version of this test matched the module's own DOCSTRING describing
    the constant — prose about a defect is not the defect. Same trap the
    V1-51 structural guard hit, and the same fix.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(_sim))
    divisors = [
        node.right.value
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant)
        and isinstance(node.right.value, (int, float))
    ]
    assert 2.7 not in divisors, (
        "the rosValue->points divisor is restated as a literal in "
        "league_intel.sim; it belongs to "
        "sim_calibration.FALLBACK_ROS_VALUE_PER_POINT"
    )


def test_the_owner_still_holds_the_constant():
    """NON-VACUITY: the test above passes trivially if the constant
    stopped existing anywhere. It has an owner, and this names it."""
    assert _sc.FALLBACK_ROS_VALUE_PER_POINT == 2.7
    assert _sc.PointsModel().ros_value_per_point == 2.7
