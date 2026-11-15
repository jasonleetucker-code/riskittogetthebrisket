"""The ``sleeper_api`` circuit breaker counts availability failures, not answers.

The breaker exists to stop a Sleeper OUTAGE turning into minutes of timeouts.
Sleeper's own HTTP 404 for one specific league (empty / JSON ``null`` body) is an
answer about one id, so it must never count toward the trip threshold -- five
deleted leagues in a row used to open the breaker and fast-fail every healthy
league behind them for the rest of a Sharp transaction crawl.  It is also not
evidence that Sleeper is healthy, so it is reported to the breaker as NOTHING
(a HALF_OPEN probe that gets one stays HALF_OPEN).  A 404 with any other body
(HTML, a gateway / WAF message) is not Sleeper's and counts as a failure.  5xx,
429, timeouts, transport errors and non-JSON bodies still count.
"""

from __future__ import annotations

import io
import json
import socket
import urllib.error

import pytest

from src.api import sleeper_overlay
from src.utils import circuit_breaker

URL = "https://api.sleeper.app/v1/league/L1/rosters"


def _http_error(code: int, body: bytes | io.BytesIO = b"") -> urllib.error.HTTPError:
    fp = body if isinstance(body, io.BytesIO) else io.BytesIO(body)
    return urllib.error.HTTPError(URL, code, "status", {}, fp)  # type: ignore[arg-type]


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _fresh_breaker():
    circuit_breaker.reset_all_for_tests()
    yield
    circuit_breaker.reset_all_for_tests()


@pytest.fixture()
def net(monkeypatch):
    """Scripted ``urlopen``: each call pops the next outcome (an exception is
    raised, bytes are returned as a 200 body)."""
    script: list = []
    calls: list[str] = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        outcome = script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Resp(outcome)

    monkeypatch.setattr(sleeper_overlay.urllib.request, "urlopen", fake_urlopen)

    class Net:
        def __init__(self) -> None:
            self.script = script
            self.calls = calls

    return Net()


def _breaker():
    return circuit_breaker.get_or_create("sleeper_api")


def _state() -> str:
    return _breaker().snapshot()["state"]


class TestA404IsAnAnswer:
    def test_a_run_of_404s_never_opens_the_breaker(self, net):
        """The incident: >= 5 definitive 404s inside the window tripped it."""
        net.script.extend(_http_error(404) for _ in range(25))
        for _ in range(25):
            assert sleeper_overlay._http_get_json(URL) is None
        snap = _breaker().snapshot()
        assert snap["state"] == circuit_breaker.CLOSED
        assert snap["counters"]["failure"] == 0
        assert snap["counters"]["opens"] == 0
        assert snap["recentFailuresInWindow"] == 0
        assert len(net.calls) == 25, "every 404 must have reached the network"

    def test_a_404_is_reported_to_the_breaker_as_nothing_at_all(self, net):
        """Neither a failure NOR a success: a 404 about one id is no evidence that
        Sleeper is healthy."""
        net.script.extend([_http_error(404), _http_error(404, b"null")])
        for _ in range(2):
            assert sleeper_overlay._http_get_json_classified(URL)[0] == (
                sleeper_overlay.FETCH_NOT_FOUND
            )
        counters = _breaker().snapshot()["counters"]
        assert counters["success"] == 0
        assert counters["failure"] == 0

    def test_a_healthy_call_after_many_404s_is_not_fast_failed(self, net):
        net.script.extend(_http_error(404) for _ in range(10))
        net.script.append(json.dumps([{"roster_id": 1}]).encode())
        for _ in range(10):
            sleeper_overlay._http_get_json(URL)
        assert sleeper_overlay._http_get_json(URL) == [{"roster_id": 1}]

    def test_404_is_classified_not_found(self, net):
        net.script.append(_http_error(404))
        assert sleeper_overlay._http_get_json_classified(URL) == (
            sleeper_overlay.FETCH_NOT_FOUND,
            None,
        )

    def test_a_200_with_a_null_body_is_also_not_found(self, net):
        """Sleeper answers JSON ``null`` for an id that does not exist
        (``sleeper_client.request_json_classified`` reads it the same way)."""
        net.script.append(b"null")
        assert sleeper_overlay._http_get_json_classified(URL) == (
            sleeper_overlay.FETCH_NOT_FOUND,
            None,
        )
        assert _breaker().snapshot()["counters"]["failure"] == 0

    def test_404s_neither_trip_nor_erase_real_failures(self, net):
        """A 404 is not a success that forgives an outage: four genuine
        failures plus any number of 404s leave the breaker one failure from
        tripping -- exactly where four failures alone leave it."""
        net.script.extend(_http_error(503) for _ in range(4))
        net.script.extend(_http_error(404) for _ in range(40))
        net.script.append(_http_error(503))
        for _ in range(44):
            sleeper_overlay._http_get_json(URL)
        assert _state() == circuit_breaker.CLOSED
        assert _breaker().snapshot()["recentFailuresInWindow"] == 4
        sleeper_overlay._http_get_json(URL)
        assert _state() == circuit_breaker.OPEN


