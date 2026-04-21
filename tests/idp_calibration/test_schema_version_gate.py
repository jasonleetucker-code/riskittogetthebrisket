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

import pytest

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


def test_promotion_refuses_pre_v2_artifact(tmp_path, monkeypatch):
    """Gate on the write path: a saved run artifact that predates the
    current engine must be refused by ``build_production_config``, so
    it cannot be stamped with ``"version": 2`` and silently bypass the
    runtime loader gate."""
    from src.idp_calibration import promotion

    v1_artifact = {
        "run_id": "legacy_run",
        "schema_version": 1,
        "settings": {},
        "resolved_seasons": [2024],
        "multipliers": {
            "DL": {
                "position": "DL",
                "buckets": [
                    {"label": "1-6", "intrinsic": 1.0, "market": 1.0, "final": 1.0, "count": 10},
                ],
            },
        },
        "anchors": {},
    }
    with pytest.raises(promotion.StaleArtifactSchemaError):
        promotion.build_production_config(v1_artifact, active_mode="blended")


def test_promotion_refuses_artifact_with_no_schema_version(tmp_path):
    """Legacy artifacts without a ``schema_version`` field must also
    be rejected (parsed as 0 → below the minimum)."""
    from src.idp_calibration import promotion

    artifact = {
        "run_id": "unversioned",
        "settings": {},
        "resolved_seasons": [2024],
        "multipliers": {
            "DL": {
                "position": "DL",
                "buckets": [
                    {"label": "1-6", "intrinsic": 1.0, "market": 1.0, "final": 1.0, "count": 10},
                ],
            },
        },
    }
    with pytest.raises(promotion.StaleArtifactSchemaError):
        promotion.build_production_config(artifact, active_mode="blended")


def test_promotion_refuses_non_blended_mode_under_v2(tmp_path):
    """Schema v2 ``intrinsic`` / ``market`` are offense-anchored VOR
    magnitudes, not multipliers. The promotion factory must refuse
    non-blended modes so no v2 config can ship with ``active_mode``
    pointing at a display-only channel."""
    from src.idp_calibration import promotion

    v2_artifact = {
        "run_id": "v2_run",
        "schema_version": 2,
        "settings": {},
        "resolved_seasons": [2024],
        "multipliers": {
            "DL": {
                "position": "DL",
                "buckets": [
                    {"label": "1-6", "intrinsic": 3.5, "market": 3.0, "final": 1.17, "count": 10},
                ],
            },
        },
    }
    for bad_mode in ("intrinsic_only", "market_only"):
        with pytest.raises(ValueError, match="not applicable"):
            promotion.build_production_config(v2_artifact, active_mode=bad_mode)
    # ``blended`` is accepted.
    cfg = promotion.build_production_config(v2_artifact, active_mode="blended")
    assert cfg["version"] == 2
    assert cfg["active_mode"] == "blended"


def test_runtime_coerces_non_blended_mode_back_to_final(tmp_path, monkeypatch):
    """Defence-in-depth: even if a hand-edited v2 config smuggles
    ``active_mode="intrinsic_only"`` past the factory, the runtime
    must coerce back to ``blended`` so it never reads the raw
    offense-anchored VOR magnitude in the ``intrinsic`` channel as a
    multiplier."""
    cfg_path = tmp_path / "config" / "idp_calibration.json"
    _write(
        cfg_path,
        {
            "version": 2,
            "active_mode": "intrinsic_only",  # intentionally malformed
            "multipliers": {
                "DL": {
                    "position": "DL",
                    "buckets": [
                        {"label": "1-6", "intrinsic": 3.5, "market": 3.0, "final": 1.17, "count": 10},
                    ],
                },
            },
        },
    )
    monkeypatch.setattr(
        production, "production_config_path", lambda base=None: cfg_path
    )
    production.reset_cache()
    # Reading ``intrinsic`` directly would return 3.5 (offense-anchored
    # magnitude). Runtime coercion must instead read ``final`` → 1.17.
    val = production.get_idp_bucket_multiplier("DL", 1)
    assert abs(val - 1.17) < 1e-6, (
        f"Runtime did not coerce intrinsic_only → blended; got {val}"
    )
