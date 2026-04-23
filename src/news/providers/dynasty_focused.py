"""Dynasty-focused and high-authority fantasy football RSS providers.

Each entry here is a subclass of ``RssNewsProvider`` and just
pins a name, label, and feed URL.  The base class owns fetch,
parse, classification, and player tagging — new providers are
~6 lines each.

Sources picked from the public-RSS feed list with these criteria:

* **Dynasty-relevant** — this is a dynasty valuation site, so
  dynasty-specific sources (DLF, Dynasty Nerds) are on-brand.
* **High authority** — PFF and FFToday have long-running feeds
  with broad fantasy coverage.
* **Analytics-heavy** — Player Profiler and Razzball provide a
  different editorial voice than wire-service RSS, useful for
  the relevance signal in the ticker.

Feeds that were NOT added (kept out of the default registry):

* **Footballguys** — paywalled content, RSS URL not publicly
  documented.
* **RotoWire** — separate provider (licensed API planned);
  public RSS coverage is thinner than the paid feed.
* **Walter Football / Draft sites** — scout-focused, not in-
  season news.
* **Small community blogs** — low volume, better left for
  per-request additions rather than default-enabled.

Any of the skipped sources can be added as a 6-line subclass
once the feed URL is confirmed — that's the whole point of the
base class.
"""
from __future__ import annotations

from ._rss import RssNewsProvider


class DynastyLeagueFootballProvider(RssNewsProvider):
    """Dynasty League Football (DLF) — dynasty-specific rankings & analysis."""

    name = "dlf"
    label = "Dynasty League Football"
    feed_url = "https://dynastyleaguefootball.com/feed"
    user_agent = "brisket-news-dlf/1.0"


class DynastyNerdsProvider(RssNewsProvider):
    """Dynasty Nerds — dynasty rankings, rookie breakdowns, trade advice."""

    name = "dynastynerds"
    label = "Dynasty Nerds"
    feed_url = "https://dynastynerds.com/feed"
    user_agent = "brisket-news-nerds/1.0"


class PffProvider(RssNewsProvider):
    """Pro Football Focus — broad NFL analysis + fantasy grades."""

    name = "pff"
    label = "PFF"
    feed_url = "https://www.pff.com/feed"
    user_agent = "brisket-news-pff/1.0"


class FfTodayProvider(RssNewsProvider):
    """FFToday — fantasy football news + projections."""

    name = "fftoday"
    label = "FFToday"
    feed_url = "https://www.fftoday.com/rss/news.xml"
    user_agent = "brisket-news-fftoday/1.0"


class PlayerProfilerProvider(RssNewsProvider):
    """Player Profiler — advanced-metrics player analysis."""

    name = "playerprofiler"
    label = "Player Profiler"
    feed_url = "https://www.playerprofiler.com/feed"
    user_agent = "brisket-news-pp/1.0"


class RazzballProvider(RssNewsProvider):
    """Razzball — strategy, waiver-wire picks, weekly advice."""

    name = "razzball"
    label = "Razzball"
    feed_url = "https://football.razzball.com/feed"
    user_agent = "brisket-news-razzball/1.0"


__all__ = [
    "DynastyLeagueFootballProvider",
    "DynastyNerdsProvider",
    "FfTodayProvider",
    "PffProvider",
    "PlayerProfilerProvider",
    "RazzballProvider",
]
