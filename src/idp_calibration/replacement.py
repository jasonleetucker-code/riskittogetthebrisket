"""Replacement-level calculations for the IDP calibration lab.

Given a :class:`~src.idp_calibration.lineup.LineupDemand` and the
already-scored players for a league/season, this module derives the
effective replacement *rank* per position and interpolates the
replacement *points* from the scored-player list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .lineup import LineupDemand

POSITIONS: tuple[str, ...] = ("DL", "LB", "DB")

MODES: tuple[str, ...] = ("strict_starter", "starter_plus_buffer", "manual")


@dataclass
class ReplacementSettings:
    mode: str = "starter_plus_buffer"
    buffer_pct: float = 0.15
    manual: dict[str, int] = field(default_factory=dict)

    def normalized(self) -> "ReplacementSettings":
        mode = self.mode if self.mode in MODES else "starter_plus_buffer"
        buf = max(0.0, min(1.0, float(self.buffer_pct or 0.0)))
        manual = {str(k).upper(): int(v) for k, v in (self.manual or {}).items() if v}
        return ReplacementSettings(mode=mode, buffer_pct=buf, manual=manual)


@dataclass
class ReplacementLevel:
    position: str
    replacement_rank: int
    replacement_points: float
    cohort_size: int
    note: str = ""


def compute_replacement_levels(
    scored: Iterable[dict[str, Any]],
    demand: LineupDemand,
    settings: ReplacementSettings,
) -> dict[str, ReplacementLevel]:
    """Compute per-position replacement rank + points.

    ``scored`` is an iterable of dicts with at least
    ``{position, points}``. Within each position the list is sorted
    descending by points, and the replacement point is taken as the
    points at ``replacement_rank`` (1-indexed). If the cohort is
    smaller than ``replacement_rank`` the last available player's
    points are used and the ``note`` field reports the fallback.
    """
    settings = settings.normalized()
    by_position: dict[str, list[float]] = {pos: [] for pos in POSITIONS}
    for row in scored:
        pos = str(row.get("position") or "").upper()
        if pos not in by_position:
            continue
        try:
            pts = float(row.get("points") or 0.0)
        except (TypeError, ValueError):
            pts = 0.0
        by_position[pos].append(pts)
    out: dict[str, ReplacementLevel] = {}
    for pos in POSITIONS:
        points_desc = sorted(by_position[pos], reverse=True)
        rank = demand.replacement_rank(
            pos,
            settings.mode,
            settings.buffer_pct,
            settings.manual.get(pos),
        )
        cohort = len(points_desc)
        note = ""
        if cohort == 0:
            repl_pts = 0.0
            note = f"No scored {pos} players in this season; replacement = 0."
        elif rank <= cohort:
            repl_pts = points_desc[rank - 1]
        else:
            repl_pts = points_desc[-1]
            note = (
                f"Replacement rank {rank} exceeds cohort size {cohort}; "
                f"falling back to the last-ranked player's points."
            )
        out[pos] = ReplacementLevel(
            position=pos,
            replacement_rank=rank,
            replacement_points=float(repl_pts),
            cohort_size=cohort,
            note=note,
        )
    return out


def replacement_to_dict(levels: dict[str, ReplacementLevel]) -> dict[str, Any]:
    return {
        pos: {
            "replacement_rank": lv.replacement_rank,
            "replacement_points": round(lv.replacement_points, 3),
            "cohort_size": lv.cohort_size,
            "note": lv.note,
        }
        for pos, lv in levels.items()
    }
