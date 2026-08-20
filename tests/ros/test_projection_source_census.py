"""C5-PROJ-A — the projection-source capability census stays structurally
sound and reflects the measured facts this unit found, not aspirational
ones.

This is a foundational, no-automation deliverable: the census records
what exists and what is authorized before any of C5-PROJ-B onward is
built. These tests pin (1) the file validates against its own closed
vocabulary, (2) the vocabulary rejects a malformed entry (so the
validator is not vacuous), and (3) the specific measured facts this
census exists to preserve — which sources are real projections today,
which are rankings mislabelled as projections, and which are genuinely
greenfield.
"""

from __future__ import annotations

from src.ros import projection_source_census as census


def test_the_shipped_census_validates():
    errors = census.validate_census()
    assert errors == [], f"census failed validation: {errors}"


def test_load_census_returns_the_validated_data():
    data = census.load_census()
    assert len(data["sources"]) >= 10
    assert len(data["discoveryLanes"]) == 2


def test_every_source_key_is_unique():
    data = census.load_census()
    keys = [s["key"] for s in data["sources"]]
    assert len(keys) == len(set(keys))


def test_the_validator_is_not_vacuous_bad_evidence_class():
    bad = {
        "sources": [
            {
                "key": "x",
                "evidenceClass": "TOTALLY_MADE_UP",
                "horizons": ["WEEKLY"],
                "implementationStatus": "GREENFIELD",
                "accessPosture": "PUBLIC_NO_AUTH",
                "providerFamily": "x",
                "targetPopulation": ["OFFENSE"],
                "acquisitionOwnerLane": "Claude 11",
            }
        ],
        "discoveryLanes": [{"lane": "DFS_PROJECTION"}],
    }
    errors = census.validate_census(bad)
    assert any("evidenceClass" in e for e in errors)


def test_the_validator_is_not_vacuous_bad_horizon():
    bad = {
        "sources": [
            {
                "key": "x",
                "evidenceClass": "PROJECTION_MODEL",
                "horizons": ["NEXT_TUESDAY"],
                "implementationStatus": "GREENFIELD",
                "accessPosture": "PUBLIC_NO_AUTH",
                "providerFamily": "x",
                "targetPopulation": ["OFFENSE"],
                "acquisitionOwnerLane": "Claude 11",
            }
        ],
        "discoveryLanes": [{"lane": "DFS_PROJECTION"}],
    }
    errors = census.validate_census(bad)
    assert any("horizon" in e for e in errors)


def test_live_status_requires_a_real_module_reference():
    bad = {
        "sources": [
            {
                "key": "x",
                "evidenceClass": "PROJECTION_MODEL",
                "horizons": ["WEEKLY"],
                "implementationStatus": "LIVE",
                "existingModule": None,
                "accessPosture": "PUBLIC_NO_AUTH",
                "providerFamily": "x",
                "targetPopulation": ["OFFENSE"],
                "acquisitionOwnerLane": "Claude 11",
            }
        ],
        "discoveryLanes": [{"lane": "DFS_PROJECTION"}],
    }
    errors = census.validate_census(bad)
    assert any("LIVE but existingModule is empty" in e for e in errors)


def test_duplicate_keys_are_rejected():
    bad = {
        "sources": [
            {
                "key": "dup",
                "evidenceClass": "PROJECTION_MODEL",
                "horizons": ["WEEKLY"],
                "implementationStatus": "GREENFIELD",
                "accessPosture": "PUBLIC_NO_AUTH",
                "providerFamily": "x",
                "targetPopulation": ["OFFENSE"],
                "acquisitionOwnerLane": "Claude 11",
            },
            {
                "key": "dup",
                "evidenceClass": "PROJECTION_MODEL",
                "horizons": ["WEEKLY"],
                "implementationStatus": "GREENFIELD",
                "accessPosture": "PUBLIC_NO_AUTH",
                "providerFamily": "x",
                "targetPopulation": ["OFFENSE"],
                "acquisitionOwnerLane": "Claude 11",
            },
        ],
        "discoveryLanes": [{"lane": "DFS_PROJECTION"}],
    }
    errors = census.validate_census(bad)
    assert any("duplicate key" in e for e in errors)


