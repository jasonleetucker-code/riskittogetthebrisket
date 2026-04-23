"""Pin the normalized NewsItem serialization contract.

Both the legacy frontend vocabulary (``ts``, ``body``, ``players``)
and the enriched vocabulary (``publishedAt``, ``summary``,
``impactedPlayers``, ``tags``) must survive the
``NewsItem.to_dict`` round-trip on every item.  If either side
breaks, every downstream consumer breaks — hence a dedicated
contract test instead of folding it into a provider test.
"""
from __future__ import annotations

from src.news.base import NewsItem, PlayerMention, stable_id, to_iso_utc
from datetime import datetime, timezone


def _sample_item() -> NewsItem:
    return NewsItem(
        id="espn-abc123",
        ts="2026-04-23T10:00:00+00:00",
        provider="espn",
        provider_label="ESPN",
        severity="alert",
        kind="injury",
        headline="Star RB exits with hamstring",
        body="Player pulled from practice after feeling tightness.",
        players=[PlayerMention(name="Bijan Robinson", impact="negative")],
        url="https://example.com/news/1",
        tags=["injury"],
        confidence=0.72,
    )


def test_to_dict_preserves_legacy_fields():
    item = _sample_item().to_dict()
    # Every field the existing frontend reads today must be present.
    for key in (
        "id",
        "ts",
        "provider",
        "providerLabel",
        "severity",
        "kind",
        "headline",
        "body",
        "players",
        "url",
    ):
        assert key in item, f"missing legacy field: {key}"
    assert item["providerLabel"] == "ESPN"
    assert item["players"] == [{"name": "Bijan Robinson", "impact": "negative"}]


def test_to_dict_includes_enriched_aliases():
    item = _sample_item().to_dict()
    # Enriched fields the brief calls out: publishedAt, summary,
    # impactedPlayers, tags, confidence, relevance.
    assert item["publishedAt"] == item["ts"]
    assert item["summary"] == item["body"]
    assert item["impactedPlayers"] == ["Bijan Robinson"]
    assert item["tags"] == ["injury"]
    assert item["confidence"] == 0.72
    assert "relevance" in item  # may be None


def test_stable_id_is_deterministic():
    a = stable_id("espn", "guid-42")
    b = stable_id("espn", "guid-42")
    c = stable_id("espn", "guid-43")
    assert a == b
    assert a != c
    assert a.startswith("espn-")


def test_to_iso_utc_normalizes_naive_datetime():
    naive = datetime(2026, 4, 23, 10, 0, 0)
    out = to_iso_utc(naive)
    assert out.endswith("+00:00")
    # Round-trip check.
    assert datetime.fromisoformat(out).tzinfo is not None


def test_to_iso_utc_preserves_aware_datetime():
    aware = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    out = to_iso_utc(aware)
    assert out == "2026-04-23T10:00:00+00:00"
