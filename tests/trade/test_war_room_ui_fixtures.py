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
    # Long-term strategy with an unprojected incoming player: the roster lens
    # abstains, the decision still stands on trade value (not an evidence gap).
    long_term = load["partial-long-term"]["analysis"]
    assert long_term["lenses"]["roster"]["unavailableReason"] == "partial_projection_coverage"
    assert long_term["decision"]["strategy"]["used"] == "LONG_TERM"
    assert long_term["decision"]["headline"] != "NOT_ENOUGH_EVIDENCE"
    assert "no current-season roster effect" in long_term["decision"]["confidence"]["statement"]
    # The capacity check raised: the simulator's own failure shapes (a bare
    # exception class name on rosterCapacity) and both reason-code gaps.
    unmeasured = load["roster-unmeasured"]
    assert unmeasured["rosterCapacity"]["unavailable"] == "KeyError"
    assert unmeasured["rosterUtility"]["unavailableReason"] == "roster_capacity_unavailable"
    assert unmeasured["analysis"]["lenses"]["feasibility"]["unavailableReason"] == "KeyError"
    gaps = unmeasured["analysis"]["decision"]["missingEvidence"]
    assert [g["code"] for g in gaps] == ["roster_unknown", "roster_limit_unknown"]
    # The roster simulation raised: the simulator's error:<Exception> reason.
    err = load["roster-error"]["analysis"]
    assert err["lenses"]["roster"]["unavailableReason"] == "error:KeyError"
    assert err["uncertainty"] == ["Roster impact not available (error:KeyError)"]
    # A strategy-decided NO whose package value turns negative after the cut.
    cut_no = load["strategy-cut-no"]["analysis"]["decision"]
    assert (cut_no["headline"], cut_no["deciding"]) == ("NO", "strategy")
    value = next(r for r in cut_no["reasons"] if r["component"] == "objectiveValue")
    assert value["evidence"]["forcedReleaseCost"] > 0 > value["evidence"]["netGap"]
    # Slot codes and repeats in the owner's own lineupHoles.
    holes = load["superflex-holes"]["analysis"]["lenses"]["roster"]["detail"]["lineupHoles"]
    assert "SUPER_FLEX" in holes["after"]["noEligiblePlayer"]
    # The KTC rollback's own label; the comparables' format codes; capacity notes.
    ktc = load["ktc-rollback"]["analysis"]["lenses"]["market"]["detail"]["packageModel"]
    assert ktc["family"] == "ktc"
    comps = load["comparables-formats"]["analysis"]["lenses"]["comparables"]["detail"]
    assert any(r.startswith("Format: ") for t in comps["comparableTrades"] for r in t["reasons"])
    notes = load["outgoing-not-held"]["analysis"]["lenses"]["feasibility"]["detail"]["notes"]
    assert any("free no spot" in n for n in notes)
    notes = load["over-limit"]["analysis"]["lenses"]["feasibility"]["detail"]["notes"]
    assert any(n.startswith("roster is ALREADY") for n in notes)
    # A strategy-decided NO_TOO_CLOSE: neutral value, lineup gain, no counter.
    close = load["too-close-strategy"]["analysis"]["decision"]
    assert (close["headline"], close["deciding"]) == ("NO_TOO_CLOSE", "strategy")
    assert close["mainCounterargument"] is None
