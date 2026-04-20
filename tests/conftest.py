"""Global test fixtures.

Keeps unrelated tests (TEP, picks, identity, etc.) isolated from any
promoted IDP calibration config that happens to sit at
``config/idp_calibration.json`` on the dev machine. Tests that want
to exercise calibration (``tests/idp_calibration/*``) explicitly
monkeypatch the path themselves.

The redirect happens at module import time (before pytest collection)
so unittest ``setUpClass`` hooks that build the contract can't leak
the live calibration into tests that shouldn't see it.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.idp_calibration import production as _production

_NEUTRAL_PATH = Path(
    tempfile.mkdtemp(prefix="pytest-no-calibration-")
) / "idp_calibration.json"


def _neutral_config_path(base: Path | None = None) -> Path:  # noqa: ARG001
    return _NEUTRAL_PATH


# Stash the real implementation so the calibration-specific tests can
# restore it via monkeypatch if they need to hit a specific config
# file. In practice those tests also monkeypatch this attribute, which
# layers on top of the neutral override without us needing to expose
# a switch.
_production._original_production_config_path = _production.production_config_path
_production.production_config_path = _neutral_config_path
_production.reset_cache()


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
