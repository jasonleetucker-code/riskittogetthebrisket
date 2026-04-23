"""News provider registry.

The service layer imports providers from here rather than from
individual modules so adding a provider is a one-line change in
``_PROVIDER_FACTORIES`` below.  Providers register a factory (not
an instance) so the service can construct them with per-deploy
config loaded at startup.

Registered providers (ordered by priority — earliest first):

1. **sleeper** — Sleeper trending adds/drops (API, not RSS).
2. **espn** — ESPN NFL news RSS.
3. **fantasypros** — FantasyPros player-news RSS.
4. **cbs** — CBS Sports NFL headlines RSS.
5. **dlf** — Dynasty League Football RSS.
6. **dynastynerds** — Dynasty Nerds RSS.
7. **pff** — Pro Football Focus RSS.
8. **fftoday** — FFToday news RSS (explicit .xml endpoint).
9. **playerprofiler** — Player Profiler analytics RSS.
10. **razzball** — Razzball fantasy advice RSS.
11. **rotowire** — stub, OFF until licensed.

Every RSS provider inherits from ``RssNewsProvider`` (in
``_rss.py``) — adding another source is a 6-line subclass.
"""
from __future__ import annotations

from typing import Callable, Dict

from ..base import NewsProvider
from .cbs import CbsFantasyRssProvider
from .dynasty_focused import (
    DynastyLeagueFootballProvider,
    DynastyNerdsProvider,
    FfTodayProvider,
    PffProvider,
    PlayerProfilerProvider,
    RazzballProvider,
)
from .espn import EspnRssProvider
from .fantasypros import FantasyProsRssProvider
from .rotowire import RotowireProvider
from .sleeper import SleeperTrendingProvider


ProviderFactory = Callable[..., NewsProvider]


# Ordered dict — iteration order is the priority order providers
# run in.  Earlier providers' items appear first in the aggregated
# feed before sort-by-(severity, timestamp).
_PROVIDER_FACTORIES: Dict[str, ProviderFactory] = {
    "sleeper": SleeperTrendingProvider,
    "espn": EspnRssProvider,
    "fantasypros": FantasyProsRssProvider,
    "cbs": CbsFantasyRssProvider,
    "dlf": DynastyLeagueFootballProvider,
    "dynastynerds": DynastyNerdsProvider,
    "pff": PffProvider,
    "fftoday": FfTodayProvider,
    "playerprofiler": PlayerProfilerProvider,
    "razzball": RazzballProvider,
    "rotowire": RotowireProvider,
}


def available_provider_names() -> list[str]:
    """Return registered provider names in priority order."""
    return list(_PROVIDER_FACTORIES.keys())


def build_provider(name: str, **config) -> NewsProvider:
    """Construct a registered provider by name.

    Raises ``KeyError`` if the name is not registered.
    """
    key = name.lower()
    factory = _PROVIDER_FACTORIES[key]
    return factory(**config)


__all__ = [
    "CbsFantasyRssProvider",
    "DynastyLeagueFootballProvider",
    "DynastyNerdsProvider",
    "EspnRssProvider",
    "FantasyProsRssProvider",
    "FfTodayProvider",
    "PffProvider",
    "PlayerProfilerProvider",
    "RazzballProvider",
    "RotowireProvider",
    "SleeperTrendingProvider",
    "available_provider_names",
    "build_provider",
]