class TestOnlySleepersOwn404IsSpared:
    """A 404 is Sleeper's only when its body is empty or JSON ``null``.  Anything
    else (an HTML page, a WAF / gateway message, an error envelope) is something in
    front of Sleeper refusing us -- the outage the breaker exists for."""

    @pytest.mark.parametrize("body", [b"", b"null", b"  null\n", b" \r\n", b"\tnull\r\n"])
    def test_an_empty_or_null_body_is_not_found(self, net, body):
        net.script.append(_http_error(404, body))
        assert sleeper_overlay._http_get_json_classified(URL) == (
            sleeper_overlay.FETCH_NOT_FOUND,
            None,
        )
        assert _breaker().snapshot()["counters"]["failure"] == 0

    @pytest.mark.parametrize(
        "body",
        [
            b"<html><body>404 Not Found</body></html>",
            b"Not Found",
            b'{"error": "not found"}',
            b"{}",
            b"[]",
            b"nul",
            b"nullnull",
            b"0",
            b"x" * 10_000,  # an over-long page is never recognised, however it starts
            b"null" + b" " * 200,  # nor is padding that exceeds the bound
        ],
    )
    def test_any_other_body_is_an_error_and_counts(self, net, body):
        net.script.append(_http_error(404, body))
        assert sleeper_overlay._http_get_json_classified(URL) == (
            sleeper_overlay.FETCH_ERROR,
            None,
        )
        snap = _breaker().snapshot()
        assert snap["counters"]["failure"] == 1
        assert snap["lastError"] == "http_404_unrecognised_body"

    def test_five_foreign_404s_open_the_breaker(self, net):
        """A gateway answering 404 to everything is an outage, not five deleted
        leagues."""
        net.script.extend(_http_error(404, b"<html>blocked</html>") for _ in range(5))
        for _ in range(5):
            assert sleeper_overlay._http_get_json(URL) is None
        assert _state() == circuit_breaker.OPEN

    def test_the_body_is_read_with_a_hard_bound(self, net):
        """Never an unbounded ``read()`` of an error page."""

        class _Spy(io.BytesIO):
            def __init__(self, data):
                super().__init__(data)
                self.requested = []

            def read(self, n=-1):
                self.requested.append(n)
                return super().read(n)

        spy = _Spy(b"x" * 1_000_000)
        net.script.append(_http_error(404, spy))
        assert sleeper_overlay._http_get_json_classified(URL)[0] == sleeper_overlay.FETCH_ERROR
        assert spy.requested, "the body must be examined"
        bound = sleeper_overlay._NOT_FOUND_BODY_MAX_BYTES
        assert all(isinstance(n, int) and 0 <= n <= bound + 1 for n in spy.requested)

    def test_an_unreadable_body_is_not_recognised(self, net):
        class _Broken(io.BytesIO):
            def read(self, n=-1):
                raise OSError("connection reset while reading the body")

        net.script.append(_http_error(404, _Broken()))
        assert sleeper_overlay._http_get_json_classified(URL) == (
            sleeper_overlay.FETCH_ERROR,
            None,
        )
        assert _breaker().snapshot()["counters"]["failure"] == 1

    def test_other_statuses_ignore_the_body_rule(self, net):
        """Only a 404 is ever spared; a 410 or 5xx with an empty body is a failure."""
        net.script.extend([_http_error(410), _http_error(500)])
        for _ in range(2):
            assert sleeper_overlay._http_get_json_classified(URL)[0] == sleeper_overlay.FETCH_ERROR
        assert _breaker().snapshot()["counters"]["failure"] == 2


