"""Per-source freshness snapshot tests.

Covers the ``server._per_source_freshness`` helper that maps every
registered source's CSV mtime onto a ``{lastFetched, ageHours}``
record.  This is what feeds ``check_and_alert`` in
``src.api.source_health_alerts`` and the per-source rows on the
``/tools/source-health`` page.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

import server as srv


def test_per_source_freshness_returns_dict_with_known_sources():
    out = srv._per_source_freshness()
    assert isinstance(out, dict)
    # KTC always has a CSV in the live repo; this confirms the
    # path-resolution + mtime read works end-to-end.
    if "ktc" in out:
        entry = out["ktc"]
        assert "lastFetched" in entry
        assert "ageHours" in entry
        assert isinstance(entry["ageHours"], (int, float))
        assert entry["ageHours"] >= 0
        # ISO-8601 with timezone marker.
        parsed = datetime.fromisoformat(entry["lastFetched"])
        assert parsed.tzinfo is not None


def test_freshness_records_have_consistent_age_window():
    out = srv._per_source_freshness()
    if not out:
        pytest.skip("no CSV sources present in this checkout")
    now = time.time()
    for src, entry in out.items():
        # Reverse-derive the lastFetched epoch and confirm ageHours
        # matches it within ±2 minutes (rounded to 2 decimals).
        last = datetime.fromisoformat(entry["lastFetched"]).astimezone(timezone.utc)
        derived_hours = (now - last.timestamp()) / 3600.0
        assert abs(derived_hours - entry["ageHours"]) < 2 / 60, (
            f"{src}: derived={derived_hours:.4f}h vs reported={entry['ageHours']}h"
        )


def test_per_source_freshness_returns_empty_when_repo_missing(monkeypatch, tmp_path):
    # Point the helper at a directory with no CSVs and confirm it
    # returns {} cleanly (alert system tolerates this — no spurious
    # alerts when sources legitimately don't exist yet).
    bogus = tmp_path / "fake_repo_root"
    bogus.mkdir()
    monkeypatch.setattr(srv, "__file__", str(bogus / "server.py"))
    out = srv._per_source_freshness()
    assert out == {}


def test_source_health_snapshot_includes_sources_block():
    """``_build_source_health_snapshot`` must surface the per-source
    freshness map under ``sources`` so ``source_health_alerts``
    can find ``lastFetched``."""
    snap = srv._build_source_health_snapshot({"sites": [], "settings": {}})
    assert "sources" in snap
    assert isinstance(snap["sources"], dict)
