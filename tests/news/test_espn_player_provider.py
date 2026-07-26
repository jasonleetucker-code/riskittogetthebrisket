"""Tests for the per-player ESPN news provider.

All HTTP is mocked — the fetcher is injected and returns fixture
JSON in the shape of ESPN's
``/apis/fantasy/v2/games/ffl/news/players?playerId=`` endpoint
(probed 2026-07-26; see the provider docstring).

Pinned behavior:

* feed parsing → NewsItem with PRE-STAMPED mention identity
* per-player TTL cache (no refetch within the TTL)
* the per-fetch request budget (politeness cap)
* stale-serving + per-player failure isolation
* total-failure raise for the service's outage detection
* registry presence + default enablement
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.news.providers import available_provider_names, build_provider
from src.news.providers.espn_player import EspnPlayerNewsProvider
from src.news.service import _DEFAULT_ENABLED


def _feed_payload(*entries):
    return json.dumps({"feed": list(entries)}).encode("utf-8")


def _entry(id_, headline, *, story="", published=None, web_url=None):
    published = published or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    links = {"web": {"href": web_url}} if web_url else {"mobile": {"href": "http://m.espn/x"}}
    return {
        "id": id_,
        "headline": headline,
        "story": story,
        "published": published,
        "links": links,
        "type": "Rotowire",
    }


TARGETS = [
    {"name": "Bijan Robinson", "espnId": "4430807", "position": "RB", "team": "ATL"},
    {"name": "Micah Parsons", "espnId": "4361423", "position": "LB", "team": "DAL"},
]


class _RecordingFetcher:
    """Returns per-espn-id fixture payloads and records every URL."""

    def __init__(self, payloads_by_id, errors_by_id=None):
        self.payloads = dict(payloads_by_id)
        self.errors = dict(errors_by_id or {})
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        for espn_id, err in self.errors.items():
            if f"playerId={espn_id}" in url:
                raise err
        for espn_id, payload in self.payloads.items():
            if f"playerId={espn_id}" in url:
                return payload
        raise AssertionError(f"unexpected url: {url}")


def _provider(fetcher, *, targets=None, clock=None, **kwargs):
    return EspnPlayerNewsProvider(
        targets_supplier=lambda: list(targets if targets is not None else TARGETS),
        fetcher=fetcher,
        clock=clock or (lambda: 0.0),
        **kwargs,
    )


class TestParse:
    def test_items_carry_prestamped_identity(self):
        fetcher = _RecordingFetcher(
            {
                "4430807": _feed_payload(
                    _entry(
                        "1",
                        "Robinson practices fully",
                        story="Good sign.",
                        web_url="https://espn.com/a",
                    )
                ),
                "4361423": _feed_payload(_entry("2", "Parsons contract talks")),
            }
        )
        items = _provider(fetcher).fetch()
        assert len(items) == 2
        by_headline = {it.headline: it for it in items}
        bijan = by_headline["Robinson practices fully"]
        m = bijan.players[0]
        assert (m.name, m.position, m.team) == ("Bijan Robinson", "RB", "ATL")
        assert m.ambiguous is False
        assert bijan.url == "https://espn.com/a"
        assert bijan.body == "Good sign."
        assert bijan.provider == "espn_player"
        assert bijan.ts.endswith("+00:00")

    def test_stable_ids_and_kind_tags(self):
        fetcher = _RecordingFetcher({"4430807": _feed_payload(_entry("9", "Note"))})
        target = [TARGETS[0]]
        first = _provider(fetcher, targets=target).fetch()
        second = _provider(
            _RecordingFetcher({"4430807": _feed_payload(_entry("9", "Note"))}),
            targets=target,
        ).fetch()
        assert first[0].id == second[0].id
        assert first[0].id.startswith("espn_player-")
        assert "player" in first[0].tags

    def test_no_targets_no_requests(self):
        fetcher = _RecordingFetcher({})
        assert _provider(fetcher, targets=[]).fetch() == []
        assert fetcher.calls == []


class TestCacheAndPoliteness:
    def test_player_ttl_prevents_refetch(self):
        clock = {"t": 0.0}
        fetcher = _RecordingFetcher(
            {
                "4430807": _feed_payload(_entry("1", "A")),
                "4361423": _feed_payload(_entry("2", "B")),
            }
        )
        provider = _provider(fetcher, clock=lambda: clock["t"], player_ttl_s=1800)
        provider.fetch()
        assert len(fetcher.calls) == 2
        # Within the TTL: served entirely from the player cache.
        clock["t"] += 600
        items = provider.fetch()
        assert len(fetcher.calls) == 2
        assert len(items) == 2
        # Past the TTL: refreshes again.
        clock["t"] += 1800
        provider.fetch()
        assert len(fetcher.calls) == 4

    def test_request_budget_caps_fanout_per_fetch(self):
        many_targets = [
            {"name": f"Player {i}", "espnId": str(1000 + i), "position": "WR", "team": "ATL"}
            for i in range(20)
        ]
        payloads = {str(1000 + i): _feed_payload(_entry(str(i), f"Note {i}")) for i in range(20)}
        fetcher = _RecordingFetcher(payloads)
        provider = _provider(fetcher, targets=many_targets, max_requests_per_fetch=5)
        provider.fetch()
        assert len(fetcher.calls) == 5
        # The next cycle picks up the never-fetched players first.
        provider.fetch()
        assert len(fetcher.calls) == 10
        assert len(set(fetcher.calls)) == 10  # no repeats while others wait

    def test_failure_keeps_stale_entry_and_other_players(self):
        clock = {"t": 0.0}
        good = _feed_payload(_entry("1", "Fresh note"))
        fetcher = _RecordingFetcher({"4430807": good, "4361423": good})
        provider = _provider(fetcher, clock=lambda: clock["t"], player_ttl_s=100)
        first = provider.fetch()
        assert len(first) == 2
        # Bijan's refresh now fails; his cached items keep serving.
        clock["t"] += 200
        failing = _RecordingFetcher({"4361423": good}, errors_by_id={"4430807": OSError("down")})
        provider._fetcher = failing
        items = provider.fetch()
        assert len(items) == 2  # stale Bijan entry + fresh Parsons

    def test_total_failure_with_empty_cache_raises(self):
        fetcher = _RecordingFetcher(
            {}, errors_by_id={"4430807": OSError("x"), "4361423": OSError("y")}
        )
        provider = _provider(fetcher)
        with pytest.raises(OSError):
            provider.fetch()

    def test_supplier_failure_degrades_to_empty(self):
        provider = EspnPlayerNewsProvider(
            targets_supplier=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            fetcher=_RecordingFetcher({}),
        )
        assert provider.fetch() == []


class TestRegistration:
    def test_registered_and_buildable(self):
        assert "espn_player" in available_provider_names()
        provider = build_provider("espn_player")
        assert provider.name == "espn_player"
        # Bare construction (no supplier) is inert, not broken.
        assert provider.fetch() == []

    def test_enabled_by_default(self):
        assert "espn_player" in _DEFAULT_ENABLED


def test_old_entries_survive_provider_but_die_at_service():
    """The provider doesn't own the freshness policy — the service's
    7-day cutoff does.  An old ESPN note flows out of the provider
    and is dropped at aggregation."""
    from src.news.service import NewsService

    old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fetcher = _RecordingFetcher(
        {
            "4430807": _feed_payload(
                _entry("old", "Ancient note", published=old),
            )
        }
    )
    provider = _provider(fetcher, targets=[TARGETS[0]])
    assert len(provider.fetch()) == 1
    svc = NewsService([provider], cache_ttl_s=0)
    assert svc.aggregate().items == []
