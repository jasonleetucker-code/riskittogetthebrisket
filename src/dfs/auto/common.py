"""Pieces every automated sport shares (NFL weekly, NBA/NHL daily): the pool report,
the count-aware projection ensemble, the snapshot projection report and the
content hash.  One definition each — ``nfl.py`` and ``daily.py`` import them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Mapping

from src.dfs.imports import content_hash

#: Two families disagreeing by more than this (relative to their mean) is flagged.
DISAGREEMENT_FLAG = 0.30
SAFE_SOURCE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z\-]{0,30}$")


@dataclass
class PoolReport:
    rows_read: int = 0
    used: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)
    identity: dict[str, int] = field(default_factory=dict)
    quarantined_identity: list[dict[str, Any]] = field(default_factory=list)
    families: dict[str, int] = field(default_factory=dict)
    withheld_for_status: list[str] = field(default_factory=list)
    disagreements: int = 0
    notes: list[str] = field(default_factory=list)
    #: Every refusal counted by reason (uncapped; ``rejected`` keeps a sample).
    rejected_by_reason: dict[str, int] = field(default_factory=dict)

    def reject(self, row: Mapping[str, Any], reason: str) -> None:
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
        if len(self.rejected) < 200:
            self.rejected.append(
                {"name": str(row.get("name") or "")[:60], "team": row.get("team"), "reason": reason}
            )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "rowsRead": self.rows_read,
            "rowsUsed": self.used,
            "rejected": self.rejected,
            "rejectedByReason": dict(sorted(self.rejected_by_reason.items())),
            "identity": dict(sorted(self.identity.items())),
            "quarantinedIdentity": self.quarantined_identity[:50],
            "projectionFamilies": dict(sorted(self.families.items())),
            "withheldForStatus": self.withheld_for_status[:50],
            "familyDisagreements": self.disagreements,
        }
        if self.notes:
            out["notes"] = list(self.notes)
        return out


def ensemble(values: list[float]) -> float | None:
    """Independent projection families → one number.  n=1 passthrough, n=2 mean,
    n≥3 median — the count-aware ladder the Calculator's blend uses at small n."""
    if not values:
        return None
    if len(values) <= 2:
        return round(sum(values) / len(values), 2)
    return round(float(median(values)), 2)


def projection_report(
    report: PoolReport, athletes: list[Any], projected: int, note: str
) -> dict[str, Any]:
    """Same shape as a projection-file import (``imports._join_values``): the page
    and every consumer read ONE report contract whichever path filled the slate."""
    return {
        "source": "auto_ensemble",
        "rowsRead": report.rows_read,
        "matched": projected,
        "unmatched": [
            {"name": q["name"], "reason": f"identity_{q['state']}"}
            for q in report.quarantined_identity
            if q["state"] != "ambiguous"
        ][:200],
        "ambiguous": [
            {"name": q["name"], "candidates": q["candidates"], "reason": "ambiguous_identity"}
            for q in report.quarantined_identity
            if q["state"] == "ambiguous"
        ][:200],
        "invalid": [],
        "conflicts": [],
        "athletesWithoutProjection": len(athletes) - projected,
        "athletesWithoutOwnership": len(athletes),
        "note": note,
    }


def body_hash(body: dict[str, Any]) -> str:
    return content_hash({"ruleset": body["ruleset"], "athletes": body["athletes"]})
