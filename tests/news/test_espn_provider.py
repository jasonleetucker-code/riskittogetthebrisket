"""ESPN RSS provider tests.

Tests inject a fake RSS-body fetcher so no network access happens.
"""
from __future__ import annotations

from src.news.providers.espn import EspnRssProvider


_SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ESPN.com - NFL</title>
    <item>
      <title>Bijan Robinson ruled out with hamstring injury</title>
      <link>https://espn.com/nfl/story/a</link>
      <guid>espn-a</guid>
      <pubDate>Thu, 23 Apr 2026 10:42:00 GMT</pubDate>
      <description><![CDATA[Falcons RB was a late scratch.]]></description>
    </item>
    <item>
      <title>CeeDee Lamb signs extension with Cowboys</title>
      <link>https://espn.com/nfl/story/b</link>
      <guid>espn-b</guid>
      <pubDate>Thu, 23 Apr 2026 09:00:00 GMT</pubDate>
      <description>Dallas locks up their WR1 through 2030.</description>
    </item>
    <item>
      <title>Roundup: around the league</title>
      <link>https://espn.com/nfl/story/c</link>
      <guid>espn-c</guid>
      <pubDate>Thu, 23 Apr 2026 08:00:00 GMT</pubDate>
      <description>Minor notes and rumors.</description>
    </item>
  </channel>
</rss>
"""


def _provider(rss_bytes=_SAMPLE_RSS):
    return EspnRssProvider(fetcher=lambda _url: rss_bytes)


def test_rss_items_parse_and_classify():
    items = _provider().fetch(player_names=["Bijan Robinson", "CeeDee Lamb"])
    assert len(items) == 3
    by_head = {i.headline: i for i in items}

    injury = by_head["Bijan Robinson ruled out with hamstring injury"]
    assert injury.severity == "alert"
    assert injury.kind == "injury"
    assert injury.players[0].name == "Bijan Robinson"
    assert injury.players[0].impact == "negative"

    extension = by_head["CeeDee Lamb signs extension with Cowboys"]
    assert extension.severity == "watch"
    assert extension.kind in {"transaction", "performance"}
    assert extension.players[0].name == "CeeDee Lamb"
    assert extension.players[0].impact == "positive"

    generic = by_head["Roundup: around the league"]
    assert generic.severity == "info"
    assert generic.players == []


def test_player_match_is_case_insensitive():
    items = _provider().fetch(player_names=["bijan robinson"])
    matches = [i for i in items if i.players]
    assert any(p.name.lower() == "bijan robinson" for i in matches for p in i.players)


def test_no_player_context_still_emits_items():
    items = _provider().fetch(player_names=None)
    # Items still render; they just have empty players[].
    assert len(items) == 3
    assert all(i.players == [] for i in items)


def test_malformed_rss_returns_empty():
    provider = EspnRssProvider(fetcher=lambda _url: b"<not-rss>")
    assert provider.fetch() == []


def test_fetch_error_returns_empty():
    def boom(_url):
        raise OSError("simulated network down")

    provider = EspnRssProvider(fetcher=boom)
    assert provider.fetch() == []


def test_stable_ids_and_iso_timestamps():
    items = _provider().fetch()
    ids = [i.id for i in items]
    assert len(set(ids)) == 3
    for i in items:
        # ISO 8601 UTC — parseable by datetime.fromisoformat.
        from datetime import datetime

        parsed = datetime.fromisoformat(i.ts)
        assert parsed.tzinfo is not None
