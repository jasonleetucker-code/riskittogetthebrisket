"""FantasyPros player-news provider.

FantasyPros publishes a public player-news RSS feed at
``https://www.fantasypros.com/nfl/rss/player-news.php``.  The
feed is unauthenticated and has the same RSS 2.0 structure as
ESPN — ``<channel><item><title|link|guid|pubDate|description>``
— so we reuse the shared RSS helper for parsing, severity
classification, and player tagging.

Why this is a separate provider and not a config knob on the
ESPN class: FantasyPros and ESPN have meaningfully different
editorial voice and latency (FantasyPros tends to surface
fantasy-relevant injury + beat-writer notes faster and with
tighter fantasy framing; ESPN skews broader league news).
Keeping them as separate provider rows means per-source
diagnostics (count, elapsed_ms, error) surface independently in
``providerRuns`` — ops can see FantasyPros degrade without ESPN
being affected.

Licensing note: FantasyPros' public RSS feed is intended for
aggregator consumption.  Their paid API has a separate licence
and is out of scope for this provider; if we ever want the
structured API, build a second adapter rather than flipping
this one over.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from ..base import NewsItem, NewsProvider
from . import _rss

DEFAULT_FEED_URL = "https://www.fantasypros.com/nfl/rss/player-news.php"


class FantasyProsRssProvider(NewsProvider):
    """Provider backed by FantasyPros' public player-news RSS feed."""

    name = "fantasypros"
    label = "FantasyPros"
    timeout_s = 5.0

    def __init__(
        self,
        *,
        feed_url: str = DEFAULT_FEED_URL,
        fetcher=None,
    ) -> None:
        super().__init__(feed_url=feed_url)
        self._feed_url = feed_url
        self._fetcher = fetcher or self._default_fetcher

    def _default_fetcher(self, url: str) -> bytes:
        return _rss.default_http_fetcher(
            url,
            timeout=self.timeout_s,
            user_agent="brisket-news-fantasypros/1.0",
        )

    def fetch(
        self,
        *,
        player_names: Optional[Iterable[str]] = None,
        limit: int = 50,
    ) -> List[NewsItem]:
        return _rss.fetch_rss_items(
            feed_url=self._feed_url,
            provider_name=self.name,
            provider_label=self.label,
            fetcher=self._fetcher,
            known_names=player_names,
            limit=limit,
        )


__all__ = ["DEFAULT_FEED_URL", "FantasyProsRssProvider"]
