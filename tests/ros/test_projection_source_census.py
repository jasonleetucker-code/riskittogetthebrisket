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
        """…of the season horizon.  Game Day U5 (2026-09-25) made the WEEKLY
        ``sleeperWeeklyProjections`` LIVE as well; it feeds Game Day only and
        never the full-season ensemble (whose source set is a fixed tuple)."""
        sources = census.load_census()["sources"]
        live = sorted(s["key"] for s in sources if s["implementationStatus"] == "LIVE")
        assert live == ["clayProjections", "idpShowProjections", "sleeperWeeklyProjections"]
        season_live = sorted(
            s["key"]
            for s in sources
            if s["implementationStatus"] == "LIVE" and "WEEKLY" not in s["horizons"]
        )
        assert season_live == ["clayProjections", "idpShowProjections"]

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


class TestSleeperWeeklyEntry:
    """C5-PROJ-C: the first WEEKLY-horizon source is censused with its
    game type, ancestry, access posture and an explicit licensing open
    item — and built behind a flag that really defaults OFF."""

    def test_entry_is_a_weekly_seasonal_lane_projection(self):
        src = census.get_source("sleeperWeeklyProjections")
        assert src is not None
        assert src["horizons"] == ["WEEKLY"]
        assert src["gameType"] == "WEEKLY"
        assert src["valuationLane"] == "SEASONAL_INTELLIGENCE"
        assert src["evidenceClass"] == "PROJECTION_MODEL"
        assert set(src["targetPopulation"]) == {"OFFENSE", "IDP"}
        assert {"K", "DL", "LB", "DB"} <= set(src["positionsCovered"])

    def test_game_type_is_a_recognized_non_dynasty_value(self):
        from src.api.data_contract import GAME_TYPE_DYNASTY, GAME_TYPES

        src = census.get_source("sleeperWeeklyProjections")
        assert src["gameType"] in GAME_TYPES
        assert src["gameType"] != GAME_TYPE_DYNASTY

    def test_ancestry_names_rotowire_as_the_independence_family(self):
        src = census.get_source("sleeperWeeklyProjections")
        assert src["providerFamily"] == "rotowire"
        assert src["modelAncestry"]["chain"] == ["rotowire", "sleeper"]

    def test_access_is_owner_attested_and_automatable(self):
        # Owner attestation 2026-09-25: the basis is the owner's written
        # statement (recorded), not public terms.
        src = census.get_source("sleeperWeeklyProjections")
        assert src["accessPosture"] == "OWNER_ATTESTED_AUTHORIZED"
        assert src["licensingStatus"] == "OWNER_ATTESTED_AUTHORIZED"
        assert "SOURCE_ACCESS_EVIDENCE_2026-09-25" in src["accessAttestation"]
        assert "sleeperWeeklyProjections" in {s["key"] for s in census.automatable_sources()}

    def test_attested_status_requires_the_record(self):
        bad = {
            "sources": [
                {
                    "key": "x",
                    "evidenceClass": "PROJECTION_MODEL",
                    "horizons": ["WEEKLY"],
                    "implementationStatus": "GREENFIELD",
                    "accessPosture": "OWNER_ATTESTED_AUTHORIZED",
                    "providerFamily": "x",
                    "targetPopulation": ["OFFENSE"],
                    "acquisitionOwnerLane": "Claude 11",
                }
            ],
            "discoveryLanes": [{"lane": "DFS_PROJECTION"}],
        }
        assert any("accessAttestation" in e for e in census.validate_census(bad))

    def test_live_since_the_collector_shipped_with_its_rollback_flag_named(self):
        """Game Day U5 (2026-09-25) activated the source: the shared live
        collector owns its cadence, so the flag defaults ON and the status
        moved IMPLEMENTED_FLAG_OFF -> LIVE deliberately.  The flag stays
        named as the rollback lever."""
        from src.api import feature_flags

        src = census.get_source("sleeperWeeklyProjections")
        assert src["implementationStatus"] == "LIVE"
        assert src["featureFlag"] == "sleeper_weekly_projections"
        assert feature_flags._DEFAULTS["sleeper_weekly_projections"] is True

    def test_validator_rejects_flag_off_status_whose_flag_defaults_on(self, monkeypatch):
        import copy

        from src.api import feature_flags

        data = copy.deepcopy(census.load_census())
        entry = next(s for s in data["sources"] if s["key"] == "sleeperWeeklyProjections")
        entry["implementationStatus"] = "IMPLEMENTED_FLAG_OFF"
        monkeypatch.setitem(feature_flags._DEFAULTS, "sleeper_weekly_projections", True)
        errors = census.validate_census(data)
        assert any("defaults ON" in e for e in errors)
        monkeypatch.setitem(feature_flags._DEFAULTS, "sleeper_weekly_projections", False)
        assert not any("defaults ON" in e for e in census.validate_census(data))

    def test_validator_requires_a_registered_flag(self):
        bad = {
            "sources": [
                {
                    "key": "x",
                    "evidenceClass": "PROJECTION_MODEL",
                    "horizons": ["WEEKLY"],
                    "implementationStatus": "IMPLEMENTED_FLAG_OFF",
                    "existingModule": "src.x",
                    "featureFlag": "not_a_registered_flag",
                    "accessPosture": "PUBLIC_UNDOCUMENTED_NO_AUTH",
                    "licensingStatus": "UNVERIFIED",
                    "providerFamily": "x",
                    "targetPopulation": ["OFFENSE"],
                    "acquisitionOwnerLane": "Claude 11",
                }
            ],
            "discoveryLanes": [{"lane": "DFS_PROJECTION"}],
        }
        errors = census.validate_census(bad)
        assert any("not registered" in e for e in errors)

    def test_validator_rejects_an_unknown_licensing_status(self):
        bad = {
            "sources": [
                {
                    "key": "x",
                    "evidenceClass": "PROJECTION_MODEL",
                    "horizons": ["WEEKLY"],
                    "implementationStatus": "GREENFIELD",
                    "accessPosture": "PUBLIC_NO_AUTH",
                    "licensingStatus": "PROBABLY_FINE",
                    "providerFamily": "x",
                    "targetPopulation": ["OFFENSE"],
                    "acquisitionOwnerLane": "Claude 11",
                }
            ],
            "discoveryLanes": [{"lane": "DFS_PROJECTION"}],
        }
        errors = census.validate_census(bad)
        assert any("licensingStatus" in e for e in errors)
