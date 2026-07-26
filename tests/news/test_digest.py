"""Tests for the per-player news digest builder.

Pins grouping (position-aware so name-collision twins never merge),
story dedupe, the two-story minimum, severity/source aggregation,
ambiguous-mention exclusion, and the mechanical output of the
LLM-synthesis seam function.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.news.base import NewsItem, PlayerMention
from src.news.digest import (
    MIN_STORIES_FOR_DIGEST,
    build_player_digests,
    synthesize_player_digest,
)


def _ts(hours_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _item(id_, headline, *, ts=None, severity="info", provider="espn", players=None):
    return NewsItem(
        id=id_,
        ts=ts or _ts(),
        provider=provider,
        provider_label=provider.title(),
        severity=severity,
        kind="news",
        headline=headline,
        body="",
        players=players or [],
    )


def _mention(name, position=None, team=None, ambiguous=False):
    return PlayerMention(name=name, position=position, team=team, ambiguous=ambiguous)


def test_min_two_stories_required():
    items = [
        _item("a", "Only story", players=[_mention("Bijan Robinson", "RB", "ATL")]),
    ]
    assert MIN_STORIES_FOR_DIGEST == 2
    assert build_player_digests(items) == []


def test_digest_groups_newest_first_with_sources():
    items = [
        _item(
            "old",
            "Robinson practice note",
            ts=_ts(hours_ago=30),
            provider="pfk",
            players=[_mention("Bijan Robinson", "RB", "ATL")],
        ),
        _item(
            "new",
            "Robinson contract update",
            ts=_ts(hours_ago=1),
            severity="watch",
            provider="espn",
            players=[_mention("Bijan Robinson", "RB", "ATL")],
        ),
    ]
    digests = build_player_digests(items)
    assert len(digests) == 1
    d = digests[0]
    assert d["player"] == "Bijan Robinson"
    assert d["storyCount"] == 2
    assert d["itemIds"] == ["new", "old"]  # newest first
    assert d["latestTs"] == items[1].ts
    assert d["severity"] == "watch"  # max severity wins
    assert d["sources"] == ["Espn", "Pfk"]  # order of appearance, deduped
    assert d["position"] == "RB" and d["team"] == "ATL"
    # Mechanical summary carries attribution per story line.
    assert "Robinson contract update (Espn," in d["summary"]
    assert "Robinson practice note (Pfk," in d["summary"]


def test_same_story_from_two_providers_dedupes():
    items = [
        _item(
            "e1",
            "Robinson signs extension",
            provider="espn",
            players=[_mention("Bijan Robinson", "RB", "ATL")],
        ),
        _item(
            "p1",
            "Robinson Signs Extension",  # same story, case drift
            provider="pfk",
            players=[_mention("Bijan Robinson", "RB", "ATL")],
        ),
        _item(
            "e2",
            "Robinson practice note",
            players=[_mention("Bijan Robinson", "RB", "ATL")],
        ),
    ]
    digests = build_player_digests(items)
    assert len(digests) == 1
    assert digests[0]["storyCount"] == 2  # duplicate story collapsed


def test_collision_twins_never_merge():
    items = [
        _item("wr1", "WR camp riser", players=[_mention("C.J. Allen", "WR", "ATL")]),
        _item("wr2", "WR route tree note", players=[_mention("C.J. Allen", "WR", "ATL")]),
        _item("lb1", "LB rep count", players=[_mention("CJ Allen", "LB", "TEN")]),
        _item("lb2", "LB coverage note", players=[_mention("CJ Allen", "LB", "TEN")]),
    ]
    digests = build_player_digests(items)
    assert len(digests) == 2
    by_pos = {d["position"]: d for d in digests}
    assert by_pos["WR"]["storyCount"] == 2
    assert by_pos["LB"]["storyCount"] == 2


def test_ambiguous_mentions_excluded():
    items = [
        _item("a1", "Ambiguous slug story", players=[_mention("CJ Allen", ambiguous=True)]),
        _item("a2", "Another ambiguous one", players=[_mention("CJ Allen", ambiguous=True)]),
    ]
    assert build_player_digests(items) == []


def test_synthesize_seam_caps_lines_with_more_trailer():
    stories = [_item(f"s{i}", f"Story number {i}") for i in range(8)]
    text = synthesize_player_digest("Bijan Robinson", stories)
    lines = text.split("\n")
    # 6 story lines + the "+2 more" trailer.
    assert len(lines) == 7
    assert lines[-1].startswith("- +2 more")
