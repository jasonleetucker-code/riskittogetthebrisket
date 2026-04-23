"""Identity tests for the dynasty-focused RSS providers.

The fetch + parse + classification behavior is fully exercised
by the ESPN, FantasyPros, and CBS test files — every RSS
provider inherits the same base, so re-testing the same code
paths for six more subclasses would be redundant.

What still needs pinning per-provider:

1. ``name`` and ``label`` are what the frontend reads.  Typos
   here would land a silently-mislabeled chip in the ticker.
2. ``feed_url`` points at a concrete URL — regressing it to
   empty or to the wrong path would make the provider silently
   fail every fetch.
3. The class is registered in the provider registry and
   buildable by name.

Everything below is a static contract check — no HTTP.
"""
from __future__ import annotations

import pytest

from src.news.providers import available_provider_names, build_provider
from src.news.providers.dynasty_focused import (
    DynastyLeagueFootballProvider,
    DynastyNerdsProvider,
    FfTodayProvider,
    PffProvider,
    PlayerProfilerProvider,
    RazzballProvider,
)


@pytest.mark.parametrize(
    "cls,name,label",
    [
        (DynastyLeagueFootballProvider, "dlf", "Dynasty League Football"),
        (DynastyNerdsProvider, "dynastynerds", "Dynasty Nerds"),
        (PffProvider, "pff", "PFF"),
        (FfTodayProvider, "fftoday", "FFToday"),
        (PlayerProfilerProvider, "playerprofiler", "Player Profiler"),
        (RazzballProvider, "razzball", "Razzball"),
    ],
)
def test_provider_identity(cls, name, label):
    """Name, label, and URL must be set on each subclass."""
    assert cls.name == name
    assert cls.label == label
    assert cls.feed_url, f"{name} has empty feed_url"
    assert cls.feed_url.startswith("http")


@pytest.mark.parametrize(
    "name",
    [
        "dlf",
        "dynastynerds",
        "pff",
        "fftoday",
        "playerprofiler",
        "razzball",
    ],
)
def test_provider_registered_and_buildable(name):
    assert name in available_provider_names()
    provider = build_provider(name)
    assert provider.name == name
    assert provider.label  # non-empty


def test_shared_parser_produces_identity_tagged_items():
    """All subclasses route through the shared RSS parser, so
    a single fake feed should tag provider identity correctly."""
    rss = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Headline X</title>
      <link>https://example.com/a</link>
      <guid>x-a</guid>
      <pubDate>Thu, 23 Apr 2026 10:00:00 GMT</pubDate>
      <description>Body</description>
    </item>
  </channel>
</rss>
"""
    for cls in (
        DynastyLeagueFootballProvider,
        DynastyNerdsProvider,
        PffProvider,
        FfTodayProvider,
        PlayerProfilerProvider,
        RazzballProvider,
    ):
        items = cls(fetcher=lambda _url: rss).fetch()
        assert len(items) == 1
        assert items[0].provider == cls.name
        assert items[0].provider_label == cls.label
