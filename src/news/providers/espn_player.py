"""Per-player ESPN news provider.

Fetches player-scoped news from ESPN's fantasy news API:

    https://site.web.api.espn.com/apis/fantasy/v2/games/ffl/news/players?playerId={espn_id}

Probed 2026-07-26: the endpoint is genuinely player-scoped (Rotowire-
style notes with ``headline``, ``story``, ``published``, ``links``)
— unlike ``site.api.espn.com/.../news?playerId=``, which silently
ignores the param and returns the league-wide feed.

Identity: targets come from a ``targets_supplier`` callable injected
at construction (the server wires it to the live contract's
top-board rows joined against the Sleeper directory's ``espn_id``).
Each emitted mention is PRE-STAMPED with the target's position/team,
so the service's enrichment pass has nothing to guess — the espn_id
join is the strongest identity signal in the pipeline.

Politeness: the provider keeps its own per-player TTL cache
(default 30 min) and refreshes at most ``max_requests_per_fetch``
players per ``fetch()`` call (the service calls ``fetch`` once per
aggregate refresh, itself TTL-cached).  A 100-player target list
therefore trickle-refreshes over ~40 minutes at 8 requests per
3-minute cycle — never a fan-out on page load.  Stale entries keep
serving until their refresh slot comes up.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, List, Optional

from ..base import NewsItem, NewsProvider, PlayerMention, stable_id, to_iso_utc
from ._rss import classify, clean_text, default_http_fetcher

log = logging.getLogger(__name__)

_FEED_URL_TEMPLATE = (
    "https://site.web.api.espn.com/apis/fantasy/v2/games/ffl/news/players"
    "?playerId={espn_id}&limit={limit}"
)

DEFAULT_PLAYER_TTL_S = 1800.0  # 30 min per player between refetches
DEFAULT_MAX_REQUESTS_PER_FETCH = 8
# Single source of truth for target coverage: server.py's
# ``_live_espn_news_targets`` supplier imports this as its own cap,
# so the supplier's emission limit and this provider's
# ``_valid_targets`` truncation cannot drift apart.
DEFAULT_MAX_TARGETS = 150
DEFAULT_PER_PLAYER_LIMIT = 3


def _default_targets_supplier() -> List[dict[str, Any]]:
    """No wiring → no targets → provider contributes nothing."""
    return []


class EspnPlayerNewsProvider(NewsProvider):
    """Player-scoped ESPN news via espn_id targets."""

    name = "espn_player"
    label = "ESPN Player News"
    user_agent = "brisket-news-espn-player/1.0"

    def __init__(
        self,
        *,
        targets_supplier: Optional[Callable[[], List[dict[str, Any]]]] = None,
        fetcher: Optional[Callable[[str], bytes]] = None,
        player_ttl_s: float = DEFAULT_PLAYER_TTL_S,
        max_requests_per_fetch: int = DEFAULT_MAX_REQUESTS_PER_FETCH,
        max_targets: int = DEFAULT_MAX_TARGETS,
        per_player_limit: int = DEFAULT_PER_PLAYER_LIMIT,
        clock: Callable[[], float] = time.monotonic,
        **config: Any,
    ) -> None:
        super().__init__(**config)
        self._targets_supplier = targets_supplier or _default_targets_supplier
        self._fetcher = fetcher or self._default_fetcher
        self._player_ttl_s = max(0.0, float(player_ttl_s))
        self._max_requests = max(1, int(max_requests_per_fetch))
        self._max_targets = max(1, int(max_targets))
        self._per_player_limit = max(1, int(per_player_limit))
        self._clock = clock
        # espn_id → (fetched_at, [NewsItem]).  Entries persist past
        # their TTL and keep serving until their refresh slot comes
        # up — stale player news beats a hole in the feed, and the
        # service-level age cutoff drops anything genuinely old.
        self._player_cache: dict[str, tuple[float, List[NewsItem]]] = {}
        # espn_id → last attempt time (success OR failure).  Drives
        # the round-robin ordering so persistent failers can't starve
        # the budget — see ``_staleness`` in ``fetch``.
        self._last_attempt: dict[str, float] = {}

    def _default_fetcher(self, url: str) -> bytes:
        return default_http_fetcher(url, timeout=self.timeout_s, user_agent=self.user_agent)

    # ── fetch ───────────────────────────────────────────────────
    def fetch(self, *, player_names=None, limit: int = 50) -> List[NewsItem]:
        targets = self._valid_targets()
        if not targets:
            return []

        now = self._clock()

        # Refresh order: never-ATTEMPTED first, then oldest attempt.
        # Ranking by attempt time (not cache time) is what keeps the
        # round-robin advancing past repeat offenders: a persistently
        # failing target never enters the cache, so a cache-time sort
        # would rank it -inf forever and let a handful of failers
        # consume the whole budget every cycle, starving every later
        # target (Codex P2).  A failed attempt sends the target to
        # the back of the line until the others have had their slot.
        def _staleness(t: dict[str, Any]) -> float:
            return self._last_attempt.get(str(t["espnId"]), float("-inf"))

        budget = self._max_requests
        attempted = 0
        failed = 0
        last_error: Optional[Exception] = None
        for target in sorted(targets, key=_staleness):
            espn_id = str(target["espnId"])
            cached = self._player_cache.get(espn_id)
            fresh = cached is not None and (now - cached[0]) < self._player_ttl_s
            if fresh or budget <= 0:
                continue
            budget -= 1
            attempted += 1
            self._last_attempt[espn_id] = now
            try:
                raw = self._fetcher(
                    _FEED_URL_TEMPLATE.format(espn_id=espn_id, limit=self._per_player_limit)
                )
                items = self._parse_feed(raw, target)
                self._player_cache[espn_id] = (now, items)
            except Exception as exc:  # noqa: BLE001 — per-player isolation
                failed += 1
                last_error = exc
                log.warning("espn_player fetch failed for %s: %s", espn_id, exc)
                # Keep any stale entry rather than overwriting with
                # nothing; it refreshes on a later cycle.

        # Total-failure signal: every attempted request failed AND the
        # cache has nothing to serve.  Raising here lets the service's
        # per-provider isolation mark the run down (and the route's
        # all_providers_failed detection work) instead of masquerading
        # as a healthy-but-quiet feed.
        if attempted > 0 and failed == attempted and not self._player_cache:
            raise last_error if last_error else RuntimeError("espn_player: all requests failed")

        out: List[NewsItem] = []
        target_ids = {str(t["espnId"]) for t in targets}
        for espn_id, (_ts, items) in self._player_cache.items():
            if espn_id in target_ids:
                out.extend(items)
        out.sort(key=lambda it: it.ts, reverse=True)
        return out[: max(1, int(limit))]

    # ── helpers ─────────────────────────────────────────────────
    def _valid_targets(self) -> List[dict[str, Any]]:
        try:
            raw_targets = self._targets_supplier() or []
        except Exception as exc:  # noqa: BLE001 — supplier reads live state
            log.warning("espn_player targets supplier failed: %s", exc)
            return []
        out: List[dict[str, Any]] = []
        seen: set[str] = set()
        for t in raw_targets:
            if not isinstance(t, dict):
                continue
            espn_id = str(t.get("espnId") or "").strip()
            name = str(t.get("name") or "").strip()
            if not espn_id or not name or espn_id in seen:
                continue
            seen.add(espn_id)
            out.append(
                {
                    "espnId": espn_id,
                    "name": name,
                    "position": str(t.get("position") or "").strip() or None,
                    "team": str(t.get("team") or "").strip() or None,
                }
            )
            if len(out) >= self._max_targets:
                break
        return out

    def _parse_feed(self, raw: bytes, target: dict[str, Any]) -> List[NewsItem]:
        payload = json.loads(raw)
        feed = payload.get("feed") if isinstance(payload, dict) else None
        if not isinstance(feed, list):
            return []
        out: List[NewsItem] = []
        for entry in feed[: self._per_player_limit]:
            if not isinstance(entry, dict):
                continue
            headline = clean_text(str(entry.get("headline") or ""))
            if not headline:
                continue
            body = clean_text(str(entry.get("story") or entry.get("description") or ""))
            # Undated entries are SKIPPED, not stamped with now():
            # defaulting to the fetch time would fabricate freshness
            # on every refetch and smuggle possibly-old articles past
            # the service's 7-day cutoff (which drops anything that
            # can't prove its age).
            published = _parse_entry_timestamp(entry)
            if published is None:
                continue
            url = _entry_url(entry)
            entry_id = str(entry.get("id") or entry.get("contentKey") or headline)
            severity, kind, impact = classify(f"{headline}\n{body}")
            out.append(
                NewsItem(
                    id=stable_id(self.name, f"{target['espnId']}:{entry_id}"),
                    ts=to_iso_utc(published),
                    provider=self.name,
                    provider_label=self.label,
                    severity=severity,
                    kind=kind,
                    headline=headline,
                    body=body,
                    # Pre-stamped identity: the espn_id join already
                    # names exactly one player — no enrichment guess.
                    players=[
                        PlayerMention(
                            name=target["name"],
                            impact=impact,
                            position=target["position"],
                            team=target["team"],
                        )
                    ],
                    url=url,
                    tags=[kind, "player"],
                )
            )
        return out


def _parse_entry_timestamp(entry: dict[str, Any]) -> Optional[datetime]:
    """Parse ``published`` (falling back to ``lastModified``) or None.

    None means the entry carries no provable timestamp — callers skip
    it rather than inventing one.
    """
    raw = entry.get("published") or entry.get("lastModified")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry_url(entry: dict[str, Any]) -> Optional[str]:
    links = entry.get("links")
    if not isinstance(links, dict):
        return None
    for path in (("web", "href"), ("mobile", "href")):
        node: Any = links
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, str) and node.startswith("http"):
            return node
    return None


__all__ = ["EspnPlayerNewsProvider"]
