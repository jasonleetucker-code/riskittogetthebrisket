"""Measured routing recommendations; callers retain budget and authority gates."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .evidence import RunMetrics

@dataclass(frozen=True)
class RouteRecommendation:
    work_class: str
    recommendation: str
    reason: str

def recommend_route(work_class: str, historical: Iterable[RunMetrics]) -> RouteRecommendation:
    rows = list(historical)
    if work_class == "deterministic":
        return RouteRecommendation(work_class, "NO_MODEL", "deterministic judge available")
    if work_class in {"independent_review", "high_risk"}:
        return RouteRecommendation(work_class, "INDEPENDENT_CONTEXT", "correlated blind spots materially matter")
    if not rows:
        return RouteRecommendation(work_class, "CHAMPION_DEFAULT", "no measured held-out evidence")
    rejected = sum(not row.accepted or row.reviewer_rejected for row in rows)
    if rejected:
        return RouteRecommendation(work_class, "CHAMPION_DEFAULT", "historical rejection evidence requires no automatic downgrade")
    return RouteRecommendation(work_class, "LOWEST_MEASURED_SUFFICIENT", "quality evidence is clean; authority and budget still apply")
