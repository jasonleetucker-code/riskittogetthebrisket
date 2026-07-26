"""Per-player news digests.

When a player has multiple recent stories, every surface (popup,
/news tab) wants ONE combined entry instead of N near-duplicates.
``build_player_digests`` groups the aggregated items by player
identity (normalized name + position family, so name-collision twins
never merge), dedupes repeated stories, and emits a compact digest
dict per player with source attribution.

The digest TEXT comes from :func:`synthesize_player_digest` — the
single, documented seam for LLM synthesis.  Today it is a mechanical
combine (newest-first story lines with source + date attribution);
when an ``ANTHROPIC_API_KEY`` is provisioned, an LLM-written
paragraph can replace the mechanical text by swapping ONLY that
function's body.  Nothing else in the pipeline knows how the text is
produced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Sequence

from src.utils.name_clean import normalize_player_name, normalize_position_family

from .base import NewsItem

#: A digest only exists when a player has at least this many distinct
#: stories — a single article renders better as itself.
MIN_STORIES_FOR_DIGEST = 2

#: Cap the story lines included in the mechanical summary; anything
#: beyond is summarized as a "+N more" trailer.
_MAX_SUMMARY_LINES = 6

_SEVERITY_RANK = {"alert": 3, "watch": 2, "info": 1}


def _story_key(item: NewsItem) -> str:
    """Dedupe key for "the same story from multiple providers"."""
    return " ".join(str(item.headline or "").lower().split())


def _ts_epoch(item: NewsItem) -> float:
    try:
        return datetime.fromisoformat(str(item.ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _short_date(item: NewsItem) -> str:
    return str(item.ts or "")[:10]


def synthesize_player_digest(player_name: str, stories: Sequence[NewsItem]) -> str:
    """Combine a player's stories into one digest text.

    ── LLM SYNTHESIS SEAM ──────────────────────────────────────────
    This is the ONLY place digest text is produced.  The current
    implementation is a mechanical combine: one attributed line per
    story, newest first.  When ``ANTHROPIC_API_KEY`` is available,
    replace this body with a model call that writes a single
    coherent paragraph from the same ``stories`` input — callers,
    payload shape, and tests of the surrounding structure need no
    changes.  (Blocked today: the key has not been provisioned.)
    """
    lines: List[str] = []
    for item in stories[:_MAX_SUMMARY_LINES]:
        source = item.provider_label or item.provider or "news"
        lines.append(f"- {item.headline} ({source}, {_short_date(item)})")
    extra = len(stories) - _MAX_SUMMARY_LINES
    if extra > 0:
        lines.append(f"- +{extra} more stor{'y' if extra == 1 else 'ies'} this week")
    return "\n".join(lines)


def build_player_digests(items: Sequence[NewsItem]) -> List[dict[str, Any]]:
    """Group aggregated items into one digest entry per player.

    Grouping key is ``(normalized name, position family)`` so the
    documented name-collision twins (CJ Allen the LB vs C.J. Allen
    the WR) never share a digest; mentions flagged ``ambiguous`` are
    skipped entirely — a digest must never confidently attribute an
    ambiguous story.  Stories are deduped by normalized headline and
    ordered newest first; players with fewer than
    :data:`MIN_STORIES_FOR_DIGEST` distinct stories emit nothing.
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for item in sorted(items, key=_ts_epoch, reverse=True):
        for mention in item.players:
            if getattr(mention, "ambiguous", False):
                continue
            name = str(mention.name or "").strip()
            norm = normalize_player_name(name)
            if not norm:
                continue
            family = normalize_position_family(mention.position) if mention.position else ""
            key = (norm, family)
            group = groups.setdefault(
                key,
                {
                    "player": name,
                    "position": mention.position,
                    "team": mention.team,
                    "stories": [],
                    "storyKeys": set(),
                },
            )
            skey = _story_key(item)
            if not skey or skey in group["storyKeys"]:
                continue
            group["storyKeys"].add(skey)
            group["stories"].append(item)
            # Prefer the first non-null identity stamps seen.
            if not group["position"] and mention.position:
                group["position"] = mention.position
            if not group["team"] and mention.team:
                group["team"] = mention.team

    digests: List[dict[str, Any]] = []
    for group in groups.values():
        stories: List[NewsItem] = group["stories"]
        if len(stories) < MIN_STORIES_FOR_DIGEST:
            continue
        severity = max(
            (s.severity for s in stories),
            key=lambda sev: _SEVERITY_RANK.get(sev, 0),
        )
        sources: List[str] = []
        for s in stories:
            label = s.provider_label or s.provider or "news"
            if label not in sources:
                sources.append(label)
        digests.append(
            {
                "player": group["player"],
                "position": group["position"],
                "team": group["team"],
                "storyCount": len(stories),
                "latestTs": stories[0].ts,
                "severity": severity,
                "sources": sources,
                "headline": f"{group['player']}: {len(stories)} stories this week",
                "summary": synthesize_player_digest(group["player"], stories),
                "itemIds": [s.id for s in stories],
            }
        )
    digests.sort(key=lambda d: str(d["latestTs"]), reverse=True)
    return digests


__all__ = [
    "MIN_STORIES_FOR_DIGEST",
    "build_player_digests",
    "synthesize_player_digest",
]
