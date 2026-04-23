"""Global test fixtures."""
from __future__ import annotations

import os


# ── Sleeper league context isolation ──────────────────────────────────
# ``src/api/data_contract.py::_resolve_league_context`` reads the
# operator's Sleeper league to derive the roster count (rookie-pick
# anchor) and the TE-premium multiplier (``bonus_rec_te``).  During
# tests we must not hit the live Sleeper API — both because it's slow /
# flaky and because the operator's league has bonus_rec_te=0.5, which
# would silently flip the derived TEP from the 1.0 baseline the test
# fixtures assume.
#
# Clearing the env var makes ``_resolve_league_context`` return its
# fallback dict (roster_count=12, bonus_rec_te=0.0, derived TEP=1.0),
# which matches the pre-derivation behavior of every fixture-based
# test in this suite.  Tests that WANT to exercise derivation
# explicitly monkeypatch ``_resolve_league_context`` or
# ``_derive_tep_multiplier_from_league``.
os.environ.pop("SLEEPER_LEAGUE_ID", None)

# The cache is keyed by the env var, but some tests import
# data_contract before pytest runs this conftest (in which case the
# cache may already carry a live Sleeper snapshot from a prior dev
# session).  Clear it defensively.
try:
    from src.api import data_contract as _data_contract

    _data_contract._LEAGUE_CONTEXT_CACHE.clear()
    _data_contract._LEAGUE_CONTEXT_CACHE["context"] = None
    _data_contract._LEAGUE_CONTEXT_CACHE["fetched_at"] = 0.0
except Exception:  # noqa: BLE001 — conftest must never block collection
    pass
