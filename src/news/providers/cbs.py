"""CBS Sports NFL headlines RSS provider."""
from __future__ import annotations

from ._rss import RssNewsProvider

DEFAULT_FEED_URL = "https://www.cbssports.com/rss/headlines/nfl/"


class CbsFantasyRssProvider(RssNewsProvider):
    name = "cbs"
    label = "CBS Sports"
    feed_url = DEFAULT_FEED_URL
    user_agent = "brisket-news-cbs/1.0"


__all__ = ["CbsFantasyRssProvider", "DEFAULT_FEED_URL"]
