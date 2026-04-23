"""News ingestion package.

Public surface:

* ``NewsItem`` / ``PlayerMention`` — normalized response schema.
* ``NewsProvider`` — abstract base for ingestion adapters.
* ``NewsService`` / ``build_default_service`` — aggregator used
  by the ``/api/news`` route.
* ``available_provider_names`` / ``build_provider`` — registry
  introspection for diagnostics.
"""
from __future__ import annotations

from .base import NewsItem, NewsProvider, PlayerMention, stable_id, to_iso_utc
from .providers import available_provider_names, build_provider
from .service import (
    AggregatedNews,
    DEFAULT_CACHE_TTL_S,
    DEFAULT_LIMIT_PER_PROVIDER,
    DEFAULT_TOTAL_LIMIT,
    NewsService,
    ProviderRunResult,
    build_default_service,
)

__all__ = [
    "AggregatedNews",
    "DEFAULT_CACHE_TTL_S",
    "DEFAULT_LIMIT_PER_PROVIDER",
    "DEFAULT_TOTAL_LIMIT",
    "NewsItem",
    "NewsProvider",
    "NewsService",
    "PlayerMention",
    "ProviderRunResult",
    "available_provider_names",
    "build_default_service",
    "build_provider",
    "stable_id",
    "to_iso_utc",
]
