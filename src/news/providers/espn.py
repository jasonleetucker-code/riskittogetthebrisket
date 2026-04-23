"""ESPN headline-feed provider.

ESPN publishes a public NFL news RSS feed at
``https://www.espn.com/espn/rss/nfl/news``.  No auth, no key.
Treats each ``<item>`` as a news item and tags players by scanning
the headline + description for known roster names (the service
passes the live player universe in as ``player_names``).

Severity heuristic — RSS headlines carry no structured severity,
so we infer:

* keywords like "injury", "hurt", "questionable", "doubtful",
  "out", "IR" → ``alert`` + ``impact = negative``
* keywords like "traded", "signs", "contract", "extension",
  "promoted" → ``watch`` + ``impact = positive``
* everything else → ``info`` + ``impact = neutral``

Heuristics are intentionally conservative — when in doubt we emit
``info`` rather than over-alerting.  The relevance/scoring pass on
the frontend is the real filter for what surfaces in the ticker.

The RSS fetch uses stdlib only (``urllib.request`` +
``xml.etree.ElementTree``) — no new dependencies.  A 5s network
timeout keeps the service responsive when ESPN is slow.
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, List, Optional

from ..base import NewsItem, NewsProvider, PlayerMention, stable_id, to_iso_utc

log = logging.getLogger(__name__)

DEFAULT_FEED_URL = "https://www.espn.com/espn/rss/nfl/news"

# Keyword → (severity, kind, impact) heuristics.  Order matters —
# the first match wins, so list the most specific signals first
# (injury beats transaction if a headline mentions both).
# Keywords matched with word boundaries so short fragments like
# "ir", "cut", "acl" don't trip on substrings of unrelated words
# ("their", "document", "practice").  The compiled regex caches
# lazily on first use.
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


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    # RSS descriptions often contain wrapped HTML.  Strip tags and
    # normalize whitespace — we only surface the snippet as plain
    # text in the ticker.
    return _STRIP_HTML.sub("", text).strip()


def _classify(text: str) -> tuple[str, str, str]:
    """Return (severity, kind, impact) for a headline."""
    if _ALERT_RE.search(text):
        return "alert", "injury", "negative"
    if _WATCH_RE.search(text):
        kind = "transaction" if _TRANSACTION_RE.search(text) else "performance"
        return "watch", kind, "positive"
    return "info", "news", "neutral"


def _parse_pub_date(raw: Optional[str]) -> datetime:
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


def _match_players(
    text: str,
    *,
    known_names: list[str],
    impact: str,
) -> List[PlayerMention]:
    """Return PlayerMentions for every known name that appears in ``text``.

    Match uses case-insensitive substring containment.  We avoid
    full-word regex because the player-name set is already
    curated (only real player names from the live contract) so
    false positives are rare and cheap.
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


class EspnRssProvider(NewsProvider):
    """Provider backed by ESPN's public NFL news RSS feed."""

    name = "espn"
    label = "ESPN"
    timeout_s = 5.0

    def __init__(
        self,
        *,
        feed_url: str = DEFAULT_FEED_URL,
        fetcher=None,
    ) -> None:
        super().__init__(feed_url=feed_url)
        self._feed_url = feed_url
        # Tests inject a ``fetcher`` that returns the RSS body as
        # bytes/str so they don't need to stand up an HTTP server.
        self._fetcher = fetcher or self._default_fetcher

    def _default_fetcher(self, url: str) -> bytes:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "brisket-news-espn/1.0"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return resp.read()

    def fetch(
        self,
        *,
        player_names: Optional[Iterable[str]] = None,
        limit: int = 50,
    ) -> List[NewsItem]:
        try:
            raw = self._fetcher(self._feed_url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("espn rss fetch failed: %s", exc)
            return []
        except Exception as exc:  # pragma: no cover — last-resort
            log.warning("espn rss fetch errored: %s", exc)
            return []

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            log.warning("espn rss parse failed: %s", exc)
            return []

        channel = root.find("channel")
        if channel is None:
            # Some RSS variants put items at root.  Fall back.
            items_el = root.findall("item")
        else:
            items_el = channel.findall("item")

        known = [str(n) for n in (player_names or []) if n]
        out: List[NewsItem] = []
        for el in items_el[: max(1, int(limit))]:
            item = self._item_from_element(el, known_names=known)
            if item is not None:
                out.append(item)
        return out

    def _item_from_element(
        self,
        el: ET.Element,
        *,
        known_names: list[str],
    ) -> Optional[NewsItem]:
        title = _clean((el.findtext("title") or "").strip())
        if not title:
            return None
        link = (el.findtext("link") or "").strip() or None
        description = _clean(el.findtext("description") or "")
        guid = (el.findtext("guid") or link or title).strip()
        pub_raw = el.findtext("pubDate")
        published = _parse_pub_date(pub_raw)

        severity, kind, impact = _classify(f"{title}\n{description}")
        mentions = _match_players(
            f"{title}\n{description}",
            known_names=known_names,
            impact=impact,
        )

        return NewsItem(
            id=stable_id(self.name, guid),
            ts=to_iso_utc(published),
            provider=self.name,
            provider_label=self.label,
            severity=severity,
            kind=kind,
            headline=title,
            body=description,
            players=mentions,
            url=link,
            tags=[kind],
        )


__all__ = ["DEFAULT_FEED_URL", "EspnRssProvider"]
