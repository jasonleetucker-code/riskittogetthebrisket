"""Versioned challenger records; evaluation cannot accept or apply a change."""
from __future__ import annotations
from dataclasses import dataclass
from .evidence import RunMetrics, evaluate_challenger

@dataclass(frozen=True)
class ChallengerRecord:
    proposal_id: str
    champion_id: str
    challenger_id: str
    held_out_case_ids: tuple[str, ...]
    recommendation: str
    authority_required: bool = True

def evaluate(proposal_id: str, champion_id: str, challenger_id: str, held_out_case_ids: list[str], champion: list[RunMetrics], challenger: list[RunMetrics]) -> ChallengerRecord:
    result = evaluate_challenger(champion, challenger)
    return ChallengerRecord(proposal_id, champion_id, challenger_id, tuple(held_out_case_ids), str(result["recommendation"]), bool(result.get("authority_required", True)))
