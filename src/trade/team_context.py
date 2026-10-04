"""Use Team Context (C3-CTX-01) — the ONE reading of the request flag.

Every trade surface that offers the switch (``/api/trade/finder``,
``/api/trade/simulate``, ``/api/trade/analyze``) resolves it here, so the
default and the "what counts as off" rule cannot drift between routes.

ON by default.  Only an explicit boolean ``false`` turns it off: a missing,
null or malformed value is the canonical default, never a silent switch to
Asset-only (the scope manifest's "never silently switch ON -> OFF").
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["TEAM_CONTEXT_FIELD", "team_context_requested"]

#: Wire name of the switch in request bodies.
TEAM_CONTEXT_FIELD = "useTeamContext"


def team_context_requested(body: Mapping[str, Any] | None) -> bool:
    raw = (body or {}).get(TEAM_CONTEXT_FIELD) if isinstance(body, Mapping) else None
    return raw if isinstance(raw, bool) else True
