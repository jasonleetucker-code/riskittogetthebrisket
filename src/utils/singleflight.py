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
