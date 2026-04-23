"""CBS Sports RSS provider tests.

Shares the ``_rss`` helpers with ESPN / FantasyPros, so the
surface exercised here is provider identity + the raise-on-
failure contract.
"""
from __future__ import annotations

import pytest
import xml.etree.ElementTree as ET

from src.news.providers.cbs import CbsFantasyRssProvider


_SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CBS Sports - NFL</title>
    <item>
      <title>Weekly fantasy start/sit - Week 12 overreactions</title>
      <link>https://cbssports.com/nfl/news/a</link>
      <guid>cbs-a</guid>
      <pubDate>Thu, 23 Apr 2026 12:00:00 GMT</pubDate>
      <description>Strategy piece on last week's surprises.</description>
    </item>
    <item>
      <title>Breece Hall placed on IR with knee injury</title>
      <link>https://cbssports.com/nfl/news/b</link>
      <guid>cbs-b</guid>
      <pubDate>Thu, 23 Apr 2026 11:00:00 GMT</pubDate>
      <description>Jets lose their RB1.</description>
    </item>
  </channel>
</rss>
"""


def _provider(rss_bytes=_SAMPLE_RSS):
    return CbsFantasyRssProvider(fetcher=lambda _url: rss_bytes)


def test_provider_identity():
    items = _provider().fetch(player_names=["Breece Hall"])
    assert len(items) == 2
    for it in items:
        assert it.provider == "cbs"
        assert it.provider_label == "CBS Sports"


def test_injury_classified_as_alert():
    items = _provider().fetch(player_names=["Breece Hall"])
    injury = next(i for i in items if "Breece Hall" in i.headline)
    assert injury.severity == "alert"
    assert injury.kind == "injury"
    assert injury.players[0].name == "Breece Hall"
    assert injury.players[0].impact == "negative"


def test_strategy_piece_classified_as_info():
    items = _provider().fetch(player_names=[])
    strategy = next(i for i in items if "Week 12" in i.headline)
    assert strategy.severity == "info"


def test_fetch_error_propagates():
    def boom(_url):
        raise OSError("cbs down")

    with pytest.raises(OSError):
        CbsFantasyRssProvider(fetcher=boom).fetch()


def test_malformed_rss_propagates():
    provider = CbsFantasyRssProvider(fetcher=lambda _url: b"<bad>")
    with pytest.raises(ET.ParseError):
        provider.fetch()
