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
