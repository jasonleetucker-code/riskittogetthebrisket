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
    """Safety guarantee: every default-ON flag has been explicitly
    vetted as safe in production.  Adding a flag to this allowlist
    requires matching rationale in _DEFAULTS (see src/api/feature_flags.py).

    When flipping a flag default ON in _DEFAULTS, ADD IT HERE so
    the test continues to pin the intent.
    """
    flags = feature_flags.snapshot()
    # The vetted-safe-ON set — each one has explanatory comments in
    # _DEFAULTS explaining why it's safe + how to flip it off via
    # RISKIT_FEATURE_<NAME>=0 if needed.
    safe_on = {
        "unified_id_mapper",  # no behavior change, read API only
        "nfl_data_ingest",  # guarded import; empty [] if missing
        "realized_points_api",  # endpoint-only, inert until called
        "value_confidence_intervals",  # additive valueBand field
        "positional_tiers",  # additive tierId field
        "usage_signals",  # freshness + starter-guarded
        "espn_injury_feed",  # circuit-breaker protected
        "depth_chart_validation",  # circuit-breaker protected
        "monte_carlo_trade",  # new endpoint, old unchanged
    }
    # Flags that default ON and KNOWINGLY change output.  Deliberately a
    # separate set from ``safe_on``: every member of that one is there
    # because it is additive, inert, or otherwise cannot move a number,
    # and quietly admitting a value-moving flag would erode the only
    # thing the set's name promises.  Entry here requires a MEASURED
    # blast radius recorded at the point of change, not an argument that
    # the change is probably fine.
    value_moving_on = {
        # Collaborative audit finding F.  Replaces the flat 1.15 TE
        # alignment multiplier with KTC's measured base → TE++ curve.
        # Blast radius measured against the 2026-07-27 live board (810
        # rows): all 80 TEs move up, +1.08% (Bowers, against the 9999
        # ceiling) to +30.17% (Ruckert, deep), median +14.27%.  The only
        # non-TE values that move are 48 PICK rows, via the documented
        # current-year pick tethering inheriting rookie-TE values —
        # e.g. 2026 Pick 1.07 +3.91% matches Kenyon Sadiq exactly.  No
        # QB/RB/WR/IDP value changes.  Rank displacement median 7, p90
        # 22.  Rollback: RISKIT_FEATURE_TE_BASIS_CONVERSION=0.
        "te_basis_conversion",
        # IDP positional scoring fit.  Blast radius measured against the
        # 2026-07-27 live board (1,095 rows, 709 of them ranked):
        #
        #   280 IDP rows move — DB n=84 at +3.66%, DL n=113 at +0.01%,
        #   LB n=83 at -3.67%.  ZERO non-IDP values change: the
        #   multiplier is keyed on the DL/LB/DB family and nothing else
        #   resolves to one.
        #
        #   Rank displacement across the ranked board: 544 rows shift,
        #   median 4, p90 35, max 71.  279 of those are non-IDP rows
        #   moving only because IDP rows moved past them — their VALUES
        #   are untouched.
        #
        # Mean-normalised, so it re-allocates between IDP positions and
        # cannot inflate IDP as a class.  Applies to the OPT-IN
        # league-adjusted lens only, never the default market board.
        # Rollback: RISKIT_FEATURE_IDP_SCORING_FIT=0.
        "idp_scoring_fit",
    }
    off_only = {
        "dynamic_source_weights",  # held OFF until backtest data exists
    }
    assert not (safe_on & value_moving_on), "a flag cannot be both no-change and value-moving"
    for name, value in flags.items():
        if name in safe_on or name in value_moving_on:
            continue
        if name in off_only:
            assert value is False, f"flag {name!r} expected OFF but is ON"
            continue
        assert value is False, (
            f"flag {name!r} defaults ON but hasn't been vetted as "
            f"regression-safe.  Either add it to ``safe_on`` (additive / "
            f"inert / cannot move a number) or to ``value_moving_on`` "
            f"(with a MEASURED blast radius), with matching rationale in "
            f"_DEFAULTS — or flip the default to False."
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
    """Invalid env value → falls back to the registered default.
    Uses dynamic_source_weights since it's the one flag still defaulting
    OFF in the 2026-04-25 activation."""
    monkeypatch.setenv("RISKIT_FEATURE_DYNAMIC_SOURCE_WEIGHTS", "maybe")
    feature_flags.reload()
    assert feature_flags.is_enabled("dynamic_source_weights") is False


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
