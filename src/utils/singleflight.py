"""Share in-flight synchronous work without retaining completed keys or results."""

from concurrent.futures import Future
from threading import Lock
from typing import Callable, Hashable, TypeVar

T = TypeVar("T")


class SingleFlight:
    """One builder per key, per process; independent keys never hold one lock.

    The caller owns cache policy and should re-check its cache in ``build``.
    Entries exist only while work runs, including on failure. This is not a
    cross-process lock or a job queue, and builders must not recursively wait
    on the same key. ``run`` returns (result, shared_with_another_builder).
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: dict[Hashable, Future] = {}

    def run(self, key: Hashable, build: Callable[[], T]) -> tuple[T, bool]:
        with self._lock:
            pending = self._pending.get(key)
            shared = pending is not None
            if pending is None:
                pending = Future()
                self._pending[key] = pending
        if shared:
            return pending.result(), True
        try:
            result = build()
            pending.set_result(result)
            return result, False
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._lock:
                del self._pending[key]

    def run_sharing_success(
        self,
        key: Hashable,
        build: Callable[[], T],
        *,
        failed: Callable[[T], bool] | None = None,
        retry: Callable[[], T] | None = None,
    ) -> tuple[T, bool]:
        """Like :meth:`run`, but only a SUCCESS is shared.

        A follower whose leader raised, or returned a result ``failed`` flags
        (a failure sentinel such as ``{}``), makes its own attempt with
        ``retry`` (default ``build``) instead of inheriting the failure — the
        attempt it would have made had it arrived alone.  Followers' own
        attempts are not themselves shared.
        """
        with self._lock:
            pending = self._pending.get(key)
            shared = pending is not None
            if pending is None:
                pending = Future()
                self._pending[key] = pending
        if shared:
            try:
                result = pending.result()
            except Exception:  # noqa: BLE001 — the leader's failure is not ours
                return (retry or build)(), False
            if failed is not None and failed(result):
                return (retry or build)(), False
            return result, True
        try:
            result = build()
            pending.set_result(result)
            return result, False
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._lock:
                del self._pending[key]
