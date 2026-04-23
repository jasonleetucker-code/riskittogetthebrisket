"""CBS Sports Fantasy news provider.

CBS Sports publishes a public NFL-fantasy headlines RSS feed.
It's unauthenticated and follows standard RSS 2.0 shape, so
parsing + classification + player tagging reuse the shared
``_rss`` helpers.

The CBS feed tends to carry strategy and analysis pieces more
than injury microbursts, so most items classify as ``info``
unless the headline explicitly names an injury or transaction.
That's fine — the service's relevance pass handles surfacing
on the frontend.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from ..base import NewsItem, NewsProvider
from . import _rss

DEFAULT_FEED_URL = "https://www.cbssports.com/rss/headlines/nfl/"


class CbsFantasyRssProvider(NewsProvider):
    """Provider backed by CBS Sports' public NFL headlines RSS feed."""

    name = "cbs"
    label = "CBS Sports"
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
            user_agent="brisket-news-cbs/1.0",
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


__all__ = ["CbsFantasyRssProvider", "DEFAULT_FEED_URL"]