class TestMeasuredFacts:
    """The facts this census exists to preserve. If one of these ever
    flips, it should be because the underlying reality changed (a real
    fetcher was built, an access artifact was recorded) and this test
    was deliberately updated alongside it — not by accident.
    """

    def test_clay_and_idp_show_are_the_only_live_true_projections(self):
        live = [
            s["key"] for s in census.load_census()["sources"] if s["implementationStatus"] == "LIVE"
        ]
        assert sorted(live) == ["clayProjections", "idpShowProjections"]

    def test_cbs_and_nfl_fantasy_are_greenfield(self):
        for key in ("cbsSportsFantasyProjections", "nflFantasyProjections"):
            src = census.get_source(key)
            assert src is not None, key
            assert src["implementationStatus"] == "GREENFIELD"
            assert src["existingModule"] is None
            assert src["accessPosture"] == "NO_ACCESS_PATH_RECORDED"

    def test_every_wired_fantasypros_and_draftsharks_ros_entry_is_flagged_rankings_only(self):
        """These are wired and enabled in ROS_SOURCES today, but none of
        them is a true per-player projection — that is exactly the
        "rankings-only" flag this unit's own brief requires. Distinct
        from ``fantasyProsProjections``, the GREENFIELD candidate for
        FantasyPros' actual (not-yet-built) projections page."""
        flagged_keys = {
            "fantasyProsRosSf",
            "fantasyProsRosIdp",
            "fantasyProsRosOverall",
            "draftSharksOffenseProjections",
            "draftSharksIdpProjections",
        }
        for key in flagged_keys:
            src = census.get_source(key)
            assert src is not None, key
            assert src["evidenceClass"] == "RANKINGS_ONLY", key
            assert src["implementationStatus"] == "LIVE_BUT_RANKINGS_ONLY", key

    def test_fantasypros_true_projections_page_is_a_distinct_greenfield_candidate(self):
        src = census.get_source("fantasyProsProjections")
        assert src is not None
        assert src["evidenceClass"] == "PROJECTION_MODEL"
        assert src["implementationStatus"] == "GREENFIELD"
        assert src["existingModule"] is None

    def test_no_true_projection_model_is_wrongly_flagged_rankings_only(self):
        for src in census.sources_by_evidence_class("PROJECTION_MODEL"):
            assert src["implementationStatus"] != "LIVE_BUT_RANKINGS_ONLY"

    def test_dfs_and_betting_market_lanes_are_genuinely_greenfield(self):
        lanes = {lane["lane"]: lane for lane in census.load_census()["discoveryLanes"]}
        assert set(lanes) == {"DFS_PROJECTION", "BETTING_MARKET"}
        for lane in lanes.values():
            assert lane["status"] == "GREENFIELD"

    def test_draftsharks_acquisition_is_owned_by_claude_8_not_this_lane(self):
        """docs/EXECUTION_PLAN.md names Draft Sharks cross-position
        qualification as Claude 8's exclusive scope. This census must
        not claim that acquisition work for Claude 11."""
        for key in ("draftSharksOffenseProjections", "draftSharksIdpProjections"):
            src = census.get_source(key)
            assert src["acquisitionOwnerLane"] == "Claude 8", key

    def test_idp_show_access_posture_is_not_silently_treated_as_authorized(self):
        """Plan §3: subscription access must not be equated with
        unrestricted automated acquisition/redistribution rights."""
        src = census.get_source("idpShowProjections")
        assert src["accessPosture"] == "SUBSCRIPTION_SCOPE_UNRECORDED"
        assert src not in census.automatable_sources()

    def test_automatable_sources_excludes_unauthorized_ones(self):
        automatable_keys = {s["key"] for s in census.automatable_sources()}
        assert "cbsSportsFantasyProjections" not in automatable_keys
        assert "nflFantasyProjections" not in automatable_keys
        assert "idpShowProjections" not in automatable_keys
        assert "clayProjections" in automatable_keys

    def test_offense_and_idp_evidence_class_lookup_matches_target_population(self):
        idp_projection_sources = census.sources_by_evidence_class(
            "PROJECTION_MODEL", population="IDP"
        )
        keys = {s["key"] for s in idp_projection_sources}
        assert "idpShowProjections" in keys
        assert "clayProjections" in keys  # Clay covers a defensive tackle line too
        assert "cbsSportsFantasyProjections" not in keys  # offense-only candidate
