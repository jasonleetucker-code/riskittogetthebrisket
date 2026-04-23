"""Rotowire provider — placeholder until licensing lands.

Rotowire's player-news API requires a commercial licence that we
haven't finalized yet.  This stub exists so the registry can list
``rotowire`` as a recognized provider name (so ops can toggle it
in config without a code change once licensed) while the adapter
itself returns an empty list.

When the licence is in place, swap ``fetch`` for a real
implementation that hits the licensed endpoint and maps the
response to ``NewsItem`` — the rest of the stack (service,
aggregator, route, frontend) will light up automatically.
"""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from ..base import NewsItem, NewsProvider

log = logging.getLogger(__name__)


class RotowireProvider(NewsProvider):
    name = "rotowire"
    label = "Rotowire"
    timeout_s = 5.0

    def __init__(self, *, api_key: Optional[str] = None) -> None:
        super().__init__(api_key=api_key)
        self._api_key = api_key

    def fetch(
        self,
        *,
        player_names: Optional[Iterable[str]] = None,
        limit: int = 50,
    ) -> List[NewsItem]:
        # Intentional no-op.  Logged at debug so enabling the
        # provider without a licence doesn't spam warnings.
        if not self._api_key:
            log.debug("rotowire provider skipped — no api_key configured")
        return []


__all__ = ["RotowireProvider"]
