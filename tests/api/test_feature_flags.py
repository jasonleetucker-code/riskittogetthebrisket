"""Tests for the feature-flag registry.

These pin the two core guarantees:

1. Every flag has an explicit default.  Unknown flag reads raise.
2. Env-var override works, and reload() picks up mid-run changes.
"""
from __future__ import annotations

import pytest

from src.api import feature_flags


@pytest.fixture(autouse=True)
def _reset_cache():
    feature_flags.reload()
    yield
    feature_flags.reload()


def test_every_flag_defaults_off_except_safe_additive():
    """Safety guarantee: if you forgot to add an env override,
    the system behaves exactly like pre-upgrade.

    The only flag that may default ON is ``unified_id_mapper`` —
    it's a pure-read API that adds no behavior, never changes the
    canonical contract, and can't regress anything on its own.
    """
    flags = feature_flags.snapshot()
    safe_on = {"unified_id_mapper"}
    for name, value in flags.items():
        if name in safe_on:
            continue
        assert value is False, (
            f"flag {name!r} defaults ON but hasn't been vetted as "
            f"regression-safe.  Either add to the safe_on set with "
            f"rationale, or flip the default in _DEFAULTS to False."
        )


def test_unknown_flag_read_raises():
    with pytest.raises(KeyError, match="unknown feature flag"):
        feature_flags.is_enabled("does_not_exist")


def test_env_override_truthy(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    assert feature_flags.is_enabled("monte_carlo_trade") is True


def test_env_override_falsy(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_UNIFIED_ID_MAPPER", "0")
    feature_flags.reload()
    assert feature_flags.is_enabled("unified_id_mapper") is False


def test_env_override_accepts_common_strings(monkeypatch):
    for val in ("true", "TRUE", "yes", "YES", "on", "ON"):
        monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", val)
        feature_flags.reload()
        assert feature_flags.is_enabled("monte_carlo_trade") is True, val
    for val in ("false", "FALSE", "no", "NO", "off", "OFF"):
        monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", val)
        feature_flags.reload()
        assert feature_flags.is_enabled("monte_carlo_trade") is False, val


def test_garbage_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "maybe")
    feature_flags.reload()
    assert feature_flags.is_enabled("monte_carlo_trade") is False


def test_snapshot_covers_every_registered_flag():
    snap = feature_flags.snapshot()
    for name in feature_flags.registered_flags():
        assert name in snap


def test_cache_stable_within_a_read_cycle(monkeypatch):
    """Within one reload cycle the value is stable — setting env
    after first read doesn't flip the cached value."""
    feature_flags.reload()
    initial = feature_flags.is_enabled("monte_carlo_trade")
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    # No reload — cache still holds the initial False.
    assert feature_flags.is_enabled("monte_carlo_trade") == initial
    feature_flags.reload()
    assert feature_flags.is_enabled("monte_carlo_trade") is True
