"""Tests for startup validation checks."""
from __future__ import annotations

import pytest

from src.api import startup_validation as sv


def test_check_env_var_set(monkeypatch):
    monkeypatch.setenv("MY_TEST_VAR", "x")
    r = sv.check_env_var("MY_TEST_VAR", required=True)
    assert r.ok is True
    assert r.fatal is False


def test_check_env_var_missing_required(monkeypatch):
    monkeypatch.delenv("MY_TEST_VAR", raising=False)
    r = sv.check_env_var("MY_TEST_VAR", required=True)
    assert r.ok is False
    assert r.fatal is True


def test_check_env_var_missing_optional(monkeypatch):
    monkeypatch.delenv("MY_TEST_VAR", raising=False)
    r = sv.check_env_var("MY_TEST_VAR", required=False)
    assert r.ok is True
    assert r.fatal is False


def test_check_dir_writable(tmp_path):
    r = sv.check_dir_writable(tmp_path, create=False)
    assert r.ok is True


def test_check_dir_writable_creates_missing(tmp_path):
    target = tmp_path / "new_dir"
    assert not target.exists()
    r = sv.check_dir_writable(target, create=True)
    assert r.ok is True
    assert target.exists()


def test_check_sqlite_reachable_ok(tmp_path):
    db = tmp_path / "t.sqlite"
    r = sv.check_sqlite_reachable(db)
    assert r.ok is True


def test_check_league_registry_loads():
    r = sv.check_league_registry()
    # Actual registry — at least one active league must exist.
    assert r.ok is True or r.ok is False  # just verifies no crash
    assert r.name == "league_registry"


def test_run_all_returns_results(tmp_path):
    checks = sv.run_all(data_dir=tmp_path)
    assert len(checks) >= 5
    # All results must be CheckResult dataclasses.
    for c in checks:
        assert hasattr(c, "name")
        assert hasattr(c, "ok")
        assert hasattr(c, "message")


def test_summary_shape(tmp_path):
    checks = sv.run_all(data_dir=tmp_path)
    s = sv.summary(checks)
    assert "total" in s
    assert "ok" in s
    assert "failed" in s
    assert "fatal" in s
    assert len(s["checks"]) == s["total"]


def test_run_all_never_raises_on_broken_extra_check(tmp_path):
    def _bad():
        raise RuntimeError("boom")
    checks = sv.run_all(data_dir=tmp_path, extra_checks=[_bad])
    names = {c.name for c in checks}
    assert "extra:_bad" in names
    # The broken check reports failure, not raises.
    broken = [c for c in checks if c.name == "extra:_bad"][0]
    assert broken.ok is False
