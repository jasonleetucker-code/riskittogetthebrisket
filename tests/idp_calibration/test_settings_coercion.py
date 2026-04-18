"""AnalysisSettings.from_payload must never raise on garbage client input.

Malformed numeric settings would otherwise bubble out of
``api.analyze`` as a 500 because ``from_payload`` is called outside
the handler's try/except guard.
"""
from __future__ import annotations

from src.idp_calibration import api
from src.idp_calibration.engine import AnalysisSettings


def test_malformed_numeric_fields_fall_back_to_defaults():
    payload = {
        "min_games": "abc",
        "min_bucket_size": None,
        "top_n": "not a number",
        "anchor_floor": "bad",
        "blend": {"intrinsic": "lots"},
        "replacement": {"mode": "starter_plus_buffer", "buffer_pct": "15%"},
        "year_weights": {"2025": "heavy", "2024": 0.3},
        "bucket_edges": [["x", "y"], [1, 6]],
    }
    settings = AnalysisSettings.from_payload(payload)
    # Defaults restored silently — no exception.
    assert settings.min_games == 0
    assert settings.min_bucket_size == 3
    assert settings.top_n is None
    assert abs(settings.anchor_floor - 0.05) < 1e-6
    assert abs(settings.blend["intrinsic"] - 0.75) < 1e-6
    assert abs(settings.replacement.buffer_pct - 0.15) < 1e-6
    # Year weights: the malformed 2025 entry is dropped; 2024 survives.
    assert 2024 in settings.year_weights
    # Bucket edges: the malformed ["x","y"] pair is rejected; [1,6] survives.
    assert [1, 6] in settings.bucket_edges


def test_analyze_handler_returns_422_on_empty_league_ids_not_500():
    # Even with a malformed settings block, the handler should surface a
    # structured validation error, not a 500.
    status, payload = api.analyze(
        {"test_league_id": "", "my_league_id": "", "settings": {"min_games": "oops"}},
    )
    assert status == 422
    assert payload["ok"] is False


def test_manual_rank_garbage_drops_entry_silently():
    payload = {
        "replacement": {
            "mode": "manual",
            "manual": {"DL": "abc", "LB": "-5", "DB": "12"},
        },
    }
    settings = AnalysisSettings.from_payload(payload)
    assert "DL" not in settings.replacement.manual
    assert "LB" not in settings.replacement.manual  # <=0 rejected
    assert settings.replacement.manual["DB"] == 12


def test_from_payload_tolerates_non_dict_top_level():
    # Strings, lists, ints, None — none of these should raise.
    for bad in ["oops", [1, 2, 3], 42, None, True, 3.14]:
        settings = AnalysisSettings.from_payload(bad)
        # Defaults all round-trip.
        assert settings.min_games == 0
        assert settings.min_bucket_size == 3
        assert settings.top_n is None


def test_from_payload_tolerates_non_dict_sub_fields():
    # Each sub-field that was previously assumed to be a dict.
    settings = AnalysisSettings.from_payload(
        {
            "replacement": "not a dict",
            "blend": [1, 2, 3],
            "year_weights": "bogus",
            "anchor_ranks": "1,2,3",  # string is iterable but ints() will fail
            "bucket_edges": "oops",
            "seasons": "oops",
        },
    )
    # All defaults preserved — no AttributeError raised.
    assert settings.replacement.mode == "starter_plus_buffer"
    assert abs(settings.blend["intrinsic"] - 0.75) < 1e-6
    assert 2025 in settings.year_weights  # default weights
    assert settings.anchor_ranks  # default anchors restored
    assert settings.bucket_edges  # default buckets restored
    assert settings.seasons  # default seasons restored


def test_analyze_handler_survives_malformed_settings_shape():
    # Was previously a 500 via AttributeError in from_payload.
    status, payload = api.analyze(
        {"test_league_id": "A", "my_league_id": "B", "settings": "oops"},
    )
    # Since we pass real league IDs but stub adapter isn't available,
    # this will proceed through analysis using default settings.
    # The important invariant is: we do NOT get a 500 from type drift.
    assert status != 500
    assert isinstance(payload, dict)
