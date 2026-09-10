"""Capture-once serving state and a background artifact reload loop.

The application supplies the builder and validator. This module never imports
domain logic or starts work at import time. Payload dictionaries remain ordinary
dicts for existing domain readers; builders transfer ownership on publication
and consumers must treat their nested values as read-only. All views and metadata
belong to the same frozen container, installed with one reference replacement.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .artifacts import ArtifactStore, Generation, RejectedCandidate


@dataclass(frozen=True)
class PreparedPayload:
    payload: dict[str, Any]
    raw: bytes
    gzip: bytes
    etag: str


@dataclass(frozen=True)
class ServingGeneration:
    generation_id: str
    contract: dict[str, Any]
    raw: dict[str, Any]
    source: dict[str, Any]
    health: dict[str, Any]
    coverage: dict[str, Any]
    views: Mapping[str, PreparedPayload]
    indexes: Mapping[str, Mapping] = field(default_factory=dict)
    artifact_generation_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "views", MappingProxyType(dict(self.views)))
        object.__setattr__(self, "indexes", MappingProxyType(dict(self.indexes)))


class AtomicRuntime:
    def __init__(
        self,
        store: ArtifactStore,
        asset: str,
        key: str,
        build: Callable[[Generation], ServingGeneration],
        validate: Callable[[ServingGeneration], Any] | None = None,
        on_publish: Callable[[ServingGeneration], Any] | None = None,
    ):
        self.store = store
        self.asset = asset
        self.key = key
        self.build = build
        self.validate = validate
        self.on_publish = on_publish
        self._current: ServingGeneration | None = None
        self._loaded_version: tuple[int, int] | None = None
        self._last_error: str | None = None
        self._state_lock = threading.Lock()
        self._reload_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def current(self) -> ServingGeneration | None:
        """Capture this reference once before a request's first await."""
        with self._state_lock:
            return self._current

    @property
    def last_error(self) -> str | None:
        with self._state_lock:
            return self._last_error

    def _record_error(self, error: Exception) -> None:
        with self._state_lock:
            self._last_error = f"{type(error).__name__}: {error}"

    def _validate(self, candidate: ServingGeneration) -> None:
        if not isinstance(candidate, ServingGeneration):
            raise TypeError("Builder must return a ServingGeneration")
        if not isinstance(candidate.generation_id, str) or not candidate.generation_id:
            raise ValueError("Serving generation identity must be nonempty")
        if self.validate is not None and self.validate(candidate) is False:
            raise RejectedCandidate("Serving generation failed domain validation")

    def _install(self, candidate: ServingGeneration, version: tuple[int, int] | None) -> None:
        # The adapter must finish all fallible preparation before changing
        # external aliases: only this runtime's reference can be rolled back
        # if arbitrary callback code mutates its own state and then raises.
        if self.on_publish is not None:
            self.on_publish(candidate)
        with self._state_lock:
            self._current = candidate
            self._loaded_version = version
            self._last_error = None

    def publish(self, candidate: ServingGeneration) -> None:
        """Legacy in-process adapter: validate, then replace one reference.

        Failure propagates to an explicit caller and leaves current untouched.
        Publication serializes with artifact reloads so an older in-flight build
        cannot overwrite a subsequently published in-process candidate.
        """
        with self._reload_lock:
            try:
                self._validate(candidate)
                self._install(candidate, None)
            except Exception as exc:
                self._record_error(exc)
                raise

    def reload_if_changed(self) -> bool:
        """Load at most one candidate; all failures retain the last good state.

        A failed candidate is retried on the next call, so the background polling
        interval also bounds retries. Concurrent callers coalesce; this method
        returns False while another load/publication is in flight.
        """
        if not self._reload_lock.acquire(blocking=False):
            return False
        try:
            version = self.store.current_version(self.asset, self.key)
            with self._state_lock:
                if version == self._loaded_version:
                    return False
            artifact = self.store.read_current(self.asset, self.key)
            candidate = self.build(artifact)
            self._validate(candidate)
            if (
                candidate.artifact_generation_id or candidate.generation_id
            ) != artifact.generation_id:
                raise ValueError("Built serving identity does not match its artifact generation")
            # Do not install a slow build after a newer publication supersedes
            # it. The next poll consumes that newer complete pointer.
            if self.store.current_version(self.asset, self.key) != version:
                return False
            if threading.current_thread() is self._thread and self._stop.is_set():
                return False
            self._install(candidate, version)
            return True
        except Exception as exc:
            self._record_error(exc)
            return False
        finally:
            self._reload_lock.release()

    def start(self, interval: float = 1.0) -> None:
        """Start one daemon consumer; an unchanged pointer only incurs stat()."""
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Reload interval must be finite and positive")
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError("Previous artifact consumer is still stopping")
                return
            self._stop.clear()

            def consume() -> None:
                while not self._stop.is_set():
                    self.reload_if_changed()
                    self._stop.wait(interval)

            self._thread = threading.Thread(
                target=consume, name=f"serving-{self.asset}-{self.key}", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """Wake the sleeping consumer; return whether any in-flight build ended."""
        with self._lifecycle_lock:
            self._stop.set()
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout=max(0.0, timeout))
        return not thread.is_alive()
