"""Tests for the Play For Keeps (PFK) articles provider.

PFK exposes no RSS feed — the site is a client-rendered SPA and the
only server-side article list is ``/sitemap.xml`` (see the provider
docstring for the probe log).  These tests pin:

1. Sitemap parsing — ``/article/`` filtering, slug humanization,
   ``lastmod`` timestamps, newest-first ordering, limit.
2. Player tagging via the shared ``match_players`` helper.
3. Failure semantics — a raising fetcher must degrade to an empty
   contribution at the service layer without breaking the aggregate
   stream.
4. Registry presence + default enablement.

No HTTP happens anywhere below — the fetcher is always injected.
"""

from __future__ import annotations

import pytest

from src.news.providers import available_provider_names, build_provider
from src.news.providers.pfk import PfkArticlesProvider, _humanize_slug
from src.news.service import _DEFAULT_ENABLED, NewsService

SITEMAP_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://playforkeepsdynasty.com/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/articles</loc>
    <changefreq>weekly</changefreq>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/article/signal-or-noise-carnell-tate</loc>
    <lastmod>2026-07-25</lastmod>
    <changefreq>monthly</changefreq>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/article/bi-weekly-brew-new-orleans-saints-edition</loc>
    <lastmod>2026-07-20</lastmod>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/article/undated-legacy-piece</loc>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/trade-finder</loc>
    <lastmod>2026-07-25</lastmod>
  </url>
</urlset>
"""


def _provider(**kwargs) -> PfkArticlesProvider:
    return PfkArticlesProvider(fetcher=lambda _url: SITEMAP_FIXTURE, **kwargs)


class TestParse:
    def test_only_article_urls_become_items(self):
        items = _provider().fetch()
        assert len(items) == 3
        assert all("/article/" in it.url for it in items)

    def test_identity_and_shape(self):
        items = _provider().fetch()
        top = items[0]
        assert top.provider == "pfk"
        assert top.provider_label == "Play For Keeps"
        assert top.kind == "article"
        assert top.tags == ["article"]
        assert top.id.startswith("pfk-")

    def test_headline_humanized_from_slug(self):
        items = _provider().fetch()
        headlines = {it.headline for it in items}
        assert "Signal Or Noise Carnell Tate" in headlines
        assert "Bi Weekly Brew New Orleans Saints Edition" in headlines

    def test_lastmod_becomes_iso_utc_ts_newest_first(self):
        items = _provider().fetch()
        assert items[0].ts.startswith("2026-07-25")
        assert items[1].ts.startswith("2026-07-20")
        assert items[0].ts.endswith("+00:00")
        # Undated entries sink to the bottom instead of posing as fresh.
        assert items[-1].headline == "Undated Legacy Piece"

    def test_limit_respected(self):
        items = _provider().fetch(limit=1)
        assert len(items) == 1
        assert items[0].headline == "Signal Or Noise Carnell Tate"

    def test_player_mentions_matched_from_known_names(self):
        items = _provider().fetch(player_names=["Carnell Tate", "Bijan Robinson"])
        tagged = [it for it in items if it.players]
        assert len(tagged) == 1
        assert tagged[0].players[0].name == "Carnell Tate"

    @pytest.mark.parametrize(
        "slug,display_name",
        [
            # Hyphen + period in the display name, both flattened in
            # the slug — literal substring match would miss all of
            # these; normalized-key matching must not.
            ("signal-or-noise-amon-ra-st-brown", "Amon-Ra St. Brown"),
            # Apostrophe splits the slug ("ja marr") but the display
            # name normalizes with the apostrophe removed and no
            # space ("jamarr") — covered by compact comparison.
            ("why-ja-marr-chase-is-a-hold", "Ja'Marr Chase"),
            ("dandre-swift-buy-window", "D'Andre Swift"),
            # Generational suffix present in the display name only.
            ("kenneth-walker-breakout-case", "Kenneth Walker III"),
            # Dotted initials in the display name, bare in the slug.
            ("tj-hockenson-route-tree", "T.J. Hockenson"),
        ],
    )
    def test_punctuated_names_match_via_normalized_keys(self, slug, display_name):
        sitemap = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            b"  <url>\n"
            b"    <loc>https://playforkeepsdynasty.com/article/"
            + slug.encode("utf-8")
            + b"</loc>\n"
            b"    <lastmod>2026-07-25</lastmod>\n"
            b"  </url>\n"
            b"</urlset>\n"
        )
        provider = PfkArticlesProvider(fetcher=lambda _url: sitemap)
        items = provider.fetch(player_names=[display_name, "Bijan Robinson"])
        assert len(items) == 1
        assert [p.name for p in items[0].players] == [display_name]

    def test_no_false_positive_on_unrelated_names(self):
        items = _provider().fetch(player_names=["Tate Ratledge"])
        assert all(not it.players for it in items)

    def test_stable_ids_across_refetch(self):
        first = _provider().fetch()
        second = _provider().fetch()
        assert [it.id for it in first] == [it.id for it in second]

    def test_malformed_xml_raises_for_service_isolation(self):
        provider = PfkArticlesProvider(fetcher=lambda _url: b"not xml at all")
        with pytest.raises(Exception):
            provider.fetch()


class TestHumanizeSlug:
    @pytest.mark.parametrize(
        "slug,expected",
        [
            ("devon-achane-fade-mistake-2026", "Devon Achane Fade Mistake 2026"),
            ("tdlrjuly2026", "Tdlrjuly2026"),
            ("", ""),
            ("--", ""),
        ],
    )
    def test_cases(self, slug, expected):
        assert _humanize_slug(slug) == expected


class TestFailureIsolation:
    def test_network_failure_degrades_to_empty_without_breaking_aggregate(self):
        def boom(_url):
            raise OSError("connection refused")

        failing = PfkArticlesProvider(fetcher=boom)
        healthy = _provider()
        svc = NewsService([failing, healthy], cache_ttl_s=0)
        result = svc.aggregate()
        # The healthy provider's items survive; PFK contributes zero.
        assert len(result.items) == 3
        runs = {r.name: r for r in result.provider_runs}
        # Both instances share name "pfk"; the failing one ran first
        # so assert via the run list directly.
        assert result.provider_runs[0].ok is False
        assert "OSError" in (result.provider_runs[0].error or "")
        assert result.provider_runs[1].ok is True
        assert runs  # both runs recorded

    def test_all_failed_still_returns_valid_payload(self):
        def boom(_url):
            raise OSError("offline")

        svc = NewsService([PfkArticlesProvider(fetcher=boom)], cache_ttl_s=0)
        result = svc.aggregate()
        assert result.items == []
        payload = result.to_dict()
        assert payload["count"] == 0
        assert payload["providersUsed"] == []


class TestRegistration:
    def test_registered_and_buildable(self):
        assert "pfk" in available_provider_names()
        provider = build_provider("pfk")
        assert provider.name == "pfk"
        assert provider.label == "Play For Keeps"
        assert provider.sitemap_url.startswith("https://playforkeepsdynasty.com/")

    def test_enabled_by_default(self):
        assert "pfk" in _DEFAULT_ENABLED
