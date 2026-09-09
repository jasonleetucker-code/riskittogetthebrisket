"""Deterministic, report-only run evidence; no authority transitions occur here."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class RunMetrics:
    run_id: str
    accepted: bool
    correctness: float
    false_completion: bool = False
    reviewer_rejected: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    tool_calls: int = 0
    retries: int = 0
    @property
    def cache_hit_ratio(self) -> float | None:
        if self.cache_read_tokens is None or not self.input_tokens:
            return None
        return self.cache_read_tokens / self.input_tokens

@dataclass(frozen=True)
class AutonomyEvidence:
    representative_runs: int
    accepted_runs: int
    reviewer_rejections: int
    false_completions: int
    unresolved_consequential_failures: int
    receipt_complete_runs: int
    @property
    def eligible(self) -> bool:
        return (self.representative_runs > 0 and self.accepted_runs == self.representative_runs and self.reviewer_rejections == 0 and self.false_completions == 0 and self.unresolved_consequential_failures == 0 and self.receipt_complete_runs == self.representative_runs)

def autonomy_evidence(runs: Iterable[RunMetrics], *, unresolved_consequential_failures: int = 0) -> AutonomyEvidence:
    rows = list(runs)
    return AutonomyEvidence(len(rows), sum(r.accepted for r in rows), sum(r.reviewer_rejected for r in rows), sum(r.false_completion for r in rows), unresolved_consequential_failures, sum(bool(r.run_id) for r in rows))

def evaluate_challenger(champion: Iterable[RunMetrics], challenger: Iterable[RunMetrics]) -> dict[str, object]:
    c, x = list(champion), list(challenger)
    if not c or not x:
        return {"recommendation": "INSUFFICIENT_HELD_OUT_EVIDENCE"}
    champion_score = sum(r.correctness for r in c) / len(c)
    challenger_score = sum(r.correctness for r in x) / len(x)
    safe = not any(r.false_completion or r.reviewer_rejected or not r.accepted for r in x)
    return {"recommendation": "CHALLENGER_ELIGIBLE_FOR_AUTHORITY_REVIEW" if safe and challenger_score >= champion_score else "KEEP_CHAMPION", "champion_correctness": champion_score, "challenger_correctness": challenger_score, "authority_required": True}

def retrospective(runs: Iterable[RunMetrics]) -> list[dict[str, str]]:
    rows = list(runs); findings=[]
    if sum(r.retries for r in rows) >= 2: findings.append({"observation":"repeated retries","proposed_change":"add deterministic startup or replay check","status":"PROPOSED_CHALLENGER"})
    if sum(r.reviewer_rejected for r in rows): findings.append({"observation":"reviewer rejection","proposed_change":"add evaluation case or verifier","status":"PROPOSED_CHALLENGER"})
    return findings
