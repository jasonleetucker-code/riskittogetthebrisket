"""IDP comparison hooks — placeholder for future activation.

The first release of League Comparison focuses on offense (QB / RB /
WR / TE / Top-96 flex).  IDP is *scaffolded but inert* so the UI can
render an "IDP coming soon" panel without special-casing later, and so
flipping IDP on requires changing only this file plus the service
orchestrator's call site — no UI rewrite.

When ready to activate:

1. Verify that ``src.nfl_data.ingest.fetch_weekly_defensive_stats`` is
   producing usable rows for the configured seasons.
2. Verify that ``src.nfl_data.realized_points`` IDP scoring matches a
   known-good reference (e.g. another popular IDP scoring engine).
3. Replace the body of :func:`compute_idp_block` to call into the
   real metrics pipeline (mirror what offense does in
   ``service._build_offense_block``), fanning out across DL / LB / DB
   plus a Top-96 IDP pool.
4. Compare Top-96 IDP score against Top-96 offensive flex (computed
   by the offense pipeline) and emit the same shape as the offense
   block.

Until then the function returns a placeholder block so the UI can
render an "IDP coming soon" badge consistently.
"""
from __future__ import annotations

from typing import Any


def compute_idp_block() -> dict[str, Any]:
    """Return a placeholder IDP block matching the offense block shape.

    Today: ``available=False, status="placeholder"`` plus an empty
    positions dict.  Once the data is verified, replace with real
    per-position metrics (DL / LB / DB) and a Top-96 IDP-vs-flex
    deviation that feeds the similarity score.
    """
    return {
        "available": False,
        "status": "placeholder",
        "message": (
            "IDP comparison is scaffolded but not yet enabled.  Future "
            "release will compare Top-96 IDP scoring against Top-96 "
            "offensive flex scoring over the same multi-year sample."
        ),
        "positions": {},
        "top96Idp": None,
    }
