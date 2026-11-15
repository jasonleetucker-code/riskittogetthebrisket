"""camelCase payload of a :class:`TwoSidedDecision`.

Schema: ``tests/fixtures/decision_engine/two_sided_decision.schema.json``.
The integration lane's frontend materializer reads this shape verbatim; it
never computes a verdict.  Verdicts are CODES -- no headline text.
"""

from __future__ import annotations

from typing import Any

from src.trade.decision_engine.contracts import TeamDecision, TermResult, TwoSidedDecision

PAYLOAD_SCHEMA_VERSION = "two_sided_decision_v1"


def _term(t: TermResult) -> dict[str, Any]:
    return {
        "term": t.term,
        "lineageMember": t.lineage_member,
        "state": t.state,
        "countedAsVote": t.counted_as_vote,
        "direction": t.direction,
        "magnitudeClass": t.magnitude_class,
        "value": t.value,
        "unit": t.unit,
        "band": t.band,
        "mcStandardError": t.mc_standard_error,
        "predictiveSd": t.predictive_sd,
        "predictiveBasis": t.predictive_basis,
        "precisionOk": t.precision_ok,
        "reason": t.reason,
    }


def _team(d: TeamDecision) -> dict[str, Any]:
    return {
        "teamId": d.team_id,
        "verdictCode": d.verdict,
        "neutralTag": d.neutral_tag,
        "strategy": d.strategy,
        "strategySource": d.strategy_source,
        "policyRow": d.policy_row,
        "predictiveProbability": None,
        "confidence": d.confidence,
        "confidenceBottleneck": d.confidence_bottleneck,
        "confidenceAxes": dict(d.confidence_axes),
        "isProbability": False,
        "reasons": [
            {
                "code": r.code,
                "family": r.family,
                "stance": r.stance,
                "textKey": r.text_key,
                "magnitude": r.magnitude,
            }
            for r in d.reasons
        ],
        "keyNumbers": dict(d.key_numbers),
        "whatWouldChange": [dict(w) for w in d.what_would_change],
        "missingEvidence": [dict(m) for m in d.missing_evidence],
        "layersUsed": [_term(t) for t in d.terms],
        "doubleCountGuard": dict(d.double_count_guard),
        "receipt": dict(d.receipt),
    }


def to_payload(decision: TwoSidedDecision) -> dict[str, Any]:
    return {
        "schemaVersion": PAYLOAD_SCHEMA_VERSION,
        "engineVersion": decision.engine_version,
        "paramSetId": decision.param_set_id,
        "shape": decision.shape,
        "teams": [_team(t) for t in decision.teams],
        "recommendationOnly": decision.recommendation_only,
        "executes": decision.executes,
    }
