"""News provider registry.

The service layer imports providers from here rather than from
individual modules so adding a provider is a one-line change in
``_PROVIDER_FACTORIES`` below.  Providers register a factory (not an
instance) so the service can construct them with per-deploy config
loaded at startup.

Priority ordering (trending first, then RSS headline sources,
then licensed sources):
    1. Sleeper trending — real-time adds/drops, always-on, no auth
    2. ESPN RSS — broad headline firehose, public feed
    3. FantasyPros RSS — fantasy-flavored player news, public feed
    4. CBS Sports RSS — NFL headlines, public feed
    5. Rotowire — licensing pending, stub until auth'd
"""
from __future__ import annotations

from typing import Callable, Dict

from ..base import NewsProvider
from .cbs import CbsFantasyRssProvider
from .espn import EspnRssProvider
from .fantasypros import FantasyProsRssProvider
from .rotowire import RotowireProvider
from .sleeper import SleeperTrendingProvider


ProviderFactory = Callable[..., NewsProvider]


# Ordered dict — iteration order is the priority order providers
# run in.  Earlier providers' items appear first in the aggregated
# feed before sort-by-timestamp.
_PROVIDER_FACTORIES: Dict[str, ProviderFactory] = {
    "sleeper": SleeperTrendingProvider,
    "espn": EspnRssProvider,
    "fantasypros": FantasyProsRssProvider,
    "cbs": CbsFantasyRssProvider,
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
    "EspnRssProvider",
    "FantasyProsRssProvider",
    "RotowireProvider",
    "SleeperTrendingProvider",
    "available_provider_names",
    "build_provider",
]
