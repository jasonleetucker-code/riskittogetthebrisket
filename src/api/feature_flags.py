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
    # Activated with the 2026-04-25 deploy that adds nfl_data_py to
    # requirements.txt.  Safe: every fetch is guarded so an import
    # failure in prod degrades to [].  Upstream cost: one-time ~150MB
    # pip install.  Flip to False via RISKIT_FEATURE_NFL_DATA_INGEST=0
    # if pandas install ever breaks prod.
    "nfl_data_ingest": True,
    # Phase 3 — Realized fantasy points — endpoint-only, inert until
    # a client calls it.  Activated with nfl_data_ingest.
    "realized_points_api": True,
    # Phase 4 — Confidence intervals — additive ``valueBand`` field
    # on rankings contract.  Frontend ValueBandBadge renders when
    # field is present; absent = no badge (safe).  Flipping on now.
    "value_confidence_intervals": True,
    # Phase 5 — Positional tiering — additive ``tierId`` field on
    # rankings rows.  Frontend TierDivider renders when tierId set;
    # absent = no divider lines (safe).  Flipping on now.
    "positional_tiers": True,
    # Phase 6 — Usage-based signals — fires via unified_signal_engine
    # when nfl_data_ingest supplies stats.  Freshness-guarded: blocks
    # mid-week data pre-Thursday.  Active-starter-only SELL guard
    # prevents backup-role false alerts.
    "usage_signals": True,
    # Phase 7 — ESPN injury feed — external endpoint, now protected
    # by the ``espn_injuries`` circuit breaker (3 failures / 2min →
    # 3min OPEN).  Safe to activate.
    "espn_injury_feed": True,
    # Phase 8 — Depth chart cross-check — same ESPN infrastructure.
    # Gated by ``espn_depth_charts`` breaker (5 failures / 3min → 3min
    # OPEN).  Requires injury feed ON to cross-check.
    "depth_chart_validation": True,
    # Phase 9 — Monte Carlo trade simulator — new endpoint
    # /api/trade/simulate-mc.  Old /api/trade/simulate is unchanged.
    # Enabling reveals the "Simulate" button in the trade-calc UI.
    "monte_carlo_trade": True,
    # Phase 10 — Backtesting + dynamic weights — held OFF until 2-3
    # months of historical snapshots accumulate.  Flipping this on
    # without a populated dynamic_source_weights.json is a no-op
    # (falls back to static weights).  Promoted deliberately, not
    # automatically.
    "dynamic_source_weights": False,
    # IDP scoring-fit lens (Phase 1 of the IDP valuation integration).
    # Stamps ``idpScoringFit*`` fields on IDP rows: VORP under league
    # scoring, tier label, value-scale delta vs the consensus rank,
    # confidence label scaled by realized sample size.  Diagnostic
    # only — does NOT touch ``rankDerivedValue`` or any trade engine
    # in Phase 1.  The 3-yr nflverse defensive corpus + Sleeper
    # players/scoring fetches add real I/O; gated OFF by default
    # until the Phase 1 production gate passes (≥30 of top-50 IDPs
    # rated fit-positive on the prior season backtest).
    "idp_scoring_fit": False,
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
