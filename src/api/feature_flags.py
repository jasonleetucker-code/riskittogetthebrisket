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
    # Phase 6 — Usage-based signals — BUILT BUT NOT WIRED, and OFF.
    #
    # This comment used to read "fires via unified_signal_engine when
    # nfl_data_ingest supplies stats".  It did not fire, because nothing
    # in the tree calls ``detect_usage_transitions`` or
    # ``unified_signal_engine`` at all — the flag reported True for a
    # capability with no live path (gap analysis §4.2).
    #
    # It stays OFF now for a second, independent reason, measured
    # 2026-07-27 against the persisted 2025 season by
    # ``scripts/audit/measure_usage_signal_rate.py``: the detector fires
    # on a mean **17.8% of active players every week**, stable across
    # weeks 6-18.  Threshold tuning does not fix it — flooring the
    # standard deviation makes it worse (19% -> 32%), and a plain
    # 30-percentage-point absolute-move rule still hits 21%.  A
    # four-observation z-score on a bounded 0-1 share does not
    # discriminate, because real NFL snap share genuinely moves that
    # much week to week.
    #
    # Turning this on today would only enable a flag with no consumer.
    # Whoever wires the consumer must re-run the audit first.
    "usage_signals": False,
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
    # Collaborative audit, finding F — TE basis conversion at blend time.
    #
    # Replaces the flat ``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` (1.15) on
    # non-TEP sources' TE contributions with KTC's own MEASURED base →
    # TE++ uplift curve (``src/league_intel/te_premium.py``).  The blend
    # is already anchored on ``ktcSfTep``, which IS the TE++ board, so
    # this corrects the magnitude of an alignment that was happening
    # anyway — it does not add a second one.  1.15 sits below the entire
    # observed range (KTC's smallest actual uplift is 1.209), so every
    # tight end was being lifted too little.
    #
    # ON by default and deliberately so.  A flag defaulting OFF here
    # would repeat ORCHESTRATION.md 6.14/6.15's named mistake: the
    # previous TE module was left unimported so "toggle off" would be
    # byte-identical, which also meant the double-count guard could
    # never fire on it.  Both paths are exercised by
    # ``tests/api/test_te_basis_conversion.py``.
    #
    # This moves live consensus values for TEs, so it has a rollback:
    # RISKIT_FEATURE_TE_BASIS_CONVERSION=0 restores the flat 1.15.  An
    # explicit operator TE-premium slider value also wins over the
    # curve regardless of this flag.
    "te_basis_conversion": True,
    # IDP positional scoring fit (Tier 2).  This league pays coverage
    # and disruption and discounts finishing plays, so relative to DB it
    # values DL about +7% and LB about +3% versus the generic rate card
    # every ranking source prices on.  Measured, stable across pool
    # depth, and re-allocates between IDP positions rather than
    # inflating IDP as a whole — see src/league_intel/scoring_fit.py.
    #
    # OFF by default, unlike te_basis_conversion.  The operator directed
    # the TE basis explicitly and has directed nothing here, and this
    # moves every IDP value on the board.  Flip with
    # RISKIT_FEATURE_IDP_SCORING_FIT=1.
    #
    # Note what is deliberately NOT behind this flag: a per-player IDP
    # multiplier.  The same data supports one arithmetically and it is
    # noise — see the module docstring for the depth-stability
    # measurement that rules it out.
    "idp_scoring_fit": False,
    # Per-player reception-depth tilt (Tier 2).  Separate from
    # idp_scoring_fit above rather than sharing it: that flag is named
    # for IDP, and using it to gate an offence feature would make the
    # name a lie — an operator disabling "idp_scoring_fit" would
    # silently also disable every receiver adjustment.
    #
    # Also OFF by default.  Note the magnitude before enabling: the
    # per-catch spread is 8x but receptions are 17-33% of a player's
    # points, so the VALUE move is around +/-8%, not +/-120%.  See
    # src/league_intel/reception_fit.py.
    "reception_scoring_fit": False,
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
