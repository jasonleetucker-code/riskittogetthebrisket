"""Weekly IDP opportunity challengers — SHADOW / RESEARCH ONLY (issue #2039).

Three family challengers (CB; LB / S; EDGE / DT) that project a defender's weekly
stat line from opportunity (snaps / role, injury replacement, opponent opportunity
by true-position group, regressed splash plays) and rescore it under the exact league
card through the canonical scorer (:func:`src.league_intel.scorer.score_stat_line`).
They are compared with a point-in-time rolling league-scored average.

Preregistration: ``docs/projections/IDP_OPPORTUNITY_CHALLENGERS_PREREGISTRATION_2026-11-01.md``.
Results: ``docs/projections/IDP_OPPORTUNITY_CHALLENGERS_RESULTS_2026-11-01.md``.

Boundaries (pinned by ``tests/ros/idp_opportunity/test_isolation.py``):

* nothing live imports this package — no route, no waiver/streaming engine, no
  contract builder, no frontend;
* it never reads or writes a dynasty value, rank, source vote or flag;
* its only evidence type is ``weekly_opportunity`` (see :data:`EVIDENCE_TYPE`);
  rest-of-season and dynasty evidence are different, separately named types that
  this package never produces.

Point-in-time rule: a feature for week ``W`` may only read data from weeks ``< W``
(:class:`~src.ros.idp_opportunity.leakage.AsOfView` raises
:class:`~src.ros.idp_opportunity.leakage.LeakageError` otherwise).  The only week-``W``
inputs are pre-game facts — the schedule and the injury report — which are read
through explicitly named, labelled methods.
"""

from __future__ import annotations

from src.ros.idp_opportunity.leakage import (
    AsOfView,
    LeakageError,
    SeasonData,
)

#: The one evidence type this package produces.  Never ``rest_of_season`` or
#: ``dynasty``: those are distinct concepts with their own owners.
EVIDENCE_TYPE = "weekly_opportunity"
EVIDENCE_TYPES_KNOWN = ("weekly_opportunity", "rest_of_season", "dynasty")

__all__ = [
    "EVIDENCE_TYPE",
    "EVIDENCE_TYPES_KNOWN",
    "AsOfView",
    "LeakageError",
    "SeasonData",
]
