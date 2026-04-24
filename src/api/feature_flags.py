"""Feature flag registry for phased rollout of the 2026-04 upgrade.

Every new capability added in Phases 1–10 of the major upgrade is
gated here so production can stay on the proven path while new code
proves itself.  Flags default to **OFF** unless an env var overrides
them.

Pattern
-------
    from src.api.feature_flags import is_enabled

    if is_enabled("monte_carlo_trade"):
        # new probabilistic path
    else:
        # existing deterministic path

Env-var override
----------------
Set ``RISKIT_FEATURE_<UPPERCASED_NAME>=1`` (or ``true``/``yes``/``on``)
to flip a flag on at deploy time without a config edit.  Set to
``0``/``false``/``no``/``off`` to explicitly disable.

Reads are cached per-process; call ``reload()`` in tests to pick up
env changes mid-run.
"""
from __future__ import annotations

import os
import threading
from typing import Final

# ── Flag registry ─────────────────────────────────────────────────
#
# Keys MUST be snake_case.  The dict is the ONLY place to declare a
# flag — unknown keys raise on read so typos don't silently evaluate
# as "off".

_DEFAULTS: Final[dict[str, bool]] = {
    # Phase 1 — Unified ID mapper
    "unified_id_mapper": True,  # safe: no behavior change, new API only
    # Phase 2 — nfl_data_py pipeline
    "nfl_data_ingest": False,  # needs external data + package install
    # Phase 3 — Realized fantasy points
    "realized_points_api": False,  # needs nfl_data_ingest
    # Phase 4 — Confidence intervals
    "value_confidence_intervals": False,  # additive contract field
    # Phase 5 — Positional tiering
    "positional_tiers": False,  # additive contract field
    # Phase 6 — Usage-based signals
    "usage_signals": False,  # needs nfl_data_ingest
    # Phase 7 — ESPN injury feed
    "espn_injury_feed": False,  # external endpoint, rate-limit risk
    # Phase 8 — Depth chart cross-check
    "depth_chart_validation": False,  # needs espn_injury_feed
    # Phase 9 — Monte Carlo trade simulator
    "monte_carlo_trade": False,  # new endpoint, old endpoint unchanged
    # Phase 10 — Backtesting + dynamic weights
    "dynamic_source_weights": False,  # math runs offline; prod read gated
}

_ENV_PREFIX: Final[str] = "RISKIT_FEATURE_"
_cache: dict[str, bool] = {}
_lock = threading.Lock()


def _env_read(name: str) -> bool | None:
    """Return the env-var override for ``name`` or None if absent.

    Accepted truthy: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    Accepted falsy:  ``0``, ``false``, ``no``, ``off`` (case-insensitive).
    Anything else → None (treated as absent; default wins).
    """
    raw = os.getenv(f"{_ENV_PREFIX}{name.upper()}", "")
    if not raw:
        return None
    low = raw.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    return None


def is_enabled(name: str) -> bool:
    """Return the effective value for ``name``.

    Raises KeyError if the flag isn't registered in ``_DEFAULTS``.
    """
    if name not in _DEFAULTS:
        raise KeyError(
            f"unknown feature flag: {name!r}.  Register it in "
            f"src.api.feature_flags._DEFAULTS first."
        )
    with _lock:
        if name in _cache:
            return _cache[name]
        env = _env_read(name)
        effective = _DEFAULTS[name] if env is None else env
        _cache[name] = effective
        return effective


def reload() -> None:
    """Clear the process-local cache so the next ``is_enabled`` call
    re-reads env vars.  Tests that set env mid-run should call this.
    """
    with _lock:
        _cache.clear()


def snapshot() -> dict[str, bool]:
    """Return the current effective flag values for every registered
    flag.  Cheap — used by ``/api/status`` to expose what's on."""
    return {name: is_enabled(name) for name in _DEFAULTS}


def registered_flags() -> list[str]:
    """Return the registered flag names in declaration order."""
    return list(_DEFAULTS.keys())
