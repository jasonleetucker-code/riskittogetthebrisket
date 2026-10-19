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
        self._sharing: dict[Hashable, _Flight] = {}

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
        """Like :meth:`run`, but a FAILURE is never fanned out — with a bound.

        A follower whose leader raised, or returned a result ``failed`` flags
        (a failure sentinel such as ``{}``), does not inherit the failure.  The
        followers of that failed flight make exactly ONE retry, itself single
        flighted: the first follower to see the failure runs ``retry``
        (default ``build``) and the rest join it.  Its outcome — success or
        failure, value or exception — is what every one of them gets.  So a
        failed flight costs at most two builds however many callers wait on
        it, and none waits for more than the leader's attempt plus one more.
        """
        with self._lock:
            flight = self._sharing.get(key)
            leader = flight is None
            if leader:
                flight = _Flight()
                self._sharing[key] = flight
        if leader:
            try:
                result = build()
                flight.future.set_result(result)
                return result, False
            except BaseException as exc:
                flight.future.set_exception(exc)
                raise
            finally:
                with self._lock:
                    if self._sharing.get(key) is flight:
                        del self._sharing[key]
        try:
            result = flight.future.result()
            ok = failed is None or not failed(result)
        except Exception:  # noqa: BLE001 — the leader's failure is not ours (yet)
            ok = False
        if ok:
            return result, True
        # One retry wave for this failed flight, shared by all its followers
        # (late ones included: the wave hangs off the flight they waited on).
        with self._lock:
            retry_leader = flight.retry is None
            if retry_leader:
                flight.retry = Future()
        if retry_leader:
            try:
                result = (retry or build)()
                flight.retry.set_result(result)
                return result, False
            except BaseException as exc:
                flight.retry.set_exception(exc)
                raise
        return flight.retry.result(), True


class _Flight:
    """One :meth:`SingleFlight.run_sharing_success` flight and its single
    retry wave."""

    __slots__ = ("future", "retry")

    def __init__(self) -> None:
        self.future: Future = Future()
        self.retry: Future | None = None
