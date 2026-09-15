"""Durable news snapshots and an in-memory, provider-free serving adapter."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime
from typing import Iterable, Mapping

from src.serving.artifacts import ArtifactStore, CorruptArtifact, Generation, MissingArtifact

from .base import NewsItem, PlayerMention
from .service import (
    DEFAULT_CACHE_TTL_S,
    DEFAULT_TOTAL_LIMIT,
    AggregatedNews,
    NewsService,
    ProviderRunResult,
    project_news,
)

ASSET = "news-serving"
KEY = "public"
MODEL_VERSION = "news-v1"
log = logging.getLogger(__name__)


class NewsNotReady(RuntimeError):
    """No validated news snapshot is available locally."""


def _timestamp(value: object) -> float:
    if not isinstance(value, str):
        raise ValueError("news timestamp must be a string")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("news timestamp must include a timezone")
    return stamp.timestamp()


def _decode(body: bytes) -> AggregatedNews:
    """Rehydrate existing news types; reject invalid snapshots before publication."""
    payload = json.loads(body)
    schema = payload.pop("schemaVersion", None) if isinstance(payload, dict) else None
    if type(schema) is not int or schema != 1:
        raise ValueError("unsupported prepared news schema")
    if not isinstance(payload.get("items"), list) or not isinstance(
        payload.get("provider_runs"), list
    ):
        raise ValueError("invalid prepared news lists")
    items = []
    for value in payload.pop("items"):
        row = dict(value)
        mentions = [PlayerMention(**mention) for mention in row.pop("players")]
        item = NewsItem(**row, players=mentions)
        if not all(
            isinstance(getattr(item, name), str)
            for name in ("id", "provider", "headline", "body", "kind", "provider_label")
        ):
            raise ValueError("invalid news item fields")
        if not item.id or item.severity not in {"alert", "watch", "info"}:
            raise ValueError("invalid news item identity or severity")
        _timestamp(item.ts)
        if not isinstance(item.tags, list) or not all(isinstance(tag, str) for tag in item.tags):
            raise ValueError("invalid news tags")
        for mention in mentions:
            if (
                not isinstance(mention.name, str)
                or mention.impact not in {"positive", "negative", "neutral"}
                or not isinstance(mention.ambiguous, bool)
            ):
                raise ValueError("invalid news mention")
        items.append(item)
    runs = [ProviderRunResult(**row) for row in payload.pop("provider_runs")]
    if not runs or len({run.name for run in runs}) != len(runs):
        raise ValueError("news needs distinct observed provider runs")
    for run in runs:
        if (
            not isinstance(run.name, str)
            or not run.name
            or not isinstance(run.label, str)
            or type(run.ok) is not bool
            or type(run.count) is not int
            or run.count < 0
        ):
            raise ValueError("invalid news provider run")
        if type(run.elapsed_ms) is not int or run.elapsed_ms < 0 or type(run.retained) is not bool:
            raise ValueError("invalid news provider diagnostics")
        if run.error is not None and not isinstance(run.error, str):
            raise ValueError("invalid news provider error")
        if run.attempted_count is not None and (
            type(run.attempted_count) is not int
            or type(run.failed_count) is not int
            or not 0 <= run.failed_count <= run.attempted_count
        ):
            raise ValueError("invalid news provider attempt counts")
    result = AggregatedNews(items=items, provider_runs=runs, **payload)
    _timestamp(result.generated_at)
    _timestamp(result.last_attempt_at)
    if result.last_success_at is not None:
        _timestamp(result.last_success_at)
    if not isinstance(result.providers_used, list) or not all(
        isinstance(name, str) for name in result.providers_used
    ):
        raise ValueError("invalid providers used")
    if not all(type(value) is bool for value in (result.cache_hit, result.retained, result.stale)):
        raise ValueError("invalid news state flags")
    return result


def load_news(artifact: Generation) -> AggregatedNews:
    if artifact.manifest.get("modelVersion") != MODEL_VERSION:
        raise ValueError("unsupported prepared news model")
    return _decode(artifact.files["news.json"])


def refresh_prepared_news(
    store: ArtifactStore,
    service: NewsService,
    *,
    player_names: Iterable[str],
    player_meta: Mapping,
    input_generation: str,
) -> Generation:
    """Fetch providers off-request and publish valid content plus truthful attempts.

    Previous content comes from disk so a worker restart preserves it. An unreadable
    prior snapshot can recover only from a fully healthy observed refresh; a failed
    or partial refresh cannot replace a reader's retained valid snapshot with gaps.
    """
    if not service.provider_names:
        raise NewsNotReady("no news providers configured")
    unreadable_previous = False
    try:
        previous = load_news(store.read_current(ASSET, KEY))
    except MissingArtifact:
        previous = None
    except (CorruptArtifact, ValueError, KeyError, TypeError):
        previous = None
        unreadable_previous = True
    snapshot = service.refresh_snapshot(
        player_names=player_names, player_meta=player_meta, previous=previous
    )
    if unreadable_previous and not all(run.ok for run in snapshot.provider_runs):
        raise NewsNotReady("prior news unreadable and refresh incomplete")
    body = json.dumps(
        {"schemaVersion": 1, **asdict(snapshot)},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return store.publish(
        ASSET,
        KEY,
        {"news.json": body},
        {
            "modelVersion": MODEL_VERSION,
            "inputGenerations": {"canonical": input_generation},
            "configHash": "|".join(service.provider_names),
            "generatedAt": snapshot.generated_at,
            "sourceAsOf": {"news": snapshot.last_success_at},
        },
        validator=load_news,
    )


class PreparedNewsReader:
    """Reload artifacts in a background thread; aggregate performs no file/network I/O."""

    def __init__(self, store: ArtifactStore, *, clock=time.time) -> None:
        self._store = store
        self._clock = clock
        self._current: AggregatedNews | None = None
        self._version: tuple[int, int] | None = None
        self._reload_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    @property
    def provider_names(self) -> list[str]:
        current = self._current
        return [run.name for run in current.provider_runs] if current else []

    def reload_if_changed(self) -> bool:
        with self._reload_lock:
            try:
                version = self._store.current_version(ASSET, KEY)
                if version == self._version:
                    return False
                candidate = load_news(self._store.read_current(ASSET, KEY))
                if self._store.current_version(ASSET, KEY) != version:
                    return False
                self._current = candidate
                self._version = version
                self.last_error = None
                return True
            except Exception as exc:
                self.last_error = type(exc).__name__
                return False

    def aggregate(
        self,
        *,
        player_names: Iterable[str] | None = None,
        team_names: Iterable[str] | None = None,
        player_meta: Mapping | None = None,
    ) -> AggregatedNews:
        # Names and identity enrichment belong to the accepted producer snapshot.
        # Re-tagging against request-time board state would mix its generations.
        current = self._current
        if current is None:
            raise NewsNotReady("prepared news unavailable")
        now = self._clock()
        age = now - _timestamp(current.last_attempt_at)
        return project_news(
            replace(
                current,
                stale=current.stale
                or bool(self.last_error)
                or age > DEFAULT_CACHE_TTL_S
                or age < -60,
            ),
            team_names or (),
            now_epoch=now,
            total_limit=DEFAULT_TOTAL_LIMIT,
        )

    def start(self, *, interval: float = 1.0) -> None:
        if interval <= 0:
            raise ValueError("news reload interval must be positive")
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()

            def watch() -> None:
                while not self._stop.is_set():
                    self.reload_if_changed()
                    self._stop.wait(interval)

            self._thread = threading.Thread(target=watch, name="news-artifact-reader", daemon=True)
            self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> bool:
        with self._lifecycle_lock:
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()
