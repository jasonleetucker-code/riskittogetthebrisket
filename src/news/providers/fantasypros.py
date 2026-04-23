"""FantasyPros player-news RSS provider.

FantasyPros' public player-news RSS is unauthenticated and
fantasy-flavored — items tend to surface fantasy-relevant
analysis and beat-writer notes.  Separate from the paid
FantasyPros API (different adapter if we ever license it).
"""
from __future__ import annotations

from ._rss import RssNewsProvider

DEFAULT_FEED_URL = "https://www.fantasypros.com/nfl/rss/player-news.php"


class FantasyProsRssProvider(RssNewsProvider):
    name = "fantasypros"
    label = "FantasyPros"
    feed_url = DEFAULT_FEED_URL
    user_agent = "brisket-news-fantasypros/1.0"


__all__ = ["DEFAULT_FEED_URL", "FantasyProsRssProvider"]
