"""The ``sleeper_api`` circuit breaker counts availability failures, not answers.

The breaker exists to stop a Sleeper OUTAGE turning into minutes of timeouts.
An HTTP 404 for one specific league is Sleeper answering, so it must never count
toward the trip threshold -- five deleted leagues in a row used to open the
breaker and fast-fail every healthy league behind them for the rest of a Sharp
transaction crawl.  5xx, 429, timeouts, transport errors and non-JSON bodies
still count.
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


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "status", {}, io.BytesIO(b""))  # type: ignore[arg-type]


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

    def test_a_404_probe_proves_sleeper_is_up_and_closes_the_breaker(self, net):
        self._open(net)
        _breaker()._state_since -= 3600  # the open window has long expired
        net.script.append(_http_error(404))
        assert sleeper_overlay._http_get_json_classified(URL)[0] == (
            sleeper_overlay.FETCH_NOT_FOUND
        )
        assert _state() == circuit_breaker.CLOSED

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
