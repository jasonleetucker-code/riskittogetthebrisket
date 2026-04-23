"""FantasyPros RSS provider tests.

FantasyPros shares the ``_rss`` parse/classify helpers with ESPN,
so the surface tested here is mostly provider-identity + the
raise-on-failure contract.  The full classification matrix is
covered in ``test_espn_provider.py``.
"""
from __future__ import annotations

import pytest
import xml.etree.ElementTree as ET

from src.news.providers.fantasypros import FantasyProsRssProvider


_SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>FantasyPros Player News</title>
    <item>
      <title>Bijan Robinson ruled out with hamstring injury</title>
      <link>https://fantasypros.com/nfl/news/a</link>
      <guid>fp-a</guid>
      <pubDate>Thu, 23 Apr 2026 11:00:00 GMT</pubDate>
      <description><![CDATA[Report: ATL RB pulled early.]]></description>
    </item>
    <item>
      <title>Jahmyr Gibbs signs rookie extension</title>
      <link>https://fantasypros.com/nfl/news/b</link>
      <guid>fp-b</guid>
      <pubDate>Thu, 23 Apr 2026 10:00:00 GMT</pubDate>
      <description>Lions lock up their lead back.</description>
    </item>
  </channel>
</rss>
"""


def _provider(rss_bytes=_SAMPLE_RSS):
    return FantasyProsRssProvider(fetcher=lambda _url: rss_bytes)


def test_items_parse_and_tag_provider_identity():
    items = _provider().fetch(
        player_names=["Bijan Robinson", "Jahmyr Gibbs"]
    )
    assert len(items) == 2
    for it in items:
        assert it.provider == "fantasypros"
        assert it.provider_label == "FantasyPros"

    injury, transaction = items[0], items[1]
    assert injury.severity == "alert"
    assert injury.players[0].name == "Bijan Robinson"
    assert transaction.severity == "watch"
    assert transaction.players[0].name == "Jahmyr Gibbs"


def test_fetch_error_propagates():
    """Raise on upstream failure so the service marks the run
    ``ok=False`` and all-providers-failed can trigger 503."""

    def boom(_url):
        raise OSError("fp down")

    with pytest.raises(OSError):
        FantasyProsRssProvider(fetcher=boom).fetch()


def test_malformed_rss_propagates():
    provider = FantasyProsRssProvider(fetcher=lambda _url: b"<nope>")
    with pytest.raises(ET.ParseError):
        provider.fetch()
