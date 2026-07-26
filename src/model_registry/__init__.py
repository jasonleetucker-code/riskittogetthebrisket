"""Continuous Improvement System — controlled retraining for fitted models.

The governing directive is one sentence long and every module here
exists to satisfy a clause of it:

    Do not allow a model to autonomously rewrite production code.  Use
    controlled retraining, champion-challenger validation, model
    versioning, and rollback.  Do not present low-confidence output as
    precise.

Scope.  A "model" here is any tunable that behaves like a FITTED
PARAMETER — a number produced by an optimizer against data, not chosen
by a human for a reason they could state.  The Hill scope masters are
the live example: eight constants in
``src/canonical/player_valuation.py`` refit weekly by
``.github/workflows/refit-hill-curves.yml`` and committed to main
without review.

What this package does NOT do: it does not compute values, does not
import the valuation pipeline, and does not change what any live
endpoint returns.  It records what a fitted parameter set is, where it
came from, how it scored on data it never saw, and which version is
authoritative.  Promotion and rollback are explicit operations.

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
