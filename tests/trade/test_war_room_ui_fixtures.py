"""Trade War Room — the UI's fixtures ARE the analyze endpoint's output.

``frontend/__tests__/fixtures/trade-war-room/*.json`` are what the War Room
component tests render.  This test regenerates each scenario through the real
``simulate_trade`` + ``analyze_trade`` path and requires byte equality, so a
backend change to anything the UI reads fails here until the fixtures (and
therefore the UI tests) are regenerated::

    python -m tests.trade.war_room_ui_payloads
"""

from __future__ import annotations

import json

import pytest

from tests.trade import war_room_ui_payloads as gen


@pytest.mark.parametrize("name", sorted(gen.SCENARIOS))
def test_committed_fixture_matches_the_backend(name):
    path = gen.fixture_path(name)
    assert path.exists(), f"missing {path}; run python -m tests.trade.war_room_ui_payloads"
    assert path.read_text(encoding="utf-8") == gen.serialize(gen.build(name)), (
        f"{path.name} is stale against the backend; regenerate with "
        "python -m tests.trade.war_room_ui_payloads"
    )


def test_fixtures_cover_the_states_the_ui_renders():
    load = {n: json.loads(gen.fixture_path(n).read_text(encoding="utf-8")) for n in gen.SCENARIOS}
    assert load["consolidation"]["analysis"]["lenses"]["feasibility"]["detail"]["state"] == (
        "fits_cleanly"
    )
    forced = load["forced-cut"]
    assert forced["analysis"]["lenses"]["feasibility"]["detail"]["state"] == "cut_required"
    assert forced["rosterUtility"]["cleanup"]["state"] == "applied"
    assert load["asset-only"]["analysis"]["teamContext"]["mode"] == "asset_only"
    assert load["partial-coverage"]["analysis"]["lenses"]["roster"]["unavailableReason"] == (
        "partial_projection_coverage"
    )
