"""Automated DFS data (DFS-AUTO): slates, salaries, schedule, identity, status and projections
acquired and refreshed without owner file uploads.  See docs/dfs/DECISIONS.md ADR-DFS-024.

Platform player IDs are the one thing no permitted free source publishes, so an
automatically populated athlete carries a SYNTHETIC id (``auto-…``).  It is good
for building, simulating and reviewing lineups, and it is REFUSED at every
upload export (``PLATFORM_IDS_UNAVAILABLE``) — an upload file with invented IDs
would be worse than no file.
"""

from __future__ import annotations

from collections.abc import Iterable

AUTO_ID_PREFIX = "auto-"
#: The storage namespace the scheduled refresh writes into; owners get a CLONE.
SYSTEM_OWNER = "system:auto"


class PlatformIdsUnavailable(ValueError):
    code = "PLATFORM_IDS_UNAVAILABLE"
    message = (
        "This slate was populated automatically, and no permitted free source publishes "
        "DraftKings / FanDuel player IDs, so an upload file cannot be written for it. "
        "Build, simulate and review freely; for an upload-ready file, load the platform's "
        "own salary file under Advanced, or enable a licensed slate feed."
    )

    def __init__(self, ids: list[str]):
        super().__init__(self.message)
        self.detail = {"syntheticIds": ids[:20], "count": len(ids)}


def is_auto_id(player_id: str) -> bool:
    return str(player_id).startswith(AUTO_ID_PREFIX)


def refuse_synthetic_ids(ids: Iterable[str]) -> None:
    """Every upload writer calls this before writing a single row."""
    bad = sorted({str(i) for i in ids if is_auto_id(str(i))})
    if bad:
        raise PlatformIdsUnavailable(bad)
