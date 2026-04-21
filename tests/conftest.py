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


# Stash the real implementation so calibration-specific tests can
# opt back in by passing ``base=tmp_path`` to their API calls, and so
# the wrapper below can delegate to it when a base is explicit.
_production._original_production_config_path = _production.production_config_path


def _neutral_config_path(base: Path | None = None) -> Path:
    # Honour an explicit ``base`` so opt-in calibration tests that
    # pass ``base=tmp_path`` (e.g. ``tests/idp_calibration/test_api.py``)
    # still hit their own sandbox. Without an explicit base we fall
    # through to the neutral temp file so unrelated tests never read
    # any promoted config that happens to live at
    # ``config/idp_calibration.json`` on the dev machine.
    if base is not None:
        return _production._original_production_config_path(base)
    return _NEUTRAL_PATH


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
