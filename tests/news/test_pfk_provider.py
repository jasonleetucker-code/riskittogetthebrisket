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

from datetime import datetime, timedelta, timezone

import pytest

from src.news.providers import available_provider_names, build_provider
from src.news.providers.pfk import PfkArticlesProvider, _humanize_slug
from src.news.service import _DEFAULT_ENABLED, NewsService

# Fixture dates are generated relative to real now: service-level
# tests route through the aggregation layer's 7-day freshness cutoff,
# so static dates would silently age the fixture out of every
# assertion within a week of writing it.
_TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_FIVE_DAYS_AGO = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")

SITEMAP_FIXTURE = f"""<?xml version="1.0" encoding="UTF-8"?>
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
    <lastmod>{_TODAY}</lastmod>
    <changefreq>monthly</changefreq>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/article/bi-weekly-brew-new-orleans-saints-edition</loc>
    <lastmod>{_FIVE_DAYS_AGO}</lastmod>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/article/undated-legacy-piece</loc>
  </url>
  <url>
    <loc>https://playforkeepsdynasty.com/trade-finder</loc>
    <lastmod>{_TODAY}</lastmod>
  </url>
</urlset>
""".encode("utf-8")


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
        assert items[0].ts.startswith(_TODAY)
        assert items[1].ts.startswith(_FIVE_DAYS_AGO)
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


def _single_slug_sitemap(slug: str) -> bytes:
    # lastmod is stamped as TODAY so the service-level tests below
    # survive the aggregation layer's 7-day freshness cutoff no
    # matter when they run.
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d").encode("utf-8")
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        b"  <url>\n"
        b"    <loc>https://playforkeepsdynasty.com/article/" + slug.encode("utf-8") + b"</loc>\n"
        b"    <lastmod>" + today + b"</lastmod>\n"
        b"  </url>\n"
        b"</urlset>\n"
    )


class TestCollidingSlugAmbiguity:
    """A punctuation-stripped slug matching MULTIPLE distinct known
    display names (the CJ Allen twins) can't be attributed to either
    player — the mention must be flagged ambiguous so the service's
    enrichment never stamps an arbitrary survivor's identity."""

    KNOWN = ["C.J. Allen", "CJ Allen", "Bijan Robinson"]

    def _fetch(self, slug):
        sitemap = _single_slug_sitemap(slug)
        provider = PfkArticlesProvider(fetcher=lambda _url: sitemap)
        return provider.fetch(player_names=self.KNOWN)

    def test_colliding_slug_emits_single_ambiguous_mention(self):
        items = self._fetch("signal-or-noise-cj-allen")
        assert len(items) == 1
        mentions = items[0].players
        assert len(mentions) == 1
        m = mentions[0]
        assert m.ambiguous is True
        # Deterministic: the first known display name in contract order.
        assert m.name == "C.J. Allen"
        assert (m.position, m.team) == (None, None)

    def test_single_match_slug_stays_unflagged(self):
        items = self._fetch("bijan-robinson-buy-window")
        assert len(items) == 1
        m = items[0].players[0]
        assert m.ambiguous is False
        assert m.name == "Bijan Robinson"

    def test_ambiguous_mention_stays_unstamped_through_service(self):
        from src.news.service import NewsService

        sitemap = _single_slug_sitemap("signal-or-noise-cj-allen")
        provider = PfkArticlesProvider(fetcher=lambda _url: sitemap)
        svc = NewsService([provider], cache_ttl_s=0)
        out = svc.aggregate(
            player_names=self.KNOWN,
            player_meta={
                "C.J. Allen": {"position": "WR", "team": "ATL"},
                "CJ Allen": {"position": "LB", "team": "TEN"},
            },
        )
        m = out.items[0].players[0]
        assert m.ambiguous is True
        assert (m.position, m.team) == (None, None)
        serialized = out.to_dict()["items"][0]["players"][0]
        assert serialized["ambiguous"] is True
        assert serialized["position"] is None

    def test_single_match_slug_still_enriches_through_service(self):
        from src.news.service import NewsService

        sitemap = _single_slug_sitemap("bijan-robinson-buy-window")
        provider = PfkArticlesProvider(fetcher=lambda _url: sitemap)
        svc = NewsService([provider], cache_ttl_s=0)
        out = svc.aggregate(
            player_names=self.KNOWN,
            player_meta={"Bijan Robinson": {"position": "RB", "team": "ATL"}},
        )
        m = out.items[0].players[0]
        assert m.ambiguous is False
        assert (m.position, m.team) == ("RB", "ATL")

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
        # The healthy provider's DATED items survive; PFK's failing
        # instance contributes zero.  The static fixture's third
        # (undated) entry is stamped epoch by the provider and falls
        # to the service's 7-day freshness cutoff — deliberately:
        # an article that can't prove its age doesn't ship.
        assert {i.headline for i in result.items} == {
            "Signal Or Noise Carnell Tate",
            "Bi Weekly Brew New Orleans Saints Edition",
        }
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
