"""Which board an engine request is answered from (the valuation-mode seam).

Pure twin of the decision ``server._valuation_scoped_contract`` makes, so a
non-route caller (``src.trade.analyze_service``) applies the SAME rule without
importing the server.  The server seam delegates here, so there is still one
place the league-adjusted lens could ever reach an engine — and it is closed:

The league-adjusted lens was WITHDRAWN 2026-08-14 (rejected for promotion to
canonical; ``docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md``).  A
request for it is IGNORED, never refused — the canonical market board is
served and the response is stamped so the answer travels with the payload.
Pinned by ``tests/api/test_canonical_value_invariance.py``.
"""

from __future__ import annotations

from typing import Any

MARKET = "market"
LEAGUE_ADJUSTED = "leagueAdjusted"
WITHDRAWN_NOTE = "league_adjusted_withdrawn: not_canonical"


def scoped_contract(contract: Any, requested_mode: str | None) -> tuple[Any, str, str | None]:
    """``(contract, mode_served, note)`` for one request.

    The contract is returned untouched (never copied, never repriced); the
    mode served is always ``"market"``; ``note`` names the withdrawal when the
    lens was asked for.
    """
    if requested_mode == LEAGUE_ADJUSTED:
        return contract, MARKET, WITHDRAWN_NOTE
    return contract, MARKET, None
