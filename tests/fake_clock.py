"""Opt-in fake wall clock for the year-boundary harness (never on by default).

``pytest --fake-now=2027-01-01T00:30:00Z`` (or ``RISKIT_FAKE_NOW=...``) makes
every ``datetime.now()/utcnow()/today()``, ``date.today()`` and ``time.time()``
in the process answer from a clock that STARTS at the given instant and then
ticks forward in real time (so timeouts, durations and ``sleep`` loops still
behave).  Off unless the option/env var is given, so the blocking gate is
byte-for-byte unchanged.

Why not ``freezegun``: the dev dependency set is hash-locked
(``requirements-dev.lock.txt``); adding a package for an advisory harness would
change the locked dependency identity.  This is a small stdlib shim.

Mechanism: the ``datetime`` module's ``datetime``/``date`` classes are replaced
by subclasses whose ``now``/``today``/``utcnow`` read the fake clock, and every
already-imported module that did ``from datetime import datetime`` is rebound
(modules imported later pick the fakes up from the patched ``datetime``
module).  Fake classes return REAL ``datetime``/``date`` instances, so nothing
downstream ever holds a subclass object (pickle, sqlite adapters, ``type() is``
checks all behave normally).  Naive local time honours the process ``TZ``.

Not covered (none used by the date-sensitive suites): SQLite's
``datetime('now')``, ``time.monotonic``, C extensions reading the OS clock.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time as _time
from datetime import timezone

_REAL_DATETIME = _dt.datetime
_REAL_DATE = _dt.date
_REAL_TIME = _time.time
_REAL_TIME_NS = _time.time_ns
_REAL_MONOTONIC = _time.monotonic

# Public: the genuine classes, for code that must subclass them even while the
# fake clock has replaced ``datetime.datetime`` / ``datetime.date``.
REAL_DATETIME = _REAL_DATETIME
REAL_DATE = _REAL_DATE

_start_epoch: float | None = None
_start_mono: float = 0.0
_installed = False
_seen_modules = 0


def parse_instant(text: str) -> float:
    """ISO-8601 instant -> epoch seconds.  A naive value is read as UTC."""
    s = text.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    parsed = _REAL_DATETIME.fromisoformat(s)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _now_epoch() -> float:
    assert _start_epoch is not None
    return _start_epoch + (_REAL_MONOTONIC() - _start_mono)


class _DateMeta(type):
    def __instancecheck__(cls, obj):  # real date/datetime objects count
        return isinstance(obj, _REAL_DATE)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, _REAL_DATE)


class _DatetimeMeta(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _REAL_DATETIME)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, _REAL_DATETIME)


class FakeDate(_REAL_DATE, metaclass=_DateMeta):
    def __new__(cls, *args, **kwargs):
        return _REAL_DATE(*args, **kwargs)

    @classmethod
    def today(cls):
        return _REAL_DATETIME.fromtimestamp(_now_epoch()).date()


class FakeDatetime(_REAL_DATETIME, metaclass=_DatetimeMeta):
    def __new__(cls, *args, **kwargs):
        return _REAL_DATETIME(*args, **kwargs)

    @classmethod
    def now(cls, tz=None):
        return _REAL_DATETIME.fromtimestamp(_now_epoch(), tz)

    @classmethod
    def utcnow(cls):
        return _REAL_DATETIME.fromtimestamp(_now_epoch(), timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()


def _fake_time() -> float:
    return _now_epoch()


def _fake_time_ns() -> int:
    return int(_now_epoch() * 1_000_000_000)


_SWAPS = {
    id(_REAL_DATETIME): FakeDatetime,
    id(_REAL_DATE): FakeDate,
    id(_REAL_TIME): _fake_time,
    id(_REAL_TIME_NS): _fake_time_ns,
}


def _rebind_modules(only_new: bool) -> None:
    global _seen_modules
    mods = list(sys.modules.items())
    start = _seen_modules if only_new else 0
    for _name, mod in mods[start:]:
        d = getattr(mod, "__dict__", None)
        if not isinstance(d, dict) or mod is sys.modules.get(__name__):
            continue
        for key, val in list(d.items()):
            repl = _SWAPS.get(id(val))
            if repl is not None:
                try:
                    d[key] = repl
                except Exception:  # noqa: BLE001 — read-only module dict
                    pass
    _seen_modules = len(mods)


def install(now_text: str) -> None:
    """Start the fake clock (idempotent).  Called only when explicitly opted in."""
    global _start_epoch, _start_mono, _installed
    _start_epoch = parse_instant(now_text)
    _start_mono = _REAL_MONOTONIC()
    if _installed:
        return
    _installed = True
    _dt.datetime = FakeDatetime  # type: ignore[misc]
    _dt.date = FakeDate  # type: ignore[misc]
    _time.time = _fake_time  # type: ignore[assignment]
    _time.time_ns = _fake_time_ns  # type: ignore[assignment]
    _rebind_modules(only_new=False)


def refresh() -> None:
    """Rebind ``from datetime import datetime`` names in modules imported since."""
    if _installed:
        _rebind_modules(only_new=True)


def requested(config=None) -> str | None:
    value = None
    if config is not None:
        value = config.getoption("--fake-now", default=None)
    return value or os.environ.get("RISKIT_FAKE_NOW") or None
