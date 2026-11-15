"""Waiver Advisor must be discoverable only when its private page can answer.

The independent IDP mode is still checked by the client-side streaming gate;
a disabled streaming mode must not hide the rest of the Waiver Advisor.
"""

from __future__ import annotations

import pytest

import server
from src.api import feature_flags


@pytest.mark.parametrize(
    ("advisor_on", "data_ready", "expected"),
    [
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    ],
)
def test_waiver_advisor_nav_tracks_flag_and_live_data(
    monkeypatch, advisor_on, data_ready, expected
):
    real = feature_flags.is_enabled
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda name: advisor_on if name == "waiver_advisor" else real(name),
    )
    monkeypatch.setattr(
        server,
        "latest_contract_data",
        {"playersArray": [{"id": "p1"}]} if data_ready else None,
    )
    assert server._waiver_advisor_available() is expected
    assert server._nav_gated_features()["waiverAdvisor"]["available"] is expected


@pytest.mark.parametrize(
    ("advisor_on", "streaming_on", "data_ready", "expected"),
    [
        (True, True, True, True),
        (True, True, False, False),
        (True, False, True, False),
        (False, True, True, False),
        (False, False, False, False),
    ],
)
def test_idp_streaming_nav_needs_both_flags_and_live_data(
    monkeypatch, advisor_on, streaming_on, data_ready, expected
):
    real = feature_flags.is_enabled
    flags = {"waiver_advisor": advisor_on, "idp_streaming": streaming_on}
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda name: flags[name] if name in flags else real(name),
    )
    monkeypatch.setattr(
        server,
        "latest_contract_data",
        {"playersArray": [{"id": "p1"}]} if data_ready else None,
    )
    assert server._idp_streaming_available() is expected
    assert server._nav_gated_features()["idpStreaming"]["available"] is expected


def test_idp_streaming_nav_fails_closed_when_resolution_raises(monkeypatch):
    def boom(name):
        raise RuntimeError("flag store unreadable")

    monkeypatch.setattr(feature_flags, "is_enabled", boom)
    monkeypatch.setattr(server, "latest_contract_data", {"playersArray": [{"id": "p1"}]})
    assert server._nav_gated_features()["idpStreaming"] == {"available": False}
