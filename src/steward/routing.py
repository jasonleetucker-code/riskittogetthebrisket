"""Measured routing recommendations; callers retain budget and authority gates.

Recommend-only, by construction: nothing here dispatches a model call.
Every non-trivial recommendation carries the measured evidence it was
based on (run count, mean cost/latency, rejection rate) rather than a bare
label -- a recommendation with no cited evidence is not "measurably
informed," it is a guess wearing an evidence-shaped name. No threshold
here picks a cheaper tier from cost/latency alone: that would need a real
held-out evaluation harness, which is explicitly deferred (no calibrated
threshold exists yet), so cost and latency are reported as facts, never
used to downgrade quality on their own.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .evidence import RunMetrics


@dataclass(frozen=True)
class RouteRecommendation:
    work_class: str
    recommendation: str
    reason: str
    measured_runs: int = 0
    measured_mean_cost_usd: float | None = None
    measured_mean_latency_ms: float | None = None
    measured_rejection_rate: float | None = None


def recommend_route(work_class: str, historical: Iterable[RunMetrics]) -> RouteRecommendation:
    rows = list(historical)
    if work_class == "deterministic":
        return RouteRecommendation(work_class, "NO_MODEL", "deterministic judge available")
    if work_class in {"independent_review", "high_risk"}:
        return RouteRecommendation(
            work_class, "INDEPENDENT_CONTEXT", "correlated blind spots materially matter"
        )
    if not rows:
        return RouteRecommendation(work_class, "CHAMPION_DEFAULT", "no measured held-out evidence")
    rejected = sum(not row.accepted or row.reviewer_rejected for row in rows)
    rejection_rate = rejected / len(rows)
    costs = [row.cost_usd for row in rows if row.cost_usd is not None]
    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
    mean_cost = sum(costs) / len(costs) if costs else None
    mean_latency = sum(latencies) / len(latencies) if latencies else None
    if rejected:
        return RouteRecommendation(
            work_class,
            "CHAMPION_DEFAULT",
            "historical rejection evidence requires no automatic downgrade",
            measured_runs=len(rows),
            measured_mean_cost_usd=mean_cost,
            measured_mean_latency_ms=mean_latency,
            measured_rejection_rate=rejection_rate,
        )
    return RouteRecommendation(
        work_class,
        "LOWEST_MEASURED_SUFFICIENT",
        "quality evidence is clean; authority and budget still apply",
        measured_runs=len(rows),
        measured_mean_cost_usd=mean_cost,
        measured_mean_latency_ms=mean_latency,
        measured_rejection_rate=rejection_rate,
    )
