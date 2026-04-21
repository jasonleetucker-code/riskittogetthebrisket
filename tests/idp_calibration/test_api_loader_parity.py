"""Pin: ``/production`` and ``/status`` report a consistent view.

Before schema v2, ``api.production`` went through
``promotion.load_production`` (raw JSON, no gate) while ``api.status``
went through ``production.is_promoted`` (schema-gated via
``_load_if_stale``).  During the v1→v2 rollout window a legacy
``config/idp_calibration.json`` could sit on disk and produce
contradictory signals — ``/production`` would report ``present: true``
while ``/status`` reported ``production_present: false``.

Both endpoints now route through ``production.promoted_state`` so
they read the same thing, and when a file exists but fails the schema
gate both endpoints surface an explicit ``stale`` flag for operators.
"""
from __future__ import annotations

import json

import pytest

from src.idp_calibration import api, production


def _write_config(path, version: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": version,
                "active_mode": "blended",
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
        )
    )


@pytest.fixture
def tmp_base(tmp_path):
    production.reset_cache()
    yield tmp_path
    production.reset_cache()


def test_no_config_both_endpoints_agree(tmp_base):
    """No config on disk → both endpoints report not-present,
    not-stale."""
    _, prod = api.production(base=tmp_base)
    _, stat = api.status(base=tmp_base)
    assert prod["present"] is False
    assert prod["stale"] is False
    assert stat["production_present"] is False
    assert stat["production_stale"] is False


def test_v2_config_both_endpoints_report_active(tmp_base):
    """Fresh v2 config → both endpoints report present, not-stale."""
    cfg = tmp_base / "config" / "idp_calibration.json"
    _write_config(cfg, version=2)
    _, prod = api.production(base=tmp_base)
    _, stat = api.status(base=tmp_base)
    assert prod["present"] is True
    assert prod["stale"] is False
    assert stat["production_present"] is True
    assert stat["production_stale"] is False
    # And /production returns the actual config.
    assert prod["config"]["version"] == 2


def test_v1_config_both_endpoints_report_stale(tmp_base):
    """Pre-schema-v2 config on disk → /production no longer reports
    ``present: true`` (which would contradict /status); both endpoints
    surface an explicit ``stale`` signal with the on-disk version.
    """
    cfg = tmp_base / "config" / "idp_calibration.json"
    _write_config(cfg, version=1)

    _, prod = api.production(base=tmp_base)
    _, stat = api.status(base=tmp_base)

    # /production: not applied, flagged as stale, version surfaced.
    assert prod["present"] is False
    assert prod["stale"] is True
    assert prod["stale_version"] == 1
    assert prod["required_version"] == 2
    assert prod["config"] is None

    # /status: agrees.
    assert stat["production_present"] is False
    assert stat["production_stale"] is True
    assert stat["production_stale_version"] == 1
    assert stat["required_schema_version"] == 2


def test_delete_then_restore_same_mtime_forces_reread(tmp_base):
    """Regression: ``promoted_state`` previously short-circuited on
    ``not path.exists()`` without resetting the cache. If the file
    was then restored with the same mtime (preserved-timestamp
    restore or coarse filesystem mtime), the mtime fast-path would
    reuse the old cached config.

    With the short-circuit removed, the file-missing branch inside
    ``_load_if_stale`` clears the cache, so even a same-mtime
    restore triggers a fresh disk read.
    """
    import os

    cfg = tmp_base / "config" / "idp_calibration.json"
    _write_config(cfg, version=2)
    original_mtime = cfg.stat().st_mtime

    # Prime the cache with the v2 config.
    _, prod = api.production(base=tmp_base)
    assert prod["present"] is True
    assert prod["config"]["version"] == 2

    # Simulate a delete/restore cycle that preserves mtime.
    cfg.unlink()
    _, prod_missing = api.production(base=tmp_base)
    assert prod_missing["present"] is False
    assert prod_missing["stale"] is False

    # Restore a DIFFERENT config at the SAME mtime. If the cache
    # still held the old config, the mtime fast-path would replay
    # it; with the file-missing cache-reset, the loader re-reads.
    _write_config(cfg, version=1)  # v1 → would be refused as stale
    os.utime(cfg, (original_mtime, original_mtime))
    assert cfg.stat().st_mtime == original_mtime

    _, prod_restored = api.production(base=tmp_base)
    assert prod_restored["present"] is False
    assert prod_restored["stale"] is True
    assert prod_restored["stale_version"] == 1, (
        "Same-mtime restore reused the v2 cache entry instead of "
        "re-reading the v1 file — cache-reset regression."
    )


def test_missing_version_treated_as_stale_v0(tmp_base):
    """A config with no version field (hand-edited or very old) gets
    parsed as v0 and surfaced as stale with stale_version=0."""
    cfg = tmp_base / "config" / "idp_calibration.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        json.dumps(
            {
                "active_mode": "blended",
                "multipliers": {},
                "anchors": {},
            }
        )
    )

    _, prod = api.production(base=tmp_base)
    _, stat = api.status(base=tmp_base)

    assert prod["present"] is False
    assert prod["stale"] is True
    assert prod["stale_version"] == 0
    assert stat["production_present"] is False
    assert stat["production_stale"] is True
    assert stat["production_stale_version"] == 0
