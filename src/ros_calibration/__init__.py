"""ROS scale calibration — RESEARCH / SHADOW ONLY.

Translates the rest-of-season ``rosValue`` index (a per-board log-rank score
on 0-100, see ``src/ros/aggregate.py``) into a COMPARABLE currency —
expected weekly fantasy points under the league's exact card — so offense and
IDP contributions can be compared or summed.

Status: ``RESEARCH_EVIDENCE_NOT_FOR_PROMOTION``.  Nothing in production imports
this package (pinned by ``tests/ros_calibration/test_isolation.py``); the only
consumer is ``scripts/ros_scale_calibration_study.py``.  It never writes a live
value, rank or ``rosValue``.  Preregistration:
``docs/league-intelligence/ROS_SCALE_CALIBRATION_PREREGISTRATION_2026-10-28.md``.
"""

from __future__ import annotations

__all__ = ["conversion", "metrics", "par"]
