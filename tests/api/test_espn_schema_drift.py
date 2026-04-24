"""Tests for ESPN schema drift detection."""
from __future__ import annotations

import json

from src.api import espn_schema_drift as esd


def test_shape_of_primitives():
    assert esd.shape_of(None) == "null"
    assert esd.shape_of(True) == "bool"
    assert esd.shape_of(1) == "int"
    assert esd.shape_of(1.5) == "float"
    assert esd.shape_of("x") == "string"


def test_shape_of_empty_list():
    assert esd.shape_of([]) == "list[]"


def test_shape_of_flat_object():
    assert esd.shape_of({"a": 1, "b": "x"}) == "object{a:int,b:string}"


def test_shape_stable_across_value_changes():
    a = {"injuries": [{"athlete": {"id": "1", "name": "A"}}]}
    b = {"injuries": [{"athlete": {"id": "999", "name": "Something else entirely"}}]}
    assert esd.shape_of(a) == esd.shape_of(b)


def test_shape_changes_on_key_rename():
    a = {"injuries": [{"athlete": {"id": "1"}}]}
    b = {"injuries": [{"player": {"id": "1"}}]}  # athlete → player
    assert esd.shape_of(a) != esd.shape_of(b)


def test_shape_changes_on_added_field():
    a = {"athlete": {"id": "1"}}
    b = {"athlete": {"id": "1", "jersey": "17"}}
    assert esd.shape_of(a) != esd.shape_of(b)


def test_list_with_mixed_element_shapes_merges():
    """A list with two elements — one missing a field — should still
    produce a stable hash so padding differences don't cause drift."""
    a = [{"id": "1"}, {"id": "2", "extra": "x"}]
    b = [{"id": "3"}, {"id": "4", "extra": "y"}]
    assert esd.shape_of(a) == esd.shape_of(b)


def test_detect_drift_new_endpoint(tmp_path):
    baseline = tmp_path / "b.json"
    result = esd.detect_drift(
        {"new_ep": {"a": 1}}, baseline_path=baseline,
    )
    assert result["new_ep"]["status"] == "new"


def test_detect_drift_unchanged(tmp_path):
    baseline = tmp_path / "b.json"
    sample = {"a": 1, "b": "x"}
    h = esd.hash_shape(sample)
    esd.save_baseline({"ep": {"hash": h}}, path=baseline)
    result = esd.detect_drift({"ep": sample}, baseline_path=baseline)
    assert result["ep"]["status"] == "unchanged"


def test_detect_drift_changed(tmp_path):
    baseline = tmp_path / "b.json"
    esd.save_baseline(
        {"ep": {"hash": "deadbeef00000000"}},
        path=baseline,
    )
    result = esd.detect_drift({"ep": {"a": 1}}, baseline_path=baseline)
    assert result["ep"]["status"] == "drifted"


def test_save_and_reload_baseline(tmp_path):
    b = tmp_path / "bb.json"
    esd.save_baseline({"ep": {"hash": "abc", "first_seen": "2026-04-24"}}, path=b)
    got = esd.load_baseline(b)
    assert got["ep"]["hash"] == "abc"


def test_run_drift_check_delivers_email_on_drift(tmp_path):
    baseline = tmp_path / "b.json"
    esd.save_baseline({"ep1": {"hash": "old_hash_xx"}}, path=baseline)
    sends = []
    def delivery(to, subj, body):
        sends.append((to, subj, body))
        return True
    result = esd.run_drift_check(
        {"ep1": lambda: {"new": "shape"}},
        delivery=delivery, to_email="ops@example.com",
        baseline_path=baseline,
    )
    assert result["drifted"] >= 1
    assert len(sends) == 1
    assert "drift" in sends[0][1].lower()


def test_run_drift_check_no_email_when_unchanged(tmp_path):
    baseline = tmp_path / "b.json"
    sample = {"x": 1}
    esd.save_baseline({"ep": {"hash": esd.hash_shape(sample)}}, path=baseline)
    sends = []
    def delivery(to, subj, body):
        sends.append((to, subj, body))
        return True
    result = esd.run_drift_check(
        {"ep": lambda: sample},
        delivery=delivery, to_email="ops@example.com",
        baseline_path=baseline,
    )
    assert result["drifted"] == 0
    assert len(sends) == 0


def test_format_drift_email_shape():
    report = {
        "ep1": {"status": "drifted", "current_hash": "abc", "baseline_hash": "xyz"},
        "ep2": {"status": "new", "current_hash": "def", "baseline_hash": None},
    }
    subject, body = esd.format_drift_email(report)
    assert "drift" in subject.lower()
    assert "ep1" in body
    assert "ep2" in body
