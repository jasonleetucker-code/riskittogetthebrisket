"""What the measured result actually covers — and whether today matches it.

``COMPONENT_VALIDATION["mispricing"]`` claims an out-of-sample result and
cites the file that produced it.  Neither the claim nor the file says
which *configuration* of the pipeline was measured, and one configuration
knob is not covered by it:

``scripts/run_consensus_edge_backtest.py`` calls ``fair_value_index``
with **no** ``scoring_fit_board``.  ``service.build_board`` passes one.
Today that is a distinction without a difference — the checked-in Sleeper
directory is a 15-row stub with zero ``gsis_id``s, so the join is empty,
the reception axis refuses, and the fit is exactly 1.0 everywhere.  The
day a real directory reaches production, served fair values get
multiplied by per-player multipliers that ρ +0.126 never saw, and
nothing anywhere would say so.

**Why the backtest is not simply taught to apply the fit.**  It cannot,
honestly.  The reception multipliers are measured from a season's
weekly rows and a reception-depth payload, neither of which the panel
reconstructs as-of.  Applying today's multipliers to a board from three
months ago would be look-ahead leakage — the multipliers were fitted on
data from *after* the origin date — dressed as a fix.  So the backtest
asserts the fit is inert, and this module is how the divergence becomes
visible if it ever stops being.

The honest resolution is therefore not to make the two identical but to
make the gap a **reported fact** on both sides: the measurement stamps
what it measured, the board stamps whether it is running that
configuration, and a mismatch downgrades the validation claim in the
payload instead of silently invalidating it.
"""

from __future__ import annotations

from typing import Any

# The configuration the committed measurements were produced under.
# Update ONLY alongside a re-run that measures the new configuration.
MEASURED_CONFIGURATION: dict[str, Any] = {
    "scoringFitApplied": False,
    "sharpFlowPresent": False,
    "note": (
        "Measured with league scoring fit INERT and no sharp ledger. The "
        "reception-depth multipliers cannot be reconstructed as-of a past date, "
        "so applying them in a replay would be look-ahead leakage rather than a "
        "closer match to production."
    ),
}


def scope_for_board(scoring_fit_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Whether this board is running the configuration that was measured.

    Returns a block for the payload carrying the comparison and, when it
    fails, a plain statement of what that costs the validation claim.
    ``matchesMeasured`` is the field a consumer should gate on; the rest
    is there so the answer can be checked rather than trusted.
    """
    fit_active = bool((scoring_fit_meta or {}).get("active"))
    differences: list[str] = []
    if fit_active != MEASURED_CONFIGURATION["scoringFitApplied"]:
        differences.append(
            "league scoring fit is applied to fair value on this board but was "
            "inert in the backtest, so the measured rho does not describe the "
            "values being served"
        )

    return {
        "measuredConfiguration": MEASURED_CONFIGURATION,
        "boardConfiguration": {"scoringFitApplied": fit_active},
        "matchesMeasured": not differences,
        "differences": differences,
    }
