"""Play For Keeps (PFK) dynasty articles provider.

PFK (https://playforkeepsdynasty.com) publishes dynasty articles at
``/articles``, but the site is a client-side React SPA — the article
list is rendered in the browser from a Supabase table, so neither
``/articles`` nor the usual RSS candidates carry the list:

* ``/feed``, ``/rss.xml``, ``/feed.xml`` — all return the SPA shell
  HTML (catch-all route), not a feed.  Probed 2026-07-25.
* Per-article pages serve the generic site-wide Open Graph meta, not
  article-specific tags.
* ``/sitemap.xml`` — a real, crawler-sanctioned XML document listing
  every ``/article/<slug>`` URL with a ``<lastmod>`` date.

So this provider consumes the sitemap: a single polite request per
cache refresh, filtered down to ``/article/`` entries.  Headlines are
derived from the slug (hyphens → spaces, title-cased) — lossy but
honest, and good enough for classification + player tagging via the
shared ``_rss`` helpers.

Failure semantics follow ``_rss.py``: upstream errors propagate so
the service layer's per-provider isolation marks the run
``ok=False`` and the aggregate stream continues on the survivors —
the provider degrades to zero items without poisoning ``/api/news``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable, List, Optional

from ..base import NewsItem, NewsProvider, stable_id, to_iso_utc
from ._rss import classify, default_http_fetcher, match_players

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_ARTICLE_PATH_RE = re.compile(r"/article/([^/?#]+)")


def _humanize_slug(slug: str) -> str:
    """Turn an article slug into a readable headline.

    ``bi-weekly-brew-new-orleans-saints-edition`` →
    ``Bi Weekly Brew New Orleans Saints Edition``.  Deliberately
    simple — the slug is the only server-rendered text PFK exposes.
    """
    words = [w for w in slug.replace("_", "-").split("-") if w]
    return " ".join(w.capitalize() if not w.isupper() else w for w in words)


def _parse_lastmod(raw: Optional[str]) -> Optional[datetime]:
    """Parse a sitemap ``<lastmod>`` (date or full ISO 8601) to UTC."""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PfkArticlesProvider(NewsProvider):
    """Play For Keeps dynasty articles via the public sitemap."""

    name = "pfk"
    label = "Play For Keeps"
    sitemap_url = "https://playforkeepsdynasty.com/sitemap.xml"
    user_agent = "brisket-news-pfk/1.0"

    def __init__(
        self,
        *,
        sitemap_url: Optional[str] = None,
        fetcher: Optional[Callable[[str], bytes]] = None,
        **config,
    ) -> None:
        super().__init__(**config)
        self._sitemap_url = sitemap_url or self.sitemap_url
        # Tests inject a fetcher returning raw XML bytes so the test
        # stays offline — same pattern as ``RssNewsProvider``.
        self._fetcher = fetcher or self._default_fetcher

    def _default_fetcher(self, url: str) -> bytes:
        return default_http_fetcher(
            url,
            timeout=self.timeout_s,
            user_agent=self.user_agent,
        )

    def fetch(self, *, player_names=None, limit: int = 50) -> List[NewsItem]:
        raw = self._fetcher(self._sitemap_url)
        root = ET.fromstring(raw)

        known = [str(n) for n in (player_names or []) if n]
        candidates: List[tuple[Optional[datetime], str, str]] = []
        # Namespace-agnostic iteration: real sitemaps carry the
        # sitemap.org namespace, but be defensive about bare tags.
        for url_el in list(root.iter(f"{_SITEMAP_NS}url")) + list(root.iter("url")):
            loc = (url_el.findtext(f"{_SITEMAP_NS}loc") or url_el.findtext("loc") or "").strip()
            m = _ARTICLE_PATH_RE.search(loc)
            if not m:
                continue
            lastmod = _parse_lastmod(
                url_el.findtext(f"{_SITEMAP_NS}lastmod") or url_el.findtext("lastmod")
            )
            candidates.append((lastmod, m.group(1), loc))

        # Newest first; undated entries sink to the bottom rather than
        # masquerading as fresh news on every refresh.
        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        candidates.sort(key=lambda c: c[0] or epoch, reverse=True)

        out: List[NewsItem] = []
        for lastmod, slug, loc in candidates[: max(1, int(limit))]:
            headline = _humanize_slug(slug)
            if not headline:
                continue
            severity, _kind, impact = classify(headline)
            mentions = match_players(headline, known_names=known, impact=impact)
            out.append(
                NewsItem(
                    id=stable_id(self.name, loc),
                    ts=to_iso_utc(lastmod) if lastmod else to_iso_utc(epoch),
                    provider=self.name,
                    provider_label=self.label,
                    severity=severity,
                    kind="article",
                    headline=headline,
                    body="",
                    players=mentions,
                    url=loc,
                    tags=["article"],
                )
            )
        return out


__all__ = ["PfkArticlesProvider"]