class TestRealFailuresStillTrip:
    @pytest.mark.parametrize("code", [500, 502, 503, 429, 403])
    def test_five_http_errors_open_the_breaker(self, net, code):
        net.script.extend(_http_error(code) for _ in range(5))
        for _ in range(5):
            assert sleeper_overlay._http_get_json(URL) is None
        assert _state() == circuit_breaker.OPEN
        assert _breaker().snapshot()["counters"]["failure"] == 5

    def test_an_open_breaker_fast_fails_without_touching_the_network(self, net):
        net.script.extend(_http_error(500) for _ in range(5))
        for _ in range(5):
            sleeper_overlay._http_get_json(URL)
        assert len(net.calls) == 5
        assert sleeper_overlay._http_get_json_classified(URL) == (
            sleeper_overlay.FETCH_BREAKER_OPEN,
            None,
        )
        assert len(net.calls) == 5, "an open breaker must not call Sleeper"

    def test_timeouts_and_transport_errors_count(self, net):
        net.script.extend(
            [
                TimeoutError("slow"),
                urllib.error.URLError("dns"),
                socket.timeout("t"),
                urllib.error.URLError("reset"),
                TimeoutError("slow"),
            ]
        )
        for _ in range(5):
            assert sleeper_overlay._http_get_json_classified(URL)[0] == (
                sleeper_overlay.FETCH_ERROR
            )
        assert _state() == circuit_breaker.OPEN

    def test_non_json_bodies_count(self, net):
        net.script.extend(b"<html>blocked</html>" for _ in range(5))
        for _ in range(5):
            assert sleeper_overlay._http_get_json_classified(URL)[0] == (
                sleeper_overlay.FETCH_ERROR
            )
        assert _state() == circuit_breaker.OPEN


class TestHalfOpenProbe:
    def _open(self, net):
        net.script.extend(_http_error(500) for _ in range(5))
        for _ in range(5):
            sleeper_overlay._http_get_json(URL)
        assert _state() == circuit_breaker.OPEN

    def test_a_404_probe_leaves_the_breaker_half_open(self, net):
        """A 404 says one id is absent, not that Sleeper is healthy -- it must not
        close a breaker that tripped on an outage.  It is not a failure either, so
        it does not re-open it: the next real answer decides."""
        self._open(net)
        _breaker()._state_since -= 3600  # the open window has long expired
        net.script.append(_http_error(404))
        assert sleeper_overlay._http_get_json_classified(URL)[0] == (
            sleeper_overlay.FETCH_NOT_FOUND
        )
        assert _state() == circuit_breaker.HALF_OPEN
        counters = _breaker().snapshot()["counters"]
        assert counters["closes"] == 0 and counters["success"] == 0
        # more 404s change nothing; calls are still allowed through in HALF_OPEN
        net.script.extend([_http_error(404), _http_error(404)])
        sleeper_overlay._http_get_json(URL)
        sleeper_overlay._http_get_json(URL)
        assert _state() == circuit_breaker.HALF_OPEN
        # a real 200 closes it
        net.script.append(json.dumps([1]).encode())
        assert sleeper_overlay._http_get_json(URL) == [1]
        assert _state() == circuit_breaker.CLOSED

    def test_a_404_with_a_foreign_body_probe_reopens_it(self, net):
        self._open(net)
        _breaker()._state_since -= 3600
        net.script.append(_http_error(404, b"<html>gateway</html>"))
        assert sleeper_overlay._http_get_json_classified(URL)[0] == sleeper_overlay.FETCH_ERROR
        assert _state() == circuit_breaker.OPEN

    def test_a_500_probe_reopens_it(self, net):
        self._open(net)
        _breaker()._state_since -= 3600
        net.script.append(_http_error(500))
        sleeper_overlay._http_get_json(URL)
        assert _state() == circuit_breaker.OPEN


class TestWrapperContract:
    def test_http_get_json_returns_the_payload_unchanged(self, net):
        net.script.append(json.dumps({"a": 1}).encode())
        assert sleeper_overlay._http_get_json(URL) == {"a": 1}

    def test_a_breaker_that_cannot_be_built_never_breaks_the_fetch(self, net, monkeypatch):
        monkeypatch.setattr("src.utils.circuit_breaker.get_or_create", lambda *a, **k: None)
        net.script.append(_http_error(404))
        assert sleeper_overlay._http_get_json_classified(URL)[0] == (
            sleeper_overlay.FETCH_NOT_FOUND
        )
