"""Versioned challenger records; evaluation cannot accept or apply a change.

The full model-harness optimization pipeline this module is a slice of:
`baseline -> prompt_audit -> cost_optimization -> model_effort_sweep ->
challenger_optimization -> held_out_evaluation -> recommendation`. Only the
last two stages are actually implemented here (`evaluate()` wraps
`evidence.evaluate_challenger`, the held-out-evaluation step, and stamps a
recommendation); `challenger_optimization`'s output is a caller-supplied
input, not something this module produces. `baseline` / `prompt_audit` /
`cost_optimization` / `model_effort_sweep` are named so the gap is visible
rather than silently absent, and are explicitly DEFERRED_BY_AUTHORITY: they
need real held-out evaluation-harness infrastructure (representative task
sets, scoring, statistical comparison) this pass does not build. Naming a
stage is not the same as having built it.
"""

from __future__ import annotations
from dataclasses import dataclass
from .evidence import RunMetrics, evaluate_challenger

#: Every stage the directive names. `IMPLEMENTED_STAGES` is the subset this
#: module actually performs; the rest are DEFERRED_BY_AUTHORITY.
PIPELINE_STAGES = (
    "baseline",
    "prompt_audit",
    "cost_optimization",
    "model_effort_sweep",
    "challenger_optimization",
    "held_out_evaluation",
    "recommendation",
)
IMPLEMENTED_STAGES = ("challenger_optimization", "held_out_evaluation", "recommendation")
DEFERRED_STAGES = tuple(stage for stage in PIPELINE_STAGES if stage not in IMPLEMENTED_STAGES)


@dataclass(frozen=True)
class ChallengerRecord:
    proposal_id: str
    champion_id: str
    challenger_id: str
    held_out_case_ids: tuple[str, ...]
    recommendation: str
    authority_required: bool = True
    #: Which pipeline stage produced this record -- always
    #: "held_out_evaluation" today, since that is the only stage `evaluate()`
    #: performs. Exists so a caller can never mistake this for having run
    #: the earlier, deferred stages too.
    pipeline_stage_reached: str = "held_out_evaluation"


def evaluate(
    proposal_id: str,
    champion_id: str,
    challenger_id: str,
    held_out_case_ids: list[str],
    champion: list[RunMetrics],
    challenger: list[RunMetrics],
) -> ChallengerRecord:
    result = evaluate_challenger(champion, challenger)
    return ChallengerRecord(
        proposal_id,
        champion_id,
        challenger_id,
        tuple(held_out_case_ids),
        str(result["recommendation"]),
        bool(result.get("authority_required", True)),
    )
