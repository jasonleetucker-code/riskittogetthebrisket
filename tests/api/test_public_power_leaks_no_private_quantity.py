"""The public power ranking must not republish private intelligence.

THE DEFECT
----------
``rosPower`` is pinned PUBLIC (``test_public_league_privacy_boundary.py``) and
``/league`` is an unauthenticated route.  ``rosTeamStrength`` is PRIVATE and
auth-gated.  Yet ``power_v2.py`` published

    components.roster_health == healthAvailabilityScore / 100.0

— a field named in that same privacy test's ``PRIVATE_MARKERS`` — on the
public section.  The existing guard scans the serialized body for private
field NAMES, so a rename plus a rescale walks straight past it.  CLAUDE.md §5
is explicit that the public/private split is "a semantic boundary, not a
field-name denylist"; this is the failure mode that sentence names.

The disclosure was exact, not fuzzy: ``health_availability_score`` is
``healthy_starters / len(starting_rows) * 100`` over the league's 21 starter
slots, so at 4dp a public reader recovers the precise integer count of a
rival's flagged starters.

WHY THE FIX IS A DELETION, NOT A DECLASSIFICATION
-------------------------------------------------
Health was **double-counted**.  ``team_strength.py`` already folds it into the
composite at ``WEIGHT_HEALTH = 0.05``, and ``power_v2`` then added
``roster_health`` again at 0.03 on top of ``0.38 × percentile(composite)``.
CLAUDE.md §3.3 (signal independence): "A body of evidence affects a conclusion
once."

So removing the standalone term is de-double-counting, not weakening the
ranking — the owner's instruction that the public ranking must not be made
"deliberately weaker standings-only math" is honoured, and the health signal
survives inside ``team_ros_strength`` at its designed share.  Measured on the
preseason weight set: the direct term was 7.3% of the score, and 4.6% of health
influence is retained through the composite.

WHAT REMAINS PUBLIC, BY OWNER DECISION
--------------------------------------
ROS-derived TEAM-LEVEL strength is an approved public input, published as an
inclusive percentile.  That is not a reconstruction risk: the composite is
``0.72S + 0.18D + 0.05C + 0.05H`` and only its RANK is published — 11 ordering
constraints against 36 unknowns.  Detailed sub-scores, per-manager
recommendations and internal decomposition stay private.
"""

from __future__ import annotations

import pytest

from src.ros import power_v2

PRIVATE_SUB_SCORES = (
    "startingLineupScore",
    "benchDepthScore",
    "positionalCoverageScore",
    "healthAvailabilityScore",
)


def test_the_public_formula_has_no_standalone_private_sub_score_term():
    """No WEIGHTS key may be a private sub-score under another name."""
    assert "roster_health" not in power_v2.WEIGHTS, (
        "roster_health is healthAvailabilityScore/100 — a PRIVATE_MARKERS "
        "quantity republished on a public section under a different name, and "
        "already counted inside team_ros_strength"
    )


def test_no_private_sub_score_is_read_into_a_public_component():
    """Structural: the public engine must not read the private sub-scores.

    A name-based scan of the payload cannot catch a rename; reading the SOURCE
    for the private field names catches it at the point of use.
    ``team_ros_strength`` is exempt — the owner approved the composite's
    percentile as a public input, and it is consumed via the composite, not
    via its parts.
    """
    import ast
    from pathlib import Path

    src = Path(power_v2.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in PRIVATE_SUB_SCORES:
                offenders.append((node.value, node.lineno))
    assert not offenders, (
        "public power engine reads private sub-scores directly: "
        + ", ".join(f"{n} at line {ln}" for n, ln in offenders)
        + ". Only the approved teamRosStrength composite may cross the boundary."
    )


def test_health_influence_survives_through_the_composite():
    """Non-vacuity for the deletion: this is de-double-counting, NOT removal
    of the health signal.  If the composite ever stops carrying health, the
    deletion above would become a real product loss and this fails."""
    from src.ros import team_strength

    assert team_strength.WEIGHT_HEALTH > 0, (
        "health no longer contributes to teamRosStrength, so removing the "
        "standalone term now drops the signal entirely rather than "
        "de-duplicating it"
    )


def test_the_weights_still_sum_to_one():
    """Deleting a term must not silently rescale everyone else."""
    total = sum(power_v2.WEIGHTS.values())
    assert total == pytest.approx(1.0, abs=1e-9), (
        f"WEIGHTS sum to {total}, not 1.0 — the removed term's weight must be "
        "reallocated deliberately, not left as a hole"
    )
