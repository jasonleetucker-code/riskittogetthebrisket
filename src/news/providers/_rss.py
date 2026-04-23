"""Shared RSS parsing + classification helpers.

Both the ESPN and FantasyPros providers hit the same basic shape —
a ``<channel>`` with ``<item>`` children carrying ``<title>``,
``<link>``, ``<guid>``, ``<pubDate>``, ``<description>`` — and
both feed into the same keyword-based severity classifier.  This
module holds the common bits so only the URL + provider identity
differ between the two adapters.

Nothing here issues network I/O; the default stdlib fetcher lives
on the subclasses so tests can inject a fake fetcher.
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, List, Optional

from ..base import NewsItem, NewsProvider, PlayerMention, stable_id, to_iso_utc

# Keywords matched with word boundaries so short fragments like
# "ir", "cut", "acl" don't trip on substrings of unrelated words
# ("their", "document", "practice").
_ALERT_KEYWORDS = (
    "injury",
    "injured",
    "hurt",
    "out for season",
    "out for the season",
    "season-ending",
    "torn",
    "acl",
    "achilles",
    "concussion",
    "placed on ir",
    "on the ir",
    "to ir",
    "questionable",
    "doubtful",
    "ruled out",
    "suspended",
    "arrest",
)
_WATCH_KEYWORDS = (
    "trade",
    "traded",
    "signs",
    "signed",
    "contract",
    "extension",
    "restructure",
    "promoted",
    "starter",
    "named starter",
    "released",
    "waived",
    "claim",
    "claimed",
    "activated",
)

_ALERT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _ALERT_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_WATCH_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _WATCH_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_TRANSACTION_RE = re.compile(
    r"\b(?:trade|traded|signs?|signed|contract|released|waived)\b",
    re.IGNORECASE,
)

_STRIP_HTML = re.compile(r"<[^>]+>")


def clean_text(text: Optional[str]) -> str:
    """Strip HTML and normalize whitespace on an RSS text field."""
    if not text:
        return ""
    return _STRIP_HTML.sub("", text).strip()


def classify(text: str) -> tuple[str, str, str]:
    """Return ``(severity, kind, impact)`` for a headline + body.

    Heuristics intentionally skew conservative — when in doubt
    the item drops to ``info`` rather than over-alerting, since
    the ticker's alert lane is narrow and each false positive
    costs real estate from roster-relevant signal.
    """
    if _ALERT_RE.search(text):
        return "alert", "injury", "negative"
    if _WATCH_RE.search(text):
        kind = "transaction" if _TRANSACTION_RE.search(text) else "performance"
        return "watch", kind, "positive"
    return "info", "news", "neutral"


def parse_pub_date(raw: Optional[str]) -> datetime:
    """Parse an RSS ``pubDate`` into an aware UTC datetime."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def match_players(
    text: str,
    *,
    known_names: list[str],
    impact: str,
) -> List[PlayerMention]:
    """Case-insensitive substring match against the known-names list.

    The known-names set is already curated (only real player names
    from the live contract), so full-word matching would be
    overkill — the false-positive rate is bounded by the input
    vocabulary rather than headline wording.
    """
    if not known_names or not text:
        return []
    haystack = text.lower()
    seen: set[str] = set()
    out: List[PlayerMention] = []
    for name in known_names:
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        if key in haystack:
            out.append(PlayerMention(name=name, impact=impact))
            seen.add(key)
    return out


def default_http_fetcher(url: str, *, timeout: float, user_agent: str) -> bytes:
    """Stdlib RSS fetcher used when a subclass doesn't inject one."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_rss_items(
    *,
    feed_url: str,
    provider_name: str,
    provider_label: str,
    fetcher: Callable[[str], bytes],
    known_names: Iterable[str] | None,
    limit: int,
) -> List[NewsItem]:
    """Fetch + parse an RSS feed into normalized ``NewsItem``s.

    Upstream failures (network, parse) propagate — the service
    layer's exception handler catches them and marks the provider
    run ``ok=False``.  That's what makes ``all_providers_failed``
    detection work: a silent ``return []`` here would masquerade
    as a healthy-but-quiet feed and the frontend would never
    fall back to its DEMO fixture on a real outage.
    """
    raw = fetcher(feed_url)
    root = ET.fromstring(raw)

    channel = root.find("channel")
    items_el = channel.findall("item") if channel is not None else root.findall("item")

    known = [str(n) for n in (known_names or []) if n]
    out: List[NewsItem] = []
    for el in items_el[: max(1, int(limit))]:
        item = _item_from_element(
            el,
            provider_name=provider_name,
            provider_label=provider_label,
            known_names=known,
        )
        if item is not None:
            out.append(item)
    return out


def _item_from_element(
    el: ET.Element,
    *,
    provider_name: str,
    provider_label: str,
    known_names: list[str],
) -> Optional[NewsItem]:
    title = clean_text((el.findtext("title") or "").strip())
    if not title:
        return None
    link = (el.findtext("link") or "").strip() or None
    description = clean_text(el.findtext("description") or "")
    guid = (el.findtext("guid") or link or title).strip()
    published = parse_pub_date(el.findtext("pubDate"))

    severity, kind, impact = classify(f"{title}\n{description}")
    mentions = match_players(
        f"{title}\n{description}",
        known_names=known_names,
        impact=impact,
    )

    return NewsItem(
        id=stable_id(provider_name, guid),
        ts=to_iso_utc(published),
        provider=provider_name,
        provider_label=provider_label,
        severity=severity,
        kind=kind,
        headline=title,
        body=description,
        players=mentions,
        url=link,
        tags=[kind],
    )


class RssNewsProvider(NewsProvider):
    """Base class for any public RSS news feed.

    Subclasses override the class attributes ``name``, ``label``,
    and ``feed_url``.  ``user_agent`` is optional; it defaults to
    a generic brisket UA but per-provider UAs are nice for the
    upstream ops team to attribute traffic.

    The subclass contract is deliberately tiny — everything about
    fetch + parse + classify + player-match lives in this module.
    Adding a new RSS source is a ~5-line subclass:

        class FootballguysRssProvider(RssNewsProvider):
            name = "footballguys"
            label = "Footballguys"
            feed_url = "https://www.footballguys.com/.../rss"
            user_agent = "brisket-news-fbg/1.0"
    """

    feed_url: str = ""
    user_agent: str = "brisket-news/1.0"

    def __init__(self, *, feed_url=None, fetcher=None):
        super().__init__()
        self._feed_url = feed_url or self.feed_url
        # Tests inject a fetcher that returns the raw RSS bytes so
        # the test stays offline.
        self._fetcher = fetcher or self._default_fetcher

    def _default_fetcher(self, url: str) -> bytes:
        return default_http_fetcher(
            url,
            timeout=self.timeout_s,
            user_agent=self.user_agent,
        )

    def fetch(self, *, player_names=None, limit: int = 50) -> List[NewsItem]:
        return fetch_rss_items(
            feed_url=self._feed_url,
            provider_name=self.name,
            provider_label=self.label,
            fetcher=self._fetcher,
            known_names=player_names,
            limit=limit,
        )


__all__ = [
    "RssNewsProvider",
    "classify",
    "clean_text",
    "default_http_fetcher",
    "fetch_rss_items",
    "match_players",
    "parse_pub_date",
]
