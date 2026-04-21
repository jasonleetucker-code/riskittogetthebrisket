"""Production loader refuses pre-v2 configs.

Schema v1 (the old engine) wrote ``final`` as a top-bucket-normalised
VOR decay curve. Under v2 that same field carries a cross-league
relativity ratio. Applying a v1 config under v2 semantics would
mis-interpret the numbers, so the loader must decline to activate
any config older than :data:`_MIN_SUPPORTED_VERSION` and the live
post-pass must fall through to its no-op branch.
"""
from __future__ import annotations

import json
import logging

from src.idp_calibration import production


def _write(path, blob: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob))


def test_v1_config_is_refused_and_warns_once(tmp_path, monkeypatch, caplog):
    cfg = tmp_path / "config" / "idp_calibration.json"
    _write(
        cfg,
        {
            "version": 1,
            "active_mode": "blended",
            "multipliers": {"final": {"DL": {"1-6": 0.5}}},
        },
    )
    monkeypatch.setattr(
        production, "production_config_path", lambda base=None: cfg
    )
    production.reset_cache()
    with caplog.at_level(logging.WARNING, logger="src.idp_calibration.production"):
        assert production.load_production_config() is None
        # Repeated reads don't re-warn; the one-shot flag debounces noise.
        assert production.load_production_config() is None
    warnings = [r for r in caplog.records if "schema v1" in r.getMessage()]
    assert len(warnings) == 1, f"expected 1 warning, got {len(warnings)}"
    # Bucket lookup falls through to identity.
    assert production.get_idp_bucket_multiplier("DL", 1) == 1.0


def test_v0_missing_version_is_refused(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "idp_calibration.json"
    _write(
        cfg,
        {
            # No version field ⇒ parsed as 0 ⇒ refused.
            "active_mode": "blended",
            "multipliers": {"final": {"DL": {"1-6": 0.5}}},
        },
    )
    monkeypatch.setattr(
        production, "production_config_path", lambda base=None: cfg
    )
    production.reset_cache()
    assert production.load_production_config() is None


def test_v2_config_loads_cleanly(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "idp_calibration.json"
    _write(
        cfg,
        {
            "version": 2,
            "active_mode": "blended",
            "multipliers": {"final": {"DL": {"1-6": 0.5}}},
        },
    )
    monkeypatch.setattr(
        production, "production_config_path", lambda base=None: cfg
    )
    production.reset_cache()
    cfg_loaded = production.load_production_config()
    assert cfg_loaded is not None
    assert cfg_loaded["version"] == 2
    # And the real bucket lookup returns the configured value (0.5),
    # NOT identity.
    assert abs(production.get_idp_bucket_multiplier("DL", 1) - 0.5) < 1e-9
