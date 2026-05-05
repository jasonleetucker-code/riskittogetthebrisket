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


def _redirect_repo_root(monkeypatch, tmp_path, source_key: str, csv_rel: str):
    """Helper: point ``server._per_source_freshness`` at ``tmp_path``
    as the fake repo root with a single registered source.  Returns
    the (csv_path, stamp_path) tuple for the caller to populate."""
    monkeypatch.setattr(srv, "__file__", str(tmp_path / "server.py"))
    csv_path = tmp_path / csv_rel
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path = tmp_path / "data" / "scrape_state" / f"{source_key}_last_success"
    from src.api import data_contract as dc
    monkeypatch.setattr(dc, "_SOURCE_CSV_PATHS", {source_key: csv_rel})
    return csv_path, stamp_path


def test_freshness_prefers_stamp_over_csv_mtime(monkeypatch, tmp_path):
    """Stamp content (epoch) wins over CSV mtime when both exist - the
    load-bearing behaviour for monthly-cadence vendors where the CSV
    is rewritten with byte-identical content most of the month and
    git checkout --force on prod skips rewriting unchanged files,
    freezing CSV mtime on the last *content* change rather than the
    last *fetcher success*."""
    csv_path, stamp_path = _redirect_repo_root(
        monkeypatch, tmp_path, "fantasyProsFitzmaurice",
        "CSVs/site_raw/fantasyProsFitzmaurice.csv",
    )
    # CSV mtime: 4 days old
    csv_path.write_text("name,rank\nfoo,1\n")
    old = time.time() - 4 * 86400
    import os as _os
    _os.utime(csv_path, (old, old))
    # Stamp: 30 minutes old
    fresh_epoch = int(time.time() - 1800)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(f"{fresh_epoch}\n")

    out = srv._per_source_freshness()
    entry = out["fantasyProsFitzmaurice"]
    # ageHours should reflect the 30-min stamp, not the 4-day CSV.
    assert entry["ageHours"] < 1.0, (
        f"stamp ignored - ageHours={entry['ageHours']} suggests fall-through to CSV mtime"
    )


def test_freshness_falls_back_to_csv_when_stamp_missing(monkeypatch, tmp_path):
    """No stamp file ⇒ CSV mtime is used.  Preserves backwards-compat
    for sources that haven't been wired into the stamp pattern yet."""
    csv_path, _ = _redirect_repo_root(
        monkeypatch, tmp_path, "ktc", "CSVs/site_raw/ktc.csv",
    )
    csv_path.write_text("name,rank\n")
    # No stamp file written.
    out = srv._per_source_freshness()
    assert "ktc" in out
    assert out["ktc"]["ageHours"] >= 0


def test_freshness_falls_back_to_csv_when_stamp_unparseable(monkeypatch, tmp_path):
    """Corrupt stamp content (non-numeric) falls through to CSV mtime
    instead of dropping the source from the freshness map."""
    csv_path, stamp_path = _redirect_repo_root(
        monkeypatch, tmp_path, "ktc", "CSVs/site_raw/ktc.csv",
    )
    csv_path.write_text("name,rank\n")
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text("not-a-number\n")
    out = srv._per_source_freshness()
    assert "ktc" in out


def test_freshness_drops_source_when_no_stamp_and_no_csv(monkeypatch, tmp_path):
    """Source entirely absent from disk ⇒ omitted from output (alert
    engine has nothing to alert on; the source-registry parity check
    is the right place to surface "missing CSV")."""
    _redirect_repo_root(
        monkeypatch, tmp_path, "missingSource", "CSVs/site_raw/missingSource.csv",
    )
    out = srv._per_source_freshness()
    assert "missingSource" not in out
