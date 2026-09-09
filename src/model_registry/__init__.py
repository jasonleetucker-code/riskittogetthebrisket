"""Continuous Improvement System — controlled retraining for fitted models.

The governing directive is one sentence long and every module here
exists to satisfy a clause of it:

    A fitted model may become canonical automatically only through a
    deterministic, fail-closed champion/challenger policy with reproducible
    evidence, scope-specific validation, downstream impact checks, versioning
    and rollback. Raw refits never write production directly.

Scope.  A "model" here is any tunable that behaves like a FITTED
PARAMETER — a number produced by an optimizer against data, not chosen
by a human for a reason they could state.  The Hill scope masters are
the live example: eight constants in
``src/canonical/player_valuation.py`` refit after each material two-hour market-data refresh by
``.github/workflows/refit-hill-curves.yml`` and committed to main
without review.

What this package does NOT do: it does not compute values and does not
import the valuation pipeline.  ``src/api/data_contract.py`` reads it
read-only, for exactly one purpose (V1-21 / W04-F011): stamping the
served ``hillCurves.provenance`` block with which champion produced the
live Hill-master constants.  That stamp never changes a player's value —
it is metadata about the constants, not an input to computing them — so
the package still computes nothing and still owns no valuation math.
It records what a fitted parameter set is, where it came from, how it
scored on data it never saw, and which version is authoritative.
Promotion and rollback remain explicit registry operations; Hill Autopilot may invoke promotion only after its codified readiness gates clear.

Modules
-------
``versioning``  Model versions, provenance, the champion pointer,
                promote/rollback as single operations.
``holdout``     Out-of-sample evaluation, with a hard guard against
                scoring a model on its own training sources.
``promotion``   The champion-challenger decision and its stated limits.
"""

from src.model_registry.holdout import (
    HoldoutResult,
    SourceRole,
    evaluate_offense_master,
    source_roles,
)
from src.model_registry.promotion import PromotionDecision, decide_promotion
from src.model_registry.versioning import (
    ModelRegistry,
    ModelVersion,
    RegistryError,
    fingerprint_file,
)

__all__ = [
    "HoldoutResult",
    "ModelRegistry",
    "ModelVersion",
    "PromotionDecision",
    "RegistryError",
    "SourceRole",
    "decide_promotion",
    "evaluate_offense_master",
    "fingerprint_file",
    "source_roles",
]
