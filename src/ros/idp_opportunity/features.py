"""Reusable point-in-time weekly IDP features (shadow / research consumers only).

:func:`role_change` is the clean role-change detector requested for the streaming
research (the +19.9 vs +0.4 gap, issue #2039 §D).  It reads ONLY weeks before the
view's cutoff, through the :class:`~src.ros.idp_opportunity.leakage.AsOfView` guard,
and never the week-W injury report — so it is point-in-time safe by construction.

NOT EVALUATED in the 2026-11-01 preregistered study: it is offered as an input for a
future preregistered test, and carries no validated weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.ros.idp_opportunity.leakage import AsOfView
from src.ros.idp_opportunity.model import opt_float

__all__ = ["RoleChange", "role_change"]


def _share(line: Any) -> float | None:
    """Snap share, or ``None`` when either count is missing or the player did not play."""
    snp = opt_float(line, "def_snp")
    tm = opt_float(line, "tm_def_snp")
    if snp is None or tm is None or snp <= 0 or tm <= 0:
        return None
    return snp / tm


@dataclass(frozen=True)
class RoleChange:
    """``state``: ``ok`` | ``no_history`` | ``single_week`` (missing is never 0)."""

    state: str
    last_week: int | None = None
    last_share: float | None = None
    baseline_share: float | None = None
    delta: float | None = None
    baseline_weeks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "lastWeek": self.last_week,
            "lastShare": self.last_share,
            "baselineShare": self.baseline_share,
            "delta": self.delta,
            "baselineWeeks": self.baseline_weeks,
        }


def role_change(view: AsOfView, sleeper_id: str, *, baseline_weeks: int = 3) -> RoleChange:
    """Snap-share change in the player's most recent played week before the cutoff,
    against the mean of up to ``baseline_weeks`` played weeks before that one."""
    played: list[tuple[int, float]] = []
    for w in view.weeks_before():
        s = _share(view.stats_week(w).get(str(sleeper_id)))
        if s is not None:
            played.append((w, s))
    if not played:
        return RoleChange("no_history")
    last_w, last_s = played[-1]
    base = [s for _, s in played[:-1][-baseline_weeks:]]
    if not base:
        return RoleChange("single_week", last_week=last_w, last_share=last_s)
    b = sum(base) / len(base)
    return RoleChange("ok", last_w, last_s, b, last_s - b, len(base))
