"""ESPN NFL news RSS provider.

Thin subclass over ``RssNewsProvider`` — ESPN publishes a public
NFL news RSS feed with no auth.  Fetch, parse, classification,
and player tagging all live in the base class.
"""
from __future__ import annotations

from ._rss import RssNewsProvider

DEFAULT_FEED_URL = "https://www.espn.com/espn/rss/nfl/news"


class EspnRssProvider(RssNewsProvider):
    name = "espn"
    label = "ESPN"
    feed_url = DEFAULT_FEED_URL
    user_agent = "brisket-news-espn/1.0"


__all__ = ["DEFAULT_FEED_URL", "EspnRssProvider"]
